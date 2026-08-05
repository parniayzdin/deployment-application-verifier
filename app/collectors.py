"""Collect post deployment evidence from HTTP endpoints and AWS services."""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

from app.models import (
    ApiObservation,
    CleanupObservation,
    CloudWatchObservation,
    DeploymentTrigger,
    DynamoDbObservation,
    LambdaObservation,
    VerificationObservation,
    VerificationPlan,
)


class AwsEvidenceCollector:
    """Execute a verification plan and return only directly observed facts."""

    def __init__(
        self,
        lambda_client,
        logs_client,
        dynamodb_client,
        http_open: Callable[..., Any] = urllib.request.urlopen,
        monotonic: Callable[[], float] = time.monotonic,
        epoch_time: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.lambda_client = lambda_client
        self.logs_client = logs_client
        self.dynamodb_client = dynamodb_client
        self.http_open = http_open
        self.monotonic = monotonic
        self.epoch_time = epoch_time
        self.sleep = sleep
        self.serializer = TypeSerializer()
        self.deserializer = TypeDeserializer()

    def collect(
        self, plan: VerificationPlan, trigger: DeploymentTrigger
    ) -> VerificationObservation:
        """Run configured checks in a predictable order."""

        api = self._call_api(plan, trigger.deployment_id)
        lambda_observation = self._invoke_lambda(plan, trigger.deployment_id)
        cloudwatch = self._read_logs(plan)
        dynamodb, cleanup = self._check_dynamodb(plan)
        return VerificationObservation(
            deployment_id=trigger.deployment_id,
            stack_status=trigger.stack_status,
            api=api,
            lambda_execution=lambda_observation,
            cloudwatch=cloudwatch,
            dynamodb=dynamodb,
            cleanup=cleanup,
        )

    def _call_api(
        self, plan: VerificationPlan, deployment_id: str
    ) -> ApiObservation:
        check = plan.api_check
        headers = dict(check.headers)
        headers.setdefault("X-Verification-Id", deployment_id)
        data = None
        if check.request_body is not None:
            data = json.dumps(check.request_body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(
            check.url,
            data=data,
            headers=headers,
            method=check.method,
        )
        started = self.monotonic()
        error: str | None = None
        try:
            response = self.http_open(request, timeout=check.timeout_seconds)
            status = (
                response.status
                if hasattr(response, "status")
                else response.getcode()
            )
            raw_body = response.read()
            close = getattr(response, "close", None)
            if close:
                close()
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw_body = exc.read()
            error = str(exc.reason)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            status = 599
            raw_body = b""
            error = str(exc)
        latency_ms = max(0, round((self.monotonic() - started) * 1000))
        return ApiObservation(
            status_code=status,
            response_body=_decode_body(raw_body),
            expected_status_codes=check.expected_status_codes,
            latency_ms=latency_ms,
            error=error,
        )

    def _invoke_lambda(
        self, plan: VerificationPlan, deployment_id: str
    ) -> LambdaObservation:
        check = plan.lambda_check
        if check is None:
            return LambdaObservation(checked=False, completed=None)
        payload = dict(check.payload)
        payload.setdefault("verification_id", deployment_id)
        try:
            response = self.lambda_client.invoke(
                FunctionName=check.function_name,
                InvocationType="RequestResponse",
                Payload=json.dumps(payload).encode("utf-8"),
            )
            status = int(response.get("StatusCode", 500))
            function_error = response.get("FunctionError")
            completed = status == check.expected_status_code and not function_error
            return LambdaObservation(
                checked=True,
                completed=completed,
                status_code=status,
                function_error=function_error,
            )
        except Exception as exc:  # AWS SDK exceptions share no small base type.
            return LambdaObservation(
                checked=True,
                completed=False,
                status_code=500,
                function_error=str(exc),
            )

    def _read_logs(self, plan: VerificationPlan) -> CloudWatchObservation:
        check = plan.cloudwatch_check
        if check is None:
            return CloudWatchObservation(checked=False, errors=[])
        if check.settle_seconds:
            self.sleep(check.settle_seconds)
        start_ms = int((self.epoch_time() - check.lookback_seconds) * 1000)
        messages: list[str] = []
        next_token: str | None = None
        try:
            while len(messages) < check.max_results:
                request: dict[str, Any] = {
                    "logGroupName": check.log_group_name,
                    "startTime": start_ms,
                    "filterPattern": check.filter_pattern,
                    "limit": min(100, check.max_results - len(messages)),
                }
                if next_token:
                    request["nextToken"] = next_token
                response = self.logs_client.filter_log_events(**request)
                messages.extend(
                    str(event.get("message", "")).strip()[:1000]
                    for event in response.get("events", [])
                    if event.get("message")
                )
                new_token = response.get("nextToken")
                if not new_token or new_token == next_token:
                    break
                next_token = new_token
            return CloudWatchObservation(
                checked=True,
                errors=list(dict.fromkeys(messages))[: check.max_results],
            )
        except Exception as exc:  # See Lambda exception note above.
            return CloudWatchObservation(
                checked=True,
                errors=[],
                collection_error=str(exc),
            )

    def _check_dynamodb(
        self, plan: VerificationPlan
    ) -> tuple[DynamoDbObservation, CleanupObservation]:
        check = plan.dynamodb_check
        if check is None:
            return (
                DynamoDbObservation(checked=False, expected_record_found=None),
                CleanupObservation(required=False, completed=True),
            )

        key = {
            name: self.serializer.serialize(value)
            for name, value in check.key.items()
        }
        try:
            response = self.dynamodb_client.get_item(
                TableName=check.table_name,
                Key=key,
                ConsistentRead=True,
            )
            raw_item = response.get("Item")
            item = (
                {
                    name: self.deserializer.deserialize(value)
                    for name, value in raw_item.items()
                }
                if raw_item
                else None
            )
            mismatches = _attribute_mismatches(item, check.expected_attributes)
            found = item is not None and not mismatches
            cleanup_completed = True
            if check.cleanup_after_verification and raw_item:
                self.dynamodb_client.delete_item(
                    TableName=check.table_name,
                    Key=key,
                )
            return (
                DynamoDbObservation(
                    checked=True,
                    expected_record_found=found,
                    mismatches=mismatches,
                ),
                CleanupObservation(
                    required=check.cleanup_after_verification and raw_item is not None,
                    completed=cleanup_completed,
                ),
            )
        except Exception as exc:  # See Lambda exception note above.
            return (
                DynamoDbObservation(
                    checked=True,
                    expected_record_found=False,
                    collection_error=str(exc),
                ),
                CleanupObservation(
                    required=check.cleanup_after_verification,
                    completed=False,
                ),
            )


def _decode_body(raw_body: bytes) -> Any:
    if not raw_body:
        return {}
    text = raw_body.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def _attribute_mismatches(
    item: dict[str, Any] | None, expected: dict[str, Any]
) -> list[str]:
    if item is None:
        return []
    return [
        f"{name}: expected {expected_value!r}, observed {item.get(name)!r}"
        for name, expected_value in expected.items()
        if item.get(name) != expected_value
    ]

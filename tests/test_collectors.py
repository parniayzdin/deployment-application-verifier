"""Tests for AWS evidence collection using local fakes only."""

import io
import urllib.error

from app.collectors import AwsEvidenceCollector
from app.models import (
    ApiCheck,
    CloudWatchCheck,
    DeploymentTrigger,
    DynamoDbCheck,
    LambdaCheck,
    VerificationPlan,
)


class FakeHttpResponse:
    status = 201

    def read(self) -> bytes:
        return b'{"saved": true}'

    def close(self) -> None:
        return None


class FakeLambdaClient:
    def __init__(self, response=None):
        self.response = response or {
            "StatusCode": 200,
            "Payload": io.BytesIO(b'{"ok": true}'),
        }
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeLogsClient:
    def __init__(self, events=None, error=None):
        self.events = events or []
        self.error = error
        self.calls = []

    def filter_log_events(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"events": self.events}


class FakeDynamoClient:
    def __init__(self, item=None):
        self.item = item
        self.deleted = []

    def get_item(self, **kwargs):
        return {"Item": self.item} if self.item else {}

    def delete_item(self, **kwargs):
        self.deleted.append(kwargs)
        return {}


def make_trigger() -> DeploymentTrigger:
    return DeploymentTrigger(
        deployment_id="deployment-1",
        stack_id=(
            "arn:aws:cloudformation:us-east-1:123456789012:"
            "stack/payments-api-dev/abc"
        ),
        stack_name="payments-api-dev",
        stack_status="UPDATE_COMPLETE",
    )


def make_plan() -> VerificationPlan:
    return VerificationPlan(
        stack_name="payments-api-dev",
        api_check=ApiCheck(
            url="https://example.test/payments",
            expected_status_codes=[201],
            request_body={"payment_id": "synthetic-1"},
        ),
        lambda_check=LambdaCheck(function_name="payments-handler"),
        cloudwatch_check=CloudWatchCheck(log_group_name="/aws/lambda/payments"),
        dynamodb_check=DynamoDbCheck(
            table_name="payments",
            key={"payment_id": "synthetic-1"},
            expected_attributes={"status": "CREATED"},
        ),
    )


def test_collects_healthy_evidence_and_cleans_up() -> None:
    lambda_client = FakeLambdaClient()
    logs_client = FakeLogsClient()
    dynamodb = FakeDynamoClient(
        {
            "payment_id": {"S": "synthetic-1"},
            "status": {"S": "CREATED"},
        }
    )
    times = iter([10.0, 10.05])
    collector = AwsEvidenceCollector(
        lambda_client,
        logs_client,
        dynamodb,
        http_open=lambda request, timeout: FakeHttpResponse(),
        monotonic=lambda: next(times),
        epoch_time=lambda: 1000,
    )

    observation = collector.collect(make_plan(), make_trigger())

    assert observation.api.status_code == 201
    assert observation.api.latency_ms == 50
    assert observation.lambda_execution.completed is True
    assert observation.cloudwatch.errors == []
    assert observation.dynamodb.expected_record_found is True
    assert observation.cleanup.completed is True
    assert len(dynamodb.deleted) == 1
    assert lambda_client.calls[0]["FunctionName"] == "payments-handler"


def test_api_network_error_becomes_failed_observation() -> None:
    times = iter([20.0, 20.01])

    def fail_request(request, timeout):
        raise urllib.error.URLError("connection refused")

    collector = AwsEvidenceCollector(
        FakeLambdaClient(),
        FakeLogsClient(),
        FakeDynamoClient(),
        http_open=fail_request,
        monotonic=lambda: next(times),
    )
    plan = VerificationPlan(
        stack_name="payments-api-dev",
        api_check=ApiCheck(url="https://example.test/health"),
    )

    observation = collector.collect(plan, make_trigger())

    assert observation.api.status_code == 599
    assert "connection refused" in observation.api.error
    assert observation.lambda_execution.checked is False
    assert observation.cloudwatch.checked is False
    assert observation.dynamodb.checked is False


def test_cloudwatch_access_error_is_preserved_as_evidence() -> None:
    times = iter([1.0, 1.0])
    collector = AwsEvidenceCollector(
        FakeLambdaClient(),
        FakeLogsClient(error=RuntimeError("access denied")),
        FakeDynamoClient(),
        http_open=lambda request, timeout: FakeHttpResponse(),
        monotonic=lambda: next(times),
    )
    plan = VerificationPlan(
        stack_name="payments-api-dev",
        api_check=ApiCheck(
            url="https://example.test/health", expected_status_codes=[201]
        ),
        cloudwatch_check=CloudWatchCheck(log_group_name="/aws/lambda/payments"),
    )

    observation = collector.collect(plan, make_trigger())

    assert observation.cloudwatch.collection_error == "access denied"


def test_dynamodb_attribute_mismatch_fails_side_effect() -> None:
    times = iter([1.0, 1.0])
    dynamodb = FakeDynamoClient(
        {
            "payment_id": {"S": "synthetic-1"},
            "status": {"S": "FAILED"},
        }
    )
    collector = AwsEvidenceCollector(
        FakeLambdaClient(),
        FakeLogsClient(),
        dynamodb,
        http_open=lambda request, timeout: FakeHttpResponse(),
        monotonic=lambda: next(times),
    )

    observation = collector.collect(make_plan(), make_trigger())

    assert observation.dynamodb.expected_record_found is False
    assert "expected 'CREATED'" in observation.dynamodb.mismatches[0]

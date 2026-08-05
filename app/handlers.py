"""AWS Lambda entry points for EventBridge and the management API."""

import base64
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import boto3
from pydantic import ValidationError

from app.collectors import AwsEvidenceCollector
from app.event_parser import parse_cloudformation_event
from app.models import DeploymentTrigger, VerificationPlan
from app.repositories import DynamoPlanRepository, DynamoReportRepository
from app.service import VerificationService
from app.settings import Settings

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)
_service: VerificationService | None = None


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Dispatch EventBridge events and API Gateway requests."""

    if event.get("source") == "aws.cloudformation":
        return event_handler(event, context)
    return api_handler(event, context)


def event_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Verify a stack after a successful CloudFormation status change."""

    trigger = parse_cloudformation_event(event)
    result = get_service().run(trigger)
    LOGGER.info(
        "verification_event status=%s stack=%s deployment_id=%s",
        result.status,
        trigger.stack_name,
        trigger.deployment_id,
    )
    return result.model_dump(mode="json")


def api_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Manage plans, run manual checks, and retrieve stored reports."""

    method, path = _method_and_path(event)
    if method == "GET" and path == "/health":
        return _response(200, {"status": "ok"})

    try:
        service = get_service()
        segments = [segment for segment in path.split("/") if segment]

        if len(segments) == 2 and segments[0] == "plans":
            stack_name = segments[1]
            if method == "GET":
                plan = service.plans.get(stack_name)
                return (
                    _response(200, plan.model_dump(mode="json"))
                    if plan
                    else _response(404, {"error": "verification plan not found"})
                )
            if method == "PUT":
                body = _body(event)
                supplied_name = body.get("stack_name")
                if supplied_name and supplied_name != stack_name:
                    return _response(
                        400,
                        {"error": "path stack name and body stack_name must match"},
                    )
                body["stack_name"] = stack_name
                plan = VerificationPlan.model_validate(body)
                service.plans.put(plan)
                return _response(200, plan.model_dump(mode="json"))

        if len(segments) == 2 and segments[0] == "verify" and method == "POST":
            body = _body(event, required=False)
            status = body.get("stack_status", "UPDATE_COMPLETE")
            trigger = DeploymentTrigger(
                deployment_id=body.get(
                    "deployment_id", f"manual-{uuid.uuid4()}"
                ),
                stack_id=f"manual:stack/{segments[1]}/manual",
                stack_name=segments[1],
                stack_status=status,
                occurred_at=datetime.now(UTC),
            )
            result = service.run(trigger)
            return _response(200, result.model_dump(mode="json"))

        if len(segments) == 2 and segments[0] == "reports" and method == "GET":
            report = service.reports.get(segments[1])
            return (
                _response(200, report.model_dump(mode="json"))
                if report
                else _response(404, {"error": "verification report not found"})
            )

        return _response(404, {"error": "route not found"})
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        return _response(400, {"error": str(exc)})
    except Exception:
        LOGGER.exception("unhandled management API error")
        return _response(500, {"error": "internal server error"})


def get_service() -> VerificationService:
    """Create AWS clients once per warm Lambda execution environment."""

    global _service
    if _service is None:
        settings = Settings.from_env()
        dynamodb = boto3.client("dynamodb")
        _service = VerificationService(
            plans=DynamoPlanRepository(dynamodb, settings.plans_table),
            reports=DynamoReportRepository(
                dynamodb, settings.reports_table, settings.report_ttl_days
            ),
            collector=AwsEvidenceCollector(
                lambda_client=boto3.client("lambda"),
                logs_client=boto3.client("logs"),
                dynamodb_client=dynamodb,
            ),
        )
    return _service


def _method_and_path(event: dict[str, Any]) -> tuple[str, str]:
    request_context = event.get("requestContext") or {}
    http = request_context.get("http") or {}
    method = http.get("method") or event.get("httpMethod") or ""
    path = event.get("rawPath") or event.get("path") or "/"
    return str(method).upper(), str(path).rstrip("/") or "/"


def _body(event: dict[str, Any], required: bool = True) -> dict[str, Any]:
    raw = event.get("body")
    if raw in (None, ""):
        if required:
            raise ValueError("request body is required")
        return {}
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    parsed = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(parsed, dict):
        raise ValueError("request body must be a JSON object")
    return parsed


def _response(status_code: int, body: Any) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }

"""Normalize supported CloudFormation EventBridge events."""

from datetime import UTC, datetime
from typing import Any

from app.models import DeploymentTrigger


class UnsupportedEvent(ValueError):
    """Raised when an event cannot safely start verification."""


def parse_cloudformation_event(event: dict[str, Any]) -> DeploymentTrigger:
    """Validate and normalize a successful stack status change event."""

    if event.get("source") != "aws.cloudformation":
        raise UnsupportedEvent("event source must be aws.cloudformation")
    if event.get("detail-type") != "CloudFormation Stack Status Change":
        raise UnsupportedEvent(
            "detail-type must be CloudFormation Stack Status Change"
        )

    detail = event.get("detail") or {}
    status_details = detail.get("status-details") or {}
    status = status_details.get("status")
    if status not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
        raise UnsupportedEvent(f"stack status {status!r} is not verifiable")

    stack_id = detail.get("stack-id")
    if not isinstance(stack_id, str) or not stack_id:
        raise UnsupportedEvent("event is missing detail.stack-id")

    event_id = event.get("id")
    if not isinstance(event_id, str) or not event_id:
        raise UnsupportedEvent("event is missing its idempotency id")

    return DeploymentTrigger(
        deployment_id=event_id,
        stack_id=stack_id,
        stack_name=stack_name_from_id(stack_id),
        stack_status=status,
        occurred_at=_parse_time(event.get("time")),
    )


def stack_name_from_id(stack_id: str) -> str:
    """Extract a stack name from its ARN without accepting malformed values."""

    marker = ":stack/"
    if marker not in stack_id:
        raise UnsupportedEvent("stack-id is not a CloudFormation stack ARN")
    remainder = stack_id.split(marker, 1)[1]
    stack_name = remainder.split("/", 1)[0]
    if not stack_name:
        raise UnsupportedEvent("stack-id does not contain a stack name")
    return stack_name


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        return datetime.now(UTC)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise UnsupportedEvent("event time is not ISO 8601") from exc

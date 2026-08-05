"""Tests for CloudFormation EventBridge normalization."""

import json
from pathlib import Path

import pytest

from app.event_parser import UnsupportedEvent, parse_cloudformation_event

EVENT_PATH = Path("events/cloudformation-complete.json")


def load_event() -> dict:
    return json.loads(EVENT_PATH.read_text(encoding="utf-8"))


def test_parses_successful_stack_event() -> None:
    trigger = parse_cloudformation_event(load_event())

    assert trigger.stack_name == "payments-api-dev"
    assert trigger.stack_status == "UPDATE_COMPLETE"
    assert trigger.deployment_id == "11111111-2222-3333-4444-555555555555"


def test_rejects_in_progress_stack_event() -> None:
    event = load_event()
    event["detail"]["status-details"]["status"] = "UPDATE_IN_PROGRESS"

    with pytest.raises(UnsupportedEvent, match="not verifiable"):
        parse_cloudformation_event(event)


def test_rejects_wrong_event_source() -> None:
    event = load_event()
    event["source"] = "custom.application"

    with pytest.raises(UnsupportedEvent, match="event source"):
        parse_cloudformation_event(event)


def test_rejects_malformed_stack_arn() -> None:
    event = load_event()
    event["detail"]["stack-id"] = "payments-api-dev"

    with pytest.raises(UnsupportedEvent, match="stack ARN"):
        parse_cloudformation_event(event)

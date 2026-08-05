"""Tests for loading and validating synthetic evidence."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.loaders import load_observation
from app.models import VerificationObservation


FIXTURE_PATH = Path(
    "tests/fixtures/post_deployment/false_green_missing_environment_variable.json"
)


def test_loads_false_green_observation() -> None:
    """A green stack can still contain evidence of an application failure."""

    observation = load_observation(FIXTURE_PATH)

    assert observation.stack_status == "UPDATE_COMPLETE"
    assert observation.api.status_code == 500
    assert observation.lambda_execution.completed is False
    assert observation.cloudwatch.errors == ["KeyError: PAYMENTS_TABLE"]
    assert observation.dynamodb.expected_record_found is False


def test_rejects_invalid_http_status() -> None:
    """Impossible HTTP status codes must not enter the verification pipeline."""

    with pytest.raises(ValidationError):
        VerificationObservation.model_validate(
            {
                "deployment_id": "synthetic-deployment-002",
                "stack_status": "UPDATE_COMPLETE",
                "api": {"status_code": 999, "response_body": {}},
                "lambda_execution": {"completed": True},
                "cloudwatch": {"errors": []},
                "dynamodb": {"expected_record_found": True},
                "cleanup": {"required": True, "completed": True},
            }
        )

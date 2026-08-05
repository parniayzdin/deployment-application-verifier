"""Tests for deterministic post-deployment verification rules."""

from pathlib import Path

from app.loaders import load_observation
from app.models import VerificationObservation, VerificationStatus
from app.verifier import verify_observation

FIXTURE_PATH = Path(
    "tests/fixtures/post_deployment/false_green_missing_environment_variable.json"
)


def test_false_green_deployment_fails_application_verification() -> None:
    """A successful stack must not hide a broken deployed application."""

    report = verify_observation(load_observation(FIXTURE_PATH))

    assert report.infrastructure_status is VerificationStatus.PASSED
    assert report.application_status is VerificationStatus.FAILED
    assert {item.source for item in report.confirmed_evidence} == {
        "cloudformation",
        "api",
        "lambda",
        "cloudwatch",
        "dynamodb",
        "cleanup",
    }
    assert report.likely_causes[0].supported_by == ["cloudwatch", "dynamodb"]
    assert "PAYMENTS_TABLE" in report.likely_causes[0].message
    assert "PAYMENTS_TABLE" in report.recommended_next_steps[0]


def test_healthy_application_passes_without_speculative_causes() -> None:
    """All successful checks produce a PASS without invented explanations."""

    observation = VerificationObservation.model_validate(
        {
            "deployment_id": "synthetic-deployment-healthy",
            "stack_status": "CREATE_COMPLETE",
            "api": {"status_code": 201, "response_body": {"saved": True}},
            "lambda_execution": {"completed": True},
            "cloudwatch": {"errors": []},
            "dynamodb": {"expected_record_found": True},
            "cleanup": {"required": True, "completed": True},
        }
    )

    report = verify_observation(observation)

    assert report.infrastructure_status is VerificationStatus.PASSED
    assert report.application_status is VerificationStatus.PASSED
    assert report.likely_causes == []
    assert report.recommended_next_steps == []


def test_optional_checks_do_not_fail_an_api_only_plan() -> None:
    """A plan may intentionally verify only its public API contract."""

    observation = VerificationObservation.model_validate(
        {
            "deployment_id": "api-only",
            "stack_status": "UPDATE_COMPLETE",
            "api": {"status_code": 200, "response_body": {"ok": True}},
            "lambda_execution": {"checked": False, "completed": None},
            "cloudwatch": {"checked": False, "errors": []},
            "dynamodb": {
                "checked": False,
                "expected_record_found": None,
            },
            "cleanup": {"required": False, "completed": True},
        }
    )

    report = verify_observation(observation)

    assert report.application_status is VerificationStatus.PASSED
    assert {item.source for item in report.confirmed_evidence} == {
        "cloudformation",
        "api",
        "cleanup",
    }


def test_unexpected_api_status_produces_actionable_diagnosis() -> None:
    observation = VerificationObservation.model_validate(
        {
            "deployment_id": "api-failed",
            "stack_status": "UPDATE_COMPLETE",
            "api": {
                "status_code": 503,
                "response_body": {},
                "expected_status_codes": [200],
            },
            "lambda_execution": {"checked": False, "completed": None},
            "cloudwatch": {"checked": False, "errors": []},
            "dynamodb": {
                "checked": False,
                "expected_record_found": None,
            },
            "cleanup": {"required": False, "completed": True},
        }
    )

    report = verify_observation(observation)

    assert report.application_status is VerificationStatus.FAILED
    assert report.likely_causes[0].supported_by == ["api"]
    assert "API Gateway" in report.recommended_next_steps[0]

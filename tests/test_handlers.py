"""Tests for API Gateway routing without AWS credentials."""

import json

import pytest

import app.handlers as handlers
from app.models import ApiCheck, VerificationPlan
from app.repositories import InMemoryPlanRepository, InMemoryReportRepository
from app.service import VerificationService
from tests.test_service import FakeCollector


@pytest.fixture
def local_service(monkeypatch):
    service = VerificationService(
        InMemoryPlanRepository(), InMemoryReportRepository(), FakeCollector()
    )
    monkeypatch.setattr(handlers, "_service", service)
    return service


def api_event(method: str, path: str, body=None) -> dict:
    return {
        "httpMethod": method,
        "path": path,
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {},
    }


def response_body(response: dict) -> dict:
    return json.loads(response["body"])


def test_health_does_not_require_aws_configuration(monkeypatch) -> None:
    monkeypatch.setattr(handlers, "_service", None)

    response = handlers.api_handler(api_event("GET", "/health"), None)

    assert response["statusCode"] == 200
    assert response_body(response) == {"status": "ok"}


def test_put_and_get_plan(local_service) -> None:
    body = {
        "api_check": {
            "url": "https://example.test/health",
            "expected_status_codes": [200],
        }
    }

    put_response = handlers.api_handler(
        api_event("PUT", "/plans/store-api", body), None
    )
    get_response = handlers.api_handler(
        api_event("GET", "/plans/store-api"), None
    )

    assert put_response["statusCode"] == 200
    assert response_body(get_response)["stack_name"] == "store-api"


def test_rejects_plan_name_mismatch(local_service) -> None:
    response = handlers.api_handler(
        api_event(
            "PUT",
            "/plans/store-api",
            {
                "stack_name": "different-stack",
                "api_check": {"url": "https://example.test/health"},
            },
        ),
        None,
    )

    assert response["statusCode"] == 400


def test_manual_verification_and_report_lookup(local_service) -> None:
    local_service.plans.put(
        VerificationPlan(
            stack_name="payments-api-dev",
            api_check=ApiCheck(url="https://example.test/health"),
        )
    )
    verify_response = handlers.api_handler(
        api_event(
            "POST",
            "/verify/payments-api-dev",
            {"deployment_id": "manual-test-1"},
        ),
        None,
    )
    report_response = handlers.api_handler(
        api_event("GET", "/reports/manual-test-1"), None
    )

    assert response_body(verify_response)["status"] == "COMPLETED"
    assert report_response["statusCode"] == 200
    assert response_body(report_response)["deployment_id"] == "manual-test-1"


def test_missing_route_returns_404(local_service) -> None:
    response = handlers.api_handler(api_event("GET", "/unknown"), None)

    assert response["statusCode"] == 404

"""Tests for cloud independent verification orchestration."""

from pathlib import Path

from app.loaders import load_observation
from app.models import ApiCheck, RunStatus, VerificationPlan
from app.repositories import InMemoryPlanRepository, InMemoryReportRepository
from app.service import VerificationService
from tests.test_collectors import make_trigger


class FakeCollector:
    def __init__(self):
        self.calls = 0

    def collect(self, plan, trigger):
        self.calls += 1
        observation = load_observation(
            Path("tests/fixtures/post_deployment/healthy.json")
        )
        return observation.model_copy(update={"deployment_id": trigger.deployment_id})


def test_runs_plan_and_stores_report() -> None:
    plan = VerificationPlan(
        stack_name="payments-api-dev",
        api_check=ApiCheck(url="https://example.test/health"),
    )
    reports = InMemoryReportRepository()
    collector = FakeCollector()
    service = VerificationService(
        InMemoryPlanRepository([plan]), reports, collector
    )

    result = service.run(make_trigger())

    assert result.status is RunStatus.COMPLETED
    assert result.report.stack_name == "payments-api-dev"
    assert reports.get("deployment-1") is not None
    assert collector.calls == 1


def test_duplicate_event_returns_existing_report_without_collecting_again() -> None:
    plan = VerificationPlan(
        stack_name="payments-api-dev",
        api_check=ApiCheck(url="https://example.test/health"),
    )
    collector = FakeCollector()
    service = VerificationService(
        InMemoryPlanRepository([plan]), InMemoryReportRepository(), collector
    )

    first = service.run(make_trigger())
    second = service.run(make_trigger())

    assert first.status is RunStatus.COMPLETED
    assert second.status is RunStatus.DUPLICATE
    assert collector.calls == 1


def test_unknown_stack_is_skipped() -> None:
    collector = FakeCollector()
    service = VerificationService(
        InMemoryPlanRepository(), InMemoryReportRepository(), collector
    )

    result = service.run(make_trigger())

    assert result.status is RunStatus.SKIPPED
    assert collector.calls == 0


def test_disabled_plan_is_skipped() -> None:
    plan = VerificationPlan(
        stack_name="payments-api-dev",
        enabled=False,
        api_check=ApiCheck(url="https://example.test/health"),
    )
    service = VerificationService(
        InMemoryPlanRepository([plan]), InMemoryReportRepository(), FakeCollector()
    )

    result = service.run(make_trigger())

    assert result.status is RunStatus.SKIPPED

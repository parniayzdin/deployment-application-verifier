"""Application service coordinating plans, evidence, rules, and reports."""

from datetime import UTC, datetime
from typing import Protocol

from app.models import (
    DeploymentTrigger,
    RunStatus,
    VerificationObservation,
    VerificationRunResult,
)
from app.repositories import PlanRepository, ReportRepository
from app.verifier import verify_observation


class EvidenceCollector(Protocol):
    """Cloud independent evidence collection contract."""

    def collect(self, plan, trigger) -> VerificationObservation: ...


class VerificationService:
    """Idempotently run the configured checks for a deployment."""

    def __init__(
        self,
        plans: PlanRepository,
        reports: ReportRepository,
        collector: EvidenceCollector,
    ):
        self.plans = plans
        self.reports = reports
        self.collector = collector

    def run(self, trigger: DeploymentTrigger) -> VerificationRunResult:
        """Skip unknown stacks and return an existing report for duplicate events."""

        existing = self.reports.get(trigger.deployment_id)
        if existing:
            return VerificationRunResult(
                status=RunStatus.DUPLICATE,
                message="This deployment event was already verified.",
                report=existing,
            )

        plan = self.plans.get(trigger.stack_name)
        if plan is None:
            return VerificationRunResult(
                status=RunStatus.SKIPPED,
                message=f"No verification plan exists for {trigger.stack_name}.",
            )
        if not plan.enabled:
            return VerificationRunResult(
                status=RunStatus.SKIPPED,
                message=f"Verification is disabled for {trigger.stack_name}.",
            )

        observation = self.collector.collect(plan, trigger)
        report = verify_observation(observation).model_copy(
            update={
                "stack_name": trigger.stack_name,
                "created_at": datetime.now(UTC),
            }
        )
        self.reports.put(report)
        return VerificationRunResult(
            status=RunStatus.COMPLETED,
            message=f"Verification completed for {trigger.stack_name}.",
            report=report,
        )

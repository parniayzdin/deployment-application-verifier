"""DynamoDB and in memory repositories for plans and reports."""

from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.models import VerificationPlan, VerificationReport


class PlanRepository(Protocol):
    """Storage contract for reusable stack verification plans."""

    def get(self, stack_name: str) -> VerificationPlan | None: ...

    def put(self, plan: VerificationPlan) -> None: ...


class ReportRepository(Protocol):
    """Storage contract for idempotent verification reports."""

    def get(self, deployment_id: str) -> VerificationReport | None: ...

    def put(self, report: VerificationReport) -> None: ...


class DynamoPlanRepository:
    """Store validated plan JSON using a small, inspectable DynamoDB shape."""

    def __init__(self, client, table_name: str):
        self.client = client
        self.table_name = table_name

    def get(self, stack_name: str) -> VerificationPlan | None:
        response = self.client.get_item(
            TableName=self.table_name,
            Key={"stack_name": {"S": stack_name}},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if not item:
            return None
        return VerificationPlan.model_validate_json(item["payload"]["S"])

    def put(self, plan: VerificationPlan) -> None:
        self.client.put_item(
            TableName=self.table_name,
            Item={
                "stack_name": {"S": plan.stack_name},
                "payload": {"S": plan.model_dump_json()},
                "updated_at": {"S": datetime.now(UTC).isoformat()},
            },
        )


class DynamoReportRepository:
    """Store report JSON with a DynamoDB TTL for automatic retention cleanup."""

    def __init__(self, client, table_name: str, ttl_days: int = 30):
        self.client = client
        self.table_name = table_name
        self.ttl_days = ttl_days

    def get(self, deployment_id: str) -> VerificationReport | None:
        response = self.client.get_item(
            TableName=self.table_name,
            Key={"deployment_id": {"S": deployment_id}},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if not item:
            return None
        return VerificationReport.model_validate_json(item["payload"]["S"])

    def put(self, report: VerificationReport) -> None:
        expires_at = int(
            (datetime.now(UTC) + timedelta(days=self.ttl_days)).timestamp()
        )
        self.client.put_item(
            TableName=self.table_name,
            Item={
                "deployment_id": {"S": report.deployment_id},
                "stack_name": {"S": report.stack_name or "unknown"},
                "payload": {"S": report.model_dump_json()},
                "created_at": {"S": report.created_at.isoformat()},
                "expires_at": {"N": str(expires_at)},
            },
        )


class InMemoryPlanRepository:
    """Small repository used by unit tests and local examples."""

    def __init__(self, plans: list[VerificationPlan] | None = None):
        self.plans = {plan.stack_name: plan for plan in plans or []}

    def get(self, stack_name: str) -> VerificationPlan | None:
        return self.plans.get(stack_name)

    def put(self, plan: VerificationPlan) -> None:
        self.plans[plan.stack_name] = plan


class InMemoryReportRepository:
    """Small repository used by unit tests and local examples."""

    def __init__(self):
        self.reports: dict[str, VerificationReport] = {}

    def get(self, deployment_id: str) -> VerificationReport | None:
        return self.reports.get(deployment_id)

    def put(self, report: VerificationReport) -> None:
        self.reports[report.deployment_id] = report

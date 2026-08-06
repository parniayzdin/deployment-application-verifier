"""Tests for the compact DynamoDB persistence format."""

from app.models import (
    ApiCheck,
    VerificationPlan,
    VerificationReport,
    VerificationStatus,
)
from app.repositories import DynamoPlanRepository, DynamoReportRepository


class FakeDynamoRepositoryClient:
    def __init__(self):
        self.items = {}

    def put_item(self, TableName, Item):
        key_name = "deployment_id" if "deployment_id" in Item else "stack_name"
        key_value = Item[key_name]["S"]
        self.items[(TableName, key_value)] = Item
        return {}

    def get_item(self, TableName, Key, ConsistentRead):
        key_name, encoded = next(iter(Key.items()))
        item = self.items.get((TableName, encoded["S"]))
        return {"Item": item} if item else {}


def test_plan_round_trip() -> None:
    client = FakeDynamoRepositoryClient()
    repository = DynamoPlanRepository(client, "plans")
    plan = VerificationPlan(
        stack_name="store-api",
        api_check=ApiCheck(url="https://example.test/health"),
    )

    repository.put(plan)

    assert repository.get("store-api") == plan
    assert repository.get("missing") is None


def test_report_round_trip_and_ttl() -> None:
    client = FakeDynamoRepositoryClient()
    repository = DynamoReportRepository(client, "reports", ttl_days=7)
    report = VerificationReport(
        deployment_id="deployment-1",
        stack_name="store-api",
        infrastructure_status=VerificationStatus.PASSED,
        application_status=VerificationStatus.PASSED,
        confirmed_evidence=[],
        likely_causes=[],
        recommended_next_steps=[],
    )

    repository.put(report)
    stored = repository.get("deployment-1")

    assert stored == report
    assert int(client.items[("reports", "deployment-1")]["expires_at"]["N"]) > 0

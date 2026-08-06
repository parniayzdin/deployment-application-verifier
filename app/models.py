"""Validated domain models for verification plans, evidence, and reports."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    """Reject unknown fields so configuration mistakes fail early."""

    model_config = ConfigDict(extra="forbid")


class ApiCheck(StrictModel):
    """An HTTP request that proves the deployed application responds."""

    url: str = Field(min_length=1)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    request_body: Any | None = None
    expected_status_codes: list[int] = Field(default_factory=lambda: [200])
    timeout_seconds: float = Field(default=8.0, gt=0, le=25)

    @field_validator("url")
    @classmethod
    def require_http_url(cls, value: str) -> str:
        """Allow only explicit HTTP or HTTPS verification endpoints."""

        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be an absolute HTTP or HTTPS URL")
        return value

    @field_validator("expected_status_codes")
    @classmethod
    def validate_status_codes(cls, values: list[int]) -> list[int]:
        """Require at least one valid expected HTTP status."""

        if not values or any(value < 100 or value > 599 for value in values):
            raise ValueError("expected_status_codes must contain valid HTTP statuses")
        return values


class LambdaCheck(StrictModel):
    """An optional direct Lambda invocation used for component verification."""

    function_name: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    expected_status_code: int = Field(default=200, ge=100, le=599)


class CloudWatchCheck(StrictModel):
    """A bounded CloudWatch Logs query for errors around the test request."""

    log_group_name: str = Field(min_length=1)
    filter_pattern: str = '?ERROR ?Exception ?"Task timed out"'
    lookback_seconds: int = Field(default=300, ge=1, le=3600)
    settle_seconds: float = Field(default=0, ge=0, le=10)
    max_results: int = Field(default=20, ge=1, le=100)


class DynamoDbCheck(StrictModel):
    """An optional expected side effect in a target DynamoDB table."""

    table_name: str = Field(min_length=1)
    key: dict[str, Any] = Field(min_length=1)
    expected_attributes: dict[str, Any] = Field(default_factory=dict)
    cleanup_after_verification: bool = True


class VerificationPlan(StrictModel):
    """Reusable instructions for verifying one CloudFormation stack."""

    stack_name: str = Field(min_length=1)
    enabled: bool = True
    api_check: ApiCheck
    lambda_check: LambdaCheck | None = None
    cloudwatch_check: CloudWatchCheck | None = None
    dynamodb_check: DynamoDbCheck | None = None


class ApiObservation(StrictModel):
    """What the verifier observed after calling the deployed API."""

    status_code: int = Field(ge=100, le=599)
    response_body: Any
    expected_status_codes: list[int] = Field(
        default_factory=lambda: [200, 201, 202, 204]
    )
    latency_ms: int | None = Field(default=None, ge=0)
    error: str | None = None


class LambdaObservation(StrictModel):
    """What happened during an optional direct Lambda invocation."""

    checked: bool = True
    completed: bool | None
    status_code: int | None = Field(default=None, ge=100, le=599)
    function_error: str | None = None


class CloudWatchObservation(StrictModel):
    """Relevant runtime error messages collected for the request."""

    checked: bool = True
    errors: list[str]
    collection_error: str | None = None


class DynamoDbObservation(StrictModel):
    """Whether an expected test record and its attributes were present."""

    checked: bool = True
    expected_record_found: bool | None
    mismatches: list[str] = Field(default_factory=list)
    collection_error: str | None = None


class CleanupObservation(StrictModel):
    """Whether synthetic test data required cleanup and was removed."""

    required: bool
    completed: bool


class VerificationObservation(StrictModel):
    """All observations collected for one deployment verification run."""

    deployment_id: str = Field(min_length=1)
    stack_status: Literal["CREATE_COMPLETE", "UPDATE_COMPLETE"]
    api: ApiObservation
    lambda_execution: LambdaObservation
    cloudwatch: CloudWatchObservation
    dynamodb: DynamoDbObservation
    cleanup: CleanupObservation


class VerificationStatus(StrEnum):
    """The two possible outcomes for a verification check."""

    PASSED = "PASSED"
    FAILED = "FAILED"


EvidenceSource = Literal[
    "cloudformation", "api", "lambda", "cloudwatch", "dynamodb", "cleanup"
]


class ConfirmedEvidence(StrictModel):
    """A fact directly observed by the verifier."""

    source: EvidenceSource
    check: str
    message: str


class LikelyCause(StrictModel):
    """A possible explanation supported by, but not equal to, confirmed facts."""

    message: str
    supported_by: list[EvidenceSource]


class VerificationReport(StrictModel):
    """The evidence backed result for one verification run."""

    deployment_id: str
    stack_name: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    infrastructure_status: VerificationStatus
    application_status: VerificationStatus
    confirmed_evidence: list[ConfirmedEvidence]
    likely_causes: list[LikelyCause]
    recommended_next_steps: list[str]


class DeploymentTrigger(StrictModel):
    """Normalized trigger created from EventBridge or a manual request."""

    deployment_id: str = Field(min_length=1)
    stack_id: str = Field(min_length=1)
    stack_name: str = Field(min_length=1)
    stack_status: Literal["CREATE_COMPLETE", "UPDATE_COMPLETE"]
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RunStatus(StrEnum):
    """How the orchestration layer handled a deployment trigger."""

    COMPLETED = "COMPLETED"
    DUPLICATE = "DUPLICATE"
    SKIPPED = "SKIPPED"


class VerificationRunResult(StrictModel):
    """Serializable result returned by Lambda handlers."""

    status: RunStatus
    message: str
    report: VerificationReport | None = None

"""Validated data shapes for observations and verification reports."""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ApiObservation(BaseModel):
    """What the verifier observed after calling the deployed API."""

    status_code: int = Field(ge=100, le=599)
    response_body: dict[str, Any]


class LambdaObservation(BaseModel):
    """Whether the Lambda finished the synthetic request successfully."""

    completed: bool


class CloudWatchObservation(BaseModel):
    """Relevant runtime error messages collected for the request."""

    errors: list[str]


class DynamoDbObservation(BaseModel):
    """Whether the expected synthetic record exists after the request."""

    expected_record_found: bool


class CleanupObservation(BaseModel):
    """Whether synthetic test data required cleanup and was removed."""

    required: bool
    completed: bool


class VerificationObservation(BaseModel):
    """All observations collected for one post-deployment verification run."""

    deployment_id: str = Field(min_length=1)
    stack_status: Literal["CREATE_COMPLETE", "UPDATE_COMPLETE"]
    api: ApiObservation
    lambda_execution: LambdaObservation
    cloudwatch: CloudWatchObservation
    dynamodb: DynamoDbObservation
    cleanup: CleanupObservation


class VerificationStatus(str, Enum):
    """The two possible outcomes for a verification check."""

    PASSED = "PASSED"
    FAILED = "FAILED"


EvidenceSource = Literal[
    "cloudformation", "api", "lambda", "cloudwatch", "dynamodb", "cleanup"
]


class ConfirmedEvidence(BaseModel):
    """A fact directly observed by the verifier."""

    source: EvidenceSource
    check: str
    message: str


class LikelyCause(BaseModel):
    """A possible explanation supported by, but not equal to, confirmed facts."""

    message: str
    supported_by: list[EvidenceSource]


class VerificationReport(BaseModel):
    """The evidence-backed result for one verification run."""

    deployment_id: str
    infrastructure_status: VerificationStatus
    application_status: VerificationStatus
    confirmed_evidence: list[ConfirmedEvidence]
    likely_causes: list[LikelyCause]
    recommended_next_steps: list[str]

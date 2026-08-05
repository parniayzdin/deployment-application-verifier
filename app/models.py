"""Validated data shapes for post-deployment observations."""

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

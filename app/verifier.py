"""Deterministic rules for deciding whether a deployed application works."""

from app.models import (
    ConfirmedEvidence,
    LikelyCause,
    VerificationObservation,
    VerificationReport,
    VerificationStatus,
)


def verify_observation(observation: VerificationObservation) -> VerificationReport:
    """Apply explicit checks and return an evidence backed PASS or FAIL report."""

    evidence = [
        ConfirmedEvidence(
            source="cloudformation",
            check="infrastructure_deployment",
            message=f"CloudFormation reported {observation.stack_status}.",
        )
    ]
    application_checks: list[bool] = []

    api_passed = observation.api.status_code in observation.api.expected_status_codes
    application_checks.append(api_passed)
    evidence.append(
        ConfirmedEvidence(
            source="api",
            check="api_response",
            message=_api_message(observation, api_passed),
        )
    )

    if observation.lambda_execution.checked:
        lambda_passed = observation.lambda_execution.completed is True
        application_checks.append(lambda_passed)
        evidence.append(
            ConfirmedEvidence(
                source="lambda",
                check="lambda_completion",
                message=_lambda_message(observation, lambda_passed),
            )
        )

    if observation.cloudwatch.checked:
        cloudwatch_passed = (
            not observation.cloudwatch.errors
            and observation.cloudwatch.collection_error is None
        )
        application_checks.append(cloudwatch_passed)
        if cloudwatch_passed:
            evidence.append(
                ConfirmedEvidence(
                    source="cloudwatch",
                    check="runtime_errors",
                    message="CloudWatch contained no matching runtime errors.",
                )
            )
        else:
            messages = list(observation.cloudwatch.errors)
            if observation.cloudwatch.collection_error:
                messages.append(observation.cloudwatch.collection_error)
            evidence.extend(
                ConfirmedEvidence(
                    source="cloudwatch",
                    check="runtime_errors",
                    message=f"CloudWatch recorded: {message}",
                )
                for message in messages
            )

    if observation.dynamodb.checked:
        database_passed = observation.dynamodb.expected_record_found is True
        application_checks.append(database_passed)
        evidence.append(
            ConfirmedEvidence(
                source="dynamodb",
                check="expected_side_effect",
                message=_database_message(observation, database_passed),
            )
        )

    if observation.cleanup.required:
        application_checks.append(observation.cleanup.completed)
    evidence.append(
        ConfirmedEvidence(
            source="cleanup",
            check="synthetic_data_cleanup",
            message=_cleanup_message(observation),
        )
    )

    likely_causes, recommendations = _diagnose(observation, api_passed)

    return VerificationReport(
        deployment_id=observation.deployment_id,
        infrastructure_status=VerificationStatus.PASSED,
        application_status=(
            VerificationStatus.PASSED
            if application_checks and all(application_checks)
            else VerificationStatus.FAILED
        ),
        confirmed_evidence=evidence,
        likely_causes=likely_causes,
        recommended_next_steps=recommendations,
    )


def _api_message(observation: VerificationObservation, passed: bool) -> str:
    latency = (
        f" in {observation.api.latency_ms} ms" if observation.api.latency_ms else ""
    )
    if passed:
        return f"The API returned HTTP {observation.api.status_code}{latency}."
    expected = ", ".join(map(str, observation.api.expected_status_codes))
    suffix = f" Error: {observation.api.error}" if observation.api.error else ""
    return (
        f"The API returned HTTP {observation.api.status_code}{latency}; expected "
        f"one of [{expected}].{suffix}"
    )


def _lambda_message(observation: VerificationObservation, passed: bool) -> str:
    if passed:
        return "The direct Lambda verification invocation completed successfully."
    error = observation.lambda_execution.function_error
    return (
        f"The direct Lambda verification invocation failed: {error}."
        if error
        else "The direct Lambda verification invocation did not complete successfully."
    )


def _database_message(observation: VerificationObservation, passed: bool) -> str:
    if passed:
        return "The expected synthetic DynamoDB record and attributes were found."
    if observation.dynamodb.collection_error:
        return (
            "The DynamoDB verification could not complete: "
            f"{observation.dynamodb.collection_error}"
        )
    if observation.dynamodb.mismatches:
        return "DynamoDB attribute mismatches: " + "; ".join(
            observation.dynamodb.mismatches
        )
    return "The expected synthetic DynamoDB record was not found."


def _diagnose(
    observation: VerificationObservation, api_passed: bool
) -> tuple[list[LikelyCause], list[str]]:
    causes: list[LikelyCause] = []
    recommendations: list[str] = []
    missing_table_setting = any(
        "PAYMENTS_TABLE" in error for error in observation.cloudwatch.errors
    )

    if missing_table_setting:
        causes.append(
            LikelyCause(
                message=(
                    "The Lambda configuration may be missing the PAYMENTS_TABLE "
                    "environment variable."
                ),
                supported_by=["cloudwatch", "dynamodb"],
            )
        )
        recommendations.append(
            "Verify the Lambda PAYMENTS_TABLE environment variable and redeploy."
        )

    if not api_passed and not missing_table_setting:
        causes.append(
            LikelyCause(
                message="The deployed API did not satisfy its response contract.",
                supported_by=["api"],
            )
        )
        recommendations.append(
            "Trace the request through API Gateway and the target service logs."
        )

    if (
        observation.lambda_execution.checked
        and observation.lambda_execution.completed is not True
    ):
        recommendations.append(
            "Inspect the Lambda function error and its execution role permissions."
        )

    if (
        observation.dynamodb.checked
        and observation.dynamodb.expected_record_found is not True
        and not missing_table_setting
    ):
        causes.append(
            LikelyCause(
                message="The expected database side effect was not confirmed.",
                supported_by=["dynamodb"],
            )
        )
        recommendations.append(
            "Review the application write path, expected attributes, and IAM access."
        )

    if observation.cloudwatch.collection_error:
        recommendations.append(
            "Confirm that the verifier can read the configured CloudWatch log group."
        )
    if observation.cleanup.required and not observation.cleanup.completed:
        recommendations.append(
            "Remove the synthetic test data before running another verification."
        )

    return causes, list(dict.fromkeys(recommendations))


def _cleanup_message(observation: VerificationObservation) -> str:
    """Describe the cleanup result."""

    if not observation.cleanup.required:
        return "This synthetic request did not require cleanup."
    if observation.cleanup.completed:
        return "Synthetic test data cleanup completed."
    return "Synthetic test data cleanup did not complete."

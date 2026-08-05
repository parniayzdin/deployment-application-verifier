"""Deterministic rules for deciding whether the deployed application works."""

from app.models import (
    ConfirmedEvidence,
    LikelyCause,
    VerificationObservation,
    VerificationReport,
    VerificationStatus,
)


def verify_observation(observation: VerificationObservation) -> VerificationReport:
    """Apply explicit checks and return an evidence-backed PASS or FAIL report."""

    evidence = [
        ConfirmedEvidence(
            source="cloudformation",
            check="infrastructure_deployment",
            message=f"CloudFormation reported {observation.stack_status}.",
        )
    ]
    application_checks: list[bool] = []

    api_passed = 200 <= observation.api.status_code < 300
    application_checks.append(api_passed)
    evidence.append(
        ConfirmedEvidence(
            source="api",
            check="api_response",
            message=(
                f"The API returned HTTP {observation.api.status_code}."
                if api_passed
                else (
                    f"The API returned HTTP {observation.api.status_code}; "
                    "a successful 2xx response was expected."
                )
            ),
        )
    )

    lambda_passed = observation.lambda_execution.completed
    application_checks.append(lambda_passed)
    evidence.append(
        ConfirmedEvidence(
            source="lambda",
            check="lambda_completion",
            message=(
                "The Lambda completed the synthetic request."
                if lambda_passed
                else "The Lambda did not complete the synthetic request."
            ),
        )
    )

    cloudwatch_passed = not observation.cloudwatch.errors
    application_checks.append(cloudwatch_passed)
    if cloudwatch_passed:
        evidence.append(
            ConfirmedEvidence(
                source="cloudwatch",
                check="runtime_errors",
                message="CloudWatch contained no related runtime errors.",
            )
        )
    else:
        evidence.extend(
            ConfirmedEvidence(
                source="cloudwatch",
                check="runtime_errors",
                message=f"CloudWatch recorded: {error}",
            )
            for error in observation.cloudwatch.errors
        )

    database_passed = observation.dynamodb.expected_record_found
    application_checks.append(database_passed)
    evidence.append(
        ConfirmedEvidence(
            source="dynamodb",
            check="expected_side_effect",
            message=(
                "The expected synthetic DynamoDB record was found."
                if database_passed
                else "The expected synthetic DynamoDB record was not found."
            ),
        )
    )

    cleanup_passed = not observation.cleanup.required or observation.cleanup.completed
    application_checks.append(cleanup_passed)
    evidence.append(
        ConfirmedEvidence(
            source="cleanup",
            check="synthetic_data_cleanup",
            message=_cleanup_message(observation),
        )
    )

    likely_causes: list[LikelyCause] = []
    recommendations: list[str] = []

    missing_table_setting = any(
        "PAYMENTS_TABLE" in error for error in observation.cloudwatch.errors
    )
    if missing_table_setting:
        likely_causes.append(
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
        recommendations.append(
            "Trace the request through API Gateway and Lambda using the runtime logs."
        )
    if not database_passed and not missing_table_setting:
        recommendations.append(
            "Review the Lambda DynamoDB write path and its IAM permissions."
        )
    if not cleanup_passed:
        recommendations.append(
            "Remove the synthetic test data before running another verification."
        )

    return VerificationReport(
        deployment_id=observation.deployment_id,
        infrastructure_status=VerificationStatus.PASSED,
        application_status=(
            VerificationStatus.PASSED
            if all(application_checks)
            else VerificationStatus.FAILED
        ),
        confirmed_evidence=evidence,
        likely_causes=likely_causes,
        recommended_next_steps=recommendations,
    )


def _cleanup_message(observation: VerificationObservation) -> str:
    """Describe the cleanup result without treating an unneeded cleanup as a failure."""

    if not observation.cleanup.required:
        return "This synthetic request did not require cleanup."
    if observation.cleanup.completed:
        return "Synthetic test data cleanup completed."
    return "Synthetic test data cleanup did not complete."

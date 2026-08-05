# Post-deployment application verifier

This backend project will verify that an application actually works after AWS
CloudFormation reports a successful deployment.

The project does not have a product name yet. This repository title is only a
description of what the software does.

## Current milestone

The current milestone is intentionally local and small. It loads synthetic
post-deployment evidence, validates its structure, applies deterministic
verification rules, and produces an evidence-backed report.

The included scenario represents this outcome:

```text
CloudFormation stack: UPDATE_COMPLETE
API request: HTTP 500
Lambda: failed
CloudWatch: missing PAYMENTS_TABLE setting
DynamoDB test record: missing
```

No AWS account, credentials, database, webhook, AI model, or frontend is used
in this milestone.

## Current workflow

```text
Synthetic JSON evidence
        |
        v
Evidence loader
        |
        v
Pydantic validation
        |
        v
Deterministic verification rules
        |
        v
PASS or FAIL report
```

The report keeps confirmed evidence, likely causes, and recommended next steps
separate. Later milestones will add more synthetic failure scenarios and only
then real AWS integrations.

## Run locally

Create and activate a Python virtual environment, then install the two required
packages:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Generate the report for the synthetic observation:

```powershell
python -m app.main tests/fixtures/post_deployment/false_green_missing_environment_variable.json
```

Run the automated tests:

```powershell
python -m pytest
```

"""Load synthetic evidence from disk."""

import json
from pathlib import Path

from app.models import VerificationObservation


def load_observation(path: Path) -> VerificationObservation:
    """Read one JSON evidence file and validate its complete structure."""

    with path.open(encoding="utf-8") as evidence_file:
        raw_observation = json.load(evidence_file)

    return VerificationObservation.model_validate(raw_observation)

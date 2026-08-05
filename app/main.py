"""Small command-line entry point for the current local milestone."""

import argparse
from pathlib import Path

from app.loaders import load_observation


def parse_args() -> argparse.Namespace:
    """Read the evidence file path supplied on the command line."""

    parser = argparse.ArgumentParser(
        description="Load and validate synthetic post-deployment evidence."
    )
    parser.add_argument("evidence_file", type=Path)
    return parser.parse_args()


def main() -> None:
    """Validate the evidence and print the normalized JSON representation."""

    args = parse_args()
    observation = load_observation(args.evidence_file)
    print(observation.model_dump_json(indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from app import __version__
from app.asyncio_compat import run_with_compatible_event_loop
from app.db.engine import SessionFactory, dispose_engine
from app.research.preregistration import normalize_preregistration_spec
from app.services.experiment_preregistration import (
    preregistration_report_metadata,
    register_experiment_family,
)


async def run(args: argparse.Namespace) -> None:
    path = Path(args.spec)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Preregistration specification must be a JSON object")
    normalized = normalize_preregistration_spec(
        raw,
        expected_family=str(raw.get("experiment_family", "")),
    )
    if args.validate_only:
        print(json.dumps({"status": "VALID", "specification": normalized}, indent=2, ensure_ascii=False))
        return
    try:
        async with SessionFactory() as session:
            row = await register_experiment_family(
                session,
                experiment_family=normalized["experiment_family"],
                registered_at=datetime.now(UTC),
                specification=normalized,
                release_version=__version__,
            )
            await session.commit()
            result = preregistration_report_metadata(row)
        print(json.dumps({"status": "REGISTERED", "preregistration": result}, indent=2, ensure_ascii=False))
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate or immutably register an experiment-family specification before its first trial."
        )
    )
    parser.add_argument("--spec", required=True, help="Path to the completed preregistration JSON")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate the specification without connecting to PostgreSQL",
    )
    run_with_compatible_event_loop(run(parser.parse_args()))


if __name__ == "__main__":
    main()

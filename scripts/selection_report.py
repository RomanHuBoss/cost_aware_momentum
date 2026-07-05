from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.asyncio_compat import run_with_compatible_event_loop
from app.db.engine import SessionFactory, dispose_engine
from app.services.selection_experiments import selection_bias_report


async def build_report(days: int) -> dict:
    if days <= 0:
        raise ValueError("days must be positive")
    since = datetime.now(UTC) - timedelta(days=days)
    async with SessionFactory() as session:
        return await selection_bias_report(session, since=since)


async def async_main(args: argparse.Namespace) -> None:
    report = await build_report(args.days)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)
    await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build prospective operator-selection diagnostics from immutable plan opportunities"
    )
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--output", default="reports/operator_selection_bias.json")
    args = parser.parse_args()
    run_with_compatible_event_loop(async_main(args))


if __name__ == "__main__":
    main()

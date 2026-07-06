from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.asyncio_compat import run_with_compatible_event_loop
from app.db.engine import SessionFactory, dispose_engine
from app.services.attrition import build_candidate_live_attrition_report


async def build_report(hours: int) -> dict[str, object]:
    if hours <= 0:
        raise ValueError("hours must be positive")
    until = datetime.now(UTC)
    since = until - timedelta(hours=hours)
    async with SessionFactory() as session:
        return await build_candidate_live_attrition_report(
            session,
            since=since,
            until=until,
        )


async def async_main(args: argparse.Namespace) -> None:
    report = await build_report(args.hours)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)
    await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build fail-closed attrition and mature counterfactual outcome attribution diagnostics"
    )
    parser.add_argument("--hours", type=int, default=168)
    parser.add_argument("--output", default="reports/candidate_live_attrition.json")
    args = parser.parse_args()
    run_with_compatible_event_loop(async_main(args))


if __name__ == "__main__":
    main()

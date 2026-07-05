from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from app.asyncio_compat import run_with_compatible_event_loop
from app.config import get_settings
from app.db.engine import SessionFactory, dispose_engine
from app.services.drift_monitor import build_production_drift_report


async def async_main(args: argparse.Namespace) -> None:
    settings = get_settings()
    async with SessionFactory() as session:
        report = await build_production_drift_report(session, settings, now=datetime.now(UTC))
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)
    await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a production model drift report")
    parser.add_argument("--output", default="reports/production_drift.json")
    args = parser.parse_args()
    run_with_compatible_event_loop(async_main(args))


if __name__ == "__main__":
    main()

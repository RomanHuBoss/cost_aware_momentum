from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.asyncio_compat import run_with_compatible_event_loop
from app.config import get_settings
from app.db.engine import SessionFactory, dispose_engine
from app.services.experiment_ledger import experiment_governance_report


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    try:
        async with SessionFactory() as session:
            report = await experiment_governance_report(
                session,
                experiment_family=args.family,
                segments=(args.segments if args.segments is not None else settings.experiment_pbo_segments),
                minimum_trials=(
                    args.minimum_trials
                    if args.minimum_trials is not None
                    else settings.experiment_min_trials
                ),
                minimum_periods=(
                    args.minimum_periods
                    if args.minimum_periods is not None
                    else settings.experiment_min_periods
                ),
                maximum_pbo=(
                    args.maximum_pbo if args.maximum_pbo is not None else settings.experiment_max_pbo
                ),
                minimum_dsr_probability=(
                    args.minimum_dsr_probability
                    if args.minimum_dsr_probability is not None
                    else settings.experiment_min_dsr_probability
                ),
            )
        output = Path(args.output or "reports/experiment-selection.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"output": str(output), "report": report}, indent=2, ensure_ascii=False))
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build append-only experiment disclosure, CSCV/PBO and DSR governance evidence."
    )
    parser.add_argument("--family", required=True, help="Exact experiment_family from a backtest report")
    parser.add_argument("--segments", type=int)
    parser.add_argument("--minimum-trials", type=int)
    parser.add_argument("--minimum-periods", type=int)
    parser.add_argument("--maximum-pbo", type=float)
    parser.add_argument("--minimum-dsr-probability", type=float)
    parser.add_argument("--output")
    run_with_compatible_event_loop(run(parser.parse_args()))


if __name__ == "__main__":
    main()

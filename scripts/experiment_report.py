from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.asyncio_compat import run_with_compatible_event_loop
from app.db.engine import SessionFactory, dispose_engine
from app.services.experiment_ledger import experiment_governance_report


async def run(args: argparse.Namespace) -> None:
    requested_governance = {
        key: value
        for key, value in {
            "pbo_segments": args.segments,
            "minimum_trials": args.minimum_trials,
            "minimum_periods": args.minimum_periods,
            "maximum_pbo": args.maximum_pbo,
            "minimum_dsr_probability": args.minimum_dsr_probability,
            "dependence_block_periods": args.dependence_block_periods,
            "minimum_independent_blocks": args.minimum_independent_blocks,
            "bootstrap_replicates": args.bootstrap_replicates,
            "confidence_level": args.confidence_level,
        }.items()
        if value is not None
    }
    try:
        async with SessionFactory() as session:
            report = await experiment_governance_report(
                session,
                experiment_family=args.family,
                requested_governance=requested_governance,
            )
        output = Path(args.output or "reports/experiment-selection.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"output": str(output), "report": report}, indent=2, ensure_ascii=False))
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=("Build preregistered experiment disclosure, CSCV/PBO, DSR and dependence evidence. "
            "Optional policy flags must exactly match the immutable preregistration.")
    )
    parser.add_argument("--family", required=True, help="Exact experiment_family from a backtest report")
    parser.add_argument("--segments", type=int)
    parser.add_argument("--minimum-trials", type=int)
    parser.add_argument("--minimum-periods", type=int)
    parser.add_argument("--maximum-pbo", type=float)
    parser.add_argument("--minimum-dsr-probability", type=float)
    parser.add_argument("--dependence-block-periods", type=int)
    parser.add_argument("--minimum-independent-blocks", type=int)
    parser.add_argument("--bootstrap-replicates", type=int)
    parser.add_argument("--confidence-level", type=float)
    parser.add_argument("--output")
    run_with_compatible_event_loop(run(parser.parse_args()))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from app.asyncio_compat import run_with_compatible_event_loop
from app.db.engine import SessionFactory, dispose_engine
from app.db.models import ExecutionPlan, ManualTrade, MarketSignal, OperatorDecision
from app.services.selection_experiments import selection_bias_report


async def build_report(hours: int, selection_days: int = 90) -> dict:
    since = datetime.now(UTC) - timedelta(hours=hours)
    selection_since = datetime.now(UTC) - timedelta(days=selection_days)
    async with SessionFactory() as session:
        signal_rows = (
            await session.execute(
                select(MarketSignal.direction, MarketSignal.status, func.count())
                .where(MarketSignal.publish_time >= since)
                .group_by(MarketSignal.direction, MarketSignal.status)
            )
        ).all()
        plan_rows = (
            await session.execute(
                select(ExecutionPlan.status, func.count())
                .where(ExecutionPlan.created_at >= since)
                .group_by(ExecutionPlan.status)
            )
        ).all()
        decision_rows = (
            await session.execute(
                select(OperatorDecision.action, func.count())
                .where(OperatorDecision.decided_at >= since)
                .group_by(OperatorDecision.action)
            )
        ).all()
        trade_rows = (
            await session.execute(
                select(
                    func.count(ManualTrade.id),
                    func.coalesce(func.sum(ManualTrade.realized_pnl), 0),
                    func.coalesce(func.sum(ManualTrade.fees_paid), 0),
                    func.coalesce(func.sum(ManualTrade.funding_cash_flow), 0),
                ).where(ManualTrade.entry_time >= since)
            )
        ).one()
        selection_report = await selection_bias_report(session, since=selection_since)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "window_hours": hours,
        "signals": [{"direction": d, "status": s, "count": c} for d, s, c in signal_rows],
        "execution_plans": [{"status": s, "count": c} for s, c in plan_rows],
        "operator_decisions": [{"action": a, "count": c} for a, c in decision_rows],
        "manual_trades": {
            "count": trade_rows[0],
            "realized_pnl": str(trade_rows[1]),
            "fees": str(trade_rows[2]),
            "funding_cash_flow": str(trade_rows[3]),
        },
        "operator_selection_bias": selection_report,
    }


async def async_main(args: argparse.Namespace) -> None:
    report = await build_report(args.hours, args.selection_days)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)
    await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an auditable operational report")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--selection-days", type=int, default=90)
    parser.add_argument("--output", default="reports/daily_report.json")
    args = parser.parse_args()
    run_with_compatible_event_loop(async_main(args))


if __name__ == "__main__":
    main()

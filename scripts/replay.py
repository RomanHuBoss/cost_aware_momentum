from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.asyncio_compat import run_with_compatible_event_loop
from app.db.engine import SessionFactory, dispose_engine
from app.db.models import AuditEvent, ExecutionPlan, MarketSignal
from app.risk.math import calculate_position_plan
from app.services.plan_snapshots import (
    plan_cost_scenario,
    plan_entry_price,
    plan_instrument_constraints,
)


async def replay(signal_id: UUID) -> dict:
    async with SessionFactory() as session:
        signal = await session.get(MarketSignal, signal_id)
        if signal is None:
            raise SystemExit(f"Signal {signal_id} not found")
        plans = (
            (
                await session.execute(
                    select(ExecutionPlan)
                    .where(ExecutionPlan.signal_id == signal_id)
                    .order_by(ExecutionPlan.profile_id, ExecutionPlan.version)
                )
            )
            .scalars()
            .all()
        )
        events = (
            (
                await session.execute(
                    select(AuditEvent)
                    .where(AuditEvent.entity_id.in_([str(signal_id), *[str(p.id) for p in plans]]))
                    .order_by(AuditEvent.event_time, AuditEvent.id)
                )
            )
            .scalars()
            .all()
        )

        replayed = []
        for plan in plans:
            try:
                entry_price = plan_entry_price(plan.sizing_snapshot)
                constraints = plan_instrument_constraints(plan.sizing_snapshot)
                costs = plan_cost_scenario(plan.sizing_snapshot)
                recomputed = calculate_position_plan(
                    effective_capital=plan.effective_capital,
                    risk_rate=plan.risk_rate,
                    entry=entry_price,
                    stop=signal.stop_loss,
                    take_profit=signal.take_profit_1,
                    direction=signal.direction,
                    costs=costs,
                    constraints=constraints,
                    leverage=plan.leverage,
                    capital_verified=plan.capital_verified,
                )
            except ValueError as exc:
                replayed.append(
                    {
                        "plan_id": str(plan.id),
                        "version": plan.version,
                        "stored_status": plan.status,
                        "stored_qty": str(plan.qty),
                        "replay_status": "INVALID_SNAPSHOT",
                        "replay_entry_price": None,
                        "recomputed_qty_without_dynamic_caps": None,
                        "stored_actual_stress_loss": str(plan.actual_stress_loss),
                        "recomputed_actual_stress_loss_without_dynamic_caps": None,
                        "validation_error": str(exc),
                        "note": (
                            "Replay was blocked because the immutable plan snapshot is incomplete "
                            "or invalid; no zero-cost or signal-entry fallback was applied."
                        ),
                    }
                )
                continue

            replayed.append(
                {
                    "plan_id": str(plan.id),
                    "version": plan.version,
                    "stored_status": plan.status,
                    "stored_qty": str(plan.qty),
                    "replay_status": "RECOMPUTED",
                    "replay_entry_price": str(entry_price),
                    "recomputed_qty_without_dynamic_caps": str(recomputed.qty),
                    "stored_actual_stress_loss": str(plan.actual_stress_loss),
                    "recomputed_actual_stress_loss_without_dynamic_caps": str(
                        recomputed.actual_stress_loss
                    ),
                    "validation_error": None,
                    "note": (
                        "Dynamic margin/liquidity/portfolio caps are preserved in the snapshot "
                        "but not reapplied by this compact replay."
                    ),
                }
            )

    return {
        "signal": {
            "id": str(signal.id),
            "natural_key": signal.natural_key,
            "symbol": signal.symbol,
            "direction": signal.direction,
            "event_time": signal.event_time.isoformat(),
            "model_version": signal.model_version,
            "calibration_version": signal.calibration_version,
            "feature_schema_version": signal.feature_schema_version,
            "data_cutoff": signal.data_cutoff.isoformat(),
            "feature_snapshot": signal.feature_snapshot,
        },
        "plans": replayed,
        "audit_chain": [
            {
                "id": event.id,
                "event_time": event.event_time.isoformat(),
                "event_type": event.event_type,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "previous_hash": event.previous_hash,
                "event_hash": event.event_hash,
                "payload": event.payload,
            }
            for event in events
        ],
    }


async def async_main(args: argparse.Namespace) -> None:
    data = await replay(UUID(args.signal_id))
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)
    await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a deterministic recommendation replay bundle")
    parser.add_argument("--signal-id", required=True)
    parser.add_argument("--output", default="reports/replay.json")
    args = parser.parse_args()
    run_with_compatible_event_loop(async_main(args))


if __name__ == "__main__":
    main()

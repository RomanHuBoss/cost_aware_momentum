from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.asyncio_compat import run_with_compatible_event_loop
from app.db.engine import SessionFactory, dispose_engine
from app.db.models import AuditEvent, ExecutionPlan, MarketSignal
from app.risk.math import CostScenario, InstrumentConstraints, calculate_position_plan


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
            snapshot = plan.sizing_snapshot or {}
            instrument = snapshot.get("instrument") or {}
            costs_data = snapshot.get("costs") or {}
            constraints = InstrumentConstraints(
                qty_step=Decimal(str(instrument.get("qty_step", "1"))),
                min_qty=Decimal(str(instrument.get("min_qty", "1"))),
                min_notional=Decimal(str(instrument.get("min_notional", "0"))),
                max_qty=(
                    Decimal(str(instrument["max_qty"])) if instrument.get("max_qty") is not None else None
                ),
                max_leverage=Decimal(str(instrument.get("max_leverage", plan.leverage))),
            )
            costs = CostScenario(
                fee_rate_round_trip=Decimal(str(costs_data.get("fee_rate_round_trip", "0"))),
                slippage_rate=Decimal(str(costs_data.get("slippage_rate", "0"))),
                stop_gap_reserve_rate=Decimal(str(costs_data.get("stop_gap_reserve_rate", "0"))),
                funding_rate=Decimal(str(costs_data.get("funding_rate", "0"))),
            )
            recomputed = calculate_position_plan(
                effective_capital=plan.effective_capital,
                risk_rate=plan.risk_rate,
                entry=signal.entry_reference,
                stop=signal.stop_loss,
                direction=signal.direction,
                costs=costs,
                constraints=constraints,
                leverage=plan.leverage,
                capital_verified=plan.capital_verified,
            )
            replayed.append(
                {
                    "plan_id": str(plan.id),
                    "version": plan.version,
                    "stored_status": plan.status,
                    "stored_qty": str(plan.qty),
                    "recomputed_qty_without_dynamic_caps": str(recomputed.qty),
                    "stored_actual_stress_loss": str(plan.actual_stress_loss),
                    "recomputed_actual_stress_loss_without_dynamic_caps": str(recomputed.actual_stress_loss),
                    "note": "Dynamic margin/liquidity/portfolio caps are preserved in the snapshot but not reapplied by this compact replay.",
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

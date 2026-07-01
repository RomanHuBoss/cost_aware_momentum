from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.risk.math import (
    CostScenario,
    InstrumentConstraints,
    finite_decimal,
    nonnegative_finite_decimal,
    positive_finite_decimal,
    validate_cost_scenario,
)


def snapshot_mapping(value: object, name: str = "plan.sizing_snapshot") -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def snapshot_section(snapshot: object, section: str) -> Mapping[str, Any]:
    root = snapshot_mapping(snapshot)
    if section not in root:
        raise ValueError(f"plan.{section} is required")
    value = root[section]
    if not isinstance(value, Mapping):
        raise ValueError(f"plan.{section} must be an object")
    return value


def _required_value(values: Mapping[str, Any], key: str, *, prefix: str) -> Any:
    if key not in values or values[key] is None or values[key] == "":
        raise ValueError(f"{prefix}.{key} is required")
    return values[key]


def plan_trading_costs(snapshot: object) -> CostScenario:
    costs = snapshot_section(snapshot, "costs")
    return validate_cost_scenario(
        CostScenario(
            fee_rate_round_trip=nonnegative_finite_decimal(
                _required_value(costs, "fee_rate_round_trip", prefix="plan.costs"),
                "plan.costs.fee_rate_round_trip",
            ),
            slippage_rate=nonnegative_finite_decimal(
                _required_value(costs, "slippage_rate", prefix="plan.costs"),
                "plan.costs.slippage_rate",
            ),
            stop_gap_reserve_rate=nonnegative_finite_decimal(
                _required_value(costs, "stop_gap_reserve_rate", prefix="plan.costs"),
                "plan.costs.stop_gap_reserve_rate",
            ),
            funding_rate=Decimal("0"),
        )
    )


def plan_cost_scenario(snapshot: object) -> CostScenario:
    trading = plan_trading_costs(snapshot)
    costs = snapshot_section(snapshot, "costs")
    return CostScenario(
        fee_rate_round_trip=trading.fee_rate_round_trip,
        slippage_rate=trading.slippage_rate,
        stop_gap_reserve_rate=trading.stop_gap_reserve_rate,
        funding_rate=finite_decimal(
            _required_value(costs, "funding_rate", prefix="plan.costs"),
            "plan.costs.funding_rate",
        ),
    )


def plan_instrument_constraints(snapshot: object) -> InstrumentConstraints:
    instrument = snapshot_section(snapshot, "instrument")
    raw_max_qty = instrument.get("max_qty")
    max_qty = (
        None
        if raw_max_qty is None
        else positive_finite_decimal(raw_max_qty, "plan.instrument.max_qty")
    )
    return InstrumentConstraints(
        qty_step=positive_finite_decimal(
            _required_value(instrument, "qty_step", prefix="plan.instrument"),
            "plan.instrument.qty_step",
        ),
        min_qty=positive_finite_decimal(
            _required_value(instrument, "min_qty", prefix="plan.instrument"),
            "plan.instrument.min_qty",
        ),
        min_notional=positive_finite_decimal(
            _required_value(instrument, "min_notional", prefix="plan.instrument"),
            "plan.instrument.min_notional",
        ),
        max_qty=max_qty,
        max_leverage=positive_finite_decimal(
            _required_value(instrument, "max_leverage", prefix="plan.instrument"),
            "plan.instrument.max_leverage",
        ),
    )


def plan_entry_price(snapshot: object) -> Decimal:
    root = snapshot_mapping(snapshot)
    return positive_finite_decimal(
        _required_value(root, "entry_price", prefix="plan"),
        "plan.entry_price",
    )


def plan_planning_time(snapshot: object) -> datetime:
    root = snapshot_mapping(snapshot)
    raw_time = _required_value(root, "planning_time", prefix="plan")
    try:
        value = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("plan.planning_time must be a valid ISO timestamp") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("plan.planning_time must be timezone-aware")
    return value

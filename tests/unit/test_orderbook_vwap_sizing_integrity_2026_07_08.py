from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.config import Settings
from app.risk.math import CostScenario, InstrumentConstraints, calculate_position_plan
from app.services.execution import (
    orderbook_depth_notional_cap,
    orderbook_fill_for_qty,
    validate_execution_plan_for_acceptance,
)


def D(value: str) -> Decimal:
    return Decimal(value)


def _snapshot(*, direction: str) -> SimpleNamespace:
    if direction == "LONG":
        return SimpleNamespace(
            bids=[["99.9", "10"]],
            asks=[["100", "1"], ["100.1", "1"]],
        )
    return SimpleNamespace(
        bids=[["100", "1"], ["99.9", "1"]],
        asks=[["100.1", "10"]],
    )


def _depth_limited_plan(*, direction: str, entry: Decimal, stop: Decimal, take_profit: Decimal):
    snapshot = _snapshot(direction=direction)
    depth_cap = orderbook_depth_notional_cap(
        snapshot,
        direction=direction,
        max_impact_bps=D("20"),
    )
    plan = calculate_position_plan(
        effective_capital=D("100000"),
        risk_rate=D("0.10"),
        entry=entry,
        stop=stop,
        take_profit=take_profit,
        direction=direction,
        costs=CostScenario(D("0"), D("0"), D("0"), D("0")),
        constraints=InstrumentConstraints(
            qty_step=D("0.001"),
            min_qty=D("0.001"),
            min_notional=D("5"),
            max_qty=None,
            max_leverage=D("10"),
        ),
        leverage=1,
        liquidity_notional_cap=depth_cap,
        capital_verified=True,
    )
    fill = orderbook_fill_for_qty(
        snapshot,
        direction=direction,
        qty=plan.qty,
        max_impact_bps=D("20"),
    )
    return depth_cap, plan, fill


def test_long_depth_sizing_cap_never_requests_more_than_fillable_quantity() -> None:
    depth_cap, plan, fill = _depth_limited_plan(
        direction="LONG",
        entry=D("100"),
        stop=D("99"),
        take_profit=D("102"),
    )

    assert depth_cap == D("200")
    assert plan.qty <= fill.available_qty
    assert fill.status == "FULL"


def test_short_depth_sizing_cap_never_requests_more_than_fillable_quantity() -> None:
    depth_cap, plan, fill = _depth_limited_plan(
        direction="SHORT",
        entry=D("100"),
        stop=D("101"),
        take_profit=D("98"),
    )

    assert depth_cap == D("199.8")
    assert plan.qty <= fill.available_qty
    assert fill.status == "FULL"


def test_acceptance_allows_aggregate_vwap_between_valid_price_ticks() -> None:
    plan = SimpleNamespace(
        qty=D("1.5"),
        leverage=1,
        sizing_snapshot={"costs": {"funding_rate": "0"}},
    )
    signal = SimpleNamespace(
        direction="LONG",
        entry_reference=D("100"),
        entry_low=D("99"),
        entry_high=D("101"),
        stop_loss=D("98"),
        take_profit_1=D("104"),
        fee_rate_round_trip=D("0"),
        slippage_rate=D("0"),
        p_tp=0.90,
        p_sl=0.05,
        p_timeout=0.05,
    )
    profile = SimpleNamespace(
        risk_rate=D("0.10"),
        max_total_risk_rate=D("0.20"),
        margin_reserve_rate=D("0.25"),
        default_leverage=1,
        max_leverage=5,
        mode="manual",
    )
    risk_state = SimpleNamespace(
        effective_capital=D("100000"),
        available_margin=D("100000"),
        reserved_margin_usdt=D("0"),
    )
    spec = SimpleNamespace(
        qty_step=D("0.001"),
        min_qty=D("0.001"),
        min_notional=D("5"),
        max_qty=D("1000"),
        max_leverage=D("100"),
        tick_size=D("0.1"),
    )

    result = validate_execution_plan_for_acceptance(
        plan=plan,
        signal=signal,
        profile=profile,
        risk_state=risk_state,
        spec=spec,
        executable_price=D("100.0333333333333333333333333"),
        current_funding_rate=D("0"),
        current_liquidity_notional_cap=D("100000"),
        settings=Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            min_net_rr=0,
            min_net_ev_r=0,
            max_total_open_risk_rate=0.20,
        ),
    )

    assert result.current_notional == D("150.04999999999999999999999995")

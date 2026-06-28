from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.risk.math import (
    CostScenario,
    InstrumentConstraints,
    calculate_position_plan,
    floor_to_step,
    funding_cash_flow,
    gross_pnl,
    net_rr_and_ev,
    projected_funding_rate,
)

D = Decimal


def costs() -> CostScenario:
    return CostScenario(D("0.0011"), D("0.0008"), D("0.0010"), D("0"))


def constraints() -> InstrumentConstraints:
    return InstrumentConstraints(D("0.001"), D("0.001"), D("5"), D("1000000"), D("100"))


def test_long_short_pnl_symmetry() -> None:
    assert gross_pnl("LONG", D("2"), D("100"), D("110")) == D("20")
    assert gross_pnl("SHORT", D("2"), D("100"), D("90")) == D("20")
    assert gross_pnl("SHORT", D("2"), D("100"), D("110")) == D("-20")


def test_funding_sign() -> None:
    assert funding_cash_flow("LONG", D("1000"), D("0.0001")) == D("-0.1")
    assert funding_cash_flow("SHORT", D("1000"), D("0.0001")) == D("0.1")
    assert funding_cash_flow("LONG", D("1000"), D("-0.0001")) == D("0.1")


def test_floor_never_rounds_risk_up() -> None:
    assert floor_to_step(D("0.977654"), D("0.001")) == D("0.977")


def test_reference_sizing_500_usdt() -> None:
    plan = calculate_position_plan(
        effective_capital=D("500"),
        risk_rate=D("0.0035"),
        entry=D("100"),
        stop=D("98.5"),
        direction="LONG",
        costs=costs(),
        constraints=constraints(),
        leverage=3,
        capital_verified=False,
    )
    assert plan.status == "ACTIONABLE"
    assert plan.risk_budget == D("1.7500")
    assert plan.qty == D("0.977")
    assert plan.notional == D("97.700")
    assert plan.actual_stress_loss <= plan.risk_budget
    assert plan.margin_estimate == plan.notional / D("3")


def test_leverage_does_not_change_notional_or_risk() -> None:
    base = dict(
        effective_capital=D("5000"),
        risk_rate=D("0.0035"),
        entry=D("100"),
        stop=D("98.5"),
        direction="LONG",
        costs=costs(),
        constraints=constraints(),
        capital_verified=True,
    )
    plan3 = calculate_position_plan(**base, leverage=3)
    plan5 = calculate_position_plan(**base, leverage=5)
    assert plan3.notional == plan5.notional
    assert plan3.actual_stress_loss == plan5.actual_stress_loss
    assert plan5.margin_estimate < plan3.margin_estimate


def test_minimum_order_is_blocked_not_rounded_up() -> None:
    strict = InstrumentConstraints(D("1"), D("1"), D("100"), None, D("5"))
    plan = calculate_position_plan(
        effective_capital=D("100"),
        risk_rate=D("0.001"),
        entry=D("100"),
        stop=D("99"),
        direction="LONG",
        costs=costs(),
        constraints=strict,
        leverage=3,
    )
    assert plan.status == "BLOCKED_MIN_SIZE"
    assert plan.actual_stress_loss <= plan.risk_budget


def test_liquidity_cap_produces_limited_plan() -> None:
    plan = calculate_position_plan(
        effective_capital=D("10000"),
        risk_rate=D("0.01"),
        entry=D("100"),
        stop=D("98"),
        direction="LONG",
        costs=costs(),
        constraints=constraints(),
        leverage=3,
        liquidity_notional_cap=D("500"),
        capital_verified=True,
    )
    assert plan.status == "LIMITED"
    assert plan.limiting_cap == "LIQUIDITY"
    assert plan.notional <= D("500")


def test_net_rr_and_ev_reference_arithmetic() -> None:
    rr, ev_r, downside, upside = net_rr_and_ev(
        entry=D("100"),
        stop=D("98.5"),
        take_profit=D("103.6"),
        direction="LONG",
        costs=costs(),
        p_tp=0.42,
        p_sl=0.48,
        p_timeout=0.10,
    )
    assert downside == D("0.0179")
    assert upside == D("0.0341")
    assert float(rr) == pytest.approx(1.905, rel=1e-3)
    assert ev_r > 0


@pytest.mark.parametrize(
    ("direction", "stop", "take_profit"),
    [
        ("LONG", D("101"), D("110")),
        ("LONG", D("90"), D("99")),
        ("SHORT", D("99"), D("90")),
        ("SHORT", D("110"), D("101")),
    ],
)
def test_net_metrics_reject_inverted_directional_geometry(
    direction: str, stop: Decimal, take_profit: Decimal
) -> None:
    with pytest.raises(ValueError, match="geometry"):
        net_rr_and_ev(
            entry=D("100"),
            stop=stop,
            take_profit=take_profit,
            direction=direction,  # type: ignore[arg-type]
            costs=costs(),
            p_tp=0.5,
            p_sl=0.4,
            p_timeout=0.1,
        )


def test_position_sizing_blocks_inverted_stop_geometry() -> None:
    plan = calculate_position_plan(
        effective_capital=D("5000"),
        risk_rate=D("0.0035"),
        entry=D("100"),
        stop=D("101"),
        take_profit=D("110"),
        direction="LONG",
        costs=costs(),
        constraints=constraints(),
        leverage=3,
        capital_verified=True,
    )
    assert plan.status == "BLOCKED_INVALID_INPUT"
    assert plan.qty == D("0")
    assert plan.notional == D("0")
    assert plan.actual_stress_loss == D("0")
    assert plan.limiting_cap == "INVALID_GEOMETRY"
    assert any("LONG geometry" in warning for warning in plan.warnings)


@pytest.mark.parametrize("invalid_price", [D("NaN"), D("Infinity")])
def test_net_metrics_reject_non_finite_barrier_prices(invalid_price: Decimal) -> None:
    with pytest.raises(ValueError, match="positive and finite"):
        net_rr_and_ev(
            entry=D("100"),
            stop=D("90"),
            take_profit=invalid_price,
            direction="LONG",
            costs=costs(),
            p_tp=0.5,
            p_sl=0.4,
            p_timeout=0.1,
        )


def test_funding_applies_only_when_settlement_is_crossed() -> None:
    start = datetime(2026, 6, 25, 10, tzinfo=UTC)
    assert projected_funding_rate(
        start_time=start,
        horizon_hours=4,
        next_settlement=datetime(2026, 6, 25, 16, tzinfo=UTC),
        interval_minutes=480,
        current_rate=D("0.0001"),
    ) == D("0")
    assert projected_funding_rate(
        start_time=start,
        horizon_hours=12,
        next_settlement=datetime(2026, 6, 25, 16, tzinfo=UTC),
        interval_minutes=480,
        current_rate=D("0.0001"),
    ) == D("0.0001")
    assert projected_funding_rate(
        start_time=start,
        horizon_hours=24,
        next_settlement=datetime(2026, 6, 25, 16, tzinfo=UTC),
        interval_minutes=480,
        current_rate=D("0.0001"),
    ) == D("0.0003")


def test_zero_portfolio_capacity_has_portfolio_block_status() -> None:
    plan = calculate_position_plan(
        effective_capital=D("5000"),
        risk_rate=D("0.0035"),
        entry=D("100"),
        stop=D("98.5"),
        direction="LONG",
        costs=costs(),
        constraints=constraints(),
        leverage=3,
        portfolio_notional_cap=D("0"),
        capital_verified=True,
    )
    assert plan.status == "BLOCKED_PORTFOLIO"
    assert plan.limiting_cap == "PORTFOLIO"


def test_zero_margin_capacity_has_margin_block_status() -> None:
    plan = calculate_position_plan(
        effective_capital=D("5000"),
        risk_rate=D("0.0035"),
        entry=D("100"),
        stop=D("98.5"),
        direction="LONG",
        costs=costs(),
        constraints=constraints(),
        leverage=3,
        available_margin=D("0"),
        capital_verified=True,
    )
    assert plan.status == "BLOCKED_MARGIN"

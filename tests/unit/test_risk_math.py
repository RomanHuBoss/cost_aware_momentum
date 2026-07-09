from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.risk.math import (
    CostScenario,
    InstrumentConstraints,
    calculate_position_plan,
    fee_cash,
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
    assert plan.qty == D("0.978")
    assert plan.notional == D("97.800")
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
    assert downside == D("0.01789175")
    assert upside == D("0.03408020")
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


def _valid_position_plan_kwargs() -> dict:
    return {
        "effective_capital": D("5000"),
        "risk_rate": D("0.0035"),
        "entry": D("100"),
        "stop": D("98.5"),
        "take_profit": D("103.6"),
        "direction": "LONG",
        "costs": costs(),
        "constraints": constraints(),
        "leverage": 3,
        "capital_verified": True,
    }


@pytest.mark.parametrize(
    ("changes", "diagnostic"),
    [
        ({"effective_capital": D("NaN")}, "effective_capital"),
        ({"risk_rate": D("Infinity")}, "risk_rate"),
        ({"available_margin": D("NaN")}, "available_margin"),
        ({"margin_reserve_rate": D("1")}, "margin_reserve_rate"),
        ({"liquidity_notional_cap": D("NaN")}, "liquidity_notional_cap"),
        (
            {"constraints": InstrumentConstraints(D("0"), D("0.001"), D("5"), D("1000000"), D("100"))},
            "qty_step",
        ),
        (
            {"costs": CostScenario(D("-0.0011"), D("0.0008"), D("0.0010"), D("0"))},
            "fee_rate_round_trip",
        ),
    ],
)
def test_position_sizing_blocks_invalid_numeric_inputs(changes: dict, diagnostic: str) -> None:
    plan = calculate_position_plan(**(_valid_position_plan_kwargs() | changes))

    assert plan.status == "BLOCKED_INVALID_INPUT"
    assert plan.qty == D("0")
    assert plan.notional == D("0")
    assert plan.actual_stress_loss == D("0")
    assert plan.margin_estimate == D("0")
    assert plan.limiting_cap == "INVALID_INPUT"
    assert all(value.is_finite() for value in (plan.effective_capital, plan.risk_budget))
    assert any(diagnostic in warning for warning in plan.warnings)


def test_position_sizing_accepts_finite_signed_funding_rate() -> None:
    plan = calculate_position_plan(
        **(
            _valid_position_plan_kwargs()
            | {"costs": CostScenario(D("0.0011"), D("0.0008"), D("0.0010"), D("-0.0001"))}
        )
    )

    assert plan.status == "ACTIONABLE"
    assert plan.qty > 0


def test_fee_math_uses_each_barrier_leg_notional() -> None:
    fee_only = CostScenario(D("0.001"), D("0"), D("0"), D("0"))

    long_rr, _, long_downside, long_upside = net_rr_and_ev(
        entry=D("100"),
        stop=D("90"),
        take_profit=D("110"),
        direction="LONG",
        costs=fee_only,
        p_tp=0.5,
        p_sl=0.5,
        p_timeout=0.0,
    )
    short_rr, _, short_downside, short_upside = net_rr_and_ev(
        entry=D("100"),
        stop=D("110"),
        take_profit=D("90"),
        direction="SHORT",
        costs=fee_only,
        p_tp=0.5,
        p_sl=0.5,
        p_timeout=0.0,
    )

    # fee_rate_round_trip=0.1% means 0.05% on entry and 0.05% on exit.
    # Rates below are normalized by entry notional, so the exit leg depends on
    # the actual stop/TP price rather than being fixed at entry notional.
    assert long_downside == D("0.10095")
    assert long_upside == D("0.09895")
    assert short_downside == D("0.10105")
    assert short_upside == D("0.09905")
    assert long_rr == long_upside / long_downside
    assert short_rr == short_upside / short_downside


def test_projected_funding_excludes_settlement_at_exact_start_boundary() -> None:
    start = datetime(2026, 6, 25, 16, tzinfo=UTC)

    assert projected_funding_rate(
        start_time=start,
        horizon_hours=8,
        next_settlement=start,
        interval_minutes=480,
        current_rate=D("0.0001"),
    ) == D("0.0001")


def test_exchange_cap_block_is_not_reported_as_min_order() -> None:
    plan = calculate_position_plan(
        effective_capital=D("5000"),
        risk_rate=D("0.0035"),
        entry=D("100"),
        stop=D("98.5"),
        direction="LONG",
        costs=costs(),
        constraints=constraints(),
        leverage=3,
        exchange_notional_cap=D("0"),
        capital_verified=True,
    )
    assert plan.status == "BLOCKED_EXCHANGE"
    assert plan.limiting_cap == "EXCHANGE"
    assert any("бирж" in warning.lower() for warning in plan.warnings)


def test_exchange_cap_limited_plan_has_operator_warning() -> None:
    plan = calculate_position_plan(
        effective_capital=D("50000"),
        risk_rate=D("0.0035"),
        entry=D("100"),
        stop=D("98.5"),
        direction="LONG",
        costs=costs(),
        constraints=constraints(),
        leverage=3,
        exchange_notional_cap=D("500"),
        capital_verified=True,
    )
    assert plan.status == "LIMITED"
    assert plan.limiting_cap == "EXCHANGE"
    assert plan.notional <= D("500")
    assert any("бирж" in warning.lower() for warning in plan.warnings)


def test_funding_cash_flow_rejects_negative_position_value() -> None:
    with pytest.raises(ValueError, match="position_value"):
        funding_cash_flow("LONG", D("-1000"), D("0.0001"))


def test_fee_cash_rejects_negative_fee_rate() -> None:
    with pytest.raises(ValueError, match="fee_rate"):
        fee_cash(D("1"), D("100"), D("-0.001"))

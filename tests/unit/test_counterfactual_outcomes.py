from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.api.serializers import counterfactual_outcome_dict
from app.services.outcomes import (
    OutcomeBar,
    _funding_rate_for_holding_period,
    estimate_plan_outcome,
    evaluate_barrier_outcome,
)

BASE = datetime(2026, 6, 28, 12, tzinfo=UTC)


def bar(hour: int, *, high: str, low: str, close: str) -> OutcomeBar:
    start = BASE + timedelta(hours=hour)
    return OutcomeBar(
        candle_id=hour + 1,
        open_time=start,
        close_time=start + timedelta(hours=1),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
    )


def test_long_tp_resolves_before_horizon() -> None:
    result = evaluate_barrier_outcome(
        [
            bar(0, high="103", low="99", close="102"),
            bar(1, high="104.5", low="101", close="104"),
        ],
        direction="LONG",
        entry=Decimal("100"),
        stop=Decimal("98"),
        take_profit=Decimal("104"),
        window_start=BASE,
        horizon_end=BASE + timedelta(hours=4),
    )

    assert result is not None
    assert result.outcome == "TP"
    assert result.exit_price == Decimal("104")
    assert result.exit_time == BASE + timedelta(hours=2)
    assert result.source_candle_id == 2
    assert result.bars_evaluated == 2
    assert result.ambiguous is False


def test_short_tp_resolves_with_directional_geometry() -> None:
    result = evaluate_barrier_outcome(
        [bar(0, high="101", low="95.5", close="96")],
        direction="SHORT",
        entry=Decimal("100"),
        stop=Decimal("103"),
        take_profit=Decimal("96"),
        window_start=BASE,
        horizon_end=BASE + timedelta(hours=4),
    )

    assert result is not None
    assert result.outcome == "TP"
    assert result.exit_price == Decimal("96")


def test_same_bar_tp_and_sl_is_conservative_sl() -> None:
    result = evaluate_barrier_outcome(
        [bar(0, high="105", low="97", close="101")],
        direction="LONG",
        entry=Decimal("100"),
        stop=Decimal("98"),
        take_profit=Decimal("104"),
        window_start=BASE,
        horizon_end=BASE + timedelta(hours=4),
    )

    assert result is not None
    assert result.outcome == "SL"
    assert result.exit_price == Decimal("98")
    assert result.ambiguous is True


def test_timeout_waits_for_complete_horizon() -> None:
    result = evaluate_barrier_outcome(
        [bar(0, high="102", low="99", close="101")],
        direction="LONG",
        entry=Decimal("100"),
        stop=Decimal("98"),
        take_profit=Decimal("104"),
        window_start=BASE,
        horizon_end=BASE + timedelta(hours=2),
    )

    assert result is None


def test_missing_bar_keeps_outcome_pending() -> None:
    result = evaluate_barrier_outcome(
        [bar(1, high="105", low="99", close="104")],
        direction="LONG",
        entry=Decimal("100"),
        stop=Decimal("98"),
        take_profit=Decimal("104"),
        window_start=BASE,
        horizon_end=BASE + timedelta(hours=2),
    )

    assert result is None


def test_timeout_uses_confirmed_horizon_close() -> None:
    result = evaluate_barrier_outcome(
        [
            bar(0, high="102", low="99", close="101"),
            bar(1, high="103", low="99.5", close="102.25"),
        ],
        direction="LONG",
        entry=Decimal("100"),
        stop=Decimal("98"),
        take_profit=Decimal("104"),
        window_start=BASE,
        horizon_end=BASE + timedelta(hours=2),
    )

    assert result is not None
    assert result.outcome == "TIMEOUT"
    assert result.exit_price == Decimal("102.25")
    assert result.exit_time == BASE + timedelta(hours=2)
    assert result.source_candle_id == 2


def test_invalid_directional_geometry_fails_closed() -> None:
    with pytest.raises(ValueError, match="LONG geometry"):
        evaluate_barrier_outcome(
            [bar(0, high="105", low="97", close="101")],
            direction="LONG",
            entry=Decimal("100"),
            stop=Decimal("101"),
            take_profit=Decimal("104"),
            window_start=BASE,
            horizon_end=BASE + timedelta(hours=4),
        )


def test_plan_estimate_uses_snapshot_costs_and_risk_unit() -> None:
    estimate = estimate_plan_outcome(
        direction="LONG",
        outcome="TP",
        qty=Decimal("2"),
        entry_price=Decimal("100"),
        exit_price=Decimal("104"),
        actual_stress_loss=Decimal("5"),
        fee_rate_round_trip=Decimal("0.001"),
        slippage_rate=Decimal("0.0005"),
        stop_gap_reserve_rate=Decimal("0.001"),
        funding_rate=Decimal("0.0002"),
    )

    assert estimate.valuation_status == "VALUED"
    assert estimate.gross_pnl == Decimal("8")
    assert estimate.estimated_trading_costs == Decimal("0.3040")
    assert estimate.estimated_funding_cash_flow == Decimal("-0.0400")
    assert estimate.estimated_net_pnl == Decimal("7.6560")
    assert estimate.counterfactual_r == Decimal("1.5312")


def test_unsized_plan_still_gets_market_outcome_without_fake_r() -> None:
    estimate = estimate_plan_outcome(
        direction="SHORT",
        outcome="SL",
        qty=Decimal("0"),
        entry_price=Decimal("100"),
        exit_price=Decimal("103"),
        actual_stress_loss=Decimal("0"),
        fee_rate_round_trip=Decimal("0.001"),
        slippage_rate=Decimal("0.0005"),
        stop_gap_reserve_rate=Decimal("0.001"),
        funding_rate=Decimal("0.0002"),
    )

    assert estimate.valuation_status == "NOT_SIZED"
    assert estimate.estimated_net_pnl == Decimal("0")
    assert estimate.counterfactual_r is None


def test_funding_uses_only_settlements_crossed_before_exit() -> None:
    plan = SimpleNamespace(
        sizing_snapshot={
            "costs": {
                "funding_rate_per_settlement": "0.0001",
                "funding_next_settlement": (BASE + timedelta(hours=1)).isoformat(),
                "funding_interval_minutes": 120,
            }
        }
    )

    rate, complete, details = _funding_rate_for_holding_period(
        plan, start_time=BASE, exit_time=BASE + timedelta(hours=4)
    )

    assert complete is True
    assert rate == Decimal("0.0002")
    assert details["settlements"] == 2


def test_legacy_plan_does_not_charge_unverifiable_full_horizon_funding() -> None:
    plan = SimpleNamespace(sizing_snapshot={"costs": {"funding_rate": "0.0008"}})

    rate, complete, details = _funding_rate_for_holding_period(
        plan, start_time=BASE, exit_time=BASE + timedelta(hours=4)
    )
    estimate = estimate_plan_outcome(
        direction="LONG",
        outcome="TIMEOUT",
        qty=Decimal("1"),
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        actual_stress_loss=Decimal("2"),
        fee_rate_round_trip=Decimal("0.001"),
        slippage_rate=Decimal("0.0005"),
        stop_gap_reserve_rate=Decimal("0.001"),
        funding_rate=rate,
        funding_complete=complete,
    )

    assert rate == Decimal("0")
    assert details["source"] == "legacy_plan_snapshot"
    assert estimate.valuation_status == "FUNDING_UNAVAILABLE"
    assert estimate.counterfactual_r is None


def test_counterfactual_serializer_preserves_null_r_and_plan_version() -> None:
    signal_outcome = SimpleNamespace(
        outcome="TIMEOUT",
        exit_price=Decimal("101.25"),
        exit_time=BASE + timedelta(hours=4),
        horizon_end=BASE + timedelta(hours=4),
        bars_evaluated=4,
        ambiguous=False,
        evaluation_version="primary-barrier-hourly-v1",
        resolved_at=BASE + timedelta(hours=4, minutes=1),
        details={"actual_execution_pnl": False},
    )
    plan_outcome = SimpleNamespace(
        plan_id="plan-id",
        plan_version=3,
        valuation_status="FUNDING_UNAVAILABLE",
        qty=Decimal("1"),
        entry_price=Decimal("100"),
        exit_price=Decimal("101.25"),
        gross_pnl=Decimal("1.25"),
        estimated_trading_costs=Decimal("0.15"),
        estimated_funding_cash_flow=Decimal("0"),
        estimated_net_pnl=Decimal("1.10"),
        counterfactual_r=None,
        cost_assumptions={"actual_execution_pnl": False},
    )

    payload = counterfactual_outcome_dict(signal_outcome, plan_outcome)

    assert payload is not None
    assert payload["outcome"] == "TIMEOUT"
    assert payload["plan"]["plan_version"] == 3
    assert payload["plan"]["counterfactual_r"] is None
    assert payload["details"]["actual_execution_pnl"] is False

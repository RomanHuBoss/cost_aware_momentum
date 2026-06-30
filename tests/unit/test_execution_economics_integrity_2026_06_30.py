from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.api.serializers import detail_dict
from app.risk.math import (
    CostScenario,
    break_even_tp_probability,
    net_outcome_rates,
    net_rr_and_ev,
)
from app.services.execution import effective_capital

D = Decimal
DEFAULT_PLAN_ENTRY = D("101")


class _UnexpectedQuerySession:
    execute = AsyncMock(side_effect=AssertionError("database must not be queried"))


def _signal_and_plan(*, plan_entry: Decimal = DEFAULT_PLAN_ENTRY) -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace]:
    now = datetime.now(UTC)
    signal = SimpleNamespace(
        id=uuid4(),
        symbol="BTCUSDT",
        direction="LONG",
        status="PUBLISHED",
        expires_at=now + timedelta(hours=1),
        entry_low=D("99"),
        entry_high=D("102"),
        entry_reference=D("100"),
        stop_loss=D("98"),
        take_profit_1=D("105"),
        gross_rr=2.5,
        net_rr=2.0,
        net_ev_r=0.40,
        gross_edge_rate=0.05,
        fee_rate_round_trip=0.001,
        slippage_rate=0.0004,
        funding_rate_scenario=0.0002,
        stress_downside_rate=0.025,
        p_tp=0.45,
        p_sl=0.35,
        p_timeout=0.20,
        horizon_hours=4,
        model_version="model-v1",
        calibration_version="cal-v1",
        feature_schema_version="features-v1",
        reasons=["test"],
        feature_snapshot={},
        warnings=[],
        natural_key="BTCUSDT:test",
        created_at=now,
        publish_time=now,
        data_cutoff=now,
    )
    costs = CostScenario(D("0.001"), D("0.0004"), D("0.001"), D("0.0002"))
    plan_rr, plan_ev, plan_downside, _ = net_rr_and_ev(
        entry=plan_entry,
        stop=signal.stop_loss,
        take_profit=signal.take_profit_1,
        direction=signal.direction,
        costs=costs,
        p_tp=signal.p_tp,
        p_sl=signal.p_sl,
        p_timeout=signal.p_timeout,
    )
    rates = net_outcome_rates(
        entry=plan_entry,
        stop=signal.stop_loss,
        take_profit=signal.take_profit_1,
        direction=signal.direction,
        costs=costs,
    )
    break_even = break_even_tp_probability(
        downside_rate=rates.downside_rate,
        upside_rate=rates.upside_rate,
        timeout_net_rate=rates.timeout_net_rate,
        p_timeout=signal.p_timeout,
    )
    plan = SimpleNamespace(
        id=uuid4(),
        version=2,
        status="ACTIONABLE",
        actual_stress_loss=D("12"),
        risk_budget=D("15"),
        notional=D("500"),
        qty=D("4.950"),
        margin_estimate=D("166.67"),
        leverage=3,
        primary_warning=None,
        effective_capital=D("5000"),
        capital_verified=True,
        risk_rate=D("0.003"),
        qty_raw=D("4.955"),
        liquidation_buffer_rate=0.20,
        limiting_cap=None,
        warnings=[],
        profile_version=1,
        created_at=now,
        sizing_snapshot={
            "entry_price": str(plan_entry),
            "economics_schema_version": "tp-sl-timeout-v1",
            "net_rr": str(plan_rr),
            "net_ev_r": str(plan_ev),
            "stress_downside_rate": str(plan_downside),
            "upside_rate": str(rates.upside_rate),
            "timeout_net_rate": str(rates.timeout_net_rate),
            "break_even_tp_probability": str(break_even),
            "costs": {
                "fee_rate_round_trip": str(costs.fee_rate_round_trip),
                "slippage_rate": str(costs.slippage_rate),
                "stop_gap_reserve_rate": str(costs.stop_gap_reserve_rate),
                "funding_rate": str(costs.funding_rate),
            },
        },
    )
    profile = SimpleNamespace(
        id=uuid4(),
        name="Test",
        allocated_capital=D("5000"),
    )
    return signal, plan, profile


def test_three_outcome_break_even_probability_zeroes_ev_with_fixed_timeout() -> None:
    downside = D("0.02")
    upside = D("0.04")
    timeout_net = D("-0.003")
    p_timeout = D("0.20")

    threshold = break_even_tp_probability(
        downside_rate=downside,
        upside_rate=upside,
        timeout_net_rate=timeout_net,
        p_timeout=p_timeout,
    )
    p_sl = D("1") - p_timeout - threshold
    ev = threshold * upside - p_sl * downside + p_timeout * timeout_net

    assert threshold == D("0.276666666666666666666666666666666667")
    assert abs(ev) < D("1e-34")
    assert threshold != D("1") / (D("1") + upside / downside)


def test_detail_distinguishes_signal_and_execution_plan_economics() -> None:
    signal, plan, profile = _signal_and_plan(plan_entry=D("101"))

    payload = detail_dict(signal, plan, profile, ticker=None)
    plan_economics = payload["economics"]["execution_plan"]

    assert payload["economics"]["scope"] == "MARKET_SIGNAL_REFERENCE"
    assert payload["economics"]["net_rr"] == signal.net_rr
    assert payload["economics"]["net_ev_r"] == signal.net_ev_r
    assert plan_economics["scope"] == "EXECUTION_PLAN_SNAPSHOT"
    assert plan_economics["available"] is True
    assert plan_economics["entry_price"] == 101.0
    assert plan_economics["net_rr"] != signal.net_rr
    assert plan_economics["net_ev_r"] != signal.net_ev_r


def test_detail_uses_timeout_aware_break_even_not_binary_rr_formula() -> None:
    signal, plan, profile = _signal_and_plan()

    payload = detail_dict(signal, plan, profile, ticker=None)
    threshold = D(str(payload["economics"]["break_even_tp_probability"]))
    binary_threshold = D("1") / (D("1") + D(str(signal.net_rr)))

    assert payload["economics"]["break_even_probability"] == float(threshold)
    assert payload["economics"]["break_even_probability_semantics"] == (
        "P_SL=1-P_TP-P_TIMEOUT; P_TIMEOUT fixed"
    )
    assert threshold != binary_threshold


def test_corrupted_execution_plan_economics_snapshot_is_not_presented_as_valid() -> None:
    signal, plan, profile = _signal_and_plan()
    plan.sizing_snapshot["net_ev_r"] = "NaN"

    payload = detail_dict(signal, plan, profile, ticker=None)
    economics = payload["economics"]["execution_plan"]

    assert economics["available"] is False
    assert economics["integrity_status"] == "INVALID_SNAPSHOT"
    assert economics["net_rr"] is None
    assert economics["net_ev_r"] is None


@pytest.mark.asyncio
async def test_read_only_profile_without_source_account_fails_closed() -> None:
    profile = SimpleNamespace(
        mode="bybit_read_only",
        source_account_id=None,
        allocated_capital=D("5000"),
        capital_verified=True,
    )

    capital, available_margin, verified, diagnostics = await effective_capital(
        _UnexpectedQuerySession(),
        profile,
    )

    assert capital == D("0")
    assert available_margin == D("0")
    assert verified is False
    assert diagnostics["missing_source_account_id"] is True


@pytest.mark.asyncio
async def test_unknown_profile_mode_fails_closed() -> None:
    profile = SimpleNamespace(
        mode="legacy-live",
        source_account_id=None,
        allocated_capital=D("5000"),
        capital_verified=True,
    )

    capital, available_margin, verified, diagnostics = await effective_capital(
        _UnexpectedQuerySession(),
        profile,
    )

    assert capital == D("0")
    assert available_margin == D("0")
    assert verified is False
    assert diagnostics["invalid_profile_mode"] == "legacy-live"


def test_frontend_labels_signal_and_plan_economics_and_handles_nullable_break_even() -> None:
    from pathlib import Path

    javascript = Path("web/js/app.js").read_text(encoding="utf-8")

    assert "Net R/R сигнала" in javascript
    assert "Execution plan · сохраненный расчет" in javascript
    assert "Порог P(TP) при текущем P(timeout)" in javascript
    assert "d.economics.break_even_probability * 100" not in javascript

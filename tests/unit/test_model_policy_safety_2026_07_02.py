from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.serializers import signal_economics_dict
from app.config import Settings
from app.ml.runtime import Prediction
from app.risk.math import CostScenario
from app.services.execution import validate_execution_plan_for_acceptance
from app.services.signals import select_cost_aware_scenario

D = Decimal


def _neutral_predictions() -> tuple[Prediction, Prediction]:
    common = {
        "p_tp": 0.34,
        "p_sl": 0.52,
        "p_timeout": 0.14,
        "score": 0.0,
        "model_version": "baseline-momentum-v1",
        "calibration_version": "uncalibrated-baseline-v1",
        "reasons": ("neutral baseline",),
    }
    return (
        Prediction(direction="LONG", **common),
        Prediction(direction="SHORT", **common),
    )


def test_timeout_assumption_is_explicit_in_signal_economics() -> None:
    costs = CostScenario(D("0.0011"), D("0.0003"), D("0.001"), D("0"))
    adverse_timeout = select_cost_aware_scenario(
        _neutral_predictions(),
        bid_price=D("99.99"),
        ask_price=D("100.01"),
        decision_anchor_price=D("100"),
        atr_pct=D("0.05"),
        costs=costs,
        timeout_return_rate=D("-0.002"),
    )
    flat_timeout = select_cost_aware_scenario(
        _neutral_predictions(),
        bid_price=D("99.99"),
        ask_price=D("100.01"),
        decision_anchor_price=D("100"),
        atr_pct=D("0.05"),
        costs=costs,
        timeout_return_rate=D("0"),
    )

    assert adverse_timeout.ev_r < flat_timeout.ev_r
    assert adverse_timeout.ev_r == pytest.approx(D("0.0885"), abs=D("0.001"))


def test_production_rejects_actionable_baseline_override() -> None:
    with pytest.raises(ValidationError, match="ALLOW_BASELINE_ACTIONABLE"):
        Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            app_mode="production",
            allow_demo_seed=False,
            allow_baseline_model=False,
            allow_baseline_actionable=True,
            secret_key="s" * 40,
            operator_password="p" * 16,
        )


def test_legacy_actionable_baseline_plan_cannot_be_accepted() -> None:
    signal = SimpleNamespace(
        feature_snapshot={"model_runtime": {"baseline": True}},
        calibration_version="uncalibrated-baseline-v1",
        model_version="baseline-momentum-v1",
    )
    with pytest.raises(ValueError, match="diagnostic-only"):
        validate_execution_plan_for_acceptance(
            plan=SimpleNamespace(),
            signal=signal,
            profile=SimpleNamespace(),
            risk_state=SimpleNamespace(),
            spec=SimpleNamespace(),
            executable_price=D("100"),
            current_funding_rate=D("0"),
            current_liquidity_notional_cap=D("1000"),
            settings=Settings(database_url="postgresql+psycopg://u:p@localhost/db"),
        )


def test_signal_serializer_uses_persisted_timeout_assumption() -> None:
    signal = SimpleNamespace(
        entry_reference=D("100"),
        stop_loss=D("98"),
        take_profit_1=D("104"),
        direction="LONG",
        fee_rate_round_trip=D("0"),
        slippage_rate=D("0"),
        funding_rate_scenario=D("0"),
        stress_downside_rate=D("0.02"),
        p_timeout=0.20,
        gross_rr=2.0,
        net_rr=2.0,
        net_ev_r=0.0,
        gross_edge_rate=0.04,
        feature_snapshot={
            "economics_assumptions": {"timeout_gross_return_rate": "-0.01"}
        },
    )

    payload = signal_economics_dict(signal)

    assert payload["timeout_gross_return_rate"] == pytest.approx(-0.01)

from __future__ import annotations

from decimal import Decimal

import pytest

from app.ml.runtime import Prediction
from app.risk.math import CostScenario
from app.services.signals import select_cost_aware_scenario

D = Decimal


def _equal_predictions() -> tuple[Prediction, Prediction]:
    common = {
        "p_tp": 0.50,
        "p_sl": 0.30,
        "p_timeout": 0.20,
        "score": 0.0,
        "model_version": "candidate-v1",
        "calibration_version": "cal-v1",
        "reasons": (),
    }
    return (
        Prediction(direction="LONG", **common),
        Prediction(direction="SHORT", **common),
    )


def test_market_signal_policy_rejects_unvalidated_expected_funding_overlay() -> None:
    """Promotion evidence uses no ex-ante funding forecast, so signal selection must too."""

    with pytest.raises(ValueError, match="expected funding.*execution plan"):
        select_cost_aware_scenario(
            _equal_predictions(),
            bid_price=D("100"),
            ask_price=D("100"),
            decision_anchor_price=D("100"),
            atr_pct=D("0.02"),
            costs=CostScenario(
                fee_rate_round_trip=D("0"),
                slippage_rate=D("0"),
                stop_gap_reserve_rate=D("0"),
                funding_rate=D("0.005"),
            ),
        )

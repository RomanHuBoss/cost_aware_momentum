from decimal import Decimal

import numpy as np
import pytest

from app.ml.context import MARKET_CONTEXT_FEATURE_NAMES
from app.ml.features import FEATURE_NAMES
from app.ml.runtime import ModelRuntime, Prediction
from app.risk.math import CostScenario
from app.services.signals import select_cost_aware_scenario

D = Decimal


class FixedScenarioModel:
    classes_ = np.array(["TP", "SL", "TIMEOUT"])

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        rows = []
        for row in x:
            if row[-1] > 0:
                rows.append([0.35, 0.40, 0.25])
            else:
                rows.append([0.20, 0.05, 0.75])
        return np.asarray(rows, dtype=float)


def test_runtime_exposes_both_directional_scenarios() -> None:
    runtime = ModelRuntime(None, allow_baseline=False)
    runtime.bundle = {"model": FixedScenarioModel()}
    runtime.version = "fixed-v1"
    runtime.calibration_version = "fixed-cal-v1"

    scenarios = runtime.predict_scenarios({**{name: 0.0 for name in FEATURE_NAMES}, **{name: 0.0 for name in MARKET_CONTEXT_FEATURE_NAMES}})

    assert [item.direction for item in scenarios] == ["LONG", "SHORT"]
    assert scenarios[0].p_tp == pytest.approx(0.35)
    assert scenarios[1].p_timeout == pytest.approx(0.75)


def test_signal_direction_is_selected_by_exact_net_ev_not_fixed_runtime_utility() -> None:
    predictions = (
        Prediction("LONG", 0.35, 0.40, 0.25, 0.0275, "fixed-v1", "fixed-cal-v1", ()),
        Prediction("SHORT", 0.20, 0.05, 0.75, -0.0275, "fixed-v1", "fixed-cal-v1", ()),
    )
    costs = CostScenario(
        fee_rate_round_trip=D("0.0011"),
        slippage_rate=D("0.0003"),
        stop_gap_reserve_rate=D("0.001"),
        funding_rate=D("0"),
    )

    selected = select_cost_aware_scenario(
        predictions,
        bid_price=D("99.95"),
        ask_price=D("100.05"),
        decision_anchor_price=D("100"),
        atr_pct=D("0.02"),
        costs=costs,
    )

    # The old runtime utility ranks LONG higher (0.2600 vs 0.2325), but the
    # exact live net-EV calculation ranks SHORT higher because TIMEOUT is a
    # small fixed loss rather than the runtime utility's fixed 0.20 ATR units.
    assert selected.prediction.direction == "SHORT"
    assert selected.ev_r == pytest.approx(D("0.1850803635197431200602849368"))
    assert selected.ev_r > D("0.1534")


def test_signal_geometry_uses_artifact_barrier_multipliers() -> None:
    predictions = (
        Prediction("LONG", 0.80, 0.10, 0.10, 1.0, "fixed-v1", "fixed-cal-v1", ()),
        Prediction("SHORT", 0.10, 0.80, 0.10, -1.0, "fixed-v1", "fixed-cal-v1", ()),
    )
    costs = CostScenario(
        fee_rate_round_trip=D("0"),
        slippage_rate=D("0"),
        stop_gap_reserve_rate=D("0"),
        funding_rate=D("0"),
    )

    selected = select_cost_aware_scenario(
        predictions,
        bid_price=D("100"),
        ask_price=D("100"),
        decision_anchor_price=D("100"),
        atr_pct=D("0.02"),
        costs=costs,
        stop_atr_multiplier=2.0,
        tp_atr_multiplier=4.0,
    )

    assert selected.stop == D("96")
    assert selected.take_profit_1 == D("108")


def test_signal_geometry_rejects_non_finite_barrier_multiplier() -> None:
    predictions = (
        Prediction("LONG", 0.8, 0.1, 0.1, 1.0, "fixed-v1", "fixed-cal-v1", ()),
        Prediction("SHORT", 0.1, 0.8, 0.1, -1.0, "fixed-v1", "fixed-cal-v1", ()),
    )
    costs = CostScenario(D("0"), D("0"), D("0"), D("0"))

    with pytest.raises(ValueError, match="positive and finite"):
        select_cost_aware_scenario(
            predictions,
            bid_price=D("100"),
            ask_price=D("100"),
            decision_anchor_price=D("100"),
            atr_pct=D("0.02"),
            costs=costs,
            stop_atr_multiplier=float("nan"),
        )


def test_signal_geometry_is_conservatively_aligned_to_exchange_tick() -> None:
    predictions = (
        Prediction("LONG", 0.80, 0.10, 0.10, 1.0, "fixed-v1", "fixed-cal-v1", ()),
        Prediction("SHORT", 0.10, 0.80, 0.10, -1.0, "fixed-v1", "fixed-cal-v1", ()),
    )
    selected = select_cost_aware_scenario(
        predictions,
        bid_price=D("100"),
        ask_price=D("100"),
        decision_anchor_price=D("100"),
        atr_pct=D("0.013"),
        costs=CostScenario(D("0"), D("0"), D("0"), D("0")),
        stop_atr_multiplier=1.7,
        tp_atr_multiplier=2.3,
        tick_size=D("0.5"),
    )

    assert selected.entry_low % D("0.5") == 0
    assert selected.entry_high % D("0.5") == 0
    assert selected.stop % D("0.5") == 0
    assert selected.take_profit_1 % D("0.5") == 0
    assert selected.stop == D("97.5")
    assert selected.take_profit_1 == D("102.5")


def test_short_signal_geometry_uses_conservative_tick_rounding() -> None:
    predictions = (
        Prediction("LONG", 0.10, 0.80, 0.10, -1.0, "fixed-v1", "fixed-cal-v1", ()),
        Prediction("SHORT", 0.80, 0.10, 0.10, 1.0, "fixed-v1", "fixed-cal-v1", ()),
    )
    selected = select_cost_aware_scenario(
        predictions,
        bid_price=D("100"),
        ask_price=D("100"),
        decision_anchor_price=D("100"),
        atr_pct=D("0.013"),
        costs=CostScenario(D("0"), D("0"), D("0"), D("0")),
        stop_atr_multiplier=1.7,
        tp_atr_multiplier=2.3,
        tick_size=D("0.5"),
    )

    assert selected.prediction.direction == "SHORT"
    assert selected.stop == D("102.5")
    assert selected.take_profit_1 == D("97.5")
    assert selected.stop % D("0.5") == 0
    assert selected.take_profit_1 % D("0.5") == 0

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from app.ml.features import FEATURE_NAMES, latest_feature_snapshot
from app.ml.labels import triple_barrier_outcome
from app.ml.runtime import ModelRuntime, Prediction
from app.ml.training import (
    MODEL_FEATURE_NAMES,
    OUTCOME_CLASSES,
    DatasetSplit,
    PolicyEvaluationConfig,
    evaluate_policy_model,
)
from app.risk.math import (
    CostScenario,
    InstrumentConstraints,
    calculate_position_plan,
    net_rr_and_ev,
)
from app.services.signals import select_cost_aware_scenario
from scripts.backtest import policy_backtest

D = Decimal


def _candle_rows(*, prefix_price: float, invalid_close_index: int | None = None) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    for hour in range(30):
        price = prefix_price * (1.0 + hour * 0.0001)
        rows.append(
            {
                "symbol": "BTCUSDT",
                "open_time": start + timedelta(hours=hour),
                "open": price,
                "high": price * 1.002,
                "low": price * 0.998,
                "close": price,
                "volume": 1_000.0 + hour,
                "turnover": (1_000.0 + hour) * price,
            }
        )
    post_start = start + timedelta(hours=35)
    for offset in range(40):
        price = 100.0 * (1.001**offset)
        close = 0.0 if invalid_close_index == offset else price
        rows.append(
            {
                "symbol": "BTCUSDT",
                "open_time": post_start + timedelta(hours=offset),
                "open": price,
                "high": price * 1.002,
                "low": price * 0.998,
                "close": close,
                "volume": 2_000.0 + offset,
                "turnover": (2_000.0 + offset) * price,
            }
        )
    return pd.DataFrame(rows)


def test_feature_state_is_reset_after_hourly_gap() -> None:
    low_prefix = latest_feature_snapshot(_candle_rows(prefix_price=1.0))
    high_prefix = latest_feature_snapshot(_candle_rows(prefix_price=1_000_000.0))

    assert low_prefix.quality_flags == high_prefix.quality_flags
    assert low_prefix.values["ema_distance_12"] == pytest.approx(
        high_prefix.values["ema_distance_12"], abs=1e-12
    )
    assert low_prefix.values["ema_slope_12"] == pytest.approx(
        high_prefix.values["ema_slope_12"], abs=1e-12
    )


def test_invalid_price_inside_required_feature_window_blocks_snapshot() -> None:
    snapshot = latest_feature_snapshot(_candle_rows(prefix_price=100.0, invalid_close_index=30))

    assert snapshot.values == {}
    assert "INVALID_MARKET_BAR" in snapshot.quality_flags


def test_barrier_label_rejects_non_finite_future_bar() -> None:
    future = pd.DataFrame([{"open": 100.0, "high": float("nan"), "low": 99.0, "close": 100.0}])

    with pytest.raises(ValueError, match="invalid prices"):
        triple_barrier_outcome(
            future,
            direction="LONG",
            stop=98.0,
            take_profit=102.0,
        )


class InvalidProbabilityModel:
    classes_ = OUTCOME_CLASSES

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        return np.tile(np.asarray([[0.80, 0.40, -0.20]], dtype=float), (len(x), 1))


def test_runtime_rejects_probability_rows_outside_simplex() -> None:
    runtime = ModelRuntime(None, allow_baseline=False)
    runtime.bundle = {"model": InvalidProbabilityModel()}

    with pytest.raises(ValueError, match="probabil"):
        runtime.predict_scenarios({name: 0.0 for name in FEATURE_NAMES})


def test_ev_math_rejects_probability_rows_outside_simplex() -> None:
    with pytest.raises(ValueError, match="probabil"):
        net_rr_and_ev(
            entry=D("100"),
            stop=D("98"),
            take_profit=D("104"),
            direction="LONG",
            costs=CostScenario(D("0"), D("0"), D("0"), D("0")),
            p_tp=0.8,
            p_sl=0.4,
            p_timeout=-0.2,
        )


def test_direction_selector_requires_one_long_and_one_short_scenario() -> None:
    only_long = Prediction("LONG", 0.6, 0.2, 0.2, 1.0, "v", "c", ())

    with pytest.raises(ValueError, match="LONG.*SHORT"):
        select_cost_aware_scenario(
            (only_long,),
            bid_price=D("99.9"),
            ask_price=D("100.1"),
            last_price=D("100"),
            atr_pct=D("0.02"),
            costs=CostScenario(D("0"), D("0"), D("0"), D("0")),
        )


def _policy_split(meta: pd.DataFrame, probabilities: np.ndarray) -> tuple[DatasetSplit, object]:
    meta = meta.copy()
    if "exit_at_open" not in meta.columns:
        meta["exit_at_open"] = False
    x = np.zeros((len(meta), len(MODEL_FEATURE_NAMES)), dtype=float)
    x[:, -1] = np.where(meta["direction"].eq("LONG"), 1.0, -1.0)
    y = meta["target"].to_numpy()

    class RowProbabilityModel:
        classes_ = OUTCOME_CLASSES

        def predict_proba(self, values: np.ndarray) -> np.ndarray:
            assert len(values) == len(probabilities)
            return probabilities.copy()

    split = DatasetSplit(x, y, x, y, x, y, meta)
    return split, RowProbabilityModel()


def _policy_config() -> PolicyEvaluationConfig:
    return PolicyEvaluationConfig(
        fee_rate_round_trip=0.0,
        slippage_rate=0.0,
        stop_gap_reserve_rate=0.0,
        min_net_rr=0.0,
        min_net_ev_r=-10.0,
        timeout_return_rate=0.0,
    )


def test_policy_drawdown_is_booked_at_exit_time_not_decision_time() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    meta = pd.DataFrame(
        [
            {
                "decision_time": start,
                "label_end_time": start + timedelta(hours=2),
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "target": "TP",
                "ambiguous": False,
                "exit_index": 1,
                "realized_gross_return": 0.02,
                "barrier_upside_rate": 0.02,
                "barrier_downside_rate": 0.02,
            },
            {
                "decision_time": start + timedelta(hours=1),
                "label_end_time": start + timedelta(hours=3),
                "symbol": "ETHUSDT",
                "direction": "LONG",
                "target": "SL",
                "ambiguous": False,
                "exit_index": 0,
                "realized_gross_return": -0.02,
                "barrier_upside_rate": 0.02,
                "barrier_downside_rate": 0.02,
            },
        ]
    )
    counterparts = meta.copy()
    counterparts["direction"] = "SHORT"
    meta = pd.concat([meta, counterparts], ignore_index=True)
    probabilities = np.asarray(
        [
            [0.80, 0.10, 0.10],
            [0.80, 0.10, 0.10],
            [0.10, 0.80, 0.10],
            [0.10, 0.80, 0.10],
        ]
    )
    split, model = _policy_split(meta, probabilities)

    metrics = evaluate_policy_model(model, split, _policy_config())

    # Both outcomes are realized at the same timestamp and offset each other.
    assert metrics["policy_realized_total_r"] == pytest.approx(0.0)
    assert metrics["policy_max_drawdown_r"] == pytest.approx(0.0)


def test_policy_direction_tiebreak_uses_net_rr_before_row_order() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    meta = pd.DataFrame(
        [
            {
                "decision_time": start,
                "label_end_time": start + timedelta(hours=1),
                "symbol": "BTCUSDT",
                "direction": "SHORT",
                "target": "SL",
                "ambiguous": False,
                "exit_index": 0,
                "realized_gross_return": -0.01,
                "barrier_upside_rate": 0.01,
                "barrier_downside_rate": 0.01,
            },
            {
                "decision_time": start,
                "label_end_time": start + timedelta(hours=1),
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "target": "TP",
                "ambiguous": False,
                "exit_index": 0,
                "realized_gross_return": 0.02,
                "barrier_upside_rate": 0.02,
                "barrier_downside_rate": 0.01,
            },
        ]
    )
    # SHORT EV/R = .6*1 - .2 = .4; LONG EV/R = .4*2 - .4 = .4.
    probabilities = np.asarray([[0.60, 0.20, 0.20], [0.40, 0.40, 0.20]])
    split, model = _policy_split(meta, probabilities)

    metrics = evaluate_policy_model(model, split, _policy_config())

    assert metrics["policy_realized_mean_r"] == pytest.approx(2.0)


def test_backtest_rejects_probability_rows_outside_simplex() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    meta = pd.DataFrame(
        [
            {
                "decision_time": start,
                "open_time": start - timedelta(hours=1),
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "target": "TP",
                "exit_index": 0,
                "realized_gross_return": 0.02,
                "barrier_upside_rate": 0.02,
                "barrier_downside_rate": 0.01,
            }
        ]
    )
    x = np.zeros((1, len(MODEL_FEATURE_NAMES)), dtype=float)
    split = DatasetSplit(x, np.asarray(["TP"]), x, np.asarray(["TP"]), x, np.asarray(["TP"]), meta)

    with pytest.raises(ValueError, match="probabil"):
        policy_backtest(
            InvalidProbabilityModel(),
            split,
            round_trip_cost_bps=0.0,
            stop_gap_reserve_bps=0.0,
            minimum_net_ev_r=-10.0,
        )


def test_exchange_max_leverage_below_one_is_blocked_not_overridden() -> None:
    plan = calculate_position_plan(
        effective_capital=D("1000"),
        risk_rate=D("0.01"),
        entry=D("100"),
        stop=D("98"),
        take_profit=D("104"),
        direction="LONG",
        costs=CostScenario(D("0"), D("0"), D("0"), D("0")),
        constraints=InstrumentConstraints(D("0.001"), D("0.001"), D("5"), None, D("0.5")),
        leverage=1,
        capital_verified=True,
    )

    assert plan.status == "BLOCKED_INVALID_INPUT"
    assert any("max_leverage" in warning for warning in plan.warnings)

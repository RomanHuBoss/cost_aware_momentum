from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

import app.ml.training as training
from app.ml.training import (
    MODEL_FEATURE_NAMES,
    OUTCOME_CLASSES,
    DatasetSplit,
    PolicyEvaluationConfig,
    evaluate_policy_model,
)
from scripts.backtest import policy_backtest


class CertainTpModel:
    classes_ = OUTCOME_CLASSES

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        return np.tile(np.asarray([[1.0, 0.0, 0.0]], dtype=float), (len(x), 1))


def _exact_stop_split() -> DatasetSplit:
    decision_time = datetime(2026, 7, 1, tzinfo=UTC)
    meta = pd.DataFrame(
        [
            {
                "decision_time": decision_time,
                "label_end_time": decision_time + timedelta(hours=1),
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "target": "SL",
                "exit_index": 0,
                "exit_at_open": False,
                "realized_gross_return": -0.10,
                "barrier_upside_rate": 0.10,
                "barrier_downside_rate": 0.10,
            },
            {
                "decision_time": decision_time,
                "label_end_time": decision_time + timedelta(hours=1),
                "symbol": "BTCUSDT",
                "direction": "SHORT",
                "target": "SL",
                "exit_index": 0,
                "exit_at_open": False,
                "realized_gross_return": -0.20,
                "barrier_upside_rate": 0.001,
                "barrier_downside_rate": 0.20,
            },
        ]
    )
    values = np.zeros((len(meta), len(MODEL_FEATURE_NAMES)), dtype=float)
    values[:, -1] = np.where(meta["direction"].eq("LONG"), 1.0, -1.0)
    targets = meta["target"].to_numpy()
    return DatasetSplit(values, targets, values, targets, values, targets, meta)


def test_policy_realized_return_does_not_book_unused_gap_reserve_as_cash_loss() -> None:
    metrics = evaluate_policy_model(
        CertainTpModel(),
        _exact_stop_split(),
        PolicyEvaluationConfig(
            fee_rate_round_trip=0.0,
            slippage_rate=0.0,
            stop_gap_reserve_rate=0.01,
            min_net_rr=0.0,
            min_net_ev_r=-1.0,
            horizon_hours=1,
        ),
    )

    # The exact stop loses 10%. The 1% reserve belongs in the risk denominator
    # (11%), but no extra 1% cash loss occurred: -10% / 11% = -0.90909R.
    assert metrics["policy_trade_mean_r"] == pytest.approx(-0.10 / 0.11)


def test_backtest_realized_return_does_not_book_unused_gap_reserve_as_cash_loss() -> None:
    metrics = policy_backtest(
        CertainTpModel(),
        _exact_stop_split(),
        round_trip_cost_bps=0.0,
        stop_gap_reserve_bps=100.0,
        slippage_bps=0.0,
        minimum_net_rr=0.0,
        minimum_net_ev_r=-1.0,
        horizon_hours=1,
    )

    assert metrics["net_return"] == pytest.approx(-0.10)
    assert metrics["stress_net_return_with_stop_gap_reserve"] == pytest.approx(-0.11)


def test_horizon_uncertainty_partitions_all_hourly_phases_without_anchor_bias() -> None:
    assert hasattr(training, "_horizon_separated_phase_series")

    start = pd.Timestamp("2026-07-01T00:00:00Z")
    cohorts = pd.Series(
        [0.10, -0.20, 0.03, 0.11, -0.19, 0.04, 0.12, -0.18, 0.05],
        index=pd.date_range(start, periods=9, freq="h"),
        dtype=float,
    )
    shifted = cohorts.copy()
    shifted.index = pd.date_range(start + timedelta(hours=1), periods=9, freq="h")

    phases = training._horizon_separated_phase_series(cohorts, horizon_hours=3)
    shifted_phases = training._horizon_separated_phase_series(shifted, horizon_hours=3)

    assert len(phases) == 3
    assert all(len(values) == 3 for values in phases.values())
    assert sorted(tuple(values.to_numpy(float)) for values in phases.values()) == sorted(
        tuple(values.to_numpy(float)) for values in shifted_phases.values()
    )

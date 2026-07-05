from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app.ml.training import (
    MODEL_FEATURE_NAMES,
    OUTCOME_CLASSES,
    DatasetSplit,
    PolicyEvaluationConfig,
    evaluate_policy_model,
)


class FeatureGatedPolicyModel:
    classes_ = OUTCOME_CLASSES

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        probabilities = np.zeros((len(x), len(OUTCOME_CLASSES)), dtype=float)
        actionable = x[:, 0] > 0.5
        probabilities[actionable, 0] = 1.0  # TP
        probabilities[~actionable, 1] = 1.0  # SL
        return probabilities


def _sparse_policy_split() -> DatasetSplit:
    start = datetime(2026, 7, 1, tzinfo=UTC)
    records: list[dict[str, object]] = []
    markers: list[float] = []
    directions: list[float] = []
    for hour in range(16):
        decision_time = start + timedelta(hours=hour)
        actionable = hour < 8
        for direction, code in (("LONG", 1.0), ("SHORT", -1.0)):
            records.append(
                {
                    "decision_time": decision_time,
                    "label_end_time": decision_time + timedelta(hours=8),
                    "symbol": "BTCUSDT",
                    "direction": direction,
                    "target": "TP",
                    "exit_index": 0,
                    "exit_at_open": False,
                    "realized_gross_return": 0.10,
                    "barrier_upside_rate": 0.10,
                    "barrier_downside_rate": 0.10,
                }
            )
            markers.append(1.0 if actionable else 0.0)
            directions.append(code)

    meta = pd.DataFrame.from_records(records)
    values = np.zeros((len(meta), len(MODEL_FEATURE_NAMES)), dtype=float)
    values[:, 0] = np.asarray(markers, dtype=float)
    values[:, -1] = np.asarray(directions, dtype=float)
    targets = meta["target"].to_numpy()
    return DatasetSplit(values, targets, values, targets, values, targets, meta)


def test_policy_uncertainty_uses_zero_return_for_observed_no_trade_cohorts() -> None:
    metrics = evaluate_policy_model(
        FeatureGatedPolicyModel(),
        _sparse_policy_split(),
        PolicyEvaluationConfig(
            fee_rate_round_trip=0.0,
            slippage_rate=0.0,
            stop_gap_reserve_rate=0.0,
            min_net_rr=0.0,
            min_net_ev_r=0.0,
            horizon_hours=8,
            bootstrap_samples=500,
            confidence_level=0.95,
        ),
    )

    assert metrics["policy_trades"] == 8
    assert metrics["policy_trade_cohorts"] == 8
    assert metrics["policy_cohorts"] == 16
    assert metrics["policy_no_trade_cohorts"] == 8
    assert metrics["policy_horizon_phase_count"] == 8
    assert metrics["policy_independent_cohorts"] == 2
    assert metrics["policy_realized_mean_r"] == pytest.approx(0.5)
    assert metrics["policy_independent_mean_r"] == pytest.approx(0.5)
    assert metrics["policy_mean_r_lcb"] is not None
    assert metrics["policy_mean_r_lcb"] <= metrics["policy_independent_mean_r"]

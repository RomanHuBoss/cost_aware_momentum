from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app.ml.features import FEATURE_NAMES
from app.ml.training import (
    MODEL_FEATURE_NAMES,
    OUTCOME_CLASSES,
    DatasetSplit,
    PolicyEvaluationConfig,
    chronological_split,
    evaluate_policy_model,
    make_barrier_dataset,
)
from scripts.backtest import policy_backtest


class FixedProbabilityModel:
    classes_ = OUTCOME_CLASSES

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        return np.tile(np.asarray([[0.60, 0.25, 0.15]], dtype=float), (len(x), 1))


def _single_direction_split(rows: int = 1) -> DatasetSplit:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    meta = []
    x_test = []
    y_test = []
    for index in range(rows):
        decision_time = start + timedelta(hours=index)
        x_test.append([0.0] * (len(MODEL_FEATURE_NAMES) - 1) + [1.0])
        y_test.append("TP")
        meta.append(
            {
                "decision_time": decision_time,
                "open_time": decision_time - timedelta(hours=1),
                "label_end_time": decision_time + timedelta(hours=4),
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "target": "TP",
                "ambiguous": False,
                "exit_index": 0,
                "realized_gross_return": 0.02,
                "barrier_upside_rate": 0.02,
                "barrier_downside_rate": 0.01,
            }
        )
    values = np.asarray(x_test, dtype=float)
    targets = np.asarray(y_test)
    return DatasetSplit(values, targets, values, targets, values, targets, pd.DataFrame(meta))


def test_barrier_dataset_never_emits_unpaired_directional_scenarios() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    candles = []
    for hour in range(80):
        close = 1.0 + (hour % 5) * 0.001
        candles.append(
            {
                "symbol": "TESTUSDT",
                "open_time": start + timedelta(hours=hour),
                "close_time": start + timedelta(hours=hour + 1),
                "open": close,
                "high": close + 0.3,
                "low": close - 0.3,
                "close": close,
                "volume": 1000.0 + hour,
                "turnover": (1000.0 + hour) * close,
            }
        )

    dataset = make_barrier_dataset(pd.DataFrame(candles), horizon=4)
    assert dataset.empty
    assert dataset.attrs["hourly_continuity"]["skipped_incomplete_direction_pair_timestamps"] > 0


def test_chronological_split_rejects_incomplete_directional_pairs() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    rows = []
    for hour in range(700):
        row = {name: 0.0 for name in FEATURE_NAMES}
        decision_time = start + timedelta(hours=hour)
        row.update(
            {
                "scenario_direction": 1.0,
                "open_time": decision_time - timedelta(hours=1),
                "decision_time": decision_time,
                "label_end_time": decision_time + timedelta(hours=4),
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "target": "TP",
                "ambiguous": False,
                "exit_index": 0,
                "realized_gross_return": 0.02,
                "barrier_upside_rate": 0.02,
                "barrier_downside_rate": 0.01,
            }
        )
        rows.append(row)

    with pytest.raises(ValueError, match="one LONG and one SHORT"):
        chronological_split(pd.DataFrame(rows), purge_rows=4)


def test_holdout_policy_rejects_incomplete_directional_pairs() -> None:
    with pytest.raises(ValueError, match="one LONG and one SHORT"):
        evaluate_policy_model(
            FixedProbabilityModel(),
            _single_direction_split(),
            PolicyEvaluationConfig(
                fee_rate_round_trip=0.001,
                slippage_rate=0.0002,
                stop_gap_reserve_rate=0.0005,
                min_net_rr=0.0,
                min_net_ev_r=-1.0,
            ),
        )


def test_backtest_rejects_incomplete_directional_pairs() -> None:
    with pytest.raises(ValueError, match="one LONG and one SHORT"):
        policy_backtest(
            FixedProbabilityModel(),
            _single_direction_split(),
            round_trip_cost_bps=10.0,
            stop_gap_reserve_bps=5.0,
            horizon_hours=4,
            minimum_net_ev_r=-1.0,
        )

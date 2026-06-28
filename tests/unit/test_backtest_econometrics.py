from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from app.ml.training import MODEL_FEATURE_NAMES, OUTCOME_CLASSES, DatasetSplit
from scripts.backtest import policy_backtest


class FixedEdgeModel:
    classes_ = OUTCOME_CLASSES

    def predict_proba(self, x):
        return np.tile(np.asarray([[0.80, 0.10, 0.10]], dtype=float), (len(x), 1))


def _split(meta: pd.DataFrame) -> DatasetSplit:
    values = np.zeros((len(meta), len(MODEL_FEATURE_NAMES)), dtype=float)
    targets = meta["target"].to_numpy()
    return DatasetSplit(values, targets, values, targets, values, targets, meta)


def test_backtest_aggregates_simultaneous_positions_before_compounding() -> None:
    decision_time = datetime(2025, 1, 1, tzinfo=UTC)
    meta = pd.DataFrame(
        [
            {
                "decision_time": decision_time,
                "open_time": decision_time,
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "target": "TP",
                "realized_gross_return": 0.10,
                "barrier_upside_rate": 0.10,
                "barrier_downside_rate": 0.05,
            },
            {
                "decision_time": decision_time,
                "open_time": decision_time,
                "symbol": "ETHUSDT",
                "direction": "LONG",
                "target": "SL",
                "realized_gross_return": -0.10,
                "barrier_upside_rate": 0.10,
                "barrier_downside_rate": 0.05,
            },
        ]
    )

    metrics = policy_backtest(
        FixedEdgeModel(),
        _split(meta),
        round_trip_cost_bps=0.0,
        stop_gap_reserve_bps=0.0,
        minimum_predicted_edge=-1.0,
    )

    # Equal-weight simultaneous returns cancel. Sequential compounding would
    # incorrectly report (1.10 * 0.90) - 1 = -1%.
    assert metrics["net_return"] == pytest.approx(0.0)
    assert metrics["portfolio_periods"] == 1
    assert metrics["max_concurrent_trades"] == 2


def test_backtest_drawdown_includes_first_period_loss() -> None:
    decision_time = datetime(2025, 1, 1, tzinfo=UTC)
    meta = pd.DataFrame(
        [
            {
                "decision_time": decision_time,
                "open_time": decision_time,
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "target": "SL",
                "realized_gross_return": -0.10,
                "barrier_upside_rate": 0.10,
                "barrier_downside_rate": 0.05,
            }
        ]
    )

    metrics = policy_backtest(
        FixedEdgeModel(),
        _split(meta),
        round_trip_cost_bps=0.0,
        stop_gap_reserve_bps=0.0,
        minimum_predicted_edge=-1.0,
    )

    assert metrics["max_drawdown"] == pytest.approx(-0.10)

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from app.ml.features import FEATURE_NAMES
from app.ml.training import expanding_walk_forward_splits


def _labeled_frame(hours: int = 720) -> pd.DataFrame:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    outcomes = ("TP", "SL", "TIMEOUT")
    for hour in range(hours):
        decision_time = start + timedelta(hours=hour)
        for direction, direction_code in (("LONG", 1.0), ("SHORT", -1.0)):
            row = {name: 0.0 for name in FEATURE_NAMES}
            row[FEATURE_NAMES[0]] = float(hour)
            row.update(
                {
                    "scenario_direction": direction_code,
                    "open_time": decision_time + timedelta(hours=1),
                    "decision_time": decision_time,
                    "label_end_time": decision_time + timedelta(hours=8),
                    "symbol": "BTCUSDT",
                    "direction": direction,
                    "target": outcomes[(hour + (direction == "SHORT")) % 3],
                    "ambiguous": False,
                    "exit_index": 7,
                    "exit_at_open": False,
                    "realized_gross_return": 0.0,
                    "barrier_upside_rate": 0.02,
                    "barrier_downside_rate": 0.01,
                }
            )
            rows.append(row)
    return pd.DataFrame(rows)


def test_expanding_walk_forward_is_purged_ordered_and_expanding() -> None:
    folds = expanding_walk_forward_splits(
        _labeled_frame(),
        folds=3,
        purge_hours=8,
    )

    assert len(folds) == 3
    assert [len(fold.y_train) for fold in folds] == sorted(len(fold.y_train) for fold in folds)

    previous_test_end = None
    for fold in folds:
        assert fold.train_meta is not None
        assert fold.cal_meta is not None
        train_label_end = pd.to_datetime(fold.train_meta["label_end_time"], utc=True)
        cal_decision = pd.to_datetime(fold.cal_meta["decision_time"], utc=True)
        cal_label_end = pd.to_datetime(fold.cal_meta["label_end_time"], utc=True)
        test_decision = pd.to_datetime(fold.test_meta["decision_time"], utc=True)

        assert train_label_end.max() < cal_decision.min()
        assert cal_label_end.max() < test_decision.min()
        assert fold.test_meta.groupby(["decision_time", "symbol"])["direction"].nunique().eq(2).all()
        if previous_test_end is not None:
            assert test_decision.min() > previous_test_end
        previous_test_end = test_decision.max()


def test_expanding_walk_forward_rejects_insufficient_history() -> None:
    with pytest.raises(ValueError, match="walk-forward"):
        expanding_walk_forward_splits(
            _labeled_frame(hours=180),
            folds=3,
            purge_hours=8,
        )


def test_minimum_history_requirement_includes_purged_walk_forward_windows() -> None:
    from app.ml.features import FEATURE_LOOKBACK_HOURS
    from app.ml.training import (
        DEFAULT_WALK_FORWARD_FOLDS,
        minimum_hourly_history_timestamps_for_quality_gate,
    )

    raw_timestamps = minimum_hourly_history_timestamps_for_quality_gate(
        horizon_hours=8,
        minimum_holdout_rows=90,
        minimum_holdout_span_hours=24,
    )
    labeled_timestamps = raw_timestamps - FEATURE_LOOKBACK_HOURS - 8
    development_timestamps = int(labeled_timestamps * 0.85)
    block = development_timestamps // (DEFAULT_WALK_FORWARD_FOLDS + 3)
    initial_train = development_timestamps - (DEFAULT_WALK_FORWARD_FOLDS + 1) * block

    assert block >= 45 + 2 * 8
    assert initial_train >= 90


def test_walk_forward_validation_refits_models_before_final_holdout() -> None:
    from app.ml.lifecycle import evaluate_walk_forward_validation
    from app.ml.training import chronological_split

    dataset = _labeled_frame(hours=900)
    final_split = chronological_split(dataset, purge_rows=8)
    metrics = evaluate_walk_forward_validation(
        dataset,
        final_split,
        horizon=8,
        model_type="logistic",
        policy_config=None,
    )

    assert metrics["walk_forward_folds_completed"] == 3
    assert len(metrics["walk_forward_fold_results"]) == 3
    final_holdout_start = pd.Timestamp(metrics["walk_forward_final_holdout_start_time"])
    for fold in metrics["walk_forward_fold_results"]:
        assert pd.Timestamp(fold["test_end_time"]) < final_holdout_start
        assert fold["train_rows"] > 0
        assert fold["calibration_rows"] >= 90
        assert fold["test_rows"] >= 90

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
    TemporalCalibratedBarrierModel,
    chronological_split,
    evaluate_model,
    make_barrier_dataset,
)


def _synthetic_outcomes(x: np.ndarray) -> np.ndarray:
    directional = x[:, 0] * x[:, -1]
    return np.where(directional > 0.45, "TP", np.where(directional < -0.45, "SL", "TIMEOUT"))


def test_calibrated_barrier_model_returns_ordered_outcome_probabilities() -> None:
    rng = np.random.default_rng(42)
    x_train = rng.normal(size=(1200, 5))
    x_train[:, -1] = rng.choice([-1.0, 1.0], size=len(x_train))
    y_train = _synthetic_outcomes(x_train)
    x_cal = rng.normal(size=(600, 5))
    x_cal[:, -1] = rng.choice([-1.0, 1.0], size=len(x_cal))
    y_cal = _synthetic_outcomes(x_cal)

    model = TemporalCalibratedBarrierModel().fit(x_train, y_train, x_cal, y_cal)
    probabilities = model.predict_proba(
        np.array(
            [
                [2.0, 0.0, 0.0, 0.0, 1.0],
                [2.0, 0.0, 0.0, 0.0, -1.0],
                [0.0, 0.0, 0.0, 0.0, 1.0],
            ]
        )
    )

    assert list(model.classes_) == list(OUTCOME_CLASSES)
    assert probabilities.sum(axis=1) == pytest.approx(np.ones(3))
    assert probabilities[0, 0] > probabilities[0, 1]
    assert probabilities[1, 1] > probabilities[1, 0]
    assert probabilities[2, 2] == probabilities[2].max()



def test_evaluate_model_log_loss_respects_declared_probability_order() -> None:
    class FakeModel:
        classes_ = OUTCOME_CLASSES.copy()

        def predict_proba(self, x: np.ndarray) -> np.ndarray:
            return np.asarray(
                [
                    [0.90, 0.05, 0.05],
                    [0.05, 0.90, 0.05],
                    [0.05, 0.05, 0.90],
                ],
                dtype=float,
            )

        def _base_probabilities(self, x: np.ndarray) -> np.ndarray:
            return np.asarray(
                [
                    [0.80, 0.10, 0.10],
                    [0.10, 0.80, 0.10],
                    [0.10, 0.10, 0.80],
                ],
                dtype=float,
            )

        def predict(self, x: np.ndarray) -> np.ndarray:
            probabilities = self.predict_proba(x)
            return self.classes_[np.argmax(probabilities, axis=1)]

    x = np.zeros((3, len(MODEL_FEATURE_NAMES)), dtype=float)
    y = np.asarray(["TP", "SL", "TIMEOUT"])
    split = DatasetSplit(
        x_train=x,
        y_train=y,
        x_cal=x,
        y_cal=y,
        x_test=x,
        y_test=y,
        test_meta=pd.DataFrame({"ambiguous": [False, False, False]}),
    )

    metrics = evaluate_model(FakeModel(), split)

    assert metrics["accuracy"] == pytest.approx(1.0)
    assert metrics["log_loss"] == pytest.approx(-np.log(0.90))
    assert metrics["raw_log_loss"] == pytest.approx(-np.log(0.80))
    assert metrics["calibration_log_loss_improvement"] == pytest.approx(
        -np.log(0.80) + np.log(0.90)
    )
    assert metrics["class_prior_log_loss"] == pytest.approx(np.log(3.0))
    assert metrics["uniform_log_loss"] == pytest.approx(np.log(3.0))
    assert metrics["log_loss_skill_vs_prior"] > 0


def test_evaluate_model_rejects_invalid_probability_rows() -> None:
    class InvalidProbabilityModel:
        classes_ = OUTCOME_CLASSES.copy()

        def predict_proba(self, x: np.ndarray) -> np.ndarray:
            return np.asarray([[0.90, 0.05, 0.04]], dtype=float)

        def predict(self, x: np.ndarray) -> np.ndarray:
            return np.asarray(["TP"])

    x = np.zeros((1, len(MODEL_FEATURE_NAMES)), dtype=float)
    y = np.asarray(["TP"])
    split = DatasetSplit(
        x_train=np.vstack([x, x, x]),
        y_train=np.asarray(["TP", "SL", "TIMEOUT"]),
        x_cal=x,
        y_cal=y,
        x_test=x,
        y_test=y,
        test_meta=pd.DataFrame({"ambiguous": [False]}),
    )

    with pytest.raises(ValueError, match="sum to 1"):
        evaluate_model(InvalidProbabilityModel(), split)


def test_barrier_dataset_creates_long_and_short_scenarios() -> None:
    rows = []
    start = datetime(2025, 1, 1, tzinfo=UTC)
    close = 100.0
    for hour in range(80):
        close *= 1.001 if hour % 5 else 0.998
        rows.append(
            {
                "symbol": "BTCUSDT",
                "open_time": start + timedelta(hours=hour),
                "open": close * 0.999,
                "high": close * 1.006,
                "low": close * 0.994,
                "close": close,
                "volume": 1000 + hour * 3,
                "turnover": (1000 + hour * 3) * close,
            }
        )

    dataset = make_barrier_dataset(pd.DataFrame(rows), horizon=4)

    assert not dataset.empty
    assert set(dataset["direction"]) == {"LONG", "SHORT"}
    assert set(dataset["target"]).issubset(set(OUTCOME_CLASSES))
    assert set(dataset["scenario_direction"]) == {-1.0, 1.0}
    assert dataset.groupby(["open_time", "symbol"])["direction"].nunique().eq(2).all()
    assert all(name in dataset.columns for name in MODEL_FEATURE_NAMES)
    assert "label_end_time" in dataset.columns
    assert (dataset["label_end_time"] > dataset["open_time"]).all()


def test_chronological_split_keeps_timestamp_groups_together() -> None:
    rows = []
    start = datetime(2025, 1, 1, tzinfo=UTC)
    outcomes = ["TP", "SL", "TIMEOUT"]
    for hour in range(420):
        for symbol in ("BTCUSDT", "ETHUSDT"):
            for direction, direction_code in (("LONG", 1.0), ("SHORT", -1.0)):
                row = {name: float(hour % 7) / 10 for name in FEATURE_NAMES}
                target = outcomes[(hour + (0 if direction == "LONG" else 1)) % 3]
                row.update(
                    {
                        "scenario_direction": direction_code,
                        "open_time": start + timedelta(hours=hour),
                        "label_end_time": start + timedelta(hours=hour + 8),
                        "symbol": symbol,
                        "direction": direction,
                        "target": target,
                        "ambiguous": False,
                        "realized_gross_return": {"TP": 0.02, "SL": -0.01, "TIMEOUT": 0.0}[target],
                        "barrier_upside_rate": 0.02,
                        "barrier_downside_rate": 0.01,
                    }
                )
                rows.append(row)
    split = chronological_split(pd.DataFrame(rows), purge_rows=8)
    assert len(split.y_train) > len(split.y_cal) > 0
    assert len(split.y_test) > 0
    assert split.test_meta.groupby("open_time")["symbol"].nunique().eq(2).all()
    assert split.test_meta.groupby(["open_time", "symbol"])["direction"].nunique().eq(2).all()


def test_chronological_split_purges_by_actual_label_end_time() -> None:
    rows = []
    start = datetime(2025, 1, 1, tzinfo=UTC)
    open_by_index: dict[int, datetime] = {}
    label_end_by_index: dict[int, datetime] = {}
    outcomes = ["TP", "SL", "TIMEOUT"]

    for index in range(420):
        open_time = start + timedelta(hours=index * 4)
        label_end_time = open_time + timedelta(hours=32)
        open_by_index[index] = open_time
        label_end_by_index[index] = label_end_time
        for symbol in ("BTCUSDT", "ETHUSDT"):
            for direction, direction_code in (("LONG", 1.0), ("SHORT", -1.0)):
                row = {name: 0.0 for name in FEATURE_NAMES}
                row[FEATURE_NAMES[0]] = float(index)
                target = outcomes[(index + (0 if direction == "LONG" else 1)) % 3]
                row.update(
                    {
                        "scenario_direction": direction_code,
                        "open_time": open_time,
                        "label_end_time": label_end_time,
                        "symbol": symbol,
                        "direction": direction,
                        "target": target,
                        "ambiguous": False,
                        "realized_gross_return": 0.0,
                        "barrier_upside_rate": 0.02,
                        "barrier_downside_rate": 0.01,
                    }
                )
                rows.append(row)

    split = chronological_split(pd.DataFrame(rows), purge_rows=8)
    train_indexes = {int(value) for value in split.x_train[:, 0]}
    cal_indexes = {int(value) for value in split.x_cal[:, 0]}
    test_indexes = {int(value) for value in split.x_test[:, 0]}

    assert max(label_end_by_index[index] for index in train_indexes) < min(
        open_by_index[index] for index in cal_indexes
    )
    assert max(label_end_by_index[index] for index in cal_indexes) < min(
        open_by_index[index] for index in test_indexes
    )


def test_chronological_split_fails_closed_without_valid_label_end_time() -> None:
    rows = []
    start = datetime(2025, 1, 1, tzinfo=UTC)
    for hour in range(420):
        for direction, direction_code in (("LONG", 1.0), ("SHORT", -1.0)):
            row = {name: 0.0 for name in FEATURE_NAMES}
            row.update(
                {
                    "scenario_direction": direction_code,
                    "open_time": start + timedelta(hours=hour),
                    "symbol": "BTCUSDT",
                    "direction": direction,
                    "target": "TP" if hour % 3 == 0 else "SL",
                    "ambiguous": False,
                    "realized_gross_return": 0.0,
                    "barrier_upside_rate": 0.02,
                    "barrier_downside_rate": 0.01,
                }
            )
            rows.append(row)

    frame = pd.DataFrame(rows)
    with pytest.raises(ValueError, match="label_end_time"):
        chronological_split(frame, purge_rows=8)

    frame["label_end_time"] = frame["open_time"]
    with pytest.raises(ValueError, match="later than"):
        chronological_split(frame, purge_rows=8)


def test_policy_evaluation_selects_one_direction_and_applies_cost_gate() -> None:
    from app.ml.training import DatasetSplit, PolicyEvaluationConfig, evaluate_policy_model

    class FakeModel:
        classes_ = OUTCOME_CLASSES

        def predict_proba(self, x):
            # LONG rows (direction +1) have positive edge, SHORT rows do not.
            result = []
            for row in x:
                if row[-1] > 0:
                    result.append([0.65, 0.20, 0.15])
                else:
                    result.append([0.20, 0.60, 0.20])
            return np.asarray(result, dtype=float)

    times = [datetime(2025, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(40)]
    x = []
    meta = []
    y = []
    for index, open_time in enumerate(times):
        for direction, code in (("LONG", 1.0), ("SHORT", -1.0)):
            x.append([0.0] * (len(MODEL_FEATURE_NAMES) - 1) + [code])
            target = "TP" if direction == "LONG" and index % 3 else "SL"
            y.append(target)
            meta.append(
                {
                    "open_time": open_time,
                    "symbol": "BTCUSDT",
                    "direction": direction,
                    "target": target,
                    "ambiguous": False,
                    "realized_gross_return": 0.0,
                    "barrier_upside_rate": 0.03,
                    "barrier_downside_rate": 0.012,
                }
            )
    values = np.asarray(x, dtype=float)
    targets = np.asarray(y)
    split = DatasetSplit(values, targets, values, targets, values, targets, pd.DataFrame(meta))
    metrics = evaluate_policy_model(
        FakeModel(),
        split,
        PolicyEvaluationConfig(
            fee_rate_round_trip=0.0011,
            slippage_rate=0.0003,
            stop_gap_reserve_rate=0.001,
            min_net_rr=1.2,
            min_net_ev_r=0.05,
        ),
    )

    assert metrics["policy_candidates"] == 40
    assert metrics["policy_trades"] == 40
    assert metrics["policy_profit_factor"] is not None


def test_barrier_dataset_excludes_non_contiguous_feature_and_label_windows() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    rows = []
    close = 100.0
    for hour in range(120):
        if hour == 60:
            continue
        close *= 1.001 if hour % 5 else 0.998
        rows.append(
            {
                "symbol": "BTCUSDT",
                "open_time": start + timedelta(hours=hour),
                "open": close * 0.999,
                "high": close * 1.006,
                "low": close * 0.994,
                "close": close,
                "volume": 1000 + hour * 3,
                "turnover": (1000 + hour * 3) * close,
            }
        )

    dataset = make_barrier_dataset(pd.DataFrame(rows), horizon=4)
    labeled_times = set(pd.to_datetime(dataset["open_time"], utc=True))

    # The missing candle at hour 60 invalidates labels whose future four-bar
    # window crosses the gap, and invalidates features until 24 consecutive
    # hourly transitions have been restored.
    assert all(start + timedelta(hours=hour) not in labeled_times for hour in range(56, 60))
    assert all(start + timedelta(hours=hour) not in labeled_times for hour in range(61, 85))
    assert start + timedelta(hours=55) in labeled_times
    assert start + timedelta(hours=85) in labeled_times

    continuity = dataset.attrs["hourly_continuity"]
    assert continuity["schema"] == "strict-hourly-v1"
    assert continuity["feature_lookback_hours"] == 24
    assert continuity["label_horizon_hours"] == 4
    assert continuity["skipped_feature_gap_timestamps"] >= 24
    assert continuity["skipped_label_gap_timestamps"] >= 4

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app.ml.features import FEATURE_NAMES
from app.ml.training import (
    MODEL_FEATURE_NAMES,
    OUTCOME_CLASSES,
    TemporalCalibratedBarrierModel,
    chronological_split,
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

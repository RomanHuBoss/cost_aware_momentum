from __future__ import annotations

import numpy as np

from app.ml.training import TemporalCalibratedDirectionModel


def test_calibrated_model_probability_column_is_long() -> None:
    rng = np.random.default_rng(42)
    x_train = rng.normal(size=(500, 3))
    y_train = np.where(x_train[:, 0] + 0.2 * x_train[:, 1] > 0, "LONG", "SHORT")
    x_cal = rng.normal(size=(200, 3))
    y_cal = np.where(x_cal[:, 0] + 0.2 * x_cal[:, 1] > 0, "LONG", "SHORT")
    model = TemporalCalibratedDirectionModel().fit(x_train, y_train, x_cal, y_cal)

    probabilities = model.predict_proba(np.array([[3.0, 0.0, 0.0], [-3.0, 0.0, 0.0]]))
    assert list(model.classes_) == ["SHORT", "LONG"]
    assert probabilities[0, 1] > probabilities[0, 0]
    assert probabilities[1, 1] < probabilities[1, 0]
    assert model.predict(np.array([[3.0, 0.0, 0.0]])).item() == "LONG"


def test_chronological_split_keeps_timestamp_groups_together() -> None:
    from datetime import UTC, datetime, timedelta

    import pandas as pd

    from app.ml.features import FEATURE_NAMES
    from app.ml.training import chronological_split

    rows = []
    start = datetime(2025, 1, 1, tzinfo=UTC)
    for hour in range(400):
        for symbol in ("BTCUSDT", "ETHUSDT"):
            row = {name: float(hour % 7) / 10 for name in FEATURE_NAMES}
            row.update(
                {
                    "open_time": start + timedelta(hours=hour),
                    "symbol": symbol,
                    "future_return": 0.01 if hour % 2 else -0.01,
                    "target": "LONG" if hour % 2 else "SHORT",
                }
            )
            rows.append(row)
    split = chronological_split(pd.DataFrame(rows), purge_rows=8)
    assert len(split.y_train) > len(split.y_cal) > 0
    assert len(split.y_test) > 0
    assert split.test_meta.groupby("open_time")["symbol"].nunique().eq(2).all()

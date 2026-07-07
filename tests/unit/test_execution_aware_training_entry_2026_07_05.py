from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from app.config import Settings
from app.ml.training import make_barrier_dataset


def _candles() -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    for hour in range(25):
        close = 100.0 + (hour % 4) * 0.05
        open_price = close - 0.02
        rows.append(
            {
                "symbol": "TESTUSDT",
                "open_time": start + timedelta(hours=hour),
                "close_time": start + timedelta(hours=hour + 1),
                "open": open_price,
                "high": close + 0.50,
                "low": open_price - 0.50,
                "close": close,
                "volume": 1000.0 + hour * 7.0,
                "turnover": (1000.0 + hour * 7.0) * close,
            }
        )
    future = [
        (100.0, 101.50, 98.50, 100.20),
        (100.2, 101.70, 98.70, 100.30),
        (100.3, 101.80, 98.80, 100.40),
        (100.4, 101.90, 98.90, 100.50),
    ]
    for offset, (open_price, high, low, close) in enumerate(future, start=25):
        rows.append(
            {
                "symbol": "TESTUSDT",
                "open_time": start + timedelta(hours=offset),
                "close_time": start + timedelta(hours=offset + 1),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1200.0 + offset * 7.0,
                "turnover": (1200.0 + offset * 7.0) * close,
            }
        )
    return pd.DataFrame(rows)


def test_training_labels_use_direction_specific_executable_entry_stress() -> None:
    dataset = make_barrier_dataset(_candles(), horizon=4, entry_spread_bps=20.0)

    decision_time = pd.Timestamp("2026-01-02T01:00:00Z")
    pair = dataset[dataset["decision_time"].eq(decision_time)].set_index("direction")

    assert pair.loc["LONG", "entry_mid_proxy"] == pytest.approx(100.0)
    assert pair.loc["SHORT", "entry_mid_proxy"] == pytest.approx(100.0)
    assert pair.loc["LONG", "entry_price"] == pytest.approx(100.0 * 1.001)
    assert pair.loc["SHORT", "entry_price"] == pytest.approx(100.0 * 0.999)
    assert pair.loc["LONG", "entry_spread_bps"] == pytest.approx(20.0)
    assert pair.loc["SHORT", "entry_spread_bps"] == pytest.approx(20.0)
    assert set(pair["entry_price_source"]) == {"next_hour_open_directional_half_spread_stress"}
    assert dataset.attrs["entry_execution_model"]["entry_spread_bps"] == pytest.approx(20.0)


def test_training_entry_spread_must_be_finite_and_nonnegative() -> None:
    with pytest.raises(ValueError, match="entry_spread_bps"):
        make_barrier_dataset(_candles(), horizon=4, entry_spread_bps=-1.0)


def test_model_entry_spread_setting_rejects_negative_values() -> None:
    with pytest.raises(ValueError, match="MODEL_ENTRY_SPREAD_BPS"):
        Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            model_entry_spread_bps=-0.01,
        )

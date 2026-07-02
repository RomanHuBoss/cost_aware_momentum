from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from app.ml.training import make_barrier_dataset


def _candles_with_post_decision_gap() -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows: list[dict[str, object]] = []

    # Build enough stable, non-degenerate history for the 24-hour feature window.
    for hour in range(25):
        close = 100.0 + (hour % 4) * 0.05
        open_price = close - 0.02
        rows.append(
            {
                "symbol": "TESTUSDT",
                "open_time": start + timedelta(hours=hour),
                "close_time": start + timedelta(hours=hour + 1),
                "open": open_price,
                "high": close + 0.40,
                "low": open_price - 0.40,
                "close": close,
                "volume": 1000.0 + hour * 7.0,
                "turnover": (1000.0 + hour * 7.0) * close,
            }
        )

    # The market gaps from the completed candle (~100) to the first executable
    # point at decision time (110). The subsequent path remains inside barriers
    # centered on 110, so the gap itself must not be booked as a TP.
    future = [
        (110.0, 110.80, 109.50, 110.20),
        (110.2, 110.90, 109.60, 110.30),
        (110.3, 111.00, 109.70, 110.40),
        (110.4, 111.10, 109.80, 110.50),
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


def test_dataset_uses_first_post_decision_open_as_executable_entry_proxy() -> None:
    candles = _candles_with_post_decision_gap()
    dataset = make_barrier_dataset(candles, horizon=4)

    decision_time = pd.Timestamp("2026-01-02T01:00:00Z")
    pair = dataset[dataset["decision_time"].eq(decision_time)].set_index("direction")

    assert set(pair.index) == {"LONG", "SHORT"}
    assert pair.loc["LONG", "entry_price"] == pytest.approx(110.0)
    assert pair.loc["SHORT", "entry_price"] == pytest.approx(110.0)
    assert pair.loc["LONG", "barrier_upside_rate"] == pytest.approx(
        pair.loc["LONG", "atr_pct_14"] * 2.20
    )
    assert pair.loc["LONG", "barrier_downside_rate"] == pytest.approx(
        pair.loc["LONG", "atr_pct_14"] * 1.15
    )
    assert pair.loc["LONG", "target"] == "TIMEOUT"
    assert pair.loc["LONG", "realized_gross_return"] == pytest.approx((110.50 - 110.0) / 110.0)


def test_short_dataset_does_not_book_down_gap_before_executable_entry() -> None:
    candles = _candles_with_post_decision_gap()
    future_mask = candles["open_time"] >= pd.Timestamp("2026-01-02T01:00:00Z")
    replacement = [
        (90.0, 90.50, 89.20, 89.80),
        (89.8, 90.40, 89.10, 89.70),
        (89.7, 90.30, 89.00, 89.60),
        (89.6, 90.20, 88.90, 89.50),
    ]
    for index, values in zip(candles.index[future_mask], replacement, strict=True):
        open_price, high, low, close = values
        candles.loc[index, ["open", "high", "low", "close"]] = values
        candles.loc[index, "turnover"] = candles.loc[index, "volume"] * close

    dataset = make_barrier_dataset(candles, horizon=4)
    decision_time = pd.Timestamp("2026-01-02T01:00:00Z")
    pair = dataset[dataset["decision_time"].eq(decision_time)].set_index("direction")

    assert pair.loc["SHORT", "entry_price"] == pytest.approx(90.0)
    assert pair.loc["SHORT", "target"] == "TIMEOUT"
    assert pair.loc["SHORT", "realized_gross_return"] == pytest.approx((90.0 - 89.50) / 90.0)

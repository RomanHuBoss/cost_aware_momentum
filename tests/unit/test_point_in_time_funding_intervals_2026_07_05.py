from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from app.ml.context import build_market_context_frame
from app.ml.funding import HistoricalFundingTimeline


def _interval_history() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["BTCUSDT", "BTCUSDT"],
            "valid_from": [
                datetime(2026, 1, 1, 0, tzinfo=UTC),
                datetime(2026, 1, 2, 0, tzinfo=UTC),
            ],
            "funding_interval_minutes": [480, 240],
        }
    )


def _funding(*hours: int) -> pd.DataFrame:
    origin = pd.Timestamp("2026-01-01T00:00:00Z")
    return pd.DataFrame(
        {
            "symbol": "BTCUSDT",
            "funding_time": [origin + pd.Timedelta(hour, unit="h") for hour in hours],
            "rate": np.linspace(0.0001, 0.0001 * len(hours), len(hours)),
        }
    )


def test_replay_accepts_complete_settlements_across_point_in_time_interval_change() -> None:
    timeline = HistoricalFundingTimeline(
        _funding(0, 8, 16, 24, 28, 32),
        interval_minutes={"BTCUSDT": 240},
        interval_history=_interval_history(),
    )

    aggregate = timeline.aggregate(
        "BTCUSDT",
        start_time=datetime(2026, 1, 1, 0, tzinfo=UTC),
        end_time=datetime(2026, 1, 2, 8, tzinfo=UTC),
    )

    assert aggregate.settlements == 5
    assert aggregate.cumulative_rate == pytest.approx(sum(np.linspace(0.0001, 0.0006, 6)[1:]))
    metadata = timeline.describe()
    assert metadata["interval_source"] == "instrument_spec_history_point_in_time"
    assert metadata["interval_change_count"] == 1


def test_replay_still_fails_closed_when_new_interval_settlement_is_missing() -> None:
    timeline = HistoricalFundingTimeline(
        _funding(0, 8, 16, 24, 32),
        interval_minutes={"BTCUSDT": 240},
        interval_history=_interval_history(),
    )

    with pytest.raises(ValueError, match="missing expected settlement"):
        timeline.aggregate(
            "BTCUSDT",
            start_time=datetime(2026, 1, 1, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, 8, tzinfo=UTC),
        )


def test_market_context_uses_interval_effective_at_each_historical_decision() -> None:
    starts = pd.date_range("2025-12-31T00:00:00Z", periods=52, freq="1h")
    closes = starts + pd.Timedelta(1, unit="h")
    base = np.linspace(100.0, 105.1, len(starts))
    candles = pd.DataFrame(
        {
            "symbol": "BTCUSDT",
            "open_time": starts,
            "close_time": closes,
            "close": base,
            "turnover": np.linspace(1_000_000.0, 1_500_000.0, len(starts)),
        }
    )
    mark = candles[["symbol", "open_time", "close_time", "close"]].copy()
    index = candles[["symbol", "open_time", "close_time", "close"]].copy()
    oi = pd.DataFrame(
        {
            "symbol": "BTCUSDT",
            "event_time": closes,
            "available_at": closes,
            "value": np.linspace(10_000.0, 11_000.0, len(starts)),
        }
    )
    funding = _funding(0, 8, 16, 24, 28, 32, 36, 40, 44, 48).assign(
        available_at=lambda frame: frame["funding_time"]
    )

    frame = build_market_context_frame(
        candles,
        mark_candles=mark,
        index_candles=index,
        open_interest=oi,
        funding_history=funding,
        funding_interval_minutes={"BTCUSDT": 240},
        funding_interval_history=_interval_history(),
    ).set_index("decision_time")

    assert frame.loc[pd.Timestamp("2026-01-01T04:00:00Z"), "funding_age_fraction"] == pytest.approx(0.5)
    assert frame.loc[pd.Timestamp("2026-01-02T02:00:00Z"), "funding_age_fraction"] == pytest.approx(0.5)
    metadata = frame.attrs["market_context"]
    assert metadata["funding_interval_source"] == "instrument_spec_history_point_in_time"
    assert metadata["funding_interval_change_count"] == 1


def test_replay_metadata_discloses_pre_observation_interval_assumption() -> None:
    funding = pd.DataFrame(
        {
            "symbol": ["BTCUSDT", "BTCUSDT", "BTCUSDT"],
            "funding_time": pd.to_datetime(
                [
                    "2025-12-31T16:00:00Z",
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T08:00:00Z",
                ],
                utc=True,
            ),
            "rate": [0.0001, 0.0002, 0.0003],
        }
    )
    history = pd.DataFrame(
        {
            "symbol": ["BTCUSDT"],
            "valid_from": pd.to_datetime(["2026-01-01T00:00:00Z"], utc=True),
            "funding_interval_minutes": [480],
        }
    )

    metadata = HistoricalFundingTimeline(
        funding,
        interval_minutes={"BTCUSDT": 480},
        interval_history=history,
    ).describe()

    assert metadata["interval_backward_assumption_symbols"] == ["BTCUSDT"]

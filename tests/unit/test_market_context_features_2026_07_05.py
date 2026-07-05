from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.bybit.client import BybitClient
from app.ml.context import (
    MARKET_CONTEXT_COMPLETE_COLUMN,
    MARKET_CONTEXT_FEATURE_NAMES,
    MARKET_CONTEXT_SCHEMA_VERSION,
    build_market_context_frame,
)


def _hourly_context_inputs(hours: int = 32):
    starts = pd.date_range("2026-01-01T00:00:00Z", periods=hours, freq="1h")
    closes = starts + pd.Timedelta(1, unit="h")
    candles = pd.DataFrame(
        {
            "symbol": "BTCUSDT",
            "open_time": starts,
            "close_time": closes,
            "close": np.linspace(100.0, 103.1, hours),
            "turnover": np.linspace(1_000_000.0, 1_500_000.0, hours),
        }
    )
    index_close = np.linspace(100.0, 103.1, hours)
    basis_bps = np.linspace(5.0, 20.5, hours)
    mark = pd.DataFrame(
        {
            "symbol": "BTCUSDT",
            "open_time": starts,
            "close_time": closes,
            "close": index_close * (1.0 + basis_bps / 10_000.0),
        }
    )
    index = pd.DataFrame(
        {
            "symbol": "BTCUSDT",
            "open_time": starts,
            "close_time": closes,
            "close": index_close,
        }
    )
    oi = pd.DataFrame(
        {
            "symbol": "BTCUSDT",
            "event_time": closes,
            "available_at": closes + pd.Timedelta(5, unit="s"),
            "value": np.linspace(10_000.0, 13_100.0, hours),
        }
    )
    funding_times = pd.date_range(closes[0].floor("8h"), closes[-1] + pd.Timedelta(8, unit="h"), freq="8h")
    funding = pd.DataFrame(
        {
            "symbol": "BTCUSDT",
            "funding_time": funding_times,
            "available_at": funding_times + pd.Timedelta(5, unit="s"),
            "rate": np.linspace(0.0001, 0.0006, len(funding_times)),
        }
    )
    return candles, mark, index, oi, funding


def test_context_features_use_only_exact_or_prior_market_events() -> None:
    candles, mark, index, oi, funding = _hourly_context_inputs()
    future_time = candles.iloc[-1]["close_time"] + pd.Timedelta(1, unit="h")
    funding = pd.concat(
        [
            funding,
            pd.DataFrame(
                {
                    "symbol": ["BTCUSDT"],
                    "funding_time": [future_time],
                    "available_at": [future_time],
                    "rate": [0.99],
                }
            ),
        ],
        ignore_index=True,
    )

    frame = build_market_context_frame(
        candles,
        mark_candles=mark,
        index_candles=index,
        open_interest=oi,
        funding_history=funding,
        funding_interval_minutes={"BTCUSDT": 480},
    )
    latest = frame.iloc[-1]

    assert latest[MARKET_CONTEXT_COMPLETE_COLUMN]
    assert tuple(MARKET_CONTEXT_FEATURE_NAMES) == (
        "oi_log_change_1h",
        "oi_log_change_24h",
        "basis_bps",
        "basis_change_1h_bps",
        "settled_funding_rate",
        "funding_age_fraction",
        "turnover_oi_log_ratio",
    )
    assert latest["basis_bps"] == pytest.approx(20.5)
    assert latest["basis_change_1h_bps"] == pytest.approx(0.5)
    assert latest["oi_log_change_1h"] == pytest.approx(np.log(13_100.0 / 13_000.0))
    assert latest["oi_log_change_24h"] == pytest.approx(np.log(13_100.0 / 10_700.0))
    assert latest["settled_funding_rate"] != pytest.approx(0.99)
    assert 0.0 <= latest["funding_age_fraction"] <= 1.0
    assert np.isfinite(latest["turnover_oi_log_ratio"])
    assert frame.attrs["market_context"]["schema"] == MARKET_CONTEXT_SCHEMA_VERSION


def test_context_is_fail_closed_when_exact_oi_or_basis_history_is_missing() -> None:
    candles, mark, index, oi, funding = _hourly_context_inputs()
    latest_close = candles.iloc[-1]["close_time"]
    oi = oi[oi["event_time"] != latest_close - pd.Timedelta(24, unit="h")]

    frame = build_market_context_frame(
        candles,
        mark_candles=mark,
        index_candles=index,
        open_interest=oi,
        funding_history=funding,
        funding_interval_minutes={"BTCUSDT": 480},
    )

    assert not bool(frame.iloc[-1][MARKET_CONTEXT_COMPLETE_COLUMN])
    assert pd.isna(frame.iloc[-1]["oi_log_change_24h"])


def test_context_rejects_duplicate_point_in_time_rows() -> None:
    candles, mark, index, oi, funding = _hourly_context_inputs()
    oi = pd.concat([oi, oi.iloc[[-1]]], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate"):
        build_market_context_frame(
            candles,
            mark_candles=mark,
            index_candles=index,
            open_interest=oi,
            funding_history=funding,
            funding_interval_minutes={"BTCUSDT": 480},
        )


@pytest.mark.asyncio
async def test_open_interest_client_supports_bounded_historical_queries(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Response:
        result = {"list": [], "nextPageCursor": "next"}

    async def fake_get(self, path, params, private=False):
        captured.update({"path": path, "params": params, "private": private})
        return _Response()

    monkeypatch.setattr(BybitClient, "_get", fake_get)
    client = BybitClient(base_url="https://example.invalid")
    page = await client.get_open_interest(
        "BTCUSDT",
        "1h",
        limit=500,
        start_ms=1_000,
        end_ms=2_000,
        cursor="cursor-1",
    )

    assert page == {"items": [], "next_cursor": "next"}
    assert captured["path"] == "/v5/market/open-interest"
    assert captured["private"] is False
    assert captured["params"] == {
        "category": "linear",
        "symbol": "BTCUSDT",
        "intervalTime": "1h",
        "limit": 200,
        "startTime": 1_000,
        "endTime": 2_000,
        "cursor": "cursor-1",
    }


def test_context_metadata_declares_exchange_event_replay_not_local_receipt_reconstruction() -> None:
    candles, mark, index, oi, funding = _hourly_context_inputs()
    frame = build_market_context_frame(
        candles,
        mark_candles=mark,
        index_candles=index,
        open_interest=oi,
        funding_history=funding,
        funding_interval_minutes={"BTCUSDT": 480},
    )

    metadata = frame.attrs["market_context"]
    assert metadata["availability_schema"] == "exchange-event-close-live-receipt-v1"
    assert metadata["historical_receipt_time_reconstructed"] is False
    assert metadata["required_sources"] == [
        "last_price_hourly",
        "mark_price_hourly",
        "index_price_hourly",
        "open_interest_hourly",
        "settled_funding",
    ]


def test_barrier_dataset_requires_all_market_context_sources() -> None:
    from app.ml.training import make_barrier_dataset

    candles, mark, _index, _oi, funding = _hourly_context_inputs(hours=40)
    candles = candles.assign(
        open=candles["close"],
        high=candles["close"] * 1.002,
        low=candles["close"] * 0.998,
        volume=1_000.0,
    )
    mark = mark.assign(
        open=mark["close"],
        high=mark["close"] * 1.002,
        low=mark["close"] * 0.998,
    )

    with pytest.raises(ValueError, match="Point-in-time market context is required"):
        make_barrier_dataset(
            candles,
            horizon=2,
            mark_candles=mark,
            funding_history=funding,
            funding_interval_minutes={"BTCUSDT": 480},
            require_market_context=True,
        )


def test_market_context_live_refresh_is_enabled_by_default() -> None:
    from app.config import Settings

    settings = Settings(_env_file=None)

    assert settings.universe_sync_mark_price is True
    assert settings.universe_enrich_funding_oi is True

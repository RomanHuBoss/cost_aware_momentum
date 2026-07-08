from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.config import Settings
from app.ml.training import minimum_hourly_history_timestamps_for_quality_gate
from app.services import market_data


def test_default_initial_backfill_covers_training_quality_gate_precondition() -> None:
    settings = Settings()
    required = minimum_hourly_history_timestamps_for_quality_gate(
        horizon_hours=settings.default_horizon_hours,
        minimum_holdout_rows=settings.auto_train_min_holdout_rows,
        minimum_holdout_span_hours=settings.auto_train_min_holdout_span_hours,
    )

    assert settings.initial_backfill_bars >= required


@pytest.mark.asyncio
async def test_sync_candles_paginates_initial_backfill_beyond_bybit_page_limit(monkeypatch) -> None:
    captured: list[dict] = []

    async def capture_upsert(_session, values_list: list[dict]) -> None:
        captured.extend(values_list)

    monkeypatch.setattr(market_data, "_upsert_candle_values", capture_upsert)

    start = datetime(2026, 1, 1, tzinfo=UTC)

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def get_kline(
            self,
            symbol: str,
            *,
            interval: str,
            limit: int,
            price_type: str,
            end_ms: int | None = None,
            start_ms: int | None = None,
        ) -> list[list[str]]:
            self.calls.append(
                {
                    "symbol": symbol,
                    "interval": interval,
                    "limit": limit,
                    "price_type": price_type,
                    "end_ms": end_ms,
                    "start_ms": start_ms,
                }
            )
            # Mimic Bybit's single-page cap: a request cannot return more than
            # 1000 candles, so sync_candles must paginate when its caller asks
            # for the model-readiness bootstrap depth.
            page_limit = min(limit, 1000)
            latest_index = 1499 if end_ms is None else int((end_ms // 1000 - start.timestamp()) // 3600)
            earliest_index = max(0, latest_index - page_limit + 1)
            rows: list[list[str]] = []
            for index in range(latest_index, earliest_index - 1, -1):
                open_time = start + timedelta(hours=index)
                rows.append(
                    [
                        str(int(open_time.timestamp() * 1000)),
                        "1",
                        "1",
                        "1",
                        "1",
                        "1",
                        "1",
                    ]
                )
            return rows

    client = FakeClient()
    rows = await market_data.sync_candles(
        object(),
        client,
        ["BTCUSDT"],
        interval="60",
        limit=1206,
        price_types=("last",),
        request_batch_size=1,
    )

    assert rows == 1206
    assert len(captured) == 1206
    assert len({item["open_time"] for item in captured}) == 1206
    assert len(client.calls) == 2
    assert client.calls[0]["limit"] == 1000
    assert client.calls[0]["end_ms"] is None
    assert client.calls[1]["limit"] == 206
    assert isinstance(client.calls[1]["end_ms"], int)


def test_default_open_interest_history_backfill_covers_training_quality_gate_precondition() -> None:
    settings = Settings()
    required = minimum_hourly_history_timestamps_for_quality_gate(
        horizon_hours=settings.default_horizon_hours,
        minimum_holdout_rows=settings.auto_train_min_holdout_rows,
        minimum_holdout_span_hours=settings.auto_train_min_holdout_span_hours,
    )
    open_interest_rows = settings.history_backfill_open_interest_pages_per_symbol * 200

    assert open_interest_rows >= required
    assert settings.history_backfill_pages_per_symbol * 200 < required

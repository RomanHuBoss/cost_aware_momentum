from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import market_data
from app.workers.runner import Worker, should_retry_incomplete_coverage


@pytest.mark.asyncio
async def test_sync_candles_reports_exact_decision_candle_coverage() -> None:
    event_time = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)
    open_time = event_time - timedelta(hours=1)

    class _Client:
        async def get_kline(
            self,
            symbol: str,
            *,
            interval: str,
            limit: int,
            price_type: str,
        ) -> list[list[str]]:
            assert interval == "60"
            assert limit == 3
            assert price_type == "last"
            if symbol == "ETHUSDT":
                raise TimeoutError("simulated transient Bybit timeout")
            return [
                [
                    str(int(open_time.timestamp() * 1000)),
                    "100",
                    "101",
                    "99",
                    "100.5",
                    "10",
                    "1000",
                ]
            ]

    diagnostics: dict[str, object] = {}
    session = SimpleNamespace(execute=AsyncMock())

    rows = await market_data.sync_candles(
        session,
        _Client(),
        ["BTCUSDT", "ETHUSDT"],
        interval="60",
        limit=3,
        price_types=("last",),
        required_close_time=event_time,
        diagnostics=diagnostics,
    )

    assert rows == 1
    assert diagnostics["symbols_total"] == 2
    assert diagnostics["symbols_covered"] == 1
    assert diagnostics["requests_failed"] == 1
    assert diagnostics["missing_symbols_sample"] == ["ETHUSDT"]


@pytest.mark.asyncio
async def test_hourly_market_close_retries_partial_exact_candle_coverage() -> None:
    event_time = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)
    worker = object.__new__(Worker)
    worker.active_symbols = ("BTCUSDT", "ETHUSDT")
    worker.run_job = AsyncMock(return_value={})

    await Worker.hourly_market_close_job(worker, event_time)

    kwargs = worker.run_job.await_args.kwargs
    assert kwargs["retry_incomplete_success"] is True
    assert kwargs["retry_total_key"] == "symbols_total"
    assert kwargs["retry_covered_keys"] == ("symbols_covered",)
    assert kwargs["retry_count_key"] == "candle_sync_retry_count"


def test_partial_candle_coverage_is_retryable_until_limit() -> None:
    details = {
        "symbols_total": 2,
        "symbols_covered": 1,
        "candle_sync_retry_count": 4,
    }
    assert should_retry_incomplete_coverage(
        details,
        total_key="symbols_total",
        covered_keys=("symbols_covered",),
        retry_count_key="candle_sync_retry_count",
        max_retries=5,
    )

    details["candle_sync_retry_count"] = 5
    assert not should_retry_incomplete_coverage(
        details,
        total_key="symbols_total",
        covered_keys=("symbols_covered",),
        retry_count_key="candle_sync_retry_count",
        max_retries=5,
    )


def test_complete_candle_coverage_is_not_retryable() -> None:
    assert not should_retry_incomplete_coverage(
        {
            "symbols_total": 2,
            "symbols_covered": 2,
            "candle_sync_retry_count": 0,
        },
        total_key="symbols_total",
        covered_keys=("symbols_covered",),
        retry_count_key="candle_sync_retry_count",
        max_retries=5,
    )

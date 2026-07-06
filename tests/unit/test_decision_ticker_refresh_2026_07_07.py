from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.workers import runner as runner_module


async def _execute_job(_name, _scheduled, task, **_kwargs):
    return await task(object())


@pytest.mark.asyncio
async def test_hourly_inference_refreshes_tickers_immediately_before_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    worker = object.__new__(runner_module.Worker)
    worker.active_symbols = ("BTCUSDT", "ETHUSDT")
    worker.runtime = SimpleNamespace(version="model-v1", is_baseline=False)

    async def get_tickers(_category: str) -> list[dict[str, str]]:
        events.append("fetch_tickers")
        return [
            {"symbol": "BTCUSDT", "lastPrice": "60000"},
            {"symbol": "ETHUSDT", "lastPrice": "3000"},
        ]

    worker.client = SimpleNamespace(get_tickers=get_tickers)
    worker.run_job = _execute_job

    async def sync_tickers(_session, _client, symbols, *, items=None) -> int:
        assert symbols == {"BTCUSDT", "ETHUSDT"}
        assert items and len(items) == 2
        events.append("persist_tickers")
        return 2

    async def publish(_session, **kwargs):
        assert kwargs["symbols"] == worker.active_symbols
        events.append("publish")
        return []

    monkeypatch.setattr(runner_module, "sync_tickers", sync_tickers)
    monkeypatch.setattr(runner_module, "publish_hourly_signals", publish)

    result = await runner_module.Worker.inference_job(
        worker,
        datetime(2026, 7, 7, 1, tzinfo=UTC),
    )

    assert events == ["fetch_tickers", "persist_tickers", "publish"]
    assert result["decision_ticker_refresh"]["requested"] == 2
    assert result["decision_ticker_refresh"]["stored"] == 2


@pytest.mark.asyncio
async def test_zero_row_decision_ticker_refresh_blocks_inference_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = object.__new__(runner_module.Worker)
    worker.active_symbols = ("BTCUSDT",)
    worker.runtime = SimpleNamespace(version="model-v1", is_baseline=False)
    worker.client = SimpleNamespace(
        get_tickers=AsyncMock(return_value=[{"symbol": "BTCUSDT", "lastPrice": "0"}])
    )
    worker.run_job = _execute_job

    monkeypatch.setattr(runner_module, "sync_tickers", AsyncMock(return_value=0))
    publish = AsyncMock(return_value=[])
    monkeypatch.setattr(runner_module, "publish_hourly_signals", publish)

    with pytest.raises(RuntimeError, match="stored no active symbols"):
        await runner_module.Worker.inference_job(
            worker,
            datetime(2026, 7, 7, 1, tzinfo=UTC),
        )

    publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_catchup_inference_uses_the_same_fresh_ticker_barrier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    worker = object.__new__(runner_module.Worker)
    worker.active_symbols = ("BTCUSDT",)
    worker.runtime = SimpleNamespace(version="model-v1", is_baseline=False)

    async def get_tickers(_category: str) -> list[dict[str, str]]:
        events.append("fetch_tickers")
        return [{"symbol": "BTCUSDT", "lastPrice": "60000"}]

    worker.client = SimpleNamespace(get_tickers=get_tickers)
    worker.run_job = _execute_job

    async def sync_tickers(_session, _client, _symbols, *, items=None) -> int:
        assert items
        events.append("persist_tickers")
        return 1

    async def publish(_session, **_kwargs):
        events.append("publish")
        return []

    monkeypatch.setattr(runner_module, "sync_tickers", sync_tickers)
    monkeypatch.setattr(runner_module, "publish_hourly_signals", publish)

    result = await runner_module.Worker.catchup_inference_job(worker, "universe_expanded")

    assert events == ["fetch_tickers", "persist_tickers", "publish"]
    assert result["decision_ticker_refresh"]["stored"] == 1


@pytest.mark.asyncio
async def test_market_sync_fetches_a_new_ticker_payload_after_slow_snapshot_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    worker = object.__new__(runner_module.Worker)
    worker.active_symbols = ("BTCUSDT",)
    worker.universe_summary = {"mode": "dynamic", "selected_symbols": ["BTCUSDT"]}
    worker.last_universe_refresh = datetime(2026, 7, 7, 0, tzinfo=UTC)
    worker._universe_refresh_due = lambda _now, _backfill: False
    worker.run_job = _execute_job

    async def get_tickers(_category: str) -> list[dict[str, str]]:
        events.append("fetch_tickers")
        return [{"symbol": "BTCUSDT", "lastPrice": "60000"}]

    worker.client = SimpleNamespace(get_tickers=get_tickers)

    async def sync_orderbooks(*_args, **_kwargs):
        events.append("sync_orderbooks")
        return {"requested": 1, "stored": 1, "duplicates": 0, "failed": 0}

    async def sync_tickers(_session, _client, _symbols, *, items=None) -> int:
        assert items
        events.append("persist_tickers")
        return 1

    monkeypatch.setattr(runner_module, "sync_orderbooks", sync_orderbooks)
    monkeypatch.setattr(runner_module, "sync_tickers", sync_tickers)

    result = await runner_module.Worker.market_job(worker)

    assert events == ["sync_orderbooks", "fetch_tickers", "persist_tickers"]
    assert result["tickers"] == 1


def test_json_logging_preserves_ticker_freshness_diagnostics() -> None:
    import json
    import logging

    from app.logging import JsonFormatter

    record = logging.LogRecord(
        name="app.services.signals",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="Skipping symbol with stale ticker",
        args=(),
        exc_info=None,
    )
    record.symbol = "BTCUSDT"
    record.ticker_age_seconds = 731.5
    record.max_ticker_age_seconds = 120
    record.ticker_source_time = "2026-07-06T21:01:38+00:00"
    record.ticker_received_at = "2026-07-06T21:01:38.2+00:00"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["ticker_age_seconds"] == 731.5
    assert payload["max_ticker_age_seconds"] == 120
    assert payload["ticker_source_time"] == "2026-07-06T21:01:38+00:00"
    assert payload["ticker_received_at"] == "2026-07-06T21:01:38.2+00:00"

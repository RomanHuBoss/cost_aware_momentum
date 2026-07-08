from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.workers import runner as runner_module


async def _execute_job(_name, _scheduled, task, **_kwargs):
    return await task(object())


def _worker() -> runner_module.Worker:
    worker = object.__new__(runner_module.Worker)
    worker.active_symbols = ("BTCUSDT", "ETHUSDT")
    worker.runtime = SimpleNamespace(version="model-v1", is_baseline=False)
    worker.run_job = _execute_job
    return worker


@pytest.mark.asyncio
async def test_hourly_inference_refreshes_account_orderbooks_and_tickers_before_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    worker = _worker()

    monkeypatch.setattr(
        runner_module,
        "settings",
        SimpleNamespace(bybit_read_only_account=True, orderbook_depth_levels=200, market_poll_seconds=60),
    )

    async def sync_account(_session, _client, _settings):
        events.append("account")
        return {"enabled": True, "equity": "1000"}

    async def sync_orderbooks(_session, _client, symbols, *, depth):
        assert set(symbols) == {"BTCUSDT", "ETHUSDT"}
        assert depth == 200
        events.append("orderbooks")
        return {"requested": 2, "stored": 2, "duplicates": 0, "failed": 0}

    async def refresh_tickers(_session, symbols, *, purpose):
        assert tuple(symbols) == worker.active_symbols
        assert purpose == "hourly_inference"
        events.append("tickers")
        return {"requested": 2, "stored": 2}

    async def publish(_session, **kwargs):
        assert kwargs["symbols"] == worker.active_symbols
        events.append("publish")
        return []

    worker.client = object()
    worker._refresh_tickers_for_symbols = refresh_tickers
    monkeypatch.setattr(runner_module, "sync_read_only_account", sync_account)
    monkeypatch.setattr(runner_module, "sync_orderbooks", sync_orderbooks)
    monkeypatch.setattr(runner_module, "publish_hourly_signals", publish)

    result = await runner_module.Worker.inference_job(
        worker,
        datetime(2026, 7, 7, 1, tzinfo=UTC),
    )

    assert events == ["account", "orderbooks", "tickers", "publish"]
    assert result["execution_input_refresh"]["account"]["enabled"] is True
    assert result["execution_input_refresh"]["orderbooks"]["stored"] == 2
    assert result["decision_ticker_refresh"]["stored"] == 2
    assert isinstance(worker.last_account_sync, datetime)


@pytest.mark.asyncio
async def test_catchup_inference_uses_same_execution_snapshot_barrier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    worker = _worker()

    monkeypatch.setattr(
        runner_module,
        "settings",
        SimpleNamespace(bybit_read_only_account=True, orderbook_depth_levels=50, market_poll_seconds=60),
    )

    async def sync_account(_session, _client, _settings):
        events.append("account")
        return {"enabled": True}

    async def sync_orderbooks(_session, _client, _symbols, *, depth):
        assert depth == 50
        events.append("orderbooks")
        return {"requested": 2, "stored": 1, "duplicates": 1, "failed": 0}

    async def refresh_tickers(_session, _symbols, *, purpose):
        assert purpose == "universe_catchup_inference"
        events.append("tickers")
        return {"requested": 2, "stored": 2}

    async def publish(_session, **_kwargs):
        events.append("publish")
        return []

    worker.client = object()
    worker._refresh_tickers_for_symbols = refresh_tickers
    monkeypatch.setattr(runner_module, "sync_read_only_account", sync_account)
    monkeypatch.setattr(runner_module, "sync_orderbooks", sync_orderbooks)
    monkeypatch.setattr(runner_module, "publish_hourly_signals", publish)

    result = await runner_module.Worker.catchup_inference_job(
        worker,
        "startup_backfill",
        checked_at=datetime(2026, 7, 8, 1, 1, 15, tzinfo=UTC),
    )

    assert events == ["account", "orderbooks", "tickers", "publish"]
    assert result["execution_input_refresh"]["orderbooks"]["duplicates"] == 1
    assert isinstance(worker.last_account_sync, datetime)


@pytest.mark.asyncio
async def test_zero_orderbook_refresh_coverage_blocks_publication_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker()
    worker.client = object()

    monkeypatch.setattr(
        runner_module,
        "settings",
        SimpleNamespace(bybit_read_only_account=False, orderbook_depth_levels=200, market_poll_seconds=60),
    )
    monkeypatch.setattr(
        runner_module,
        "sync_orderbooks",
        AsyncMock(
            return_value={"requested": 2, "stored": 0, "duplicates": 0, "failed": 2}
        ),
    )
    worker._refresh_tickers_for_symbols = AsyncMock(
        return_value={"requested": 2, "stored": 2}
    )
    publish = AsyncMock(return_value=[])
    monkeypatch.setattr(runner_module, "publish_hourly_signals", publish)

    with pytest.raises(RuntimeError, match="orderbook refresh stored no active symbols"):
        await runner_module.Worker.inference_job(
            worker,
            datetime(2026, 7, 7, 1, tzinfo=UTC),
        )

    worker._refresh_tickers_for_symbols.assert_not_awaited()
    publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_account_refresh_failure_blocks_publication_before_market_signal_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker()
    worker.client = object()

    monkeypatch.setattr(
        runner_module,
        "settings",
        SimpleNamespace(bybit_read_only_account=True, orderbook_depth_levels=200, market_poll_seconds=60),
    )
    monkeypatch.setattr(
        runner_module,
        "sync_read_only_account",
        AsyncMock(side_effect=RuntimeError("private account unavailable")),
    )
    sync_orderbooks = AsyncMock(
        return_value={"requested": 2, "stored": 2, "duplicates": 0, "failed": 0}
    )
    monkeypatch.setattr(runner_module, "sync_orderbooks", sync_orderbooks)
    worker._refresh_tickers_for_symbols = AsyncMock(
        return_value={"requested": 2, "stored": 2}
    )
    publish = AsyncMock(return_value=[])
    monkeypatch.setattr(runner_module, "publish_hourly_signals", publish)

    with pytest.raises(RuntimeError, match="private account unavailable"):
        await runner_module.Worker.catchup_inference_job(
            worker,
            "startup_backfill",
            checked_at=datetime(2026, 7, 8, 1, 1, 15, tzinfo=UTC),
        )

    sync_orderbooks.assert_not_awaited()
    worker._refresh_tickers_for_symbols.assert_not_awaited()
    publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_capital_mode_skips_private_account_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    worker = _worker()
    worker.client = object()

    monkeypatch.setattr(
        runner_module,
        "settings",
        SimpleNamespace(bybit_read_only_account=False, orderbook_depth_levels=200, market_poll_seconds=60),
    )
    account = AsyncMock(return_value={"enabled": True})
    monkeypatch.setattr(runner_module, "sync_read_only_account", account)

    async def sync_orderbooks(_session, _client, _symbols, *, depth):
        assert depth == 200
        events.append("orderbooks")
        return {"requested": 2, "stored": 2, "duplicates": 0, "failed": 0}

    async def refresh_tickers(_session, _symbols, *, purpose):
        assert purpose == "hourly_inference"
        events.append("tickers")
        return {"requested": 2, "stored": 2}

    async def publish(_session, **_kwargs):
        events.append("publish")
        return []

    monkeypatch.setattr(runner_module, "sync_orderbooks", sync_orderbooks)
    worker._refresh_tickers_for_symbols = refresh_tickers
    monkeypatch.setattr(runner_module, "publish_hourly_signals", publish)

    await runner_module.Worker.inference_job(
        worker,
        datetime(2026, 7, 7, 1, tzinfo=UTC),
    )

    account.assert_not_awaited()
    assert events == ["orderbooks", "tickers", "publish"]

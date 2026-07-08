from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.workers import runner as runner_module


async def _execute_job(_name, _scheduled, task, **_kwargs):
    return await task(object())


def test_publication_window_rejects_current_hour_after_contract_delay() -> None:
    event_time = datetime(2026, 7, 8, 1, 0, tzinfo=UTC)
    checked_at = event_time + timedelta(minutes=31, seconds=26)

    window = runner_module.resolve_decision_publication_window(
        event_time=event_time,
        checked_at=checked_at,
        maximum_delay_seconds=600,
    )

    assert not window.within_window
    assert window.reason_code == "decision_publication_lag_exceeded"
    assert window.publication_lag_seconds == pytest.approx(1886.0)
    assert window.maximum_delay_seconds == 600
    assert window.as_diagnostics()["publish_time"] == checked_at.isoformat()


@pytest.mark.asyncio
async def test_stale_hourly_cycle_skips_before_market_close_or_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_time = datetime(2026, 7, 8, 1, 0, tzinfo=UTC)
    checked_at = event_time + timedelta(minutes=31, seconds=26)
    worker = object.__new__(runner_module.Worker)
    worker.active_symbols = ("BTCUSDT", "ETHUSDT")
    calls: list[str] = []

    monkeypatch.setattr(
        runner_module,
        "settings",
        SimpleNamespace(max_signal_publication_delay_seconds=600, drift_monitor_enabled=True),
    )

    async def record(name: str, _event_time: datetime) -> dict[str, object]:
        calls.append(name)
        return {}

    worker.hourly_market_close_job = lambda value: record("market_close", value)
    worker.counterfactual_outcome_job = lambda value: record("outcomes", value)
    worker.drift_monitor_job = lambda value: record("drift", value)
    worker.inference_job = lambda value, **_kwargs: record("inference", value)
    worker.retention_job = lambda value: record("retention", value)

    result = await runner_module.Worker.hourly_decision_cycle(
        worker,
        event_time,
        cycle_started_at=checked_at,
    )

    assert calls == []
    assert result["skipped"] == "decision_publication_lag_exceeded"
    assert result["publication_boundary"]["publication_lag_seconds"] == pytest.approx(1886.0)


@pytest.mark.asyncio
async def test_stale_catchup_records_terminal_skip_without_execution_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_time = datetime(2026, 7, 8, 1, 0, tzinfo=UTC)
    checked_at = event_time + timedelta(minutes=31, seconds=26)
    worker = object.__new__(runner_module.Worker)
    worker.active_symbols = ("BTCUSDT", "ETHUSDT")
    worker.runtime = SimpleNamespace(version="model-v1", is_baseline=False)
    worker.client = object()
    worker.run_job = _execute_job
    worker._refresh_execution_inputs = AsyncMock(side_effect=AssertionError("stale catchup refreshed execution inputs"))
    worker._refresh_tickers_for_symbols = AsyncMock(side_effect=AssertionError("stale catchup refreshed tickers"))
    worker.last_account_sync = None

    monkeypatch.setattr(
        runner_module,
        "settings",
        SimpleNamespace(
            bybit_read_only_account=True,
            market_poll_seconds=60,
            max_signal_publication_delay_seconds=600,
        ),
    )
    publish = AsyncMock(side_effect=AssertionError("stale catchup reached publication"))
    monkeypatch.setattr(runner_module, "publish_hourly_signals", publish)

    result = await runner_module.Worker.catchup_inference_job(
        worker,
        "startup_backfill",
        checked_at=checked_at,
    )

    assert result["skipped"] == "decision_publication_lag_exceeded"
    assert result["published"] == 0
    assert result["symbols_total"] == 2
    assert result["symbol_outcome_count"] == 2
    assert result["skip_counts"] == {"decision_publication_lag_exceeded": 2}
    assert result["publication_boundary"]["publication_lag_seconds"] == pytest.approx(1886.0)
    worker._refresh_execution_inputs.assert_not_awaited()
    worker._refresh_tickers_for_symbols.assert_not_awaited()
    publish.assert_not_awaited()

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.db.models import UniverseEligibilitySnapshot
from app.services.universe import (
    UNIVERSE_ELIGIBILITY_SCHEMA,
    build_universe_eligibility_record_hash,
    persist_universe_selection,
    select_dynamic_universe,
    validate_universe_eligibility_snapshot_record,
)
from app.workers import runner as runner_module

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _instrument(
    symbol: str,
    *,
    now: datetime,
    age_days: int = 100,
    status: str = "Trading",
) -> SimpleNamespace:
    return SimpleNamespace(
        symbol=symbol,
        category="linear",
        base_coin=symbol.removesuffix("USDT"),
        quote_coin="USDT",
        settle_coin="USDT",
        status=status,
        launch_time=now - timedelta(days=age_days),
        delivery_time=None,
        is_pre_listing=False,
        raw={"contractType": "LinearPerpetual", "symbolType": ""},
    )


def _ticker(symbol: str, *, turnover: str, bid: str = "99.9", ask: str = "100") -> dict:
    return {
        "symbol": symbol,
        "lastPrice": "99.95",
        "bid1Price": bid,
        "ask1Price": ask,
        "turnover24h": turnover,
    }


def _selection():
    now = datetime(2026, 7, 6, 12, tzinfo=UTC)
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        universe_mode="dynamic",
        universe_min_age_days=7,
        universe_min_turnover_24h=1_000_000,
        universe_max_spread_bps=50,
        universe_max_symbols=1,
    )
    instruments = [
        _instrument("BTCUSDT", now=now),
        _instrument("ETHUSDT", now=now),
        _instrument("LOWUSDT", now=now),
        _instrument("NEWUSDT", now=now, age_days=2),
    ]
    tickers = [
        _ticker("BTCUSDT", turnover="100000000"),
        _ticker("ETHUSDT", turnover="50000000"),
        _ticker("LOWUSDT", turnover="10"),
        _ticker("NEWUSDT", turnover="30000000"),
    ]
    return select_dynamic_universe(instruments, tickers, settings, now=now)


def test_dynamic_universe_preserves_every_point_in_time_eligibility_decision() -> None:
    selection = _selection()

    decisions = {decision.symbol: decision for decision in selection.decisions}
    assert set(decisions) == {"BTCUSDT", "ETHUSDT", "LOWUSDT", "NEWUSDT"}
    assert decisions["BTCUSDT"].selected is True
    assert decisions["BTCUSDT"].reason_code == "selected"
    assert decisions["BTCUSDT"].rank == 1
    assert decisions["BTCUSDT"].turnover_24h is not None
    assert decisions["BTCUSDT"].spread_bps is not None
    assert decisions["BTCUSDT"].age_seconds == 100 * 24 * 60 * 60
    assert decisions["ETHUSDT"].eligible_before_limit is True
    assert decisions["ETHUSDT"].selected is False
    assert decisions["ETHUSDT"].rank == 2
    assert decisions["ETHUSDT"].reason_code == "rank_limit"
    assert decisions["LOWUSDT"].reason_code == "low_turnover"
    assert decisions["NEWUSDT"].reason_code == "insufficient_age"
    assert selection.summary()["decision_count"] == selection.total_instruments
    assert len(selection.policy_hash) == 64


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushed = False

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flushed = True


@pytest.mark.asyncio
async def test_universe_snapshot_is_atomic_complete_and_hash_bound() -> None:
    selection = _selection()
    recorded_at = selection.observed_at + timedelta(milliseconds=250)
    session = _FakeSession()

    snapshot = await persist_universe_selection(
        session,  # type: ignore[arg-type]
        selection,
        recorded_at=recorded_at,
        release_version="test-release",
    )

    assert session.added == [snapshot]
    assert session.flushed is True
    assert snapshot.id == selection.refresh_id
    assert snapshot.eligibility_schema == UNIVERSE_ELIGIBILITY_SCHEMA
    assert snapshot.selected_symbols == ["BTCUSDT"]
    assert snapshot.total_instruments == 4
    assert snapshot.eligible_before_limit == 2
    assert snapshot.selected_count == 1
    assert len(snapshot.decisions) == 4
    assert {item["symbol"] for item in snapshot.decisions} == {
        "BTCUSDT",
        "ETHUSDT",
        "LOWUSDT",
        "NEWUSDT",
    }
    payload = {
        "id": str(selection.refresh_id),
        "observed_at": selection.observed_at.isoformat(),
        "recorded_at": recorded_at.isoformat(),
        "mode": selection.mode,
        "eligibility_schema": UNIVERSE_ELIGIBILITY_SCHEMA,
        "policy": selection.policy,
        "policy_hash": selection.policy_hash,
        "decisions": snapshot.decisions,
        "selected_symbols": ["BTCUSDT"],
        "total_instruments": 4,
        "ticker_count": 4,
        "eligible_before_limit": 2,
        "selected_count": 1,
        "release_version": "test-release",
    }
    assert snapshot.record_hash == build_universe_eligibility_record_hash(payload)


@pytest.mark.asyncio
async def test_universe_snapshot_rejects_incomplete_or_tampered_evidence() -> None:
    selection = _selection()
    session = _FakeSession()

    with pytest.raises(ValueError, match="policy hash mismatch"):
        await persist_universe_selection(
            session,  # type: ignore[arg-type]
            replace(selection, policy_hash="0" * 64),
        )

    incomplete = replace(selection, decisions=selection.decisions[:-1])
    with pytest.raises(ValueError, match="coverage is incomplete"):
        await persist_universe_selection(session, incomplete)  # type: ignore[arg-type]
    assert session.added == []


def test_universe_snapshot_model_and_migration_are_append_only() -> None:
    table = UniverseEligibilitySnapshot.__table__
    assert table.schema == "market"
    assert {column.name for column in table.columns} >= {
        "observed_at",
        "policy",
        "decisions",
        "selected_symbols",
        "record_hash",
    }

    migration = (PROJECT_ROOT / "migrations/versions/0015_universe_eligibility.py").read_text(
        encoding="utf-8"
    )
    assert 'revision = "0015_universe_eligibility"' in migration
    assert 'down_revision = "0014_ui_exposure_ledger"' in migration
    assert "CREATE TABLE IF NOT EXISTS market.universe_eligibility_snapshots" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "universe eligibility snapshots are immutable" in migration


@pytest.mark.asyncio
async def test_market_job_persists_refresh_before_committing_in_memory_state(monkeypatch) -> None:
    selection = _selection()
    worker = object.__new__(runner_module.Worker)
    worker.client = SimpleNamespace(get_tickers=AsyncMock(return_value=[]))
    worker.active_symbols = ("OLDUSDT",)
    worker.universe_summary = {"mode": "dynamic", "selected_symbols": ["OLDUSDT"]}
    worker.last_universe_refresh = None
    worker._universe_refresh_due = lambda _now, _backfill: True

    session = object()
    monkeypatch.setattr(runner_module, "resolve_universe", AsyncMock(return_value=selection))
    persist = AsyncMock()
    monkeypatch.setattr(runner_module, "persist_universe_selection", persist)
    monkeypatch.setattr(runner_module, "sync_tickers", AsyncMock(return_value=1))
    monkeypatch.setattr(runner_module, "sync_orderbooks", AsyncMock(return_value=1))
    monkeypatch.setattr(runner_module, "sync_candles", AsyncMock(return_value=3))
    monkeypatch.setattr(runner_module, "sync_funding_and_oi", AsyncMock(return_value=(1, 1)))

    async def committed_run_job(_name, _scheduled, task, **_kwargs):
        result = await task(session)
        assert worker.active_symbols == ("OLDUSDT",)
        return result

    worker.run_job = committed_run_job
    result = await runner_module.Worker.market_job(worker)

    persist.assert_awaited_once_with(session, selection)
    assert worker.active_symbols == selection.symbols
    assert worker.universe_summary["refresh_id"] == str(selection.refresh_id)
    assert worker.last_universe_refresh == selection.observed_at
    assert result["universe"]["decision_count"] == 4


@pytest.mark.asyncio
async def test_market_job_does_not_advance_memory_when_transaction_fails(monkeypatch) -> None:
    selection = _selection()
    worker = object.__new__(runner_module.Worker)
    worker.client = SimpleNamespace(get_tickers=AsyncMock(return_value=[]))
    worker.active_symbols = ("OLDUSDT",)
    worker.universe_summary = {"mode": "dynamic", "selected_symbols": ["OLDUSDT"]}
    worker.last_universe_refresh = None
    worker._universe_refresh_due = lambda _now, _backfill: True

    monkeypatch.setattr(runner_module, "resolve_universe", AsyncMock(return_value=selection))
    monkeypatch.setattr(runner_module, "persist_universe_selection", AsyncMock())
    monkeypatch.setattr(runner_module, "sync_tickers", AsyncMock(return_value=1))
    monkeypatch.setattr(runner_module, "sync_orderbooks", AsyncMock(side_effect=RuntimeError("db failure")))

    async def transactional_run_job(_name, _scheduled, task, **_kwargs):
        return await task(object())

    worker.run_job = transactional_run_job
    with pytest.raises(RuntimeError, match="db failure"):
        await runner_module.Worker.market_job(worker)

    assert worker.active_symbols == ("OLDUSDT",)
    assert worker.universe_summary == {"mode": "dynamic", "selected_symbols": ["OLDUSDT"]}
    assert worker.last_universe_refresh is None


@pytest.mark.asyncio
async def test_research_replay_revalidates_persisted_snapshot_hashes() -> None:
    selection = _selection()
    snapshot = await persist_universe_selection(
        _FakeSession(),  # type: ignore[arg-type]
        selection,
        recorded_at=selection.observed_at + timedelta(milliseconds=250),
        release_version="test-release",
    )

    payload = validate_universe_eligibility_snapshot_record(snapshot)
    assert payload["selected_symbols"] == ["BTCUSDT"]

    snapshot.record_hash = "0" * 64
    with pytest.raises(ValueError, match="record hash mismatch"):
        validate_universe_eligibility_snapshot_record(snapshot)

@pytest.mark.asyncio
async def test_research_replay_rejects_snapshot_from_another_universe_mode() -> None:
    selection = _selection()
    snapshot = await persist_universe_selection(
        _FakeSession(),  # type: ignore[arg-type]
        selection,
        recorded_at=selection.observed_at + timedelta(milliseconds=250),
        release_version="test-release",
    )
    snapshot.mode = "static"

    with pytest.raises(ValueError, match="mode is incompatible"):
        validate_universe_eligibility_snapshot_record(snapshot, expected_mode="dynamic")


@pytest.mark.asyncio
async def test_universe_snapshot_hash_is_invariant_to_postgres_session_timezone() -> None:
    selection = _selection()
    snapshot = await persist_universe_selection(
        _FakeSession(),  # type: ignore[arg-type]
        selection,
        recorded_at=selection.observed_at + timedelta(milliseconds=250),
        release_version="test-release",
    )
    original_hash = snapshot.record_hash
    database_timezone = timezone(timedelta(hours=3))
    snapshot.observed_at = snapshot.observed_at.astimezone(database_timezone)
    snapshot.recorded_at = snapshot.recorded_at.astimezone(database_timezone)

    payload = validate_universe_eligibility_snapshot_record(snapshot)

    assert snapshot.record_hash == original_hash
    assert payload["observed_at"] == selection.observed_at.isoformat()
    assert payload["recorded_at"] == (
        selection.observed_at + timedelta(milliseconds=250)
    ).isoformat()

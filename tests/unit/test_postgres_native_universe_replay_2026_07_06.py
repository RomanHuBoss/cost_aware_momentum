from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.ml.universe_replay import (
    POSTGRES_UNIVERSE_ASOF_LOADER_SCHEMA,
    UNIVERSE_REPLAY_ASOF_SQL,
    load_point_in_time_universe_snapshots,
)
from app.services.universe import persist_universe_selection, select_dynamic_universe


class _PersistSession:
    def add(self, _value: object) -> None:
        pass

    async def flush(self) -> None:
        pass


class _AsyncMappingStream:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = iter(rows)

    def mappings(self) -> _AsyncMappingStream:
        return self

    def __aiter__(self) -> _AsyncMappingStream:
        return self

    async def __anext__(self) -> dict[str, object]:
        try:
            return next(self._rows)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _StreamingSession:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.statement = None
        self.params: dict[str, object] | None = None

    async def stream(self, statement, params):
        self.statement = statement
        self.params = params
        return _AsyncMappingStream(self.rows)


def _instrument(symbol: str, *, now: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        symbol=symbol,
        category="linear",
        base_coin=symbol.removesuffix("USDT"),
        quote_coin="USDT",
        settle_coin="USDT",
        status="Trading",
        launch_time=now - timedelta(days=100),
        delivery_time=None,
        is_pre_listing=False,
        raw={"contractType": "LinearPerpetual", "symbolType": ""},
    )


async def _valid_snapshot_row() -> dict[str, object]:
    observed_at = datetime(2026, 7, 6, 9, 55, tzinfo=UTC)
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        universe_mode="dynamic",
        universe_min_age_days=7,
        universe_min_turnover_24h=1,
        universe_max_spread_bps=100,
        universe_max_symbols=1,
    )
    selection = select_dynamic_universe(
        [_instrument("BTCUSDT", now=observed_at)],
        [
            {
                "symbol": "BTCUSDT",
                "lastPrice": "100",
                "bid1Price": "99.9",
                "ask1Price": "100.1",
                "turnover24h": "1000000",
            }
        ],
        settings,
        now=observed_at,
    )
    snapshot = await persist_universe_selection(
        _PersistSession(),  # type: ignore[arg-type]
        selection,
        recorded_at=observed_at + timedelta(seconds=1),
        release_version="test-release",
    )
    return {
        column.name: getattr(snapshot, column.name)
        for column in snapshot.__table__.columns
    }


def test_asof_sql_reduces_in_postgresql_by_commit_availability() -> None:
    sql = str(UNIVERSE_REPLAY_ASOF_SQL)

    assert "unnest(CAST(:decision_times AS TIMESTAMPTZ[]))" in sql
    assert "LEFT JOIN LATERAL" in sql
    assert "snapshot.recorded_at <= decision.decision_time" in sql
    assert "snapshot.mode = :mode" in sql
    assert "snapshot.*" in sql
    assert "snapshot.observed_at >=" not in sql


@pytest.mark.asyncio
async def test_asof_loader_streams_validates_and_retains_only_compact_replay_columns() -> None:
    row = await _valid_snapshot_row()
    session = _StreamingSession([row])
    decision_time = datetime(2026, 7, 6, 10, tzinfo=UTC)

    frame = await load_point_in_time_universe_snapshots(
        session,  # type: ignore[arg-type]
        [decision_time, decision_time],
        expected_mode="dynamic",
    )

    assert session.params == {
        "decision_times": [decision_time],
        "mode": "dynamic",
    }
    assert list(frame.columns) == [
        "observed_at",
        "recorded_at",
        "selected_symbols",
        "policy_hash",
        "record_hash",
    ]
    assert frame.to_dict("records") == [
        {
            "observed_at": row["observed_at"],
            "recorded_at": row["recorded_at"],
            "selected_symbols": row["selected_symbols"],
            "policy_hash": row["policy_hash"],
            "record_hash": row["record_hash"],
        }
    ]
    assert "decisions" not in frame.columns
    assert "policy" not in frame.columns
    assert frame.attrs["universe_snapshot_loader"] == {
        "schema": POSTGRES_UNIVERSE_ASOF_LOADER_SCHEMA,
        "requested_decision_timestamps": 1,
        "snapshot_rows_streamed": 1,
        "compact_rows_retained": 1,
    }


@pytest.mark.asyncio
async def test_asof_loader_rejects_naive_decision_time_before_database_access() -> None:
    session = _StreamingSession([])

    with pytest.raises(ValueError, match="timezone-aware"):
        await load_point_in_time_universe_snapshots(
            session,  # type: ignore[arg-type]
            [datetime(2026, 7, 6, 10)],
            expected_mode="dynamic",
        )

    assert session.statement is None


def test_asof_index_migration_matches_orm_contract() -> None:
    from pathlib import Path

    from app.db.models import UniverseEligibilitySnapshot

    project_root = Path(__file__).resolve().parents[2]
    index_names = {index.name for index in UniverseEligibilitySnapshot.__table__.indexes}
    assert "ix_universe_eligibility_mode_recorded_at" in index_names

    migration = (
        project_root / "migrations/versions/0016_universe_replay_asof.py"
    ).read_text(encoding="utf-8")
    assert 'revision = "0016_universe_replay_asof"' in migration
    assert 'down_revision = "0015_universe_eligibility"' in migration
    assert "ON market.universe_eligibility_snapshots (mode, recorded_at)" in migration


@pytest.mark.asyncio
async def test_loader_evidence_flows_into_replay_report() -> None:
    from app.ml.universe_replay import apply_point_in_time_universe_replay

    row = await _valid_snapshot_row()
    session = _StreamingSession([row])
    decision_time = datetime(2026, 7, 6, 10, tzinfo=UTC)
    snapshots = await load_point_in_time_universe_snapshots(
        session,  # type: ignore[arg-type]
        [decision_time],
        expected_mode="dynamic",
    )
    dataset = __import__("pandas").DataFrame(
        [{"decision_time": decision_time, "symbol": "BTCUSDT"}]
    )

    filtered, evidence = apply_point_in_time_universe_replay(
        dataset,
        snapshots,
        max_snapshot_age_seconds=600,
        required=True,
    )

    assert len(filtered) == 1
    assert evidence["snapshot_loader"]["schema"] == POSTGRES_UNIVERSE_ASOF_LOADER_SCHEMA
    assert evidence["snapshot_loader"]["requested_decision_timestamps"] == 1

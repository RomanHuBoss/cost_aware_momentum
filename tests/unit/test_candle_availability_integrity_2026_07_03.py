from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.services import market_data

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = PROJECT_ROOT / "migrations/versions/0009_candle_receipt_availability.py"


class _Clock(datetime):
    current = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):
        value = cls.current
        if tz is None:
            return value.replace(tzinfo=None)
        return value.astimezone(tz)


def _compiled(statement) -> tuple[str, dict[str, object]]:
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


@pytest.mark.asyncio
async def test_late_fetched_confirmed_candle_is_available_only_after_receipt(monkeypatch) -> None:
    open_time = datetime(2026, 7, 3, 8, 0, tzinfo=UTC)
    response_received = datetime(2026, 7, 3, 12, 0, 7, tzinfo=UTC)
    _Clock.current = open_time + timedelta(hours=1)
    monkeypatch.setattr(market_data, "datetime", _Clock)

    class _Client:
        async def get_kline(self, *args, **kwargs):
            _Clock.current = response_received
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

    session = SimpleNamespace(execute=AsyncMock())
    await market_data.sync_candles(
        session,
        _Client(),
        ["BTCUSDT"],
        interval="60",
        limit=1,
        price_types=("last",),
    )

    statement = session.execute.await_args.args[0]
    _, params = _compiled(statement)
    assert params["confirmed_m0"] is True
    assert params["available_at_m0"] == response_received
    assert params["available_at_m0"] > open_time + timedelta(hours=1)


def test_legacy_candle_migration_moves_availability_forward_fail_closed(monkeypatch) -> None:
    assert MIGRATION_PATH.exists(), "receipt-time data migration is required"
    spec = importlib.util.spec_from_file_location("migration_0009", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    statements: list[str] = []
    monkeypatch.setattr(module.op, "execute", lambda statement: statements.append(str(statement)))
    module.upgrade()

    sql = "\n".join(statements).lower()
    assert "update market.candles" in sql
    assert "available_at = greatest(available_at, current_timestamp)" in sql
    assert "where confirmed is true" in sql

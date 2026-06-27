from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.api.v1.recommendations import recommendation_signal_query
from app.db.models import MarketSignal
from app.services.signals import supersede_published_signals


class _ScalarRows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarRows:
        return self

    def all(self) -> list[object]:
        return self._rows


def test_recommendation_query_selects_latest_row_per_symbol() -> None:
    query = recommendation_signal_query(
        include_expired=False,
        symbol=None,
        latest_per_symbol=True,
        limit=2000,
        now=datetime(2026, 6, 27, tzinfo=UTC),
    )
    sql = str(
        query.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "row_number() OVER (PARTITION BY advisory.market_signals.symbol" in sql
    assert "anon_1.symbol_rank = 1" in sql
    assert "advisory.market_signals.status = 'PUBLISHED'" in sql


def test_market_signal_has_one_published_per_symbol_index() -> None:
    index = next(
        item
        for item in MarketSignal.__table__.indexes
        if item.name == "uq_market_signal_one_published_per_symbol"
    )

    assert index.unique is True
    assert str(index.dialect_options["postgresql"]["where"]) == "status = 'PUBLISHED'"


async def test_supersede_published_signals_retires_pending_plans() -> None:
    previous = SimpleNamespace(
        id=uuid4(),
        status="PUBLISHED",
        invalidation_reason=None,
        updated_at=None,
    )
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[_ScalarRows([previous]), SimpleNamespace(rowcount=1)]),
        flush=AsyncMock(),
    )

    result = await supersede_published_signals(
        session,
        symbol="EVAAUSDT",
        replacement_natural_key="EVAAUSDT-20260627T100000Z-SHORT-h8-model",
    )

    assert result == [previous]
    assert previous.status == "SUPERSEDED"
    assert "EVAAUSDT-20260627T100000Z" in previous.invalidation_reason
    session.flush.assert_awaited_once()
    assert session.execute.await_count == 2

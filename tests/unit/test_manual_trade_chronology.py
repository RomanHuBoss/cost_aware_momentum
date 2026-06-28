from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.schemas import TradeCloseRequest
from app.api.v1 import trades as trades_module


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeSession:
    def __init__(self, execute_values):
        self.execute_values = list(execute_values)
        self.added = []
        self.committed = False

    async def execute(self, _query):
        if not self.execute_values:
            raise AssertionError("Unexpected database query")
        return _ScalarResult(self.execute_values.pop(0))

    async def get(self, _model, _key):
        return None

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.committed = True


async def _none(*_args, **_kwargs):
    return None


def _trade(*, entry_time: datetime, remaining_qty: str = "1"):
    return SimpleNamespace(
        id=uuid4(),
        plan_id=uuid4(),
        status="OPEN",
        direction="LONG",
        entry_time=entry_time,
        entry_price=Decimal("100"),
        remaining_qty=Decimal(remaining_qty),
        fees_paid=Decimal("0"),
        funding_cash_flow=Decimal("0"),
        realized_pnl=Decimal("0"),
        notes=None,
    )


def _payload(*, fill_time: datetime) -> TradeCloseRequest:
    return TradeCloseRequest(
        fill_time=fill_time,
        exit_price=Decimal("101"),
        qty=Decimal("0.5"),
        fee=Decimal("0.01"),
        funding=Decimal("0"),
    )


@pytest.fixture(autouse=True)
def _isolate_side_effects(monkeypatch):
    monkeypatch.setattr(trades_module, "_cached_or_none", _none)
    monkeypatch.setattr(trades_module, "append_audit_event", _none)
    monkeypatch.setattr(trades_module, "publish_outbox", _none)
    monkeypatch.setattr(trades_module, "store_cached", _none)


@pytest.mark.asyncio
async def test_close_rejects_fill_before_entry_without_mutation() -> None:
    entry_time = datetime(2026, 6, 28, 12, tzinfo=UTC)
    trade = _trade(entry_time=entry_time)
    session = _FakeSession([trade, entry_time])

    with pytest.raises(HTTPException) as exc_info:
        await trades_module.close_trade(
            trade.id,
            _payload(fill_time=entry_time - timedelta(minutes=1)),
            session,
            "operator",
            "chronology-1",
        )

    assert exc_info.value.status_code == 422
    assert "earlier than trade entry" in str(exc_info.value.detail)
    assert trade.remaining_qty == Decimal("1")
    assert session.added == []
    assert session.committed is False


@pytest.mark.asyncio
async def test_close_rejects_fill_earlier_than_latest_partial_fill() -> None:
    entry_time = datetime(2026, 6, 28, 12, tzinfo=UTC)
    latest_fill_time = entry_time + timedelta(hours=2)
    trade = _trade(entry_time=entry_time, remaining_qty="0.5")
    trade.status = "PARTIAL"
    session = _FakeSession([trade, latest_fill_time])

    with pytest.raises(HTTPException) as exc_info:
        await trades_module.close_trade(
            trade.id,
            _payload(fill_time=latest_fill_time - timedelta(minutes=1)),
            session,
            "operator",
            "chronology-2",
        )

    assert exc_info.value.status_code == 422
    assert "earlier than latest recorded fill" in str(exc_info.value.detail)
    assert trade.remaining_qty == Decimal("0.5")
    assert session.added == []
    assert session.committed is False


@pytest.mark.asyncio
async def test_close_allows_same_timestamp_as_latest_fill() -> None:
    entry_time = datetime(2026, 6, 28, 12, tzinfo=UTC)
    latest_fill_time = entry_time + timedelta(hours=2)
    trade = _trade(entry_time=entry_time)
    session = _FakeSession([trade, latest_fill_time])

    response = await trades_module.close_trade(
        trade.id,
        _payload(fill_time=latest_fill_time),
        session,
        "operator",
        "chronology-3",
    )

    assert response.status_code == 200
    assert trade.remaining_qty == Decimal("0.5")
    assert session.committed is True

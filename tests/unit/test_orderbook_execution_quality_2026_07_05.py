from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.risk.liquidity import simulate_market_fill
from app.services.market_data import normalize_orderbook_snapshot, sync_orderbooks


def D(value: str) -> Decimal:
    return Decimal(value)


def test_long_market_fill_uses_ask_depth_and_vwap() -> None:
    fill = simulate_market_fill(
        direction="LONG",
        requested_qty=D("2"),
        bids=[["99.9", "5"]],
        asks=[["100", "1"], ["101", "2"]],
        max_impact_bps=D("150"),
    )
    assert fill.status == "FULL"
    assert fill.filled_qty == D("2")
    assert fill.vwap == D("100.5")
    assert fill.worst_price == D("101")
    assert fill.impact_bps == D("50.0")
    assert fill.levels_used == 2


def test_market_fill_reports_partial_inside_impact_limit() -> None:
    fill = simulate_market_fill(
        direction="LONG",
        requested_qty=D("2"),
        bids=[["99.9", "5"]],
        asks=[["100", "1"], ["101", "2"]],
        max_impact_bps=D("50"),
    )
    assert fill.status == "PARTIAL"
    assert fill.filled_qty == D("1")
    assert fill.unfilled_qty == D("1")
    assert fill.vwap == D("100")
    assert fill.available_qty == D("1")


def test_short_market_fill_has_directionally_correct_impact() -> None:
    fill = simulate_market_fill(
        direction="SHORT",
        requested_qty=D("1.5"),
        bids=[["100", "1"], ["99", "1"]],
        asks=[["100.1", "5"]],
        max_impact_bps=D("150"),
    )
    assert fill.status == "FULL"
    assert abs(fill.vwap - D("99.66666666666666666666666667")) < D("1e-24")
    assert abs(fill.impact_bps - D("33.33333333333333333333333300")) < D("1e-24")


def test_orderbook_normalization_uses_matching_engine_time_and_rejects_crossed_book() -> None:
    received_at = datetime(2026, 7, 5, 12, 0, 1, tzinfo=UTC)
    values = normalize_orderbook_snapshot(
        {
            "s": "BTCUSDT",
            "b": [["99.9", "2"]],
            "a": [["100.1", "3"]],
            "ts": 1783252800500,
            "cts": 1783252800400,
            "u": 123,
            "seq": 456,
        },
        expected_symbol="BTCUSDT",
        received_at=received_at,
        requested_depth=50,
    )
    assert values["source_time"] == datetime.fromtimestamp(1783252800.4, tz=UTC)
    assert values["system_time"] == datetime.fromtimestamp(1783252800.5, tz=UTC)
    assert values["received_at"] == received_at
    assert values["best_bid"] == D("99.9")
    assert values["best_ask"] == D("100.1")

    with pytest.raises(ValueError, match="crossed"):
        normalize_orderbook_snapshot(
            {
                "s": "BTCUSDT",
                "b": [["100.2", "2"]],
                "a": [["100.1", "3"]],
                "ts": 1783252800500,
                "u": 124,
                "seq": 457,
            },
            expected_symbol="BTCUSDT",
            received_at=received_at,
            requested_depth=50,
        )


@pytest.mark.asyncio
async def test_sync_orderbooks_persists_point_in_time_snapshot() -> None:
    source_time = datetime.now(UTC) - timedelta(seconds=1)
    payload = {
        "s": "BTCUSDT",
        "b": [["99.9", "2"]],
        "a": [["100.1", "3"]],
        "ts": int(source_time.timestamp() * 1000),
        "cts": int(source_time.timestamp() * 1000),
        "u": 123,
        "seq": 456,
    }

    class Client:
        get_orderbook = AsyncMock(return_value=payload)

    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(rowcount=1)))
    result = await sync_orderbooks(session, Client(), ["BTCUSDT"], depth=50)
    assert result == {"requested": 1, "stored": 1, "duplicates": 0, "failed": 0}
    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "market.orderbook_snapshots" in sql
    assert "ON CONFLICT ON CONSTRAINT uq_orderbook_symbol_source_update" in sql


@pytest.mark.asyncio
async def test_orderbook_snapshot_older_than_policy_is_not_usable() -> None:
    from app.services.execution import orderbook_snapshot_is_fresh

    now = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)
    assert orderbook_snapshot_is_fresh(now - timedelta(seconds=10), now=now, max_age_seconds=15)
    assert not orderbook_snapshot_is_fresh(now - timedelta(seconds=16), now=now, max_age_seconds=15)
    assert not orderbook_snapshot_is_fresh(now + timedelta(seconds=1), now=now, max_age_seconds=15)
    assert not orderbook_snapshot_is_fresh(
        now - timedelta(seconds=1),
        now=now,
        max_age_seconds=15,
        received_at=now + timedelta(seconds=1),
    )

@pytest.mark.asyncio
@pytest.mark.parametrize(("requested", "expected"), [(0, 1), (5000, 1000)])
async def test_bybit_orderbook_request_clamps_supported_depth(
    requested: int,
    expected: int,
) -> None:
    from app.bybit.client import BybitClient, BybitResponse

    client = object.__new__(BybitClient)
    client._get = AsyncMock(  # type: ignore[method-assign]
        return_value=BybitResponse(
            result={"s": "BTCUSDT", "b": [], "a": [], "u": 1, "seq": 1, "ts": 1},
            server_time_ms=None,
            raw={},
        )
    )

    await client.get_orderbook("BTCUSDT", limit=requested)

    client._get.assert_awaited_once_with(  # type: ignore[attr-defined]
        "/v5/market/orderbook",
        {"category": "linear", "symbol": "BTCUSDT", "limit": expected},
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"orderbook_depth_levels": 0}, "ORDERBOOK_DEPTH_LEVELS"),
        ({"orderbook_depth_levels": 1001}, "ORDERBOOK_DEPTH_LEVELS"),
        ({"max_orderbook_age_seconds": 0}, "MAX_ORDERBOOK_AGE_SECONDS"),
        ({"max_vwap_impact_bps": -1.0}, "MAX_VWAP_IMPACT_BPS"),
        ({"orderbook_retention_hours": 0}, "ORDERBOOK_RETENTION_HOURS"),
    ],
)
def test_orderbook_execution_configuration_fails_closed(
    overrides: dict[str, int | float],
    message: str,
) -> None:
    from app.config import Settings

    with pytest.raises(ValueError, match=message):
        Settings(database_url="postgresql+psycopg://u:p@localhost/db", **overrides)


def test_orderbook_update_id_can_repeat_after_exchange_restart() -> None:
    from sqlalchemy import UniqueConstraint

    from app.db.models import OrderBookSnapshot

    constraints = [
        item
        for item in OrderBookSnapshot.__table__.constraints
        if isinstance(item, UniqueConstraint)
    ]
    natural = next(
        item for item in constraints if item.name == "uq_orderbook_symbol_source_update"
    )
    assert tuple(column.name for column in natural.columns) == (
        "symbol",
        "source_time",
        "update_id",
    )


@pytest.mark.asyncio
async def test_sync_orderbooks_reports_idempotent_duplicate_without_claiming_insert() -> None:
    source_time = datetime.now(UTC) - timedelta(seconds=1)
    payload = {
        "s": "BTCUSDT",
        "b": [["99.9", "2"]],
        "a": [["100.1", "3"]],
        "ts": int(source_time.timestamp() * 1000),
        "cts": int(source_time.timestamp() * 1000),
        "u": 1,
        "seq": 1,
    }
    client = SimpleNamespace(get_orderbook=AsyncMock(return_value=payload))
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(rowcount=0)))

    result = await sync_orderbooks(session, client, ["BTCUSDT"], depth=50)

    assert result == {"requested": 1, "stored": 0, "duplicates": 1, "failed": 0}

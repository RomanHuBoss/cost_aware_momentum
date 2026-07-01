from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.services.market_data import _candle_values, _upsert_candle_values
from app.services.signals import _candles_frame, _latest_spec


class _RowsResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _ScalarResult:
    def scalar_one_or_none(self):
        return None


def _compiled(statement) -> tuple[str, dict[str, object]]:
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


@pytest.mark.asyncio
async def test_candle_confirmation_uses_api_response_time(monkeypatch) -> None:
    from app.services import market_data

    open_time = datetime(2026, 7, 1, 3, 0, tzinfo=UTC)
    request_started = open_time + timedelta(minutes=59, seconds=59)
    response_received = open_time + timedelta(hours=1, seconds=1)
    _Clock.current = request_started
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
    count = await market_data.sync_candles(
        session,
        _Client(),
        ["BTCUSDT"],
        interval="60",
        limit=1,
        price_types=("last",),
    )

    assert count == 1
    statement = session.execute.await_args.args[0]
    _, params = _compiled(statement)
    assert params["confirmed_m0"] is True
    assert params["available_at_m0"] == open_time + timedelta(hours=1)


@pytest.mark.asyncio
async def test_confirmed_candle_upsert_is_immutable_without_revision_policy() -> None:
    session = SimpleNamespace(execute=AsyncMock())
    now = datetime(2026, 7, 1, 2, 0, tzinfo=UTC)
    values = _candle_values(
        symbol="BTCUSDT",
        interval="60",
        price_type="last",
        rows=[
            [
                str(int((now - timedelta(hours=2)).timestamp() * 1000)),
                "100",
                "101",
                "99",
                "100.5",
                "10",
                "1000",
            ]
        ],
        now=now,
        interval_minutes=60,
    )

    await _upsert_candle_values(session, values)

    statement = session.execute.await_args.args[0]
    sql, _ = _compiled(statement)
    assert "WHERE market.candles.confirmed IS false" in sql


@pytest.mark.asyncio
async def test_feature_query_separates_market_and_availability_cutoffs() -> None:
    market_cutoff = datetime(2026, 7, 1, 4, 0, tzinfo=UTC)
    availability_cutoff = market_cutoff + timedelta(minutes=3)
    session = SimpleNamespace(execute=AsyncMock(return_value=_RowsResult()))

    await _candles_frame(
        session,
        "BTCUSDT",
        market_cutoff=market_cutoff,
        available_cutoff=availability_cutoff,
        limit=50,
    )

    statement = session.execute.await_args.args[0]
    sql, params = _compiled(statement)
    assert "market.candles.close_time <=" in sql
    assert "market.candles.available_at <=" in sql
    assert market_cutoff in params.values()
    assert availability_cutoff in params.values()


@pytest.mark.asyncio
async def test_spec_query_uses_decision_availability_cutoff() -> None:
    availability_cutoff = datetime(2026, 7, 1, 4, 3, tzinfo=UTC)
    session = SimpleNamespace(execute=AsyncMock(return_value=_ScalarResult()))

    await _latest_spec(
        session,
        "BTCUSDT",
        available_cutoff=availability_cutoff,
    )

    statement = session.execute.await_args.args[0]
    sql, params = _compiled(statement)
    assert "reference.instrument_spec_history.valid_from <=" in sql
    assert "reference.instrument_spec_history.received_at <=" in sql
    assert availability_cutoff in params.values()

class _Clock(datetime):
    current = datetime(2026, 7, 1, 4, 0, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):
        value = cls.current
        if tz is None:
            return value.replace(tzinfo=None)
        return value.astimezone(tz)


@pytest.mark.asyncio
async def test_ticker_received_at_is_stamped_after_api_response(monkeypatch) -> None:
    from app.services import market_data

    request_started = datetime(2026, 7, 1, 4, 0, tzinfo=UTC)
    response_received = request_started + timedelta(seconds=7)
    _Clock.current = request_started
    monkeypatch.setattr(market_data, "datetime", _Clock)

    class _Client:
        async def get_tickers(self, category: str):
            assert category == "linear"
            _Clock.current = response_received
            return [
                {
                    "symbol": "BTCUSDT",
                    "lastPrice": "60000",
                    "bid1Price": "59999",
                    "ask1Price": "60001",
                }
            ]

    session = SimpleNamespace(execute=AsyncMock())
    count = await market_data.sync_tickers(session, _Client(), {"BTCUSDT"})

    assert count == 1
    statement = session.execute.await_args.args[0]
    _, params = _compiled(statement)
    assert response_received in params.values()
    assert request_started not in params.values()


@pytest.mark.asyncio
async def test_account_snapshot_time_is_after_wallet_and_position_reads(monkeypatch) -> None:
    from unittest.mock import Mock

    from app.config import Settings
    from app.db.models import AccountEquitySnapshot
    from app.services import market_data

    request_started = datetime(2026, 7, 1, 4, 0, tzinfo=UTC)
    response_received = request_started + timedelta(seconds=11)
    _Clock.current = request_started
    monkeypatch.setattr(market_data, "datetime", _Clock)

    class _Client:
        async def get_wallet_balance(self, account_type: str):
            assert account_type == "UNIFIED"
            _Clock.current = request_started + timedelta(seconds=5)
            return {
                "list": [
                    {
                        "totalEquity": "1000",
                        "totalAvailableBalance": "800",
                    }
                ]
            }

        async def get_positions(self, settle_coin: str):
            assert settle_coin == "USDT"
            _Clock.current = response_received
            return []

    added: list[object] = []
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult()),
        add=Mock(side_effect=added.append),
    )
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        bybit_read_only_account=True,
    )

    await market_data.sync_read_only_account(session, _Client(), settings)

    snapshot = next(item for item in added if isinstance(item, AccountEquitySnapshot))
    assert snapshot.source_time == response_received
    assert snapshot.received_at == response_received


@pytest.mark.asyncio
async def test_instrument_spec_receipt_time_is_after_api_response(monkeypatch) -> None:
    from unittest.mock import Mock

    from app.db.models import InstrumentSpecHistory
    from app.services import market_data

    request_started = datetime(2026, 7, 1, 4, 0, tzinfo=UTC)
    response_received = request_started + timedelta(seconds=13)
    _Clock.current = request_started
    monkeypatch.setattr(market_data, "datetime", _Clock)

    class _Client:
        async def get_instruments(self, category: str):
            assert category == "linear"
            _Clock.current = response_received
            return [
                {
                    "symbol": "BTCUSDT",
                    "contractType": "LinearPerpetual",
                    "status": "Trading",
                    "settleCoin": "USDT",
                    "baseCoin": "BTC",
                    "quoteCoin": "USDT",
                    "isPreListing": False,
                    "priceFilter": {"tickSize": "0.10"},
                    "lotSizeFilter": {
                        "qtyStep": "0.001",
                        "minOrderQty": "0.001",
                        "maxOrderQty": "100",
                        "minNotionalValue": "5",
                    },
                    "leverageFilter": {"maxLeverage": "100"},
                    "fundingInterval": "480",
                }
            ]

    added: list[object] = []
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult()),
        add=Mock(side_effect=added.append),
    )

    count = await market_data.sync_instruments(session, _Client())

    assert count == 1
    history = next(item for item in added if isinstance(item, InstrumentSpecHistory))
    assert history.valid_from == response_received
    assert history.received_at == response_received
    insert_statement = session.execute.await_args_list[0].args[0]
    _, params = _compiled(insert_statement)
    assert response_received in params.values()
    assert request_started not in params.values()


@pytest.mark.asyncio
async def test_funding_and_oi_availability_is_stamped_after_each_response(monkeypatch) -> None:
    from app.services import market_data

    request_started = datetime(2026, 7, 1, 4, 0, tzinfo=UTC)
    funding_received = request_started + timedelta(seconds=3)
    oi_received = request_started + timedelta(seconds=9)
    funding_time = request_started - timedelta(hours=4)
    oi_time = request_started - timedelta(hours=1)
    _Clock.current = request_started
    monkeypatch.setattr(market_data, "datetime", _Clock)

    class _Client:
        async def get_funding_history(self, symbol: str, *, limit: int):
            assert symbol == "BTCUSDT"
            assert limit == 10
            _Clock.current = funding_received
            return [
                {
                    "fundingRateTimestamp": str(int(funding_time.timestamp() * 1000)),
                    "fundingRate": "0.0001",
                }
            ]

        async def get_open_interest(self, symbol: str, interval: str, *, limit: int):
            assert symbol == "BTCUSDT"
            assert interval == "1h"
            assert limit == 20
            _Clock.current = oi_received
            return [
                {
                    "timestamp": str(int(oi_time.timestamp() * 1000)),
                    "openInterest": "12345",
                }
            ]

    session = SimpleNamespace(execute=AsyncMock())
    counts = await market_data.sync_funding_and_oi(session, _Client(), ["BTCUSDT"])

    assert counts == (1, 1)
    funding_statement = session.execute.await_args_list[0].args[0]
    oi_statement = session.execute.await_args_list[1].args[0]
    _, funding_params = _compiled(funding_statement)
    _, oi_params = _compiled(oi_statement)
    assert funding_received in funding_params.values()
    assert oi_received in oi_params.values()
    assert request_started not in funding_params.values()
    assert request_started not in oi_params.values()

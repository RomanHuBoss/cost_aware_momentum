from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.db.models import InstrumentSpecHistory
from app.services.market_data import sync_instruments


class _Result:
    def __init__(self, value: object = None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


def _instrument(
    *,
    symbol: str,
    contract_type: str,
    funding_interval: str,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "baseCoin": symbol.split("USDT", 1)[0],
        "quoteCoin": "USDT",
        "settleCoin": "USDT",
        "status": "Trading",
        "contractType": contract_type,
        "priceFilter": {"tickSize": "0.1"},
        "lotSizeFilter": {
            "qtyStep": "0.001",
            "minOrderQty": "0.001",
            "maxOrderQty": "100",
            "minNotionalValue": "5",
        },
        "leverageFilter": {"maxLeverage": "100"},
        "fundingInterval": funding_interval,
    }


@pytest.mark.asyncio
async def test_instrument_sync_ignores_linear_futures_before_funding_validation() -> None:
    session = SimpleNamespace(execute=AsyncMock(return_value=_Result()), add=Mock())
    client = SimpleNamespace(
        get_instruments=AsyncMock(
            return_value=[
                _instrument(
                    symbol="BTCUSDT-25SEP26",
                    contract_type="LinearFutures",
                    funding_interval="0",
                ),
                _instrument(
                    symbol="BTCUSDT",
                    contract_type="LinearPerpetual",
                    funding_interval="480",
                ),
            ]
        )
    )

    assert await sync_instruments(session, client) == 1

    persisted = [call.args[0] for call in session.add.call_args_list]
    assert sum(isinstance(value, InstrumentSpecHistory) for value in persisted) == 1

    inserted_symbols: list[str] = []
    for call in session.execute.await_args_list:
        statement = call.args[0]
        try:
            params = statement.compile().params
        except (AttributeError, TypeError):
            continue
        symbol = params.get("symbol")
        if symbol is not None:
            inserted_symbols.append(str(symbol))
    assert inserted_symbols == ["BTCUSDT"]

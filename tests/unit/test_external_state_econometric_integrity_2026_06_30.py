from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import numpy as np
import pandas as pd
import pytest

from app.bybit.client import BybitClient, BybitResponse
from app.config import Settings
from app.db.models import InstrumentSpecHistory
from app.ml.training import (
    MODEL_FEATURE_NAMES,
    OUTCOME_CLASSES,
    DatasetSplit,
    PolicyEvaluationConfig,
    evaluate_policy_model,
)
from app.services.market_data import (
    CandleWindow,
    sync_candle_windows,
    sync_instruments,
    sync_read_only_account,
)

BASE = datetime(2026, 6, 30, 12, tzinfo=UTC)


class _Result:
    def __init__(self, value: object = None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _ProbabilityModel:
    classes_ = OUTCOME_CLASSES

    def __init__(self, probabilities: np.ndarray) -> None:
        self._probabilities = probabilities

    def predict_proba(self, values: np.ndarray) -> np.ndarray:
        assert len(values) == len(self._probabilities)
        return self._probabilities.copy()


def _single_profitable_pair() -> tuple[DatasetSplit, _ProbabilityModel]:
    meta = pd.DataFrame(
        [
            {
                "decision_time": BASE,
                "label_end_time": BASE + timedelta(hours=1),
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "target": "TP",
                "exit_index": 0,
                "exit_at_open": False,
                "realized_gross_return": 0.01,
                "barrier_upside_rate": 0.01,
                "barrier_downside_rate": 0.01,
            },
            {
                "decision_time": BASE,
                "label_end_time": BASE + timedelta(hours=1),
                "symbol": "BTCUSDT",
                "direction": "SHORT",
                "target": "SL",
                "exit_index": 0,
                "exit_at_open": False,
                "realized_gross_return": -0.01,
                "barrier_upside_rate": 0.01,
                "barrier_downside_rate": 0.01,
            },
        ]
    )
    values = np.zeros((2, len(MODEL_FEATURE_NAMES)), dtype=float)
    values[:, -1] = [1.0, -1.0]
    targets = meta["target"].astype(str).to_numpy()
    split = DatasetSplit(values, targets, values, targets, values, targets, meta)
    probabilities = np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    return split, _ProbabilityModel(probabilities)


@pytest.mark.asyncio
async def test_get_instruments_follows_all_bybit_cursor_pages() -> None:
    client = object.__new__(BybitClient)
    client._get = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            BybitResponse(
                result={"list": [{"symbol": "BTCUSDT"}], "nextPageCursor": "page-2"},
                server_time_ms=None,
                raw={},
            ),
            BybitResponse(
                result={"list": [{"symbol": "ETHUSDT"}], "nextPageCursor": ""},
                server_time_ms=None,
                raw={},
            ),
        ]
    )

    instruments = await client.get_instruments("linear")

    assert [item["symbol"] for item in instruments] == ["BTCUSDT", "ETHUSDT"]
    assert client._get.await_args_list[0].args == (  # type: ignore[attr-defined]
        "/v5/market/instruments-info",
        {"category": "linear", "limit": 1000},
    )
    assert client._get.await_args_list[1].args[1]["cursor"] == "page-2"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_get_instruments_rejects_repeated_cursor_instead_of_looping() -> None:
    client = object.__new__(BybitClient)
    response = BybitResponse(
        result={"list": [{"symbol": "BTCUSDT"}], "nextPageCursor": "same"},
        server_time_ms=None,
        raw={},
    )
    client._get = AsyncMock(side_effect=[response, response])  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="instruments pagination repeated a cursor"):
        await client.get_instruments("linear")


@pytest.mark.asyncio
async def test_get_instruments_rejects_non_list_page() -> None:
    client = object.__new__(BybitClient)
    client._get = AsyncMock(  # type: ignore[method-assign]
        return_value=BybitResponse(
            result={"list": {"symbol": "BTCUSDT"}, "nextPageCursor": ""},
            server_time_ms=None,
            raw={},
        )
    )

    with pytest.raises(RuntimeError, match="instruments response list is invalid"):
        await client.get_instruments("linear")


@pytest.mark.asyncio
async def test_get_positions_follows_all_bybit_cursor_pages() -> None:
    client = object.__new__(BybitClient)
    client._get = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            BybitResponse(
                result={"list": [{"symbol": "BTCUSDT"}], "nextPageCursor": "page-2"},
                server_time_ms=None,
                raw={},
            ),
            BybitResponse(
                result={"list": [{"symbol": "ETHUSDT"}], "nextPageCursor": ""},
                server_time_ms=None,
                raw={},
            ),
        ]
    )

    positions = await client.get_positions("USDT")

    assert [item["symbol"] for item in positions] == ["BTCUSDT", "ETHUSDT"]
    assert client._get.await_args_list[0].args == (  # type: ignore[attr-defined]
        "/v5/position/list",
        {"category": "linear", "settleCoin": "USDT", "limit": 200},
    )
    assert client._get.await_args_list[0].kwargs == {"private": True}  # type: ignore[attr-defined]
    assert client._get.await_args_list[1].args[1]["cursor"] == "page-2"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_get_positions_rejects_repeated_cursor_instead_of_looping() -> None:
    client = object.__new__(BybitClient)
    response = BybitResponse(
        result={"list": [{"symbol": "BTCUSDT"}], "nextPageCursor": "same"},
        server_time_ms=None,
        raw={},
    )
    client._get = AsyncMock(side_effect=[response, response])  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="cursor"):
        await client.get_positions("USDT")


@pytest.mark.asyncio
async def test_instrument_sync_rejects_missing_tick_size_without_fabricating_spec() -> None:
    session = SimpleNamespace(execute=AsyncMock(return_value=_Result()), add=Mock())
    client = SimpleNamespace(
        get_instruments=AsyncMock(
            return_value=[
                {
                    "symbol": "BTCUSDT",
                    "baseCoin": "BTC",
                    "quoteCoin": "USDT",
                    "settleCoin": "USDT",
                    "status": "Trading",
                    "contractType": "LinearPerpetual",
                    "priceFilter": {},
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
        )
    )

    with pytest.raises(ValueError, match="tickSize"):
        await sync_instruments(session, client)


@pytest.mark.asyncio
async def test_instrument_sync_persists_only_complete_exchange_spec() -> None:
    session = SimpleNamespace(execute=AsyncMock(return_value=_Result()), add=Mock())
    item = {
        "symbol": "BTCUSDT",
        "baseCoin": "BTC",
        "quoteCoin": "USDT",
        "settleCoin": "USDT",
        "status": "Trading",
        "contractType": "LinearPerpetual",
        "priceFilter": {"tickSize": "0.1"},
        "lotSizeFilter": {
            "qtyStep": "0.001",
            "minOrderQty": "0.001",
            "maxOrderQty": "100",
            "minNotionalValue": "5",
        },
        "leverageFilter": {"maxLeverage": "100"},
        "fundingInterval": "480",
    }
    client = SimpleNamespace(get_instruments=AsyncMock(return_value=[item]))

    assert await sync_instruments(session, client) == 1

    spec = next(
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], InstrumentSpecHistory)
    )
    assert str(spec.tick_size) == "0.1"
    assert str(spec.qty_step) == "0.001"
    assert str(spec.min_notional) == "5"
    assert spec.funding_interval_minutes == 480


@pytest.mark.asyncio
async def test_account_sync_rejects_malformed_open_position_before_any_write() -> None:
    session = SimpleNamespace(execute=AsyncMock(return_value=_Result()), add=Mock())
    client = SimpleNamespace(
        get_wallet_balance=AsyncMock(
            return_value={
                "list": [{"totalEquity": "1000", "totalAvailableBalance": "750"}]
            }
        ),
        get_positions=AsyncMock(
            return_value=[
                {
                    "symbol": "BTCUSDT",
                    "side": "Buy",
                    "size": "0.1",
                    "avgPrice": "60000",
                    "markPrice": "",
                    "unrealisedPnl": "10",
                }
            ]
        ),
    )
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        bybit_read_only_account=True,
    )

    with pytest.raises(ValueError, match="position.markPrice"):
        await sync_read_only_account(session, client, settings)

    session.add.assert_not_called()
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_account_sync_rejects_missing_equity_before_persisting_snapshot() -> None:
    session = SimpleNamespace(execute=AsyncMock(return_value=_Result()), add=Mock())
    client = SimpleNamespace(
        get_wallet_balance=AsyncMock(
            return_value={"list": [{"totalAvailableBalance": "100"}]}
        ),
        get_positions=AsyncMock(return_value=[]),
    )
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        bybit_read_only_account=True,
    )

    with pytest.raises(ValueError, match="totalEquity"):
        await sync_read_only_account(session, client, settings)

    session.add.assert_not_called()
    client.get_positions.assert_not_awaited()


@pytest.mark.asyncio
async def test_partial_candle_window_is_reported_and_not_persisted(monkeypatch) -> None:
    class _Client:
        async def get_kline(self, *args, **kwargs):
            return [
                [
                    str(int(BASE.timestamp() * 1000)),
                    "100",
                    "101",
                    "99",
                    "100.5",
                    "10",
                    "1000",
                ]
            ]

    upsert = AsyncMock()
    monkeypatch.setattr("app.services.market_data._upsert_candle_values", upsert)

    result = await sync_candle_windows(
        SimpleNamespace(),
        _Client(),
        [CandleWindow("BTCUSDT", BASE, BASE + timedelta(hours=1))],
        interval="5",
        now=BASE + timedelta(hours=2),
    )

    assert result["windows_succeeded"] == 0
    assert result["rows_received"] == 0
    assert result["errors"][0]["error"] == "partial_window: expected 12 candles, received 1"
    upsert.assert_not_awaited()


def test_profit_factor_is_undefined_when_holdout_has_no_losses() -> None:
    split, model = _single_profitable_pair()
    config = PolicyEvaluationConfig(
        fee_rate_round_trip=0.0,
        slippage_rate=0.0,
        stop_gap_reserve_rate=0.0,
        min_net_rr=0.0,
        min_net_ev_r=-100.0,
        timeout_return_rate=0.0,
    )

    metrics = evaluate_policy_model(model, split, config)

    assert metrics["policy_trades"] == 1
    assert metrics["policy_realized_total_r"] > 0
    assert metrics["policy_profit_factor"] is None

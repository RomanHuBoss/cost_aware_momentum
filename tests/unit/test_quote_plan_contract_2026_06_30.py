from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.ml.runtime import Prediction
from app.risk.math import CostScenario
from app.services.execution import executable_entry_price
from app.services.market_data import sync_tickers
from app.services.signals import select_cost_aware_scenario
from app.services.universe import select_dynamic_universe

D = Decimal


def _predictions() -> tuple[Prediction, Prediction]:
    return (
        Prediction("LONG", 0.7, 0.2, 0.1, 1.0, "model-v1", "cal-v1", ()),
        Prediction("SHORT", 0.2, 0.7, 0.1, -1.0, "model-v1", "cal-v1", ()),
    )


def _costs() -> CostScenario:
    return CostScenario(D("0.001"), D("0.0002"), D("0.001"), D("0"))


def test_signal_policy_rejects_crossed_quote() -> None:
    with pytest.raises(ValueError, match="bid/ask"):
        select_cost_aware_scenario(
            _predictions(),
            bid_price=D("101"),
            ask_price=D("100"),
            decision_anchor_price=D("100.5"),
            atr_pct=D("0.02"),
            costs=_costs(),
        )


def test_acceptance_rejects_crossed_quote() -> None:
    with pytest.raises(ValueError, match="bid/ask"):
        executable_entry_price(
            direction="LONG",
            bid_price=D("101"),
            ask_price=D("100"),
        )


def test_signal_policy_rejects_locked_quote() -> None:
    with pytest.raises(ValueError, match="locked"):
        select_cost_aware_scenario(
            _predictions(),
            bid_price=D("100"),
            ask_price=D("100"),
            decision_anchor_price=D("100"),
            atr_pct=D("0.02"),
            costs=_costs(),
        )


def test_acceptance_rejects_locked_quote() -> None:
    with pytest.raises(ValueError, match="locked"):
        executable_entry_price(
            direction="LONG",
            bid_price=D("100"),
            ask_price=D("100"),
        )


def test_published_scenario_does_not_advertise_unmodeled_second_target() -> None:
    selected = select_cost_aware_scenario(
        _predictions(),
        bid_price=D("99.9"),
        ask_price=D("100.1"),
        decision_anchor_price=D("100"),
        atr_pct=D("0.02"),
        costs=_costs(),
    )

    assert selected.take_profit_2 is None


def test_dynamic_universe_rejects_locked_quote() -> None:
    now = __import__("datetime").datetime.now(__import__("datetime").UTC)
    instrument = SimpleNamespace(
        symbol="LOCKEDUSDT",
        category="linear",
        base_coin="LOCKED",
        quote_coin="USDT",
        settle_coin="USDT",
        status="Trading",
        launch_time=now - __import__("datetime").timedelta(days=100),
        delivery_time=None,
        is_pre_listing=False,
        raw={"contractType": "LinearPerpetual", "symbolType": ""},
    )
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        universe_mode="dynamic",
        universe_min_turnover_24h=0,
        universe_max_spread_bps=30,
    )

    selected = select_dynamic_universe(
        [instrument],
        [
            {
                "symbol": "LOCKEDUSDT",
                "lastPrice": "100",
                "bid1Price": "100",
                "ask1Price": "100",
                "turnover24h": "1000000",
            }
        ],
        settings,
        now=now,
    )

    assert selected.symbols == ()
    assert selected.excluded_counts == {"invalid_bid_ask": 1}


def test_dynamic_universe_isolates_non_finite_ticker_values() -> None:
    now = __import__("datetime").datetime.now(__import__("datetime").UTC)
    instrument = SimpleNamespace(
        symbol="BADUSDT",
        category="linear",
        base_coin="BAD",
        quote_coin="USDT",
        settle_coin="USDT",
        status="Trading",
        launch_time=now - __import__("datetime").timedelta(days=100),
        delivery_time=None,
        is_pre_listing=False,
        raw={"contractType": "LinearPerpetual", "symbolType": ""},
    )
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        universe_mode="dynamic",
        universe_min_turnover_24h=0,
        universe_max_spread_bps=0,
    )

    selected = select_dynamic_universe(
        [instrument],
        [
            {
                "symbol": "BADUSDT",
                "lastPrice": "100",
                "bid1Price": "NaN",
                "ask1Price": "101",
                "turnover24h": "Infinity",
            }
        ],
        settings,
        now=now,
    )

    assert selected.symbols == ()
    assert selected.excluded_counts == {"invalid_bid_ask": 1}


@pytest.mark.asyncio
async def test_ticker_sync_skips_non_finite_primary_price_without_aborting_batch() -> None:
    session = SimpleNamespace(execute=AsyncMock())
    count = await sync_tickers(
        session,
        SimpleNamespace(),
        None,
        items=[
            {"symbol": "BADUSDT", "lastPrice": "NaN"},
            {
                "symbol": "BTCUSDT",
                "lastPrice": "100",
                "bid1Price": "99.9",
                "ask1Price": "100.1",
                "turnover24h": "1000000",
            },
        ],
    )

    assert count == 1
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_ticker_sync_drops_locked_bid_ask() -> None:
    session = SimpleNamespace(execute=AsyncMock())
    count = await sync_tickers(
        session,
        SimpleNamespace(),
        None,
        items=[
            {
                "symbol": "BTCUSDT",
                "lastPrice": "100",
                "bid1Price": "100",
                "ask1Price": "100",
                "turnover24h": "1000000",
            }
        ],
    )

    assert count == 1
    statement = session.execute.await_args.args[0]
    params = statement.compile().params
    assert params["bid_price_m0"] is None
    assert params["ask_price_m0"] is None


def test_entry_state_uses_executable_side_not_last_price() -> None:
    from datetime import UTC, datetime, timedelta

    from app.api.serializers import entry_state

    signal = SimpleNamespace(
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        direction="LONG",
        entry_low=D("100"),
        entry_high=D("101"),
    )
    ticker = SimpleNamespace(
        last_price=D("100.5"),
        bid_price=D("100.5"),
        ask_price=D("102"),
    )

    assert entry_state(signal, ticker) == "MISSED_ENTRY"

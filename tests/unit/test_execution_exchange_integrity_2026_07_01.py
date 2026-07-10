from __future__ import annotations

import hashlib
import hmac
from decimal import Decimal

import httpx
import pytest

from app.bybit.client import BybitClient
from app.config import Settings
from app.ml.runtime import Prediction
from app.risk.math import CostScenario
from app.services.signals import select_cost_aware_scenario
from app.services.universe import select_dynamic_universe
from tests.unit.test_universe import instrument, ticker

D = Decimal


def _directional_predictions() -> tuple[Prediction, Prediction]:
    return (
        Prediction("LONG", 0.80, 0.10, 0.10, 1.0, "model", "cal", ()),
        Prediction("SHORT", 0.10, 0.80, 0.10, -1.0, "model", "cal", ()),
    )


def test_entry_zone_rounding_never_expands_beyond_continuous_policy_band() -> None:
    selected = select_cost_aware_scenario(
        _directional_predictions(),
        bid_price=D("99.5"),
        ask_price=D("100"),
        decision_anchor_price=D("100"),
        atr_pct=D("0.02"),
        entry_zone_atr_fraction=D("0.33"),
        costs=CostScenario(D("0"), D("0"), D("0"), D("0")),
        tick_size=D("0.5"),
    )

    # Continuous policy band is [99.34, 100.66].  Conservative tick rounding
    # contracts it to [99.5, 100.5] and never expands the accepted entry set.
    assert selected.entry_low == D("99.5")
    assert selected.entry_high == D("100.5")


@pytest.mark.asyncio
async def test_private_get_signature_matches_exact_transmitted_query(monkeypatch) -> None:
    api_key = "test-key"
    api_secret = "test-secret"
    recv_window = 5000

    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.query.decode("ascii")
        timestamp = request.headers["X-BAPI-TIMESTAMP"]
        plain = f"{timestamp}{api_key}{recv_window}{query}"
        expected = hmac.new(
            api_secret.encode(), plain.encode(), hashlib.sha256
        ).hexdigest()
        assert request.headers["X-BAPI-SIGN"] == expected
        return httpx.Response(
            200,
            json={"retCode": 0, "retMsg": "OK", "result": {}, "time": 0},
        )

    client = BybitClient(
        base_url="https://example.test",
        api_key=api_key,
        api_secret=api_secret,
        recv_window=recv_window,
    )
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr("app.bybit.client.time.time", lambda: 1_700_000_000.0)

    try:
        await client._get(
            "/v5/position/list",
            {"category": "linear", "settleCoin": "USDT", "limit": 200},
            private=True,
        )
    finally:
        await client.close()


def test_dynamic_universe_excludes_all_known_tradfi_symbol_types_by_default() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        universe_mode="dynamic",
        universe_min_turnover_24h=0,
        universe_max_spread_bps=0,
    )
    instruments = [
        instrument("BTCUSDT", symbol_type="innovation"),
        instrument("GOLDUSDT", symbol_type="commodity"),
        instrument("FOREXUSDT", symbol_type="forex"),
        instrument("AAPLUSDT", symbol_type="stock"),
        instrument("OLDSTOCKUSDT", symbol_type="xstocks"),
    ]
    tickers = [ticker(item.symbol, turnover="10000000") for item in instruments]

    selected = select_dynamic_universe(instruments, tickers, settings)

    assert selected.symbols == ("BTCUSDT",)
    assert selected.excluded_counts["non_crypto_symbol_type"] == 4


def test_dynamic_universe_allows_explicit_tradfi_opt_in() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        universe_mode="dynamic",
        universe_min_turnover_24h=0,
        universe_max_spread_bps=0,
        universe_allow_non_crypto_symbol_types=True,
    )
    instruments = [
        instrument("GOLDUSDT", symbol_type="commodity"),
        instrument("FOREXUSDT", symbol_type="forex"),
        instrument("AAPLUSDT", symbol_type="stock"),
    ]
    tickers = [ticker(item.symbol, turnover="10000000") for item in instruments]

    selected = select_dynamic_universe(instruments, tickers, settings)

    assert set(selected.symbols) == {"GOLDUSDT", "FOREXUSDT", "AAPLUSDT"}
    assert "non_crypto_symbol_type" not in selected.excluded_counts

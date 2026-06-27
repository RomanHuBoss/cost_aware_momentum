from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.config import Settings
from app.services.universe import select_dynamic_universe


def instrument(
    symbol: str,
    *,
    base_coin: str | None = None,
    status: str = "Trading",
    pre_listing: bool = False,
    contract_type: str = "LinearPerpetual",
    symbol_type: str = "",
    age_days: int = 100,
):
    return SimpleNamespace(
        symbol=symbol,
        category="linear",
        base_coin=base_coin or symbol.removesuffix("USDT"),
        quote_coin="USDT",
        settle_coin="USDT",
        status=status,
        launch_time=datetime.now(UTC) - timedelta(days=age_days),
        delivery_time=None,
        is_pre_listing=pre_listing,
        raw={"contractType": contract_type, "symbolType": symbol_type},
    )


def ticker(symbol: str, *, turnover: str, bid: str = "99", ask: str = "100") -> dict:
    return {
        "symbol": symbol,
        "lastPrice": "99.5",
        "bid1Price": bid,
        "ask1Price": ask,
        "turnover24h": turnover,
    }


def test_dynamic_universe_scans_all_and_applies_filters() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        universe_mode="dynamic",
        universe_min_age_days=7,
        universe_min_turnover_24h=1_000_000,
        universe_max_spread_bps=150,
        universe_max_symbols=0,
    )
    instruments = [
        instrument("BTCUSDT"),
        instrument("ETHUSDT"),
        instrument("NEWUSDT", age_days=2),
        instrument("AAPLUSDT", symbol_type="xstocks"),
        instrument("USDCUSDT", base_coin="USDC"),
        instrument("PREUSDT", pre_listing=True),
        instrument("FUTUSDT", contract_type="LinearFutures"),
    ]
    tickers = [
        ticker("BTCUSDT", turnover="100000000"),
        ticker("ETHUSDT", turnover="50000000"),
        ticker("NEWUSDT", turnover="30000000"),
        ticker("AAPLUSDT", turnover="30000000"),
        ticker("USDCUSDT", turnover="30000000"),
        ticker("PREUSDT", turnover="30000000"),
        ticker("FUTUSDT", turnover="30000000"),
    ]

    selected = select_dynamic_universe(instruments, tickers, settings)

    assert selected.symbols == ("BTCUSDT", "ETHUSDT")
    assert selected.total_instruments == 7
    assert selected.excluded_counts["insufficient_age"] == 1
    assert selected.excluded_counts["non_crypto_symbol_type"] == 1
    assert selected.excluded_counts["excluded_base_coin"] == 1
    assert selected.excluded_counts["pre_listing"] == 1
    assert selected.excluded_counts["not_perpetual"] == 1


def test_dynamic_universe_ranks_by_turnover_and_honours_limit() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        universe_mode="dynamic",
        universe_min_turnover_24h=0,
        universe_max_spread_bps=0,
        universe_max_symbols=2,
    )
    instruments = [instrument("AAAUSDT"), instrument("BBBUSDT"), instrument("CCCUSDT")]
    tickers = [
        ticker("AAAUSDT", turnover="10"),
        ticker("BBBUSDT", turnover="30"),
        ticker("CCCUSDT", turnover="20"),
    ]

    selected = select_dynamic_universe(instruments, tickers, settings)

    assert selected.eligible_before_limit == 3
    assert selected.symbols == ("BBBUSDT", "CCCUSDT")


def test_dynamic_universe_does_not_treat_region_symbol_type_as_non_crypto() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        universe_mode="dynamic",
        universe_min_turnover_24h=0,
        universe_max_spread_bps=0,
    )
    instruments = [
        instrument("REGIONUSDT", symbol_type="innovation"),
        instrument("XSTOCKUSDT", symbol_type="xstocks"),
    ]
    tickers = [
        ticker("REGIONUSDT", turnover="10000000"),
        ticker("XSTOCKUSDT", turnover="10000000"),
    ]

    selected = select_dynamic_universe(instruments, tickers, settings)

    assert selected.symbols == ("REGIONUSDT",)
    assert selected.excluded_counts["non_crypto_symbol_type"] == 1

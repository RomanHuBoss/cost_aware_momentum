from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Instrument


@dataclass(frozen=True)
class UniverseSelection:
    mode: str
    symbols: tuple[str, ...]
    total_instruments: int
    ticker_count: int
    eligible_before_limit: int
    excluded_counts: dict[str, int]

    def summary(self) -> dict:
        return {
            "mode": self.mode,
            "total_instruments": self.total_instruments,
            "ticker_count": self.ticker_count,
            "eligible_before_limit": self.eligible_before_limit,
            "selected_count": len(self.symbols),
            "selected_symbols": list(self.symbols),
            "selected_sample": list(self.symbols[:25]),
            "excluded_counts": dict(sorted(self.excluded_counts.items())),
        }


def _decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _spread_bps(ticker: dict) -> Decimal | None:
    bid = _decimal(ticker.get("bid1Price"))
    ask = _decimal(ticker.get("ask1Price"))
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return None
    mid = (bid + ask) / Decimal("2")
    if mid <= 0:
        return None
    return (ask - bid) / mid * Decimal("10000")


def select_dynamic_universe(
    instruments: Iterable[Instrument],
    ticker_items: Iterable[dict],
    settings: Settings,
    *,
    now: datetime | None = None,
) -> UniverseSelection:
    now = now or datetime.now(UTC)
    instrument_list = list(instruments)
    ticker_map = {
        str(item.get("symbol") or "").upper(): item
        for item in ticker_items
        if item.get("symbol")
    }
    excluded = Counter()
    candidates: list[tuple[str, Decimal]] = []
    excluded_symbols = set(settings.universe_excluded_symbols)
    excluded_bases = set(settings.universe_excluded_base_coins)
    minimum_launch_time = now - timedelta(days=max(0, settings.universe_min_age_days))

    for instrument in instrument_list:
        symbol = instrument.symbol.upper()
        raw = instrument.raw or {}

        if instrument.category != "linear":
            excluded["not_linear"] += 1
            continue
        if instrument.settle_coin != "USDT" or instrument.quote_coin != "USDT":
            excluded["not_usdt_settled"] += 1
            continue
        if instrument.status != "Trading":
            excluded["not_trading"] += 1
            continue
        if instrument.is_pre_listing:
            excluded["pre_listing"] += 1
            continue
        if raw.get("contractType") != "LinearPerpetual":
            excluded["not_perpetual"] += 1
            continue
        if symbol in excluded_symbols:
            excluded["excluded_symbol"] += 1
            continue
        if instrument.base_coin.upper() in excluded_bases:
            excluded["excluded_base_coin"] += 1
            continue
        # Bybit documents ``symbolType`` as the region/segment to which the pair belongs,
        # not as a crypto-vs-TradFi classifier.  Treating every non-empty value as
        # non-crypto can collapse the dynamic universe to only a handful of symbols.
        # Only explicitly identified xStocks are excluded by this guard.
        symbol_type = str(raw.get("symbolType") or "").strip().lower()
        if (
            symbol_type in {"xstocks", "xstock"}
            and not settings.universe_allow_non_crypto_symbol_types
        ):
            excluded["non_crypto_symbol_type"] += 1
            continue
        if instrument.launch_time and instrument.launch_time > minimum_launch_time:
            excluded["insufficient_age"] += 1
            continue

        ticker = ticker_map.get(symbol)
        if ticker is None:
            excluded["missing_ticker"] += 1
            continue
        last_price = _decimal(ticker.get("lastPrice"))
        turnover = _decimal(ticker.get("turnover24h"))
        spread = _spread_bps(ticker)
        if last_price is None or last_price <= 0:
            excluded["invalid_last_price"] += 1
            continue
        if spread is None:
            excluded["invalid_bid_ask"] += 1
            continue
        if settings.universe_min_turnover_24h > 0 and (
            turnover is None or turnover < Decimal(str(settings.universe_min_turnover_24h))
        ):
            excluded["low_turnover"] += 1
            continue
        if settings.universe_max_spread_bps > 0 and spread > Decimal(
            str(settings.universe_max_spread_bps)
        ):
            excluded["wide_spread"] += 1
            continue
        candidates.append((symbol, turnover or Decimal("0")))

    candidates.sort(key=lambda item: (-item[1], item[0]))
    eligible_before_limit = len(candidates)
    if settings.universe_max_symbols > 0:
        candidates = candidates[: settings.universe_max_symbols]
    symbols = tuple(symbol for symbol, _turnover in candidates)
    return UniverseSelection(
        mode="dynamic",
        symbols=symbols,
        total_instruments=len(instrument_list),
        ticker_count=len(ticker_map),
        eligible_before_limit=eligible_before_limit,
        excluded_counts=dict(excluded),
    )


async def resolve_universe(
    session: AsyncSession,
    ticker_items: Iterable[dict],
    settings: Settings,
    *,
    now: datetime | None = None,
) -> UniverseSelection:
    if settings.universe_mode == "static":
        symbols = tuple(dict.fromkeys(symbol.upper() for symbol in settings.symbols))
        return UniverseSelection(
            mode="static",
            symbols=symbols,
            total_instruments=len(symbols),
            ticker_count=len(list(ticker_items)),
            eligible_before_limit=len(symbols),
            excluded_counts={},
        )

    instruments = (await session.execute(select(Instrument))).scalars().all()
    return select_dynamic_universe(instruments, ticker_items, settings, now=now)

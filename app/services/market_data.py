from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import desc, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.bybit.client import BybitClient
from app.config import Settings
from app.db.models import (
    AccountEquitySnapshot,
    Candle,
    CapitalProfile,
    FundingRate,
    Instrument,
    InstrumentSpecHistory,
    OpenInterest,
    PositionSnapshot,
    TickerSnapshot,
)
from app.services.audit import append_audit_event, publish_outbox

logger = logging.getLogger(__name__)


def _dt_ms(value: str | int | None) -> datetime | None:
    if value in (None, "", "0", 0):
        return None
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def _decimal(value: object, default: str = "0") -> Decimal:
    if value in (None, ""):
        return Decimal(default)
    return Decimal(str(value))


async def sync_instruments(session: AsyncSession, client: BybitClient) -> int:
    now = datetime.now(UTC)
    items = await client.get_instruments("linear")
    count = 0
    for item in items:
        if item.get("settleCoin") != "USDT":
            continue
        symbol = item["symbol"]
        instrument_values = {
            "symbol": symbol,
            "category": "linear",
            "base_coin": item.get("baseCoin") or symbol.removesuffix("USDT"),
            "quote_coin": item.get("quoteCoin") or "USDT",
            "settle_coin": item.get("settleCoin") or "USDT",
            "status": item.get("status") or "Unknown",
            "launch_time": _dt_ms(item.get("launchTime")),
            "delivery_time": _dt_ms(item.get("deliveryTime")),
            "is_pre_listing": bool(item.get("isPreListing", False)),
            "raw": item,
            "updated_at": now,
        }
        stmt = insert(Instrument).values(**instrument_values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Instrument.symbol],
            set_={key: value for key, value in instrument_values.items() if key != "symbol"},
        )
        await session.execute(stmt)

        price_filter = item.get("priceFilter") or {}
        lot_filter = item.get("lotSizeFilter") or {}
        leverage_filter = item.get("leverageFilter") or {}
        funding_interval = item.get("fundingInterval")
        latest_spec = (
            await session.execute(
                select(InstrumentSpecHistory)
                .where(InstrumentSpecHistory.symbol == symbol)
                .order_by(desc(InstrumentSpecHistory.valid_from))
                .limit(1)
            )
        ).scalar_one_or_none()
        fingerprint = (
            _decimal(price_filter.get("tickSize"), "0.00000001"),
            _decimal(lot_filter.get("qtyStep"), "0.00000001"),
            _decimal(lot_filter.get("minOrderQty"), "0"),
            _decimal(lot_filter.get("maxOrderQty"), "0") or None,
            _decimal(lot_filter.get("minNotionalValue"), "5"),
            _decimal(leverage_filter.get("maxLeverage"), "1"),
            int(funding_interval) if funding_interval not in (None, "") else None,
        )
        previous = None
        if latest_spec:
            previous = (
                latest_spec.tick_size,
                latest_spec.qty_step,
                latest_spec.min_qty,
                latest_spec.max_qty,
                latest_spec.min_notional,
                latest_spec.max_leverage,
                latest_spec.funding_interval_minutes,
            )
        if previous != fingerprint:
            session.add(
                InstrumentSpecHistory(
                    symbol=symbol,
                    valid_from=now,
                    received_at=now,
                    tick_size=fingerprint[0],
                    qty_step=fingerprint[1],
                    min_qty=fingerprint[2],
                    max_qty=fingerprint[3],
                    min_notional=fingerprint[4],
                    max_leverage=fingerprint[5],
                    funding_interval_minutes=fingerprint[6],
                    raw=item,
                )
            )
        count += 1
    await append_audit_event(
        session,
        event_type="INSTRUMENT_SYNC_COMPLETED",
        entity_type="market_data",
        entity_id="linear-usdt",
        actor="worker",
        payload={"count": count},
    )
    return count


async def sync_candles(
    session: AsyncSession,
    client: BybitClient,
    symbols: Iterable[str],
    *,
    interval: str,
    limit: int,
    price_types: tuple[str, ...] = ("last", "mark", "index"),
    request_batch_size: int = 40,
) -> int:
    now = datetime.now(UTC)
    count = 0
    interval_minutes = int(interval)
    requests = [(symbol, price_type) for symbol in symbols for price_type in price_types]
    batch_size = max(1, request_batch_size)

    async def fetch(symbol: str, price_type: str) -> tuple[str, str, list[list[str]] | None]:
        try:
            rows = await client.get_kline(
                symbol, interval=interval, limit=limit, price_type=price_type
            )
            return symbol, price_type, rows
        except Exception:
            logger.exception(
                "Failed to fetch candles",
                extra={
                    "symbol": symbol,
                    "price_type": price_type,
                    "event": "candle_fetch_failed",
                },
            )
            return symbol, price_type, None

    for offset in range(0, len(requests), batch_size):
        batch = requests[offset : offset + batch_size]
        results = await asyncio.gather(*(fetch(symbol, price_type) for symbol, price_type in batch))
        for symbol, price_type, rows in results:
            if not rows:
                continue
            values_list: list[dict] = []
            for row in rows:
                # [startTime, open, high, low, close, volume, turnover]
                open_time = _dt_ms(row[0])
                if open_time is None:
                    continue
                close_time = open_time + timedelta(minutes=interval_minutes)
                values_list.append(
                    {
                        "symbol": symbol,
                        "interval": interval,
                        "open_time": open_time,
                        "close_time": close_time,
                        "available_at": close_time,
                        "price_type": price_type,
                        "open": _decimal(row[1]),
                        "high": _decimal(row[2]),
                        "low": _decimal(row[3]),
                        "close": _decimal(row[4]),
                        "volume": _decimal(row[5] if len(row) > 5 else 0),
                        "turnover": _decimal(row[6] if len(row) > 6 else 0),
                        "confirmed": close_time <= now,
                        "source": "bybit_v5",
                    }
                )
            if not values_list:
                continue
            stmt = insert(Candle).values(values_list)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_candle_natural",
                set_={
                    "close_time": stmt.excluded.close_time,
                    "available_at": stmt.excluded.available_at,
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                    "turnover": stmt.excluded.turnover,
                    "confirmed": stmt.excluded.confirmed,
                },
            )
            await session.execute(stmt)
            count += len(values_list)
    return count


async def sync_tickers(
    session: AsyncSession,
    client: BybitClient,
    symbols: set[str] | None,
    *,
    items: list[dict] | None = None,
) -> int:
    now = datetime.now(UTC)
    items = items if items is not None else await client.get_tickers("linear")
    values_list: list[dict] = []
    for item in items:
        symbol = item.get("symbol")
        if not symbol or (symbols is not None and symbol not in symbols):
            continue
        last_price = _decimal(item.get("lastPrice"))
        if last_price <= 0:
            continue
        values_list.append(
            {
                "symbol": symbol,
                "source_time": now,
                "received_at": now,
                "last_price": last_price,
                "mark_price": _decimal(item.get("markPrice"))
                if item.get("markPrice") not in (None, "")
                else None,
                "index_price": _decimal(item.get("indexPrice"))
                if item.get("indexPrice") not in (None, "")
                else None,
                "bid_price": _decimal(item.get("bid1Price"))
                if item.get("bid1Price") not in (None, "")
                else None,
                "ask_price": _decimal(item.get("ask1Price"))
                if item.get("ask1Price") not in (None, "")
                else None,
                "turnover_24h": _decimal(item.get("turnover24h"))
                if item.get("turnover24h") not in (None, "")
                else None,
                "volume_24h": _decimal(item.get("volume24h"))
                if item.get("volume24h") not in (None, "")
                else None,
                "open_interest": _decimal(item.get("openInterest"))
                if item.get("openInterest") not in (None, "")
                else None,
                "funding_rate": _decimal(item.get("fundingRate"))
                if item.get("fundingRate") not in (None, "")
                else None,
                "next_funding_time": _dt_ms(item.get("nextFundingTime")),
                "raw": item,
            }
        )
    if values_list:
        await session.execute(insert(TickerSnapshot).values(values_list))
    return len(values_list)


async def sync_funding_and_oi(
    session: AsyncSession, client: BybitClient, symbols: Iterable[str]
) -> tuple[int, int]:
    now = datetime.now(UTC)
    funding_count = 0
    oi_count = 0
    for symbol in symbols:
        try:
            funding_items = await client.get_funding_history(symbol, limit=10)
            for item in funding_items:
                funding_time = _dt_ms(item.get("fundingRateTimestamp"))
                if funding_time is None:
                    continue
                stmt = (
                    insert(FundingRate)
                    .values(
                        symbol=symbol,
                        funding_time=funding_time,
                        available_at=now,
                        rate=_decimal(item.get("fundingRate")),
                    )
                    .on_conflict_do_nothing(constraint="uq_funding_symbol_time")
                )
                await session.execute(stmt)
                funding_count += 1
        except Exception:
            logger.exception("Funding fetch failed", extra={"symbol": symbol})
        try:
            oi_items = await client.get_open_interest(symbol, "1h", limit=20)
            for item in oi_items:
                event_time = _dt_ms(item.get("timestamp"))
                if event_time is None:
                    continue
                stmt = (
                    insert(OpenInterest)
                    .values(
                        symbol=symbol,
                        interval="1h",
                        event_time=event_time,
                        available_at=now,
                        value=_decimal(item.get("openInterest")),
                    )
                    .on_conflict_do_nothing(constraint="uq_oi_natural")
                )
                await session.execute(stmt)
                oi_count += 1
        except Exception:
            logger.exception("OI fetch failed", extra={"symbol": symbol})
    return funding_count, oi_count


async def sync_read_only_account(session: AsyncSession, client: BybitClient, settings: Settings) -> dict:
    if not settings.bybit_read_only_account:
        return {"enabled": False}
    now = datetime.now(UTC)
    wallet = await client.get_wallet_balance("UNIFIED")
    account_list = wallet.get("list") or []
    if not account_list:
        raise RuntimeError("Bybit wallet response contained no account")
    account = account_list[0]
    equity = _decimal(account.get("totalEquity"))
    available = _decimal(account.get("totalAvailableBalance"))
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    first_today = (
        await session.execute(
            select(AccountEquitySnapshot)
            .where(
                AccountEquitySnapshot.account_id == "bybit-unified",
                AccountEquitySnapshot.source_time >= day_start,
            )
            .order_by(AccountEquitySnapshot.source_time)
            .limit(1)
        )
    ).scalar_one_or_none()
    day_start_equity = first_today.day_start_equity if first_today else equity
    session.add(
        AccountEquitySnapshot(
            account_id="bybit-unified",
            equity=equity,
            available_margin=available,
            day_start_equity=day_start_equity,
            source_time=now,
            received_at=now,
            quality_flags=[],
        )
    )
    positions = await client.get_positions("USDT")
    for item in positions:
        size = _decimal(item.get("size"))
        if size <= 0:
            continue
        session.add(
            PositionSnapshot(
                symbol=item.get("symbol"),
                side=(item.get("side") or "").upper(),
                qty=size,
                avg_price=_decimal(item.get("avgPrice")),
                mark_price=_decimal(item.get("markPrice")),
                unrealized_pnl=_decimal(item.get("unrealisedPnl")),
                source_time=now,
                source="bybit-read-only",
            )
        )
    await session.execute(
        update(CapitalProfile)
        .where(
            CapitalProfile.mode == "bybit_read_only",
            CapitalProfile.source_account_id == "bybit-unified",
        )
        .values(capital_verified=True)
    )
    await publish_outbox(
        session,
        event_type="ACCOUNT_SNAPSHOT_UPDATED",
        aggregate_type="account",
        aggregate_id="bybit-unified",
        payload={"equity": str(equity), "available_margin": str(available), "positions": len(positions)},
    )
    return {
        "enabled": True,
        "equity": str(equity),
        "available_margin": str(available),
        "positions": len(positions),
    }

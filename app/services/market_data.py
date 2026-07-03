from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import desc, func, select, update
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

BYBIT_READ_ONLY_ACCOUNT_ID = "bybit-unified"


@dataclass(frozen=True)
class CandleWindow:
    symbol: str
    start_time: datetime
    end_time: datetime


@dataclass(frozen=True)
class InstrumentSpecValues:
    tick_size: Decimal
    qty_step: Decimal
    min_qty: Decimal
    max_qty: Decimal
    min_notional: Decimal
    max_leverage: Decimal
    funding_interval_minutes: int | None


def _dt_ms(value: str | int | None) -> datetime | None:
    if value in (None, "", "0", 0):
        return None
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def _decimal(value: object, default: str = "0") -> Decimal:
    if value in (None, ""):
        return Decimal(default)
    return Decimal(str(value))


def _finite_decimal_or_none(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None
    return result if result.is_finite() else None


def _positive_decimal_or_none(value: object) -> Decimal | None:
    result = _finite_decimal_or_none(value)
    return result if result is not None and result > 0 else None


def _nonnegative_decimal_or_none(value: object) -> Decimal | None:
    result = _finite_decimal_or_none(value)
    return result if result is not None and result >= 0 else None


def _required_finite_decimal(value: object, field: str) -> Decimal:
    result = _finite_decimal_or_none(value)
    if result is None:
        raise ValueError(f"Bybit field {field} must be a finite decimal")
    return result


def _required_positive_decimal(value: object, field: str) -> Decimal:
    result = _required_finite_decimal(value, field)
    if result <= 0:
        raise ValueError(f"Bybit field {field} must be positive")
    return result


def _required_nonnegative_decimal(value: object, field: str) -> Decimal:
    result = _required_finite_decimal(value, field)
    if result < 0:
        raise ValueError(f"Bybit field {field} must be non-negative")
    return result


def _instrument_spec_values(item: dict) -> InstrumentSpecValues:
    price_filter = item.get("priceFilter") or {}
    lot_filter = item.get("lotSizeFilter") or {}
    leverage_filter = item.get("leverageFilter") or {}
    tick_size = _required_positive_decimal(price_filter.get("tickSize"), "priceFilter.tickSize")
    qty_step = _required_positive_decimal(lot_filter.get("qtyStep"), "lotSizeFilter.qtyStep")
    min_qty = _required_positive_decimal(
        lot_filter.get("minOrderQty"), "lotSizeFilter.minOrderQty"
    )
    max_qty = _required_positive_decimal(
        lot_filter.get("maxOrderQty"), "lotSizeFilter.maxOrderQty"
    )
    if max_qty < min_qty:
        raise ValueError("Bybit field lotSizeFilter.maxOrderQty must not be below minOrderQty")
    min_notional = _required_positive_decimal(
        lot_filter.get("minNotionalValue"), "lotSizeFilter.minNotionalValue"
    )
    max_leverage = _required_positive_decimal(
        leverage_filter.get("maxLeverage"), "leverageFilter.maxLeverage"
    )

    funding_interval: int | None = None
    raw_funding_interval = item.get("fundingInterval")
    if raw_funding_interval not in (None, ""):
        try:
            funding_interval = int(raw_funding_interval)
        except (TypeError, ValueError) as exc:
            raise ValueError("Bybit field fundingInterval must be a positive integer") from exc
        if funding_interval <= 0:
            raise ValueError("Bybit field fundingInterval must be a positive integer")
    elif item.get("contractType") == "LinearPerpetual":
        raise ValueError("Bybit field fundingInterval is required for LinearPerpetual")

    return InstrumentSpecValues(
        tick_size=tick_size,
        qty_step=qty_step,
        min_qty=min_qty,
        max_qty=max_qty,
        min_notional=min_notional,
        max_leverage=max_leverage,
        funding_interval_minutes=funding_interval,
    )


def _normalized_open_position(item: dict) -> dict[str, object] | None:
    size = _required_nonnegative_decimal(item.get("size"), "position.size")
    if size == 0:
        return None
    symbol = str(item.get("symbol") or "").strip().upper()
    if not symbol:
        raise ValueError("Bybit field position.symbol is required for an open position")
    side = str(item.get("side") or "").strip().upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("Bybit field position.side must be Buy or Sell for an open position")
    return {
        "symbol": symbol,
        "side": side,
        "qty": size,
        "avg_price": _required_positive_decimal(item.get("avgPrice"), "position.avgPrice"),
        "mark_price": _required_positive_decimal(item.get("markPrice"), "position.markPrice"),
        "unrealized_pnl": _required_finite_decimal(
            item.get("unrealisedPnl"), "position.unrealisedPnl"
        ),
    }


async def sync_instruments(session: AsyncSession, client: BybitClient) -> int:
    items = await client.get_instruments("linear")
    now = datetime.now(UTC)
    count = 0
    for item in items:
        if item.get("settleCoin") != "USDT":
            continue
        # Bybit's ``linear`` category contains both perpetuals and dated futures.
        # This application is deliberately scoped to USDT perpetuals; dated
        # futures can legitimately report fundingInterval=0 because they settle
        # by delivery instead of periodic funding. Exclude them before strict
        # perpetual specification validation.
        if item.get("contractType") != "LinearPerpetual":
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            raise ValueError("Bybit field symbol is required for a USDT instrument")
        status = item.get("status") or "Unknown"
        is_pre_listing = bool(item.get("isPreListing", False))
        spec_values = None
        if status == "Trading" and not is_pre_listing:
            spec_values = _instrument_spec_values(item)
        instrument_values = {
            "symbol": symbol,
            "category": "linear",
            "base_coin": item.get("baseCoin") or symbol.removesuffix("USDT"),
            "quote_coin": item.get("quoteCoin") or "USDT",
            "settle_coin": item.get("settleCoin") or "USDT",
            "status": status,
            "launch_time": _dt_ms(item.get("launchTime")),
            "delivery_time": _dt_ms(item.get("deliveryTime")),
            "is_pre_listing": is_pre_listing,
            "raw": item,
            "updated_at": now,
        }
        stmt = insert(Instrument).values(**instrument_values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Instrument.symbol],
            set_={key: value for key, value in instrument_values.items() if key != "symbol"},
        )
        await session.execute(stmt)

        if spec_values is None:
            count += 1
            continue
        latest_spec = (
            await session.execute(
                select(InstrumentSpecHistory)
                .where(InstrumentSpecHistory.symbol == symbol)
                .order_by(desc(InstrumentSpecHistory.valid_from))
                .limit(1)
            )
        ).scalar_one_or_none()
        fingerprint = (
            spec_values.tick_size,
            spec_values.qty_step,
            spec_values.min_qty,
            spec_values.max_qty,
            spec_values.min_notional,
            spec_values.max_leverage,
            spec_values.funding_interval_minutes,
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
            values_list = _candle_values(
                symbol=symbol,
                interval=interval,
                price_type=price_type,
                rows=rows,
                now=datetime.now(UTC),
                interval_minutes=interval_minutes,
            )
            await _upsert_candle_values(session, values_list)
            count += len(values_list)
    return count


async def sync_candle_windows(
    session: AsyncSession,
    client: BybitClient,
    windows: Iterable[CandleWindow],
    *,
    interval: str,
    now: datetime | None = None,
) -> dict[str, object]:
    """Fetch exact last-price candle windows without broad universe backfill.

    This helper is used for post-event intrabar reconstruction.  Every request is
    public/read-only, bounded to one explicit time window and independently
    fail-closed: a failed or partial fetch is reported and the outcome resolver
    keeps the corresponding signal pending.
    """

    interval_minutes = int(interval)
    if interval_minutes <= 0:
        raise ValueError("interval must be a positive minute value")
    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    unique_windows = sorted(
        {
            (item.symbol, item.start_time, item.end_time)
            for item in windows
        },
        key=lambda item: (item[1], item[0], item[2]),
    )
    rows_received = 0
    succeeded = 0
    errors: list[dict[str, str]] = []
    interval_delta = timedelta(minutes=interval_minutes)

    for symbol, start_time, end_time in unique_windows:
        if start_time.tzinfo is None or start_time.utcoffset() is None:
            raise ValueError("window.start_time must be timezone-aware")
        if end_time.tzinfo is None or end_time.utcoffset() is None:
            raise ValueError("window.end_time must be timezone-aware")
        if end_time <= start_time:
            raise ValueError("window.end_time must be later than start_time")
        duration = end_time - start_time
        if duration % interval_delta != timedelta(0):
            raise ValueError("window duration must be divisible by interval")
        limit = int(duration / interval_delta)
        if not 1 <= limit <= 1000:
            raise ValueError("window requires between 1 and 1000 candles")

        try:
            rows = await client.get_kline(
                symbol,
                interval=interval,
                limit=limit,
                start_ms=int(start_time.timestamp() * 1000),
                end_ms=int(end_time.timestamp() * 1000) - 1,
                price_type="last",
            )
            received_at = current_time if now is not None else datetime.now(UTC)
            values = _candle_values(
                symbol=symbol,
                interval=interval,
                price_type="last",
                rows=rows,
                now=received_at,
                interval_minutes=interval_minutes,
            )
            values = [
                item
                for item in values
                if item["open_time"] >= start_time and item["close_time"] <= end_time
            ]
            expected_open_times = [
                start_time + interval_delta * index for index in range(limit)
            ]
            actual_open_times = sorted(item["open_time"] for item in values)
            if actual_open_times != expected_open_times:
                raise ValueError(
                    f"partial_window: expected {limit} candles, received {len(values)}"
                )
            await _upsert_candle_values(session, values)
            rows_received += len(values)
            succeeded += 1
        except Exception as exc:
            logger.exception(
                "Failed to fetch bounded candle window",
                extra={
                    "symbol": symbol,
                    "interval": interval,
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                    "event": "candle_window_fetch_failed",
                },
            )
            errors.append(
                {
                    "symbol": symbol,
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                    "error": str(exc),
                }
            )

    return {
        "windows_requested": len(unique_windows),
        "windows_succeeded": succeeded,
        "rows_received": rows_received,
        "errors": errors,
    }


def _candle_values(
    *,
    symbol: str,
    interval: str,
    price_type: str,
    rows: Iterable[list[str]],
    now: datetime,
    interval_minutes: int,
) -> list[dict]:
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
                # Availability is the post-response receipt time, not the candle
                # close time. Historical/backfill rows must never appear to have
                # been known before this process actually received them.
                "available_at": now,
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
    return values_list


async def _upsert_candle_values(session: AsyncSession, values_list: list[dict]) -> None:
    if not values_list:
        return
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
        # A confirmed candle is an immutable market fact until an explicit,
        # auditable revision policy exists. Only the still-open candle may be
        # refreshed and then transitioned to its first confirmed snapshot.
        where=Candle.confirmed.is_(False),
    )
    await session.execute(stmt)


async def symbols_needing_history_backfill(
    session: AsyncSession,
    symbols: Iterable[str],
    *,
    interval: str,
    target_days: int,
    limit: int,
) -> list[dict[str, object]]:
    symbol_list = list(dict.fromkeys(symbols))
    if not symbol_list:
        return []
    target_start = datetime.now(UTC) - timedelta(days=target_days)
    launches = dict(
        (
            await session.execute(
                select(Instrument.symbol, Instrument.launch_time).where(
                    Instrument.symbol.in_(symbol_list)
                )
            )
        ).all()
    )
    grouped = (
        await session.execute(
            select(
                Candle.symbol,
                func.count(Candle.id).label("rows"),
                func.min(Candle.open_time).label("earliest"),
                func.max(Candle.open_time).label("latest"),
            )
            .where(
                Candle.symbol.in_(symbol_list),
                Candle.interval == interval,
                Candle.price_type == "last",
                Candle.confirmed.is_(True),
            )
            .group_by(Candle.symbol)
        )
    ).all()
    by_symbol = {
        row.symbol: {
            "symbol": row.symbol,
            "rows": int(row.rows),
            "earliest": row.earliest,
            "latest": row.latest,
        }
        for row in grouped
    }
    candidates: list[dict[str, object]] = []
    for symbol in symbol_list:
        item = by_symbol.get(
            symbol,
            {"symbol": symbol, "rows": 0, "earliest": None, "latest": None},
        )
        earliest = item["earliest"]
        launch_time = launches.get(symbol)
        effective_target = max(
            target_start,
            launch_time if isinstance(launch_time, datetime) else target_start,
        )
        item["target_start"] = effective_target
        if earliest is None or earliest > effective_target + timedelta(minutes=int(interval)):
            candidates.append(item)
    candidates.sort(
        key=lambda item: (
            int(item["rows"]),
            item["earliest"] or datetime.max.replace(tzinfo=UTC),
            str(item["symbol"]),
        )
    )
    return candidates[: max(1, limit)]


async def sync_candle_history(
    session: AsyncSession,
    client: BybitClient,
    candidates: Iterable[dict[str, object]],
    *,
    interval: str,
    target_days: int,
    page_size: int,
    max_pages_per_symbol: int,
) -> dict[str, object]:
    """Progressively extend last-price candle history backwards without blocking startup."""

    now = datetime.now(UTC)
    default_target_start = now - timedelta(days=target_days)
    interval_minutes = int(interval)
    rows_received = 0
    symbols_processed = 0
    completed_symbols: list[str] = []
    progress: list[dict[str, object]] = []

    for candidate in candidates:
        symbol = str(candidate["symbol"])
        target_start = candidate.get("target_start")
        if not isinstance(target_start, datetime):
            target_start = default_target_start
        earliest = candidate.get("earliest")
        end_ms = (
            int(earliest.timestamp() * 1000) - 1
            if isinstance(earliest, datetime)
            else int(now.timestamp() * 1000)
        )
        symbol_rows = 0
        oldest_seen = earliest if isinstance(earliest, datetime) else None
        exhausted = False
        error: str | None = None
        try:
            for _page in range(max_pages_per_symbol):
                rows = await client.get_kline(
                    symbol,
                    interval=interval,
                    limit=page_size,
                    end_ms=end_ms,
                    price_type="last",
                )
                if not rows:
                    exhausted = True
                    break
                values = _candle_values(
                    symbol=symbol,
                    interval=interval,
                    price_type="last",
                    rows=rows,
                    now=datetime.now(UTC),
                    interval_minutes=interval_minutes,
                )
                values = [item for item in values if item["open_time"] >= target_start]
                await _upsert_candle_values(session, values)
                symbol_rows += len(values)
                page_times = [_dt_ms(row[0]) for row in rows]
                page_times = [item for item in page_times if item is not None]
                if not page_times:
                    exhausted = True
                    break
                oldest_seen = min(page_times)
                if oldest_seen <= target_start or len(rows) < page_size:
                    exhausted = True
                    break
                end_ms = int(oldest_seen.timestamp() * 1000) - 1
        except Exception as exc:
            error = str(exc)
            logger.exception("Historical candle backfill failed", extra={"symbol": symbol})
        symbols_processed += 1
        rows_received += symbol_rows
        if exhausted or (oldest_seen is not None and oldest_seen <= target_start):
            completed_symbols.append(symbol)
        progress.append(
            {
                "symbol": symbol,
                "rows_received": symbol_rows,
                "oldest_seen": oldest_seen.isoformat() if oldest_seen else None,
                "target_start": target_start.isoformat(),
                "completed": symbol in completed_symbols,
                "error": error,
            }
        )

    return {
        "symbols_processed": symbols_processed,
        "rows_received": rows_received,
        "completed_symbols": completed_symbols,
        "progress": progress,
        "default_target_start": default_target_start.isoformat(),
    }


async def sync_tickers(
    session: AsyncSession,
    client: BybitClient,
    symbols: set[str] | None,
    *,
    items: list[dict] | None = None,
) -> int:
    items = items if items is not None else await client.get_tickers("linear")
    now = datetime.now(UTC)
    values_list: list[dict] = []
    for item in items:
        symbol = item.get("symbol")
        if not symbol or (symbols is not None and symbol not in symbols):
            continue
        last_price = _positive_decimal_or_none(item.get("lastPrice"))
        if last_price is None:
            continue
        bid_price = _positive_decimal_or_none(item.get("bid1Price"))
        ask_price = _positive_decimal_or_none(item.get("ask1Price"))
        if bid_price is None or ask_price is None or ask_price < bid_price:
            bid_price = None
            ask_price = None
        values_list.append(
            {
                "symbol": symbol,
                "source_time": now,
                "received_at": now,
                "last_price": last_price,
                "mark_price": _positive_decimal_or_none(item.get("markPrice")),
                "index_price": _positive_decimal_or_none(item.get("indexPrice")),
                "bid_price": bid_price,
                "ask_price": ask_price,
                "turnover_24h": _nonnegative_decimal_or_none(item.get("turnover24h")),
                "volume_24h": _nonnegative_decimal_or_none(item.get("volume24h")),
                "open_interest": _nonnegative_decimal_or_none(item.get("openInterest")),
                "funding_rate": _finite_decimal_or_none(item.get("fundingRate")),
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
    funding_count = 0
    oi_count = 0
    for symbol in symbols:
        try:
            funding_items = await client.get_funding_history(symbol, limit=10)
            funding_received_at = datetime.now(UTC)
            for item in funding_items:
                funding_time = _dt_ms(item.get("fundingRateTimestamp"))
                if funding_time is None:
                    continue
                stmt = (
                    insert(FundingRate)
                    .values(
                        symbol=symbol,
                        funding_time=funding_time,
                        available_at=funding_received_at,
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
            oi_received_at = datetime.now(UTC)
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
                        available_at=oi_received_at,
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
    wallet = await client.get_wallet_balance("UNIFIED")
    account_list = wallet.get("list") or []
    if not account_list:
        raise RuntimeError("Bybit wallet response contained no account")
    account = account_list[0]
    equity = _required_positive_decimal(account.get("totalEquity"), "totalEquity")
    available = _required_nonnegative_decimal(
        account.get("totalAvailableBalance"), "totalAvailableBalance"
    )
    raw_positions = await client.get_positions("USDT")
    positions = [
        normalized
        for item in raw_positions
        if (normalized := _normalized_open_position(item)) is not None
    ]
    now = datetime.now(UTC)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    first_today = (
        await session.execute(
            select(AccountEquitySnapshot)
            .where(
                AccountEquitySnapshot.account_id == BYBIT_READ_ONLY_ACCOUNT_ID,
                AccountEquitySnapshot.source_time >= day_start,
            )
            .order_by(AccountEquitySnapshot.source_time)
            .limit(1)
        )
    ).scalar_one_or_none()
    day_start_equity = first_today.day_start_equity if first_today else equity
    session.add(
        AccountEquitySnapshot(
            account_id=BYBIT_READ_ONLY_ACCOUNT_ID,
            equity=equity,
            available_margin=available,
            day_start_equity=day_start_equity,
            source_time=now,
            received_at=now,
            quality_flags=[],
        )
    )
    for item in positions:
        session.add(
            PositionSnapshot(
                account_id=BYBIT_READ_ONLY_ACCOUNT_ID,
                symbol=str(item["symbol"]),
                side=str(item["side"]),
                qty=item["qty"],
                avg_price=item["avg_price"],
                mark_price=item["mark_price"],
                unrealized_pnl=item["unrealized_pnl"],
                source_time=now,
                source="bybit-read-only",
            )
        )
    await session.execute(
        update(CapitalProfile)
        .where(
            CapitalProfile.mode == "bybit_read_only",
            CapitalProfile.source_account_id == BYBIT_READ_ONLY_ACCOUNT_ID,
        )
        .values(capital_verified=True)
    )
    await publish_outbox(
        session,
        event_type="ACCOUNT_SNAPSHOT_UPDATED",
        aggregate_type="account",
        aggregate_id=BYBIT_READ_ONLY_ACCOUNT_ID,
        payload={"equity": str(equity), "available_margin": str(available), "positions": len(positions)},
    )
    return {
        "enabled": True,
        "equity": str(equity),
        "available_margin": str(available),
        "positions": len(positions),
    }

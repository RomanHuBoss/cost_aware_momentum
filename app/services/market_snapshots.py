from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AccountEquitySnapshot, OrderBookSnapshot, TickerSnapshot


def latest_available_account_equity_query(
    account_id: str,
    *,
    cutoff: datetime,
):
    """Build a point-in-time account equity query for risk decisions."""

    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("Account snapshot availability cutoff must be timezone-aware")
    normalized_account_id = str(account_id).strip()
    if not normalized_account_id:
        raise ValueError("Account id is required")
    return (
        select(AccountEquitySnapshot)
        .where(
            AccountEquitySnapshot.account_id == normalized_account_id,
            AccountEquitySnapshot.source_time <= cutoff,
            AccountEquitySnapshot.received_at <= cutoff,
        )
        .order_by(
            desc(AccountEquitySnapshot.source_time),
            desc(AccountEquitySnapshot.received_at),
            desc(AccountEquitySnapshot.id),
        )
        .limit(1)
    )


async def latest_available_account_equity(
    session: AsyncSession,
    account_id: str,
    *,
    cutoff: datetime,
) -> AccountEquitySnapshot | None:
    return (
        await session.execute(
            latest_available_account_equity_query(account_id, cutoff=cutoff)
        )
    ).scalar_one_or_none()

def latest_available_orderbook_query(
    symbol: str,
    *,
    cutoff: datetime,
):
    """Build a point-in-time orderbook query.

    Both exchange/source time and local receipt time must be available at the
    decision cutoff. Filtering before ordering prevents a future-dated row from
    masking an older valid snapshot.
    """

    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("Orderbook availability cutoff must be timezone-aware")
    normalized_symbol = str(symbol).strip().upper()
    if not normalized_symbol:
        raise ValueError("Orderbook symbol is required")
    return (
        select(OrderBookSnapshot)
        .where(
            OrderBookSnapshot.symbol == normalized_symbol,
            OrderBookSnapshot.source_time <= cutoff,
            OrderBookSnapshot.received_at <= cutoff,
        )
        .order_by(
            desc(OrderBookSnapshot.source_time),
            desc(OrderBookSnapshot.received_at),
            desc(OrderBookSnapshot.id),
        )
        .limit(1)
    )


async def latest_available_orderbook(
    session: AsyncSession,
    symbol: str,
    *,
    cutoff: datetime,
) -> OrderBookSnapshot | None:
    return (
        await session.execute(latest_available_orderbook_query(symbol, cutoff=cutoff))
    ).scalar_one_or_none()

def latest_available_ticker_query(
    symbol: str,
    *,
    cutoff: datetime,
):
    """Build the latest ticker query using point-in-time availability semantics.

    A snapshot is usable only when both its market/source timestamp and local
    receipt timestamp are no later than the decision cutoff.  Filtering before
    ordering prevents a future-dated row from masking an older valid snapshot.
    """

    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("Ticker availability cutoff must be timezone-aware")
    normalized_symbol = str(symbol).strip().upper()
    if not normalized_symbol:
        raise ValueError("Ticker symbol is required")
    return (
        select(TickerSnapshot)
        .where(
            TickerSnapshot.symbol == normalized_symbol,
            TickerSnapshot.source_time <= cutoff,
            TickerSnapshot.received_at <= cutoff,
        )
        .order_by(
            desc(TickerSnapshot.source_time),
            desc(TickerSnapshot.received_at),
            desc(TickerSnapshot.id),
        )
        .limit(1)
    )


async def latest_available_ticker(
    session: AsyncSession,
    symbol: str,
    *,
    cutoff: datetime,
) -> TickerSnapshot | None:
    return (
        await session.execute(latest_available_ticker_query(symbol, cutoff=cutoff))
    ).scalar_one_or_none()

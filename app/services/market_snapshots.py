from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TickerSnapshot


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

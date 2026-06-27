from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import desc, select

from app.api.deps import SessionDep
from app.db.models import Candle

router = APIRouter(prefix="/api/v1/symbols", tags=["charts"])


@router.get("/{symbol}/chart")
async def chart(symbol: str, session: SessionDep, bars: int = Query(default=168, ge=24, le=1000)) -> dict:
    rows = (
        (
            await session.execute(
                select(Candle)
                .where(
                    Candle.symbol == symbol.upper(),
                    Candle.interval == "60",
                    Candle.price_type.in_(["last", "mark"]),
                )
                .order_by(desc(Candle.open_time))
                .limit(bars * 2)
            )
        )
        .scalars()
        .all()
    )
    by_type: dict[str, list] = {"last": [], "mark": []}
    for row in reversed(rows):
        by_type.setdefault(row.price_type, []).append(
            {
                "time": row.open_time.isoformat(),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume),
            }
        )
    return {"symbol": symbol.upper(), "interval": "60", "series": by_type}

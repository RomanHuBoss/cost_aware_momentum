from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.db.engine import SessionFactory
from app.db.models import OutboxEvent

router = APIRouter(prefix="/api/v1", tags=["events"])


@router.get("/events")
async def events(request: Request, last_event_id: int = 0) -> StreamingResponse:
    header_value = request.headers.get("last-event-id")
    cursor = int(header_value) if header_value and header_value.isdigit() else last_event_id

    async def stream():
        nonlocal cursor
        while True:
            if await request.is_disconnected():
                return
            async with SessionFactory() as session:
                rows = (
                    (
                        await session.execute(
                            select(OutboxEvent)
                            .where(OutboxEvent.id > cursor)
                            .order_by(OutboxEvent.id)
                            .limit(100)
                        )
                    )
                    .scalars()
                    .all()
                )
                for row in rows:
                    cursor = row.id
                    payload = json.dumps(
                        {
                            "id": row.id,
                            "type": row.event_type,
                            "aggregate_type": row.aggregate_type,
                            "aggregate_id": row.aggregate_id,
                            "payload": row.payload,
                            "created_at": row.created_at.isoformat(),
                        },
                        ensure_ascii=False,
                        default=str,
                    )
                    yield f"id: {row.id}\nevent: {row.event_type}\ndata: {payload}\n\n"
            if not rows:
                yield ": keepalive\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

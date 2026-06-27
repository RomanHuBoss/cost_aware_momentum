from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IdempotencyKey


class IdempotencyConflict(Exception):
    pass


async def get_cached(
    session: AsyncSession,
    *,
    key: str,
    scope: str,
    request_payload: Any,
) -> tuple[int, bytes] | None:
    row = await session.get(IdempotencyKey, {"key": key, "scope": scope})
    request_hash = hashlib.sha256(
        json.dumps(request_payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()
    if row is None:
        return None
    if row.expires_at < datetime.now(UTC):
        await session.delete(row)
        await session.flush()
        return None
    if row.request_hash != request_hash:
        raise IdempotencyConflict("Idempotency-Key was already used with a different request")
    return row.response_status, bytes(row.response_body)


async def store_cached(
    session: AsyncSession,
    *,
    key: str,
    scope: str,
    request_payload: Any,
    response_status: int,
    response_body: bytes,
    ttl_hours: int = 24,
) -> None:
    request_hash = hashlib.sha256(
        json.dumps(request_payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()
    session.add(
        IdempotencyKey(
            key=key,
            scope=scope,
            request_hash=request_hash,
            response_status=response_status,
            response_body=response_body,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
        )
    )

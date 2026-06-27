from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def lock_key(namespace: str, value: str) -> int:
    digest = hashlib.blake2b(f"{namespace}:{value}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


@asynccontextmanager
async def advisory_lock(session: AsyncSession, namespace: str, value: str) -> AsyncIterator[bool]:
    key = lock_key(namespace, value)
    acquired = bool(
        (await session.execute(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key})).scalar()
    )
    yield acquired

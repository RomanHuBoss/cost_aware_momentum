from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def database_health(session: AsyncSession) -> dict:
    result = await session.execute(text("SELECT now(), current_database(), current_user"))
    now, database, user = result.one()
    return {"ok": True, "server_time": now.isoformat(), "database": database, "user": user}


async def current_revision(session: AsyncSession) -> str | None:
    result = await session.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
    return result.scalar_one_or_none()

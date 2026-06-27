from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings, get_settings

_settings = get_settings()
engine: AsyncEngine = create_async_engine(
    _settings.database_url,
    pool_pre_ping=True,
    pool_size=_settings.database_pool_size,
    max_overflow=_settings.database_max_overflow,
)
SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session


async def dispose_engine() -> None:
    await engine.dispose()


def rebuild_engine(settings: Settings) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    custom_engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(custom_engine, class_=AsyncSession, expire_on_commit=False)
    return custom_engine, factory

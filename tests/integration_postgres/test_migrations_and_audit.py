from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.config import Settings
from app.db.engine import rebuild_engine
from app.db.models import AuditEvent, CapitalProfile, UIGlossary
from app.services.audit import append_audit_event
from app.services.idempotency import IdempotencyConflict, get_cached, store_cached

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is not configured")
    return value


@pytest.fixture(scope="session", autouse=True)
def migrate(database_url: str) -> None:
    env = {**os.environ, "DATABASE_URL": database_url}
    subprocess.run(["alembic", "downgrade", "base"], cwd=Path(__file__).parents[2], env=env, check=False)
    subprocess.run(["alembic", "upgrade", "head"], cwd=Path(__file__).parents[2], env=env, check=True)


@pytest.mark.asyncio
async def test_seeded_reference_data(database_url: str) -> None:
    settings = Settings(database_url=database_url)
    engine, factory = rebuild_engine(settings)
    async with factory() as session:
        assert (await session.execute(select(CapitalProfile))).scalars().all()
        assert len((await session.execute(select(UIGlossary))).scalars().all()) >= 10
        revision = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
        assert revision == "0003_single_active_model"
        index_definition = (
            await session.execute(
                text(
                    """
                    SELECT indexdef
                    FROM pg_indexes
                    WHERE schemaname = 'advisory'
                      AND indexname = 'uq_market_signal_one_published_per_symbol'
                    """
                )
            )
        ).scalar_one()
        assert "UNIQUE INDEX" in index_definition
        assert "WHERE" in index_definition
        assert "PUBLISHED" in index_definition
        model_index_definition = (
            await session.execute(
                text(
                    """
                    SELECT indexdef
                    FROM pg_indexes
                    WHERE schemaname = 'model'
                      AND indexname = 'uq_model_registry_single_active'
                    """
                )
            )
        ).scalar_one()
        assert "UNIQUE INDEX" in model_index_definition
        assert "WHERE" in model_index_definition
        assert "active" in model_index_definition
    await engine.dispose()


@pytest.mark.asyncio
async def test_audit_chain_and_idempotency(database_url: str) -> None:
    settings = Settings(database_url=database_url)
    engine, factory = rebuild_engine(settings)
    async with factory() as session:
        first = await append_audit_event(
            session, event_type="TEST_A", entity_type="test", entity_id="1", actor="pytest", payload={"a": 1}
        )
        await session.flush()
        second = await append_audit_event(
            session, event_type="TEST_B", entity_type="test", entity_id="1", actor="pytest", payload={"b": 2}
        )
        await store_cached(
            session,
            key="pytest-key-0001",
            scope="pytest-scope",
            request_payload={"x": 1},
            response_status=200,
            response_body=b'{"ok":true}',
        )
        await session.commit()
        assert second.previous_hash == first.event_hash
        assert len(second.event_hash) == 64

    async with factory() as session:
        cached = await get_cached(
            session, key="pytest-key-0001", scope="pytest-scope", request_payload={"x": 1}
        )
        assert cached == (200, b'{"ok":true}')
        with pytest.raises(IdempotencyConflict):
            await get_cached(session, key="pytest-key-0001", scope="pytest-scope", request_payload={"x": 2})
        events = (
            (await session.execute(select(AuditEvent).where(AuditEvent.actor == "pytest"))).scalars().all()
        )
        assert len(events) >= 2
    await engine.dispose()

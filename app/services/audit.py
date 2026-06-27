from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditEvent, OutboxEvent


async def append_audit_event(
    session: AsyncSession,
    *,
    event_type: str,
    entity_type: str,
    entity_id: str,
    actor: str,
    payload: dict,
) -> AuditEvent:
    # Serialize chain-head updates inside the current PostgreSQL transaction.
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 112913404})
    previous = (
        await session.execute(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1))
    ).scalar_one_or_none()
    previous_hash = previous.event_hash if previous else None
    event_time = datetime.now(UTC)
    canonical = json.dumps(
        {
            "event_time": event_time.isoformat(),
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor": actor,
            "payload": payload,
            "previous_hash": previous_hash,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    event_hash = hashlib.sha256(canonical.encode()).hexdigest()
    event = AuditEvent(
        event_time=event_time,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=actor,
        payload=payload,
        previous_hash=previous_hash,
        event_hash=event_hash,
    )
    session.add(event)
    return event


async def publish_outbox(
    session: AsyncSession,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict,
) -> OutboxEvent:
    event = OutboxEvent(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload,
        created_at=datetime.now(UTC),
    )
    session.add(event)
    return event

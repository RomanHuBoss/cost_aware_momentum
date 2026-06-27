from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import SessionDep
from app.db.models import UIGlossary

router = APIRouter(prefix="/api/v1/ui", tags=["ui"])


@router.get("/glossary")
async def glossary(session: SessionDep, locale: str = "ru") -> dict:
    rows = (
        (
            await session.execute(
                select(UIGlossary)
                .where(UIGlossary.locale == locale, UIGlossary.active.is_(True))
                .order_by(UIGlossary.help_key)
            )
        )
        .scalars()
        .all()
    )
    version = rows[0].version if rows else None
    return {
        "locale": locale,
        "version": version,
        "items": [
            {
                "help_key": row.help_key,
                "short_text": row.short_text,
                "long_text": row.long_text,
                "version": row.version,
            }
            for row in rows
        ],
    }

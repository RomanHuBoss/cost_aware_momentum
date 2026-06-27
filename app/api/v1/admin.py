from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import MutatingOperatorDep, SessionDep, SettingsDep
from app.api.schemas import DemoSeedRequest
from app.services.demo import seed_demo_market

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.post("/demo-seed")
async def demo_seed(
    payload: DemoSeedRequest,
    session: SessionDep,
    settings: SettingsDep,
    operator: MutatingOperatorDep,
) -> dict:
    if not settings.allow_demo_seed:
        raise HTTPException(status_code=403, detail="Demo seed is disabled")
    result = await seed_demo_market(session, settings, [symbol.upper() for symbol in payload.symbols])
    await session.commit()
    return {"ok": True, **result}

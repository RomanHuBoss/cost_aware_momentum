from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, update

from app.api.deps import MutatingOperatorDep, SessionDep, SettingsDep
from app.api.schemas import CapitalProfileCreate, CapitalProfilePatch
from app.api.serializers import profile_dict
from app.db.models import CapitalProfile, OperatorPreference
from app.services.audit import append_audit_event, publish_outbox
from app.services.execution import recalculate_all_active_signals

router = APIRouter(prefix="/api/v1/capital-profiles", tags=["capital profiles"])


@router.get("")
async def list_profiles(session: SessionDep) -> dict:
    profiles = (
        (await session.execute(select(CapitalProfile).order_by(CapitalProfile.created_at))).scalars().all()
    )
    return {"items": [profile_dict(item) for item in profiles]}


@router.post("", status_code=201)
async def create_profile(
    payload: CapitalProfileCreate,
    session: SessionDep,
    settings: SettingsDep,
    operator: MutatingOperatorDep,
) -> dict:
    if payload.mode == "bybit_read_only" and not payload.source_account_id:
        raise HTTPException(status_code=422, detail="source_account_id is required for bybit_read_only mode")
    profile = CapitalProfile(
        user_id="local-operator",
        name=payload.name,
        mode=payload.mode,
        allocated_capital=payload.allocated_capital,
        risk_rate=payload.risk_rate,
        max_total_risk_rate=payload.max_total_risk_rate,
        default_leverage=payload.default_leverage,
        max_leverage=payload.max_leverage,
        margin_reserve_rate=payload.margin_reserve_rate,
        source_account_id=payload.source_account_id,
        active=False,
        version=1,
        capital_verified=False,
    )
    session.add(profile)
    await session.flush()
    await append_audit_event(
        session,
        event_type="CAPITAL_PROFILE_CREATED",
        entity_type="capital_profile",
        entity_id=str(profile.id),
        actor=operator,
        payload=profile_dict(profile),
    )
    await session.commit()
    return profile_dict(profile)


@router.patch("/{profile_id}")
async def patch_profile(
    profile_id: UUID,
    payload: CapitalProfilePatch,
    session: SessionDep,
    settings: SettingsDep,
    operator: MutatingOperatorDep,
) -> dict:
    profile = await session.get(CapitalProfile, profile_id, with_for_update=True)
    if not profile:
        raise HTTPException(status_code=404, detail="Capital profile not found")
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(profile, key, value)
    if profile.default_leverage > profile.max_leverage:
        raise HTTPException(status_code=422, detail="default_leverage cannot exceed max_leverage")
    profile.version += 1
    profile.capital_verified = profile.mode == "bybit_read_only" and profile.capital_verified
    await recalculate_all_active_signals(session, profile=profile, settings=settings, actor=operator)
    await append_audit_event(
        session,
        event_type="CAPITAL_PROFILE_UPDATED",
        entity_type="capital_profile",
        entity_id=str(profile.id),
        actor=operator,
        payload={"version": profile.version, "changes": {k: str(v) for k, v in changes.items()}},
    )
    await session.commit()
    return profile_dict(profile)


@router.post("/{profile_id}/activate")
async def activate_profile(
    profile_id: UUID,
    session: SessionDep,
    settings: SettingsDep,
    operator: MutatingOperatorDep,
) -> dict:
    profile = await session.get(CapitalProfile, profile_id, with_for_update=True)
    if not profile:
        raise HTTPException(status_code=404, detail="Capital profile not found")
    await session.execute(update(CapitalProfile).values(active=False))
    profile.active = True
    preference = await session.get(OperatorPreference, "local-operator", with_for_update=True)
    if preference is None:
        preference = OperatorPreference(user_id="local-operator", active_profile_id=profile.id)
        session.add(preference)
    else:
        preference.active_profile_id = profile.id
    plans = await recalculate_all_active_signals(session, profile=profile, settings=settings, actor=operator)
    await append_audit_event(
        session,
        event_type="CAPITAL_PROFILE_ACTIVATED",
        entity_type="capital_profile",
        entity_id=str(profile.id),
        actor=operator,
        payload={"recalculated_plans": len(plans)},
    )
    await publish_outbox(
        session,
        event_type="ACTIVE_PROFILE_CHANGED",
        aggregate_type="capital_profile",
        aggregate_id=str(profile.id),
        payload={"profile_id": str(profile.id), "name": profile.name},
    )
    await session.commit()
    return {"profile": profile_dict(profile), "recalculated_plans": len(plans)}

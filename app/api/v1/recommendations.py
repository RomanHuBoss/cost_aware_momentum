from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Response
from sqlalchemy import desc, func, select

from app.api.deps import MutatingOperatorDep, SessionDep, SettingsDep
from app.api.schemas import DecisionRequest
from app.api.serializers import detail_dict, tile_dict
from app.db.models import (
    AuditEvent,
    CapitalProfile,
    ExecutionPlan,
    MarketSignal,
    OperatorDecision,
    TickerSnapshot,
)
from app.services.audit import append_audit_event, publish_outbox
from app.services.execution import create_execution_plan, effective_capital, open_risk_usdt
from app.services.idempotency import IdempotencyConflict, get_cached, store_cached

router = APIRouter(prefix="/api/v1/recommendations", tags=["recommendations"])


async def resolve_profile(session: SessionDep, profile_id: UUID | None) -> CapitalProfile:
    if profile_id:
        profile = await session.get(CapitalProfile, profile_id)
    else:
        profile = (
            await session.execute(select(CapitalProfile).where(CapitalProfile.active.is_(True)).limit(1))
        ).scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Capital profile not found")
    return profile


async def latest_ticker(session: SessionDep, symbol: str) -> TickerSnapshot | None:
    return (
        await session.execute(
            select(TickerSnapshot)
            .where(TickerSnapshot.symbol == symbol)
            .order_by(desc(TickerSnapshot.source_time))
            .limit(1)
        )
    ).scalar_one_or_none()


async def latest_plan(session: SessionDep, signal_id: UUID, profile_id: UUID) -> ExecutionPlan | None:
    return (
        await session.execute(
            select(ExecutionPlan)
            .where(ExecutionPlan.signal_id == signal_id, ExecutionPlan.profile_id == profile_id)
            .order_by(desc(ExecutionPlan.version))
            .limit(1)
        )
    ).scalar_one_or_none()


def recommendation_signal_query(
    *,
    include_expired: bool,
    symbol: str | None,
    latest_per_symbol: bool,
    limit: int,
    now: datetime,
):
    filters = []
    if not include_expired:
        filters.extend([MarketSignal.status == "PUBLISHED", MarketSignal.expires_at > now])
    if symbol:
        filters.append(MarketSignal.symbol == symbol.upper())

    if latest_per_symbol:
        ranked = (
            select(
                MarketSignal.id.label("signal_id"),
                func.row_number()
                .over(
                    partition_by=MarketSignal.symbol,
                    order_by=(
                        desc(MarketSignal.publish_time),
                        desc(MarketSignal.event_time),
                        desc(MarketSignal.created_at),
                        desc(MarketSignal.id),
                    ),
                )
                .label("symbol_rank"),
            )
            .where(*filters)
            .subquery()
        )
        return (
            select(MarketSignal)
            .join(ranked, ranked.c.signal_id == MarketSignal.id)
            .where(ranked.c.symbol_rank == 1)
            .order_by(desc(MarketSignal.publish_time))
            .limit(limit)
        )

    return (
        select(MarketSignal)
        .where(*filters)
        .order_by(desc(MarketSignal.publish_time))
        .limit(limit)
    )


@router.get("")
async def list_recommendations(
    session: SessionDep,
    profile_id: UUID | None = None,
    symbol: str | None = None,
    include_expired: bool = False,
    latest_per_symbol: bool = True,
    limit: int = Query(default=1000, ge=1, le=2000),
) -> dict:
    profile = await resolve_profile(session, profile_id)
    query = recommendation_signal_query(
        include_expired=include_expired,
        symbol=symbol,
        latest_per_symbol=latest_per_symbol,
        limit=limit,
        now=datetime.now(UTC),
    )

    signals = (await session.execute(query)).scalars().all()
    items: list[dict] = []
    for signal in signals:
        plan = await latest_plan(session, signal.id, profile.id)
        if plan is None:
            continue
        ticker = await latest_ticker(session, signal.symbol)
        items.append(tile_dict(signal, plan, profile, ticker))
    rank = {"ACTIONABLE": 0, "LIMITED": 1, "NO_TRADE": 2}
    items.sort(key=lambda item: (rank.get(item["executability_status"], 3), -float(item["net_ev_r"])))
    return {
        "profile": {
            "id": str(profile.id),
            "name": profile.name,
            "allocated_capital": float(profile.allocated_capital),
            "capital_verified": profile.capital_verified,
            "version": profile.version,
        },
        "items": items,
        "returned_count": len(items),
        "query_limit": limit,
        "latest_per_symbol": latest_per_symbol,
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.get("/{signal_id}")
async def recommendation_detail(
    signal_id: UUID,
    session: SessionDep,
    profile_id: UUID | None = None,
) -> dict:
    signal = await session.get(MarketSignal, signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    profile = await resolve_profile(session, profile_id)
    plan = await latest_plan(session, signal.id, profile.id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Execution plan not found for selected profile")
    ticker = await latest_ticker(session, signal.symbol)
    audit_rows = (
        (
            await session.execute(
                select(AuditEvent)
                .where(AuditEvent.entity_id.in_([str(signal.id), str(plan.id)]))
                .order_by(desc(AuditEvent.event_time))
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    payload = detail_dict(signal, plan, profile, ticker)
    payload["audit"]["events"] = [
        {
            "time": row.event_time.isoformat(),
            "type": row.event_type,
            "actor": row.actor,
            "payload": row.payload,
            "hash": row.event_hash,
        }
        for row in audit_rows
    ]
    return payload


async def _idempotent_response(
    session: SessionDep,
    *,
    idempotency_key: str,
    scope: str,
    request_payload: dict,
) -> Response | None:
    try:
        cached = await get_cached(
            session,
            key=idempotency_key,
            scope=scope,
            request_payload=request_payload,
        )
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if cached is None:
        return None
    status_code, body = cached
    return Response(content=body, status_code=status_code, media_type="application/json")


async def _select_plan_for_action(
    session: SessionDep,
    signal_id: UUID,
    payload: DecisionRequest,
) -> tuple[MarketSignal, ExecutionPlan, CapitalProfile]:
    signal = await session.get(MarketSignal, signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    if payload.plan_id:
        plan = (
            await session.execute(
                select(ExecutionPlan).where(ExecutionPlan.id == payload.plan_id).with_for_update()
            )
        ).scalar_one_or_none()
    else:
        profile = (
            await session.execute(select(CapitalProfile).where(CapitalProfile.active.is_(True)).limit(1))
        ).scalar_one_or_none()
        if profile is None:
            raise HTTPException(status_code=404, detail="Active capital profile not found")
        plan = (
            await session.execute(
                select(ExecutionPlan)
                .where(ExecutionPlan.signal_id == signal_id, ExecutionPlan.profile_id == profile.id)
                .order_by(desc(ExecutionPlan.version))
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
    if plan is None or plan.signal_id != signal_id:
        raise HTTPException(status_code=404, detail="Execution plan not found")
    profile = await session.get(CapitalProfile, plan.profile_id)
    if profile is None:
        raise HTTPException(status_code=409, detail="Capital profile no longer exists")
    return signal, plan, profile


@router.post("/{signal_id}/accept")
async def accept_recommendation(
    signal_id: UUID,
    payload: DecisionRequest,
    session: SessionDep,
    settings: SettingsDep,
    operator: MutatingOperatorDep,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=120),
) -> Response:
    request_payload = payload.model_dump(mode="json")
    scope = f"accept:{signal_id}"
    cached = await _idempotent_response(
        session,
        idempotency_key=idempotency_key,
        scope=scope,
        request_payload=request_payload,
    )
    if cached:
        return cached
    signal, plan, profile = await _select_plan_for_action(session, signal_id, payload)
    now = datetime.now(UTC)
    if signal.status != "PUBLISHED":
        replacement_id = (
            await session.execute(
                select(MarketSignal.id)
                .where(
                    MarketSignal.symbol == signal.symbol,
                    MarketSignal.status == "PUBLISHED",
                    MarketSignal.expires_at > now,
                )
                .order_by(desc(MarketSignal.publish_time))
                .limit(1)
            )
        ).scalar_one_or_none()
        body_dict = {
            "ok": False,
            "code": "RECOMMENDATION_SUPERSEDED",
            "detail": f"Recommendation status {signal.status} is not current",
            "old_signal_id": str(signal.id),
            "replacement_signal_id": str(replacement_id) if replacement_id else None,
        }
        body = json.dumps(body_dict, ensure_ascii=False).encode()
        await store_cached(
            session,
            key=idempotency_key,
            scope=scope,
            request_payload=request_payload,
            response_status=409,
            response_body=body,
        )
        await session.commit()
        return Response(content=body, status_code=409, media_type="application/json")

    conflict_reason: str | None = None
    if plan.status not in {"ACTIONABLE", "LIMITED", "VIEWED"}:
        conflict_reason = f"Plan status {plan.status} is not acceptable"
    elif signal.expires_at <= now:
        conflict_reason = "Recommendation expired"
    elif plan.profile_version != profile.version:
        conflict_reason = "Capital profile version changed"
    ticker = await latest_ticker(session, signal.symbol)
    if conflict_reason is None and (
        ticker is None or (now - ticker.source_time).total_seconds() > settings.max_ticker_age_seconds
    ):
        conflict_reason = "Ticker is stale"
    elif conflict_reason is None and ticker is not None and not (
        signal.entry_low <= ticker.last_price <= signal.entry_high
    ):
        conflict_reason = "Current price is outside entry zone"

    current_open_risk = await open_risk_usdt(session)
    current_capital, _, _, _ = await effective_capital(session, profile)
    if (
        conflict_reason is None
        and current_open_risk + plan.actual_stress_loss > current_capital * profile.max_total_risk_rate
    ):
        conflict_reason = "Portfolio risk limit changed"

    conflicting_plan = (
        await session.execute(
            select(ExecutionPlan.id)
            .join(MarketSignal, ExecutionPlan.signal_id == MarketSignal.id)
            .where(
                MarketSignal.symbol == signal.symbol,
                ExecutionPlan.id != plan.id,
                ExecutionPlan.status.in_(["ACCEPTED", "ENTERED", "PARTIAL"]),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if conflict_reason is None and conflicting_plan is not None:
        conflict_reason = "Another active plan exists for this symbol"

    if conflict_reason:
        new_plan = await create_execution_plan(
            session,
            signal=signal,
            profile=profile,
            settings=settings,
            actor=operator,
        )
        if plan.status not in {"ACCEPTED", "ENTERED", "CLOSED"}:
            plan.status = "SUPERSEDED"
            plan.superseded_by_id = new_plan.id
        body_dict = {
            "ok": False,
            "code": "PLAN_RECALCULATION_REQUIRED",
            "detail": conflict_reason,
            "old_plan_id": str(plan.id),
            "new_plan_id": str(new_plan.id),
            "new_plan_status": new_plan.status,
        }
        body = json.dumps(body_dict, ensure_ascii=False, default=str).encode()
        await store_cached(
            session,
            key=idempotency_key,
            scope=scope,
            request_payload=request_payload,
            response_status=409,
            response_body=body,
        )
        await session.commit()
        return Response(content=body, status_code=409, media_type="application/json")

    existing_decision = (
        await session.execute(select(OperatorDecision).where(OperatorDecision.plan_id == plan.id))
    ).scalar_one_or_none()
    if existing_decision:
        raise HTTPException(status_code=409, detail="Plan already has a terminal operator decision")
    decision = OperatorDecision(
        plan_id=plan.id,
        action="ACCEPT",
        reason_code=payload.reason_code,
        comment=payload.comment,
        operator_id=operator,
        decided_at=now,
        context_snapshot={
            "ticker_time": ticker.source_time.isoformat() if ticker else None,
            "current_price": str(ticker.last_price) if ticker else None,
            "profile_version": profile.version,
            "plan_version": plan.version,
            "current_open_risk": str(current_open_risk),
            "effective_capital": str(current_capital),
        },
    )
    session.add(decision)
    plan.status = "ACCEPTED"
    plan.accepted_at = now
    await append_audit_event(
        session,
        event_type="RECOMMENDATION_ACCEPTED",
        entity_type="execution_plan",
        entity_id=str(plan.id),
        actor=operator,
        payload={"signal_id": str(signal.id), "reason_code": payload.reason_code, "comment": payload.comment},
    )
    await publish_outbox(
        session,
        event_type="RECOMMENDATION_ACCEPTED",
        aggregate_type="execution_plan",
        aggregate_id=str(plan.id),
        payload={"signal_id": str(signal.id), "symbol": signal.symbol},
    )
    body_dict = {
        "ok": True,
        "signal_id": str(signal.id),
        "plan_id": str(plan.id),
        "status": plan.status,
        "message": "Рекомендация принята. Ордер на Bybit не размещался.",
    }
    body = json.dumps(body_dict, ensure_ascii=False).encode()
    await store_cached(
        session,
        key=idempotency_key,
        scope=scope,
        request_payload=request_payload,
        response_status=200,
        response_body=body,
    )
    await session.commit()
    return Response(content=body, media_type="application/json")


@router.post("/{signal_id}/reject")
async def reject_recommendation(
    signal_id: UUID,
    payload: DecisionRequest,
    session: SessionDep,
    operator: MutatingOperatorDep,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=120),
) -> Response:
    request_payload = payload.model_dump(mode="json")
    scope = f"reject:{signal_id}"
    cached = await _idempotent_response(
        session,
        idempotency_key=idempotency_key,
        scope=scope,
        request_payload=request_payload,
    )
    if cached:
        return cached
    signal, plan, profile = await _select_plan_for_action(session, signal_id, payload)
    if signal.status != "PUBLISHED":
        raise HTTPException(status_code=409, detail=f"Recommendation status is {signal.status}")
    if plan.status in {"ACCEPTED", "ENTERED", "CLOSED", "REJECTED", "SUPERSEDED", "EXPIRED"}:
        raise HTTPException(status_code=409, detail=f"Cannot reject plan in status {plan.status}")
    decision = OperatorDecision(
        plan_id=plan.id,
        action="REJECT",
        reason_code=payload.reason_code or "OPERATOR_REJECTED",
        comment=payload.comment,
        operator_id=operator,
        decided_at=datetime.now(UTC),
        context_snapshot={"profile_version": profile.version, "plan_version": plan.version},
    )
    session.add(decision)
    plan.status = "REJECTED"
    plan.rejected_at = datetime.now(UTC)
    await append_audit_event(
        session,
        event_type="RECOMMENDATION_REJECTED",
        entity_type="execution_plan",
        entity_id=str(plan.id),
        actor=operator,
        payload={
            "signal_id": str(signal.id),
            "reason_code": decision.reason_code,
            "comment": payload.comment,
        },
    )
    await publish_outbox(
        session,
        event_type="RECOMMENDATION_REJECTED",
        aggregate_type="execution_plan",
        aggregate_id=str(plan.id),
        payload={"signal_id": str(signal.id), "symbol": signal.symbol},
    )
    body_dict = {"ok": True, "signal_id": str(signal.id), "plan_id": str(plan.id), "status": plan.status}
    body = json.dumps(body_dict, ensure_ascii=False).encode()
    await store_cached(
        session,
        key=idempotency_key,
        scope=scope,
        request_payload=request_payload,
        response_status=200,
        response_body=body,
    )
    await session.commit()
    return Response(content=body, media_type="application/json")


@router.post("/{signal_id}/recalculate-plan")
async def recalculate_plan(
    signal_id: UUID,
    session: SessionDep,
    settings: SettingsDep,
    operator: MutatingOperatorDep,
    profile_id: UUID | None = None,
) -> dict:
    signal = await session.get(MarketSignal, signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    if signal.status != "PUBLISHED" or signal.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=409, detail="Recommendation is no longer current")
    profile = await resolve_profile(session, profile_id)
    old_plan = await latest_plan(session, signal.id, profile.id)
    new_plan = await create_execution_plan(
        session,
        signal=signal,
        profile=profile,
        settings=settings,
        actor=operator,
    )
    if old_plan and old_plan.status not in {"ACCEPTED", "ENTERED", "CLOSED"}:
        old_plan.status = "SUPERSEDED"
        old_plan.superseded_by_id = new_plan.id
    await session.commit()
    ticker = await latest_ticker(session, signal.symbol)
    return tile_dict(signal, new_plan, profile, ticker)

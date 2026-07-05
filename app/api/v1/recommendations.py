from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Response
from sqlalchemy import desc, func, select

from app.api.deps import MutatingOperatorDep, SessionDep, SettingsDep
from app.api.schemas import DecisionRequest
from app.api.serializers import counterfactual_outcome_dict, detail_dict, tile_dict
from app.db.models import (
    AuditEvent,
    CapitalProfile,
    ExecutionPlan,
    MarketSignal,
    OperatorDecision,
    PlanOutcome,
    ServiceHeartbeat,
    SignalOutcome,
    TickerSnapshot,
)
from app.risk.liquidity import ORDERBOOK_EXECUTION_SCHEMA_VERSION
from app.services.audit import append_audit_event, publish_outbox
from app.services.execution import (
    IMMUTABLE_PLAN_STATUSES,
    create_execution_plan,
    entry_price_is_adverse,
    execution_plan_entry_reference,
    execution_plan_scope_clause,
    funding_rate_for_plan,
    latest_orderbook,
    latest_spec,
    liquidity_notional_cap,
    load_acceptance_risk_state,
    orderbook_depth_notional_cap,
    orderbook_fill_for_qty,
    orderbook_snapshot_is_fresh,
    reconciliation_issues,
    ticker_snapshot_is_fresh,
    validate_execution_plan_for_acceptance,
)
from app.services.idempotency import IdempotencyConflict, get_cached, store_cached

router = APIRouter(prefix="/api/v1/recommendations", tags=["recommendations"])


def _plan_orderbook_contract(
    plan: ExecutionPlan,
) -> tuple[datetime | None, str | None]:
    snapshot = plan.sizing_snapshot if isinstance(plan.sizing_snapshot, dict) else {}
    execution_quality = snapshot.get("execution_quality")
    if not isinstance(execution_quality, dict):
        return None, "Execution plan lacks point-in-time orderbook evidence"
    if execution_quality.get("schema") != ORDERBOOK_EXECUTION_SCHEMA_VERSION:
        return None, "Execution plan orderbook schema is incompatible"
    if execution_quality.get("fill_status") != "FULL":
        return None, "Execution plan was not sized for a complete depth fill"
    try:
        requested_qty = Decimal(str(execution_quality["requested_qty"]))
        filled_qty = Decimal(str(execution_quality["filled_qty"]))
        vwap = Decimal(str(execution_quality["vwap"]))
        entry_price = Decimal(str(snapshot["entry_price"]))
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return None, "Execution plan orderbook evidence is incomplete"
    plan_qty = Decimal(str(plan.qty))
    values = (requested_qty, filled_qty, vwap, entry_price, plan_qty)
    if any(not value.is_finite() or value <= 0 for value in values):
        return None, "Execution plan orderbook evidence is invalid"
    if requested_qty != plan_qty or filled_qty != plan_qty or vwap != entry_price:
        return None, "Execution plan orderbook evidence does not match its size or entry"
    try:
        planning_time = datetime.fromisoformat(str(snapshot["planning_time"]))
    except (KeyError, TypeError, ValueError):
        return None, "Execution plan planning time is missing or invalid"
    if planning_time.tzinfo is None or planning_time.utcoffset() is None:
        return None, "Execution plan planning time is not timezone-aware"
    return planning_time, None


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
    active_symbols: list[str] | None = None,
):
    filters = []
    if not include_expired:
        filters.extend([MarketSignal.status == "PUBLISHED", MarketSignal.expires_at > now])
    if symbol:
        filters.append(MarketSignal.symbol == symbol.upper())
    elif active_symbols:
        filters.append(MarketSignal.symbol.in_(active_symbols))

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

    return select(MarketSignal).where(*filters).order_by(desc(MarketSignal.publish_time)).limit(limit)


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
    active_symbols: list[str] | None = None
    if not include_expired:
        worker = (
            await session.execute(
                select(ServiceHeartbeat)
                .where(ServiceHeartbeat.service_name == "worker")
                .order_by(desc(ServiceHeartbeat.last_seen_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        universe = (worker.details or {}).get("universe", {}) if worker else {}
        values = universe.get("selected_symbols") if isinstance(universe, dict) else None
        if isinstance(values, list):
            active_symbols = [str(item) for item in values if item]
    query = recommendation_signal_query(
        include_expired=include_expired,
        symbol=symbol,
        latest_per_symbol=latest_per_symbol,
        limit=limit,
        now=datetime.now(UTC),
        active_symbols=active_symbols,
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
    signal_outcome = (
        await session.execute(select(SignalOutcome).where(SignalOutcome.signal_id == signal.id))
    ).scalar_one_or_none()
    plan_outcome = (
        await session.execute(select(PlanOutcome).where(PlanOutcome.plan_id == plan.id))
    ).scalar_one_or_none()
    payload = detail_dict(signal, plan, profile, ticker)
    payload["counterfactual_outcome"] = counterfactual_outcome_dict(signal_outcome, plan_outcome)
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
    plan_planning_time: datetime | None = None
    if plan.status not in {"ACTIONABLE", "LIMITED", "VIEWED"}:
        conflict_reason = f"Plan status {plan.status} is not acceptable"
    else:
        plan_planning_time, conflict_reason = _plan_orderbook_contract(plan)
    if conflict_reason is None and plan_planning_time is not None and plan_planning_time > now:
        conflict_reason = "Execution plan planning time is in the future"
    if conflict_reason is None and signal.expires_at <= now:
        conflict_reason = "Recommendation expired"
    elif conflict_reason is None and plan.profile_version != profile.version:
        conflict_reason = "Capital profile version changed"
    ticker = await latest_ticker(session, signal.symbol)
    orderbook = await latest_orderbook(session, signal.symbol)
    if conflict_reason is None and (
        ticker is None
        or not ticker_snapshot_is_fresh(
            ticker.source_time,
            now=now,
            max_age_seconds=settings.max_ticker_age_seconds,
        )
    ):
        conflict_reason = "Ticker is stale or has a future timestamp"
    if conflict_reason is None and (
        orderbook is None
        or not orderbook_snapshot_is_fresh(
            orderbook.source_time,
            now=now,
            max_age_seconds=settings.max_orderbook_age_seconds,
            received_at=orderbook.received_at,
        )
    ):
        conflict_reason = "Orderbook is stale or has a future timestamp"
    executable_price = None
    current_depth_cap = None
    current_fill = None
    if conflict_reason is None and ticker is not None and orderbook is not None:
        try:
            current_fill = orderbook_fill_for_qty(
                orderbook,
                direction=signal.direction,
                qty=plan.qty,
                max_impact_bps=Decimal(str(settings.max_vwap_impact_bps)),
            )
            if current_fill.status != "FULL" or current_fill.vwap is None:
                raise ValueError("Current orderbook cannot fully fill the plan within impact limit")
            executable_price = current_fill.vwap
            current_depth_cap = orderbook_depth_notional_cap(
                orderbook,
                direction=signal.direction,
                max_impact_bps=Decimal(str(settings.max_vwap_impact_bps)),
            )
        except ValueError as exc:
            conflict_reason = str(exc)
    executable_inside_zone = executable_price is not None and (
        signal.entry_low <= executable_price <= signal.entry_high
    )
    if conflict_reason is None and executable_price is not None and not executable_inside_zone:
        conflict_reason = "Current executable price is outside entry zone"
    if conflict_reason is None and executable_price is not None:
        plan_entry = execution_plan_entry_reference(plan, signal)
        if entry_price_is_adverse(
            direction=signal.direction,
            reference=plan_entry,
            executable=executable_price,
        ):
            conflict_reason = "Executable entry worsened after plan sizing"

    risk_state = await load_acceptance_risk_state(
        session,
        profile=profile,
        now=now,
        max_snapshot_age_seconds=settings.max_account_snapshot_age_seconds,
    )
    current_open_risk = risk_state.open_risk_usdt
    current_capital = risk_state.effective_capital
    if conflict_reason is None and profile.mode == "bybit_read_only" and not risk_state.capital_verified:
        conflict_reason = "Account capital snapshot is stale or missing"
    if conflict_reason is None and profile.mode == "bybit_read_only":
        reconciliation_failures = await reconciliation_issues(session, profile=profile)
        if reconciliation_failures:
            conflict_reason = "Account reconciliation failed: " + "; ".join(reconciliation_failures)

    acceptance_validation = None
    current_spec = None
    if conflict_reason is None and executable_price is not None and ticker is not None:
        current_spec = await latest_spec(session, signal.symbol, cutoff=now)
        if current_spec is None:
            conflict_reason = "Current instrument constraints are unavailable"
        else:
            try:
                if ticker.funding_rate is None or ticker.next_funding_time is None:
                    raise ValueError("Current funding snapshot is incomplete")
                turnover_cap = liquidity_notional_cap(ticker.turnover_24h)
                if current_depth_cap is None:
                    raise ValueError("Current orderbook depth cap is unavailable")
                current_liquidity_cap = min(turnover_cap, current_depth_cap)
                current_funding_rate = funding_rate_for_plan(
                    start_time=now,
                    horizon_hours=signal.horizon_hours,
                    next_settlement=ticker.next_funding_time,
                    interval_minutes=current_spec.funding_interval_minutes,
                    current_rate=ticker.funding_rate,
                )
                acceptance_validation = validate_execution_plan_for_acceptance(
                    plan=plan,
                    signal=signal,
                    profile=profile,
                    risk_state=risk_state,
                    spec=current_spec,
                    executable_price=executable_price,
                    current_funding_rate=current_funding_rate,
                    current_liquidity_notional_cap=current_liquidity_cap,
                    settings=settings,
                )
            except (TypeError, ValueError) as exc:
                conflict_reason = str(exc)

    if (
        conflict_reason is None
        and acceptance_validation is not None
        and current_open_risk + acceptance_validation.current_stress_loss
        > current_capital * acceptance_validation.max_total_risk_rate
    ):
        conflict_reason = "Portfolio risk limit changed"

    conflicting_plan = None
    if conflict_reason is None:
        conflicting_plan = (
            await session.execute(
                select(ExecutionPlan.id)
                .join(MarketSignal, ExecutionPlan.signal_id == MarketSignal.id)
                .join(CapitalProfile, ExecutionPlan.profile_id == CapitalProfile.id)
                .where(
                    MarketSignal.symbol == signal.symbol,
                    ExecutionPlan.id != plan.id,
                    ExecutionPlan.status.in_(["ACCEPTED", "ENTERED", "PARTIAL"]),
                    execution_plan_scope_clause(profile),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
    if conflicting_plan is not None:
        conflict_reason = "Another active plan exists for this symbol"

    if conflict_reason and plan.status in IMMUTABLE_PLAN_STATUSES:
        body_dict = {
            "ok": False,
            "code": "PLAN_STATE_IMMUTABLE",
            "detail": conflict_reason,
            "plan_id": str(plan.id),
            "plan_status": plan.status,
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

    if conflict_reason:
        new_plan = await create_execution_plan(
            session,
            signal=signal,
            profile=profile,
            settings=settings,
            actor=operator,
            entry_price=executable_price if executable_inside_zone else None,
        )
        if plan.status not in IMMUTABLE_PLAN_STATUSES:
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
            "current_price": str(executable_price) if executable_price is not None else None,
            "last_price": str(ticker.last_price) if ticker else None,
            "bid_price": str(ticker.bid_price) if ticker else None,
            "ask_price": str(ticker.ask_price) if ticker else None,
            "capital_snapshot": risk_state.capital_snapshot,
            "profile_version": profile.version,
            "plan_version": plan.version,
            "current_open_risk": str(current_open_risk),
            "reserved_margin_usdt": str(risk_state.reserved_margin_usdt),
            "effective_capital": str(current_capital),
            "current_notional": str(acceptance_validation.current_notional),
            "current_margin_estimate": str(acceptance_validation.current_margin_estimate),
            "current_stress_loss": str(acceptance_validation.current_stress_loss),
            "current_funding_rate": str(acceptance_validation.current_funding_rate),
            "current_net_rr": str(acceptance_validation.current_net_rr),
            "current_net_ev_r": str(acceptance_validation.current_net_ev_r),
            "per_trade_risk_limit": str(acceptance_validation.per_trade_risk_limit),
            "available_margin_capacity": (
                str(acceptance_validation.available_margin_capacity)
                if acceptance_validation.available_margin_capacity is not None
                else None
            ),
            "current_liquidity_notional_cap": str(acceptance_validation.current_liquidity_notional_cap),
            "plan_planning_time": plan_planning_time.isoformat() if plan_planning_time else None,
            "operator_latency_seconds": (
                (now - plan_planning_time).total_seconds() if plan_planning_time else None
            ),
            "execution_quality": {
                "schema": ORDERBOOK_EXECUTION_SCHEMA_VERSION,
                "snapshot_source_time": orderbook.source_time.isoformat() if orderbook else None,
                "snapshot_received_at": orderbook.received_at.isoformat() if orderbook else None,
                "update_id": orderbook.update_id if orderbook else None,
                "sequence": orderbook.sequence if orderbook else None,
                "depth_requested": orderbook.depth if orderbook else None,
                "max_impact_bps": str(settings.max_vwap_impact_bps),
                "fill_status": current_fill.status if current_fill else None,
                "requested_qty": str(current_fill.requested_qty) if current_fill else None,
                "filled_qty": str(current_fill.filled_qty) if current_fill else None,
                "vwap": str(current_fill.vwap) if current_fill and current_fill.vwap else None,
                "worst_price": (
                    str(current_fill.worst_price)
                    if current_fill and current_fill.worst_price
                    else None
                ),
                "impact_bps": (
                    str(current_fill.impact_bps)
                    if current_fill and current_fill.impact_bps is not None
                    else None
                ),
                "levels_used": current_fill.levels_used if current_fill else 0,
            },
            "instrument_spec_valid_from": (
                current_spec.valid_from.isoformat() if current_spec is not None else None
            ),
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
    if old_plan and old_plan.status in IMMUTABLE_PLAN_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Plan status {old_plan.status} cannot be recalculated",
        )
    new_plan = await create_execution_plan(
        session,
        signal=signal,
        profile=profile,
        settings=settings,
        actor=operator,
    )
    if old_plan:
        old_plan.status = "SUPERSEDED"
        old_plan.superseded_by_id = new_plan.id
    await session.commit()
    ticker = await latest_ticker(session, signal.symbol)
    return tile_dict(signal, new_plan, profile, ticker)

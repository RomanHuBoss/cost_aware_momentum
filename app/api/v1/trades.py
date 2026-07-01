from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Response
from sqlalchemy import select

from app.api.deps import MutatingOperatorDep, SessionDep
from app.api.schemas import ManualEntryRequest, TradeCloseRequest
from app.db.models import ExecutionPlan, Fill, ManualTrade, MarketSignal
from app.risk.math import (
    actual_fill_stress_loss,
    gross_pnl,
    nonnegative_finite_decimal,
    positive_finite_decimal,
)
from app.services.audit import append_audit_event, publish_outbox
from app.services.execution import remaining_trade_risk
from app.services.idempotency import IdempotencyConflict, get_cached, store_cached
from app.services.plan_snapshots import plan_cost_scenario, plan_instrument_constraints

router = APIRouter(prefix="/api/v1/trades", tags=["manual trades"])


def validate_manual_fill_time(
    fill_time: datetime,
    *,
    now: datetime,
    field_name: str,
) -> None:
    """Reject naive or future-dated manual fills before they enter the journal."""

    for name, value in ((field_name, fill_time), ("now", now)):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must be timezone-aware")
    if fill_time > now:
        raise ValueError(f"{field_name} cannot be in the future")


def validate_close_fill_time(
    fill_time: datetime,
    *,
    entry_time: datetime,
    latest_fill_time: datetime | None = None,
    now: datetime | None = None,
) -> None:
    """Require manual close fills to preserve the recorded trade chronology."""
    current_time = now or datetime.now(UTC)
    validate_manual_fill_time(fill_time, now=current_time, field_name="Close fill time")
    if fill_time < entry_time:
        raise ValueError("Close fill time cannot be earlier than trade entry")
    if latest_fill_time is not None and fill_time < latest_fill_time:
        raise ValueError("Close fill time cannot be earlier than latest recorded fill")


async def _cached_or_none(session, key, scope, payload):
    try:
        cached = await get_cached(session, key=key, scope=scope, request_payload=payload)
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if cached:
        code, body = cached
        return Response(content=body, status_code=code, media_type="application/json")
    return None


@router.get("")
async def list_trades(session: SessionDep, status_filter: str | None = None) -> dict:
    query = select(ManualTrade).order_by(ManualTrade.entry_time.desc())
    if status_filter:
        query = query.where(ManualTrade.status == status_filter.upper())
    trades = (await session.execute(query)).scalars().all()
    return {
        "items": [
            {
                "id": str(t.id),
                "plan_id": str(t.plan_id),
                "symbol": t.symbol,
                "direction": t.direction,
                "status": t.status,
                "entry_time": t.entry_time.isoformat(),
                "entry_price": float(t.entry_price),
                "qty": float(t.qty),
                "remaining_qty": float(t.remaining_qty),
                "initial_stress_loss": float(t.initial_stress_loss),
                "remaining_stress_loss": float(t.remaining_stress_loss),
                "leverage": t.leverage,
                "fees_paid": float(t.fees_paid),
                "funding_cash_flow": float(t.funding_cash_flow),
                "realized_pnl": float(t.realized_pnl),
                "notes": t.notes,
            }
            for t in trades
        ]
    }


@router.post("/manual-entry")
async def manual_entry(
    payload: ManualEntryRequest,
    session: SessionDep,
    operator: MutatingOperatorDep,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=120),
) -> Response:
    request_payload = payload.model_dump(mode="json")
    scope = f"manual-entry:{payload.plan_id}"
    cached = await _cached_or_none(session, idempotency_key, scope, request_payload)
    if cached:
        return cached

    plan = (
        await session.execute(
            select(ExecutionPlan).where(ExecutionPlan.id == payload.plan_id).with_for_update()
        )
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Execution plan not found")
    if plan.status != "ACCEPTED":
        raise HTTPException(status_code=409, detail=f"Plan must be ACCEPTED, current status is {plan.status}")
    signal = await session.get(MarketSignal, plan.signal_id)
    if signal is None:
        raise HTTPException(status_code=409, detail="Signal not found")
    existing = (
        await session.execute(select(ManualTrade).where(ManualTrade.plan_id == plan.id))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Manual trade already exists for this plan")
    try:
        validate_manual_fill_time(
            payload.entry_time,
            now=datetime.now(UTC),
            field_name="Entry time",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if (
        payload.entry_time < signal.publish_time - timedelta(minutes=1)
        or payload.entry_time > signal.expires_at
    ):
        raise HTTPException(status_code=422, detail="Entry time is outside the recommendation lifetime")
    if not (signal.entry_low <= payload.entry_price <= signal.entry_high):
        raise HTTPException(status_code=422, detail="Actual entry price is outside the accepted entry zone")
    if payload.qty > plan.qty:
        raise HTTPException(status_code=422, detail="Entered quantity exceeds the accepted plan")
    if payload.leverage > plan.leverage:
        raise HTTPException(status_code=422, detail="Entered leverage exceeds the accepted plan")

    try:
        constraints = plan_instrument_constraints(plan.sizing_snapshot)
        actual_costs = plan_cost_scenario(plan.sizing_snapshot)
        accepted_risk_budget = positive_finite_decimal(
            plan.risk_budget, "accepted plan risk_budget"
        )
        accepted_stress_reservation = nonnegative_finite_decimal(
            plan.actual_stress_loss, "accepted plan actual_stress_loss"
        )
        accepted_margin_reservation = nonnegative_finite_decimal(
            plan.margin_estimate, "accepted plan margin_estimate"
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Accepted plan snapshot is incomplete or invalid: {exc}",
        ) from exc

    step_units = (payload.qty / constraints.qty_step).to_integral_value(rounding=ROUND_DOWN)
    if step_units * constraints.qty_step != payload.qty:
        raise HTTPException(
            status_code=422, detail="Entered quantity does not match the instrument qty step"
        )
    if (
        payload.qty < constraints.min_qty
        or payload.qty * payload.entry_price < constraints.min_notional
    ):
        raise HTTPException(status_code=422, detail="Actual fill is below the instrument minimum order")
    if constraints.max_qty is not None and payload.qty > constraints.max_qty:
        raise HTTPException(status_code=422, detail="Actual fill exceeds the instrument maximum quantity")
    if Decimal(payload.leverage) > constraints.max_leverage:
        raise HTTPException(status_code=422, detail="Actual leverage exceeds the instrument maximum")
    try:
        actual_stress_loss = actual_fill_stress_loss(
            qty=payload.qty,
            entry=payload.entry_price,
            stop=signal.stop_loss,
            direction=signal.direction,
            costs=actual_costs,
            actual_entry_fee=payload.fee,
        )
        actual_margin = positive_finite_decimal(
            payload.qty * payload.entry_price / Decimal(payload.leverage),
            "actual fill margin",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    tolerance = Decimal("0.00000001")
    if actual_stress_loss > accepted_risk_budget + tolerance:
        raise HTTPException(status_code=422, detail="Actual fill would exceed the accepted risk budget")
    if actual_stress_loss > accepted_stress_reservation + tolerance:
        raise HTTPException(
            status_code=422,
            detail="Actual fill would exceed the accepted stress-loss reservation",
        )
    if actual_margin > accepted_margin_reservation + tolerance:
        raise HTTPException(
            status_code=422,
            detail="Actual fill would exceed the accepted margin reservation",
        )

    trade = ManualTrade(
        plan_id=plan.id,
        symbol=signal.symbol,
        direction=signal.direction,
        status="OPEN",
        entry_time=payload.entry_time,
        entry_price=payload.entry_price,
        qty=payload.qty,
        leverage=payload.leverage,
        remaining_qty=payload.qty,
        initial_stress_loss=actual_stress_loss,
        remaining_stress_loss=actual_stress_loss,
        fees_paid=payload.fee,
        funding_cash_flow=Decimal("0"),
        realized_pnl=-payload.fee,
        notes=payload.notes,
    )
    session.add(trade)
    await session.flush()
    session.add(
        Fill(
            trade_id=trade.id,
            side="BUY" if signal.direction == "LONG" else "SELL",
            fill_time=payload.entry_time,
            price=payload.entry_price,
            qty=payload.qty,
            fee=payload.fee,
            funding=Decimal("0"),
            raw={"source": "manual-entry"},
        )
    )
    plan.status = "ENTERED"
    await append_audit_event(
        session,
        event_type="MANUAL_TRADE_ENTERED",
        entity_type="manual_trade",
        entity_id=str(trade.id),
        actor=operator,
        payload={
            "plan_id": str(plan.id),
            "symbol": trade.symbol,
            "entry_price": str(trade.entry_price),
            "qty": str(trade.qty),
            "leverage": trade.leverage,
            "deviation_from_plan_qty": str(trade.qty - plan.qty),
            "actual_entry_fee": str(payload.fee),
            "actual_stress_loss": str(actual_stress_loss),
            "actual_margin": str(actual_margin),
        },
    )
    await publish_outbox(
        session,
        event_type="MANUAL_TRADE_ENTERED",
        aggregate_type="manual_trade",
        aggregate_id=str(trade.id),
        payload={"symbol": trade.symbol, "direction": trade.direction},
    )
    response_dict = {"ok": True, "trade_id": str(trade.id), "status": trade.status}
    body = json.dumps(response_dict, ensure_ascii=False).encode()
    await store_cached(
        session,
        key=idempotency_key,
        scope=scope,
        request_payload=request_payload,
        response_status=201,
        response_body=body,
    )
    await session.commit()
    return Response(content=body, status_code=201, media_type="application/json")


@router.post("/{trade_id}/close")
async def close_trade(
    trade_id: UUID,
    payload: TradeCloseRequest,
    session: SessionDep,
    operator: MutatingOperatorDep,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=120),
) -> Response:
    request_payload = payload.model_dump(mode="json")
    scope = f"trade-close:{trade_id}"
    cached = await _cached_or_none(session, idempotency_key, scope, request_payload)
    if cached:
        return cached
    trade = (
        await session.execute(select(ManualTrade).where(ManualTrade.id == trade_id).with_for_update())
    ).scalar_one_or_none()
    if trade is None:
        raise HTTPException(status_code=404, detail="Manual trade not found")
    if trade.status not in {"OPEN", "PARTIAL"}:
        raise HTTPException(status_code=409, detail=f"Trade cannot be closed from status {trade.status}")
    if payload.qty > trade.remaining_qty:
        raise HTTPException(status_code=422, detail="Close quantity exceeds remaining quantity")

    latest_fill_time = (
        await session.execute(
            select(Fill.fill_time)
            .where(Fill.trade_id == trade.id)
            .order_by(Fill.fill_time.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    try:
        validate_close_fill_time(
            payload.fill_time,
            entry_time=trade.entry_time,
            latest_fill_time=latest_fill_time,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    pnl = gross_pnl(trade.direction, payload.qty, trade.entry_price, payload.exit_price)
    net_change = pnl - payload.fee + payload.funding
    trade.remaining_qty -= payload.qty
    trade.remaining_stress_loss = remaining_trade_risk(
        trade.initial_stress_loss, trade.qty, trade.remaining_qty
    )
    trade.fees_paid += payload.fee
    trade.funding_cash_flow += payload.funding
    trade.realized_pnl += net_change
    trade.status = "CLOSED" if trade.remaining_qty == 0 else "PARTIAL"
    if payload.notes:
        trade.notes = (trade.notes + "\n" if trade.notes else "") + payload.notes
    session.add(
        Fill(
            trade_id=trade.id,
            side="SELL" if trade.direction == "LONG" else "BUY",
            fill_time=payload.fill_time,
            price=payload.exit_price,
            qty=payload.qty,
            fee=payload.fee,
            funding=payload.funding,
            raw={"source": "manual-close"},
        )
    )
    plan = await session.get(ExecutionPlan, trade.plan_id)
    if plan:
        plan.status = "CLOSED" if trade.status == "CLOSED" else "PARTIAL"
    await append_audit_event(
        session,
        event_type="MANUAL_TRADE_CLOSED" if trade.status == "CLOSED" else "MANUAL_TRADE_PARTIAL_CLOSE",
        entity_type="manual_trade",
        entity_id=str(trade.id),
        actor=operator,
        payload={
            "fill_time": payload.fill_time.isoformat(),
            "exit_price": str(payload.exit_price),
            "qty": str(payload.qty),
            "gross_pnl": str(pnl),
            "fee": str(payload.fee),
            "funding": str(payload.funding),
            "net_change": str(net_change),
            "remaining_qty": str(trade.remaining_qty),
            "remaining_stress_loss": str(trade.remaining_stress_loss),
        },
    )
    await publish_outbox(
        session,
        event_type="MANUAL_TRADE_UPDATED",
        aggregate_type="manual_trade",
        aggregate_id=str(trade.id),
        payload={"status": trade.status, "realized_pnl": str(trade.realized_pnl)},
    )
    response_dict = {
        "ok": True,
        "trade_id": str(trade.id),
        "status": trade.status,
        "remaining_qty": float(trade.remaining_qty),
        "remaining_stress_loss": float(trade.remaining_stress_loss),
        "realized_pnl": float(trade.realized_pnl),
    }
    body = json.dumps(response_dict, ensure_ascii=False).encode()
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

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Response
from sqlalchemy import select

from app.api.deps import MutatingOperatorDep, SessionDep
from app.api.schemas import ManualEntryRequest, TradeCloseRequest
from app.db.models import ExecutionPlan, Fill, ManualTrade, MarketSignal
from app.risk.math import CostScenario, gross_pnl, stress_downside_rate
from app.services.audit import append_audit_event, publish_outbox
from app.services.execution import remaining_trade_risk
from app.services.idempotency import IdempotencyConflict, get_cached, store_cached

router = APIRouter(prefix="/api/v1/trades", tags=["manual trades"])


def validate_close_fill_time(
    fill_time: datetime,
    *,
    entry_time: datetime,
    latest_fill_time: datetime | None = None,
) -> None:
    """Require manual close fills to preserve the recorded trade chronology."""
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

    instrument = (plan.sizing_snapshot or {}).get("instrument") or {}
    qty_step = Decimal(str(instrument.get("qty_step", "0")))
    min_qty = Decimal(str(instrument.get("min_qty", "0")))
    min_notional = Decimal(str(instrument.get("min_notional", "0")))
    if qty_step > 0:
        step_units = (payload.qty / qty_step).to_integral_value(rounding=ROUND_DOWN)
        if step_units * qty_step != payload.qty:
            raise HTTPException(
                status_code=422, detail="Entered quantity does not match the instrument qty step"
            )
    if payload.qty < min_qty or payload.qty * payload.entry_price < min_notional:
        raise HTTPException(status_code=422, detail="Actual fill is below the instrument minimum order")

    cost_data = (plan.sizing_snapshot or {}).get("costs") or {}
    actual_costs = CostScenario(
        fee_rate_round_trip=Decimal(str(cost_data.get("fee_rate_round_trip", "0"))),
        slippage_rate=Decimal(str(cost_data.get("slippage_rate", "0"))),
        stop_gap_reserve_rate=Decimal(str(cost_data.get("stop_gap_reserve_rate", "0"))),
        funding_rate=Decimal(str(cost_data.get("funding_rate", "0"))),
    )
    try:
        actual_downside = stress_downside_rate(
            payload.entry_price, signal.stop_loss, signal.direction, actual_costs
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    actual_stress_loss = payload.qty * payload.entry_price * actual_downside
    if actual_stress_loss > plan.risk_budget + Decimal("0.00000001"):
        raise HTTPException(status_code=422, detail="Actual fill would exceed the accepted risk budget")

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
            "actual_stress_loss": str(actual_stress_loss),
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

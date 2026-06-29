from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.locks import acquire_advisory_xact_lock
from app.db.models import (
    AccountEquitySnapshot,
    CapitalProfile,
    ExecutionPlan,
    InstrumentSpecHistory,
    ManualTrade,
    MarketSignal,
    PositionSnapshot,
    TickerSnapshot,
)
from app.risk.math import (
    CostScenario,
    InstrumentConstraints,
    assess_liquidation_proximity,
    calculate_position_plan,
)
from app.services.audit import append_audit_event, publish_outbox


@dataclass(frozen=True)
class AcceptanceRiskState:
    open_risk_usdt: Decimal
    effective_capital: Decimal
    available_margin: Decimal | None
    capital_verified: bool
    capital_snapshot: dict


def executable_entry_price(
    *,
    direction: str,
    bid_price: Decimal | None,
    ask_price: Decimal | None,
) -> Decimal:
    """Return the current marketable entry side; never fall back to last price."""

    if direction == "LONG":
        price = ask_price
    elif direction == "SHORT":
        price = bid_price
    else:
        raise ValueError(f"Unsupported direction for executable entry: {direction}")
    if price is None or not price.is_finite() or price <= 0:
        raise ValueError("Current executable entry price is missing or invalid")
    return price


async def latest_ticker(session: AsyncSession, symbol: str) -> TickerSnapshot | None:
    return (
        await session.execute(
            select(TickerSnapshot)
            .where(TickerSnapshot.symbol == symbol)
            .order_by(desc(TickerSnapshot.source_time))
            .limit(1)
        )
    ).scalar_one_or_none()


async def latest_spec(session: AsyncSession, symbol: str) -> InstrumentSpecHistory | None:
    return (
        await session.execute(
            select(InstrumentSpecHistory)
            .where(InstrumentSpecHistory.symbol == symbol)
            .order_by(desc(InstrumentSpecHistory.valid_from))
            .limit(1)
        )
    ).scalar_one_or_none()


async def effective_capital(
    session: AsyncSession,
    profile: CapitalProfile,
    *,
    now: datetime | None = None,
    max_snapshot_age_seconds: int = 180,
) -> tuple[Decimal, Decimal | None, bool, dict]:
    if profile.mode in {"manual", "paper"} or not profile.source_account_id:
        return (
            profile.allocated_capital,
            None,
            profile.capital_verified,
            {
                "source": profile.mode,
                "allocated": str(profile.allocated_capital),
                "verified": profile.capital_verified,
            },
        )
    snapshot = (
        await session.execute(
            select(AccountEquitySnapshot)
            .where(AccountEquitySnapshot.account_id == profile.source_account_id)
            .order_by(desc(AccountEquitySnapshot.source_time))
            .limit(1)
        )
    ).scalar_one_or_none()
    if snapshot is None:
        return Decimal("0"), Decimal("0"), False, {"source": "bybit", "missing_snapshot": True}
    current_time = now or datetime.now(UTC)
    source_time = snapshot.source_time
    if source_time.tzinfo is None or current_time.tzinfo is None:
        age_seconds: float | None = None
    else:
        age_seconds = (current_time - source_time).total_seconds()
    if (
        age_seconds is None
        or age_seconds < 0
        or age_seconds > max_snapshot_age_seconds
    ):
        return (
            Decimal("0"),
            Decimal("0"),
            False,
            {
                "source": "bybit",
                "stale_snapshot": True,
                "snapshot_time": source_time.isoformat(),
                "snapshot_age_seconds": age_seconds,
                "max_snapshot_age_seconds": max_snapshot_age_seconds,
            },
        )
    capital = min(profile.allocated_capital, snapshot.equity, snapshot.day_start_equity)
    return (
        capital,
        snapshot.available_margin,
        True,
        {
            "source": "bybit",
            "allocated": str(profile.allocated_capital),
            "equity": str(snapshot.equity),
            "day_start_equity": str(snapshot.day_start_equity),
            "snapshot_time": snapshot.source_time.isoformat(),
            "snapshot_age_seconds": age_seconds,
            "max_snapshot_age_seconds": max_snapshot_age_seconds,
        },
    )


async def open_risk_usdt(session: AsyncSession) -> Decimal:
    """Conservative risk reserved by accepted and entered plans."""
    result = await session.execute(
        select(func.coalesce(func.sum(ExecutionPlan.actual_stress_loss), 0)).where(
            ExecutionPlan.status.in_(["ACCEPTED", "ENTERED", "PARTIAL"])
        )
    )
    return Decimal(str(result.scalar_one()))


async def load_acceptance_risk_state(
    session: AsyncSession,
    *,
    profile: CapitalProfile,
    now: datetime,
    max_snapshot_age_seconds: int,
) -> AcceptanceRiskState:
    """Serialize the global risk check and read all acceptance inputs under that lock."""

    await acquire_advisory_xact_lock(session, "execution_risk_accept", "global")
    current_open_risk = await open_risk_usdt(session)
    capital, available_margin, verified, snapshot = await effective_capital(
        session,
        profile,
        now=now,
        max_snapshot_age_seconds=max_snapshot_age_seconds,
    )
    return AcceptanceRiskState(
        open_risk_usdt=current_open_risk,
        effective_capital=capital,
        available_margin=available_margin,
        capital_verified=verified,
        capital_snapshot=snapshot,
    )


async def reconciliation_issues(session: AsyncSession) -> list[str]:
    """Compare the latest read-only exchange snapshot with the manual journal."""
    account_snapshot = (
        await session.execute(
            select(AccountEquitySnapshot).order_by(desc(AccountEquitySnapshot.source_time)).limit(1)
        )
    ).scalar_one_or_none()
    if account_snapshot is None:
        return []
    exchange_positions = (
        (
            await session.execute(
                select(PositionSnapshot).where(PositionSnapshot.source_time == account_snapshot.source_time)
            )
        )
        .scalars()
        .all()
    )
    journal_rows = (
        (await session.execute(select(ManualTrade).where(ManualTrade.status.in_(["OPEN", "PARTIAL"]))))
        .scalars()
        .all()
    )
    journal = {(row.symbol, row.direction): row.remaining_qty for row in journal_rows}
    issues: list[str] = []
    for position in exchange_positions:
        direction = "LONG" if position.side in {"BUY", "LONG"} else "SHORT"
        journal_qty = journal.get((position.symbol, direction))
        if journal_qty is None:
            issues.append(f"Неизвестная биржевая позиция {position.symbol} {direction}")
            continue
        tolerance = max(Decimal("0.00000001"), position.qty * Decimal("0.02"))
        if abs(journal_qty - position.qty) > tolerance:
            issues.append(f"Расхождение количества {position.symbol} {direction}")
    return issues


async def create_execution_plan(
    session: AsyncSession,
    *,
    signal: MarketSignal,
    profile: CapitalProfile,
    settings: Settings,
    actor: str = "worker",
) -> ExecutionPlan:
    current_version = (
        await session.execute(
            select(func.coalesce(func.max(ExecutionPlan.version), 0)).where(
                ExecutionPlan.signal_id == signal.id, ExecutionPlan.profile_id == profile.id
            )
        )
    ).scalar_one()
    version = int(current_version) + 1
    ticker = await latest_ticker(session, signal.symbol)
    spec = await latest_spec(session, signal.symbol)
    now = datetime.now(UTC)

    c_eff, available_margin, verified, capital_snapshot = await effective_capital(
        session,
        profile,
        now=now,
        max_snapshot_age_seconds=settings.max_account_snapshot_age_seconds,
    )
    warnings: list[str] = list(signal.warnings or [])
    status_override: str | None = None
    if profile.mode == "bybit_read_only" and not verified:
        status_override = "BLOCKED_STALE_DATA"
        warnings.append("Снимок капитала отсутствует, устарел или имеет некорректное время")
    if profile.mode == "bybit_read_only":
        issues = await reconciliation_issues(session)
        if issues:
            status_override = "BLOCKED_PORTFOLIO"
            warnings.extend(issues)
    if ticker is None or (now - ticker.source_time).total_seconds() > settings.max_ticker_age_seconds:
        status_override = "BLOCKED_STALE_DATA"
        warnings.append("Текущая цена устарела или отсутствует")
    if spec is None:
        status_override = "BLOCKED_DATA"
        warnings.append("Спецификация инструмента отсутствует")

    if spec is None:
        constraints = InstrumentConstraints(
            qty_step=Decimal("1"),
            min_qty=Decimal("1"),
            min_notional=Decimal("1000000000"),
            max_qty=None,
            max_leverage=Decimal(settings.max_leverage),
        )
    else:
        constraints = InstrumentConstraints(
            qty_step=spec.qty_step,
            min_qty=spec.min_qty,
            min_notional=spec.min_notional,
            max_qty=spec.max_qty,
            max_leverage=min(spec.max_leverage, Decimal(profile.max_leverage)),
        )

    fee_rate = Decimal(str(signal.fee_rate_round_trip))
    costs = CostScenario(
        fee_rate_round_trip=fee_rate,
        slippage_rate=Decimal(str(signal.slippage_rate)),
        stop_gap_reserve_rate=Decimal(str(settings.stop_gap_reserve_bps / 10000)),
        funding_rate=Decimal(str(signal.funding_rate_scenario)),
    )

    turnover = ticker.turnover_24h if ticker and ticker.turnover_24h else Decimal("0")
    liquidity_cap = max(Decimal("0"), turnover * Decimal("0.0001")) if turnover else None
    open_risk = await open_risk_usdt(session)
    max_total_risk = c_eff * profile.max_total_risk_rate
    remaining_portfolio_risk = max(Decimal("0"), max_total_risk - open_risk)
    portfolio_notional_cap = (
        remaining_portfolio_risk / Decimal(str(signal.stress_downside_rate))
        if signal.stress_downside_rate > 0
        else Decimal("0")
    )

    plan_math = calculate_position_plan(
        effective_capital=c_eff,
        risk_rate=profile.risk_rate,
        entry=signal.entry_reference,
        stop=signal.stop_loss,
        take_profit=signal.take_profit_1,
        direction=signal.direction,
        costs=costs,
        constraints=constraints,
        leverage=profile.default_leverage,
        available_margin=available_margin,
        margin_reserve_rate=profile.margin_reserve_rate,
        liquidity_notional_cap=liquidity_cap,
        portfolio_notional_cap=portfolio_notional_cap,
        capital_verified=verified,
    )
    if signal.status != "PUBLISHED":
        status = "EXPIRED" if signal.status == "EXPIRED" else "SUPERSEDED"
        warnings.append("Рекомендация больше не является текущей")
    elif signal.expires_at <= now:
        status = "EXPIRED"
        warnings.append("Срок действия рекомендации истек")
    elif status_override is not None:
        status = status_override
    elif plan_math.status.startswith("BLOCKED_"):
        status = plan_math.status
    elif signal.net_rr < settings.min_net_rr or signal.net_ev_r < settings.min_net_ev_r:
        status = "NO_TRADE"
        warnings.append("Недостаточное преимущество после издержек и risk policy")
    else:
        status = plan_math.status

    liquidation_buffer = Decimal("0")
    if plan_math.status != "BLOCKED_INVALID_INPUT":
        liquidation = assess_liquidation_proximity(
            entry=signal.entry_reference,
            stop=signal.stop_loss,
            leverage=plan_math.leverage,
        )
        liquidation_buffer = liquidation.buffer_rate
        if liquidation.stop_beyond_estimated_liquidation:
            warnings.append("Стоп находится за оценочной областью ликвидации")
            status = "BLOCKED_LIQUIDATION"
        elif liquidation.narrow_buffer:
            warnings.append("Небольшой оценочный запас до области ликвидации")
            if plan_math.leverage > 3:
                status = "BLOCKED_LIQUIDATION"

    combined_warnings = warnings + [item for item in plan_math.warnings if item not in warnings]
    primary_warning = combined_warnings[0] if combined_warnings else None
    plan = ExecutionPlan(
        signal_id=signal.id,
        profile_id=profile.id,
        profile_version=profile.version,
        version=version,
        status=status,
        effective_capital=plan_math.effective_capital,
        capital_verified=verified,
        risk_rate=profile.risk_rate,
        risk_budget=plan_math.risk_budget,
        actual_stress_loss=plan_math.actual_stress_loss,
        qty_raw=plan_math.qty_raw,
        qty=plan_math.qty,
        notional=plan_math.notional,
        leverage=plan_math.leverage,
        margin_estimate=plan_math.margin_estimate,
        liquidation_buffer_rate=float(liquidation_buffer),
        limiting_cap=plan_math.limiting_cap,
        primary_warning=primary_warning,
        warnings=combined_warnings,
        sizing_snapshot={
            "capital": capital_snapshot,
            "instrument": {
                "qty_step": str(constraints.qty_step),
                "min_qty": str(constraints.min_qty),
                "min_notional": str(constraints.min_notional),
                "max_qty": str(constraints.max_qty) if constraints.max_qty is not None else None,
                "max_leverage": str(constraints.max_leverage),
            },
            "caps": {
                "liquidity_notional": str(liquidity_cap) if liquidity_cap is not None else None,
                "portfolio_notional": str(portfolio_notional_cap),
                "available_margin": str(available_margin) if available_margin is not None else None,
                "open_risk_usdt": str(open_risk),
            },
            "costs": {
                "fee_rate_round_trip": str(costs.fee_rate_round_trip),
                "slippage_rate": str(costs.slippage_rate),
                "stop_gap_reserve_rate": str(costs.stop_gap_reserve_rate),
                "funding_rate": str(costs.funding_rate),
                "funding_rate_per_settlement": str(ticker.funding_rate or Decimal("0"))
                if ticker is not None
                else "0",
                "funding_next_settlement": ticker.next_funding_time.isoformat()
                if ticker is not None and ticker.next_funding_time is not None
                else None,
                "funding_interval_minutes": spec.funding_interval_minutes if spec is not None else None,
            },
        },
    )
    session.add(plan)
    await session.flush()
    await append_audit_event(
        session,
        event_type="EXECUTION_PLAN_CREATED",
        entity_type="execution_plan",
        entity_id=str(plan.id),
        actor=actor,
        payload={
            "signal_id": str(signal.id),
            "profile_id": str(profile.id),
            "profile_version": profile.version,
            "plan_version": version,
            "status": status,
            "risk_budget": str(plan.risk_budget),
            "actual_stress_loss": str(plan.actual_stress_loss),
            "notional": str(plan.notional),
        },
    )
    await publish_outbox(
        session,
        event_type="EXECUTION_PLAN_UPDATED",
        aggregate_type="execution_plan",
        aggregate_id=str(plan.id),
        payload={"signal_id": str(signal.id), "profile_id": str(profile.id), "status": status},
    )
    return plan


async def recalculate_all_active_signals(
    session: AsyncSession, *, profile: CapitalProfile, settings: Settings, actor: str
) -> list[ExecutionPlan]:
    signals = (
        (
            await session.execute(
                select(MarketSignal).where(
                    MarketSignal.status == "PUBLISHED",
                    MarketSignal.expires_at > datetime.now(UTC),
                )
            )
        )
        .scalars()
        .all()
    )
    plans: list[ExecutionPlan] = []
    for signal in signals:
        old_plan = (
            await session.execute(
                select(ExecutionPlan)
                .where(ExecutionPlan.signal_id == signal.id, ExecutionPlan.profile_id == profile.id)
                .order_by(desc(ExecutionPlan.version))
                .limit(1)
            )
        ).scalar_one_or_none()
        new_plan = await create_execution_plan(
            session, signal=signal, profile=profile, settings=settings, actor=actor
        )
        if old_plan and old_plan.status not in {"ACCEPTED", "ENTERED", "CLOSED"}:
            old_plan.status = "SUPERSEDED"
            old_plan.superseded_by_id = new_plan.id
        plans.append(new_plan)
    return plans

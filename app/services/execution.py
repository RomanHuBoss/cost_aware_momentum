from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, desc, func, select
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
    break_even_tp_probability,
    calculate_position_plan,
    finite_decimal,
    net_outcome_rates,
    net_rr_and_ev,
    nonnegative_finite_decimal,
    positive_finite_decimal,
    positive_integer,
    pretrade_funding_return_rate,
    projected_funding_rate,
    stress_downside_rate,
)
from app.services.audit import append_audit_event, publish_outbox

IMMUTABLE_PLAN_STATUSES = frozenset({"ACCEPTED", "ENTERED", "PARTIAL", "CLOSED"})


@dataclass(frozen=True)
class AcceptanceRiskState:
    open_risk_usdt: Decimal
    effective_capital: Decimal
    available_margin: Decimal | None
    capital_verified: bool
    capital_snapshot: dict


@dataclass(frozen=True)
class AcceptancePlanValidation:
    current_notional: Decimal
    current_margin_estimate: Decimal
    current_stress_loss: Decimal
    current_funding_rate: Decimal
    current_net_rr: Decimal
    current_net_ev_r: Decimal
    per_trade_risk_limit: Decimal
    available_margin_capacity: Decimal | None


def _is_step_aligned(value: Decimal, step: Decimal) -> bool:
    return value % step == 0


def signal_prices_match_tick(
    signal: MarketSignal,
    *,
    tick_size: Decimal,
) -> bool:
    prices = (
        signal.entry_reference,
        signal.entry_low,
        signal.entry_high,
        signal.stop_loss,
        signal.take_profit_1,
    )
    try:
        step = positive_finite_decimal(tick_size, "tick_size")
        return all(
            _is_step_aligned(positive_finite_decimal(value, "signal price"), step)
            for value in prices
        )
    except (ArithmeticError, ValueError):
        return False


def validate_execution_plan_for_acceptance(
    *,
    plan: ExecutionPlan,
    signal: MarketSignal,
    profile: CapitalProfile,
    risk_state: AcceptanceRiskState,
    spec: InstrumentSpecHistory,
    executable_price: Decimal,
    current_funding_rate: Decimal,
    settings: Settings,
) -> AcceptancePlanValidation:
    """Reprice and revalidate every capital-dependent acceptance invariant.

    A plan is an immutable calculation snapshot, but acceptance can occur later
    under different equity, margin, funding and instrument constraints.  This
    function deliberately uses the fresh state and fails closed instead of
    trusting the stale sizing snapshot.
    """

    entry = positive_finite_decimal(executable_price, "current executable price")
    qty = positive_finite_decimal(plan.qty, "plan qty")
    leverage = positive_integer(plan.leverage, "plan leverage")
    capital = positive_finite_decimal(risk_state.effective_capital, "effective capital")
    risk_rate = positive_finite_decimal(profile.risk_rate, "profile risk_rate")
    reserve_rate = nonnegative_finite_decimal(
        profile.margin_reserve_rate, "margin_reserve_rate"
    )
    if reserve_rate >= 1:
        raise ValueError("Fresh available margin policy is invalid")

    qty_step = positive_finite_decimal(spec.qty_step, "qty_step")
    min_qty = positive_finite_decimal(spec.min_qty, "min_qty")
    min_notional = positive_finite_decimal(spec.min_notional, "min_notional")
    max_leverage = positive_finite_decimal(spec.max_leverage, "max_leverage")
    max_qty = (
        positive_finite_decimal(spec.max_qty, "max_qty")
        if spec.max_qty is not None
        else None
    )
    tick_size = positive_finite_decimal(spec.tick_size, "tick_size")
    current_notional = qty * entry
    allowed_leverage = min(max_leverage, Decimal(profile.max_leverage))
    if (
        qty < min_qty
        or not _is_step_aligned(qty, qty_step)
        or current_notional < min_notional
        or (max_qty is not None and qty > max_qty)
        or Decimal(leverage) > allowed_leverage
        or not _is_step_aligned(entry, tick_size)
        or not signal_prices_match_tick(signal, tick_size=tick_size)
    ):
        raise ValueError("Current instrument constraints invalidate plan sizing")

    funding_rate = finite_decimal(current_funding_rate, "current funding rate")
    snapshot = plan.sizing_snapshot if isinstance(plan.sizing_snapshot, dict) else {}
    costs_snapshot = snapshot.get("costs") if isinstance(snapshot.get("costs"), dict) else {}
    try:
        stored_funding_rate = finite_decimal(
            costs_snapshot.get("funding_rate"), "stored funding rate"
        )
    except ValueError as exc:
        raise ValueError("Stored funding cost scenario is invalid") from exc
    if pretrade_funding_return_rate(signal.direction, funding_rate) < pretrade_funding_return_rate(
        signal.direction, stored_funding_rate
    ):
        raise ValueError("Current adverse funding cost increased")

    costs = CostScenario(
        fee_rate_round_trip=nonnegative_finite_decimal(
            signal.fee_rate_round_trip, "fee_rate_round_trip"
        ),
        slippage_rate=nonnegative_finite_decimal(signal.slippage_rate, "slippage_rate"),
        stop_gap_reserve_rate=nonnegative_finite_decimal(
            Decimal(str(settings.stop_gap_reserve_bps)) / Decimal("10000"),
            "stop_gap_reserve_rate",
        ),
        funding_rate=funding_rate,
    )
    downside_rate = stress_downside_rate(entry, signal.stop_loss, signal.direction, costs)
    current_stress_loss = current_notional * downside_rate
    per_trade_risk_limit = capital * risk_rate
    if current_stress_loss > per_trade_risk_limit:
        raise ValueError("Fresh per-trade risk limit changed")

    current_margin_estimate = current_notional / Decimal(leverage)
    margin_capacity: Decimal | None = None
    if risk_state.available_margin is not None:
        available_margin = nonnegative_finite_decimal(
            risk_state.available_margin, "available_margin"
        )
        margin_capacity = available_margin * (Decimal("1") - reserve_rate)
        if current_margin_estimate > margin_capacity:
            raise ValueError("Fresh available margin is insufficient")
    elif profile.mode == "bybit_read_only":
        raise ValueError("Fresh available margin is missing")

    current_net_rr, current_net_ev_r, _, _ = net_rr_and_ev(
        entry=entry,
        stop=signal.stop_loss,
        take_profit=signal.take_profit_1,
        direction=signal.direction,
        costs=costs,
        p_tp=signal.p_tp,
        p_sl=signal.p_sl,
        p_timeout=signal.p_timeout,
    )
    if (
        current_net_rr < Decimal(str(settings.min_net_rr))
        or current_net_ev_r < Decimal(str(settings.min_net_ev_r))
    ):
        raise ValueError("Current cost-adjusted economics no longer pass policy")

    return AcceptancePlanValidation(
        current_notional=current_notional,
        current_margin_estimate=current_margin_estimate,
        current_stress_loss=current_stress_loss,
        current_funding_rate=funding_rate,
        current_net_rr=current_net_rr,
        current_net_ev_r=current_net_ev_r,
        per_trade_risk_limit=per_trade_risk_limit,
        available_margin_capacity=margin_capacity,
    )


def validated_bid_ask(
    *,
    bid_price: Decimal | None,
    ask_price: Decimal | None,
) -> tuple[Decimal, Decimal]:
    """Return a finite, positive, non-crossed top-of-book quote."""

    try:
        bid = positive_finite_decimal(bid_price, "bid_price") if bid_price is not None else None
        ask = positive_finite_decimal(ask_price, "ask_price") if ask_price is not None else None
    except ValueError as exc:
        raise ValueError(f"Current executable bid/ask quote is invalid: {exc}") from exc
    if bid is None or ask is None:
        raise ValueError("Current executable bid/ask quote is missing or invalid")
    if ask < bid:
        raise ValueError("Current executable bid/ask quote is crossed")
    return bid, ask


def executable_entry_price(
    *,
    direction: str,
    bid_price: Decimal | None,
    ask_price: Decimal | None,
) -> Decimal:
    """Return the current marketable entry side; never fall back to last price."""

    bid, ask = validated_bid_ask(bid_price=bid_price, ask_price=ask_price)
    if direction == "LONG":
        return ask
    if direction == "SHORT":
        return bid
    raise ValueError(f"Unsupported direction for executable entry: {direction}")


def funding_rate_for_plan(
    *,
    start_time: datetime,
    horizon_hours: int,
    next_settlement: datetime | None,
    interval_minutes: int | None,
    current_rate: Decimal,
) -> Decimal:
    """Reproject cumulative funding from the actual plan creation time.

    A stored market signal can be recalculated hours later. Reusing its original
    cumulative funding scenario would count already-passed settlements and omit
    newly relevant ones. Unknown interval metadata is fail-closed whenever a
    non-zero settlement is known to fall inside the plan horizon.
    """

    rate = finite_decimal(current_rate, "current_rate")
    horizon_value = positive_integer(horizon_hours, "horizon_hours")
    if start_time.tzinfo is None or start_time.utcoffset() is None:
        raise ValueError("Funding start_time must be timezone-aware")
    if next_settlement is None:
        return Decimal("0")
    if next_settlement.tzinfo is None or next_settlement.utcoffset() is None:
        raise ValueError("Funding next_settlement must be timezone-aware")
    horizon_end = start_time + timedelta(hours=horizon_value)
    if next_settlement > horizon_end or rate == 0:
        return Decimal("0")
    if interval_minutes is None:
        raise ValueError(
            "Funding interval is required when a non-zero settlement falls inside the horizon"
        )
    return projected_funding_rate(
        start_time=start_time,
        horizon_hours=horizon_value,
        next_settlement=next_settlement,
        interval_minutes=interval_minutes,
        current_rate=rate,
    )


def ticker_snapshot_is_fresh(
    source_time: datetime,
    *,
    now: datetime,
    max_age_seconds: int,
) -> bool:
    """Return true only for timezone-aware snapshots in the closed age interval [0, max]."""

    if max_age_seconds <= 0 or source_time.tzinfo is None or now.tzinfo is None:
        return False
    age_seconds = (now - source_time).total_seconds()
    return 0.0 <= age_seconds <= max_age_seconds


def entry_price_is_adverse(
    *,
    direction: str,
    reference: Decimal,
    executable: Decimal,
) -> bool:
    """Detect entry drift that increases stop distance for an already-sized plan."""

    reference_value = positive_finite_decimal(reference, "reference")
    executable_value = positive_finite_decimal(executable, "executable")
    if direction == "LONG":
        return executable_value > reference_value
    if direction == "SHORT":
        return executable_value < reference_value
    raise ValueError(f"Unsupported direction for entry drift: {direction}")


def execution_plan_entry_reference(plan: ExecutionPlan, signal: MarketSignal) -> Decimal:
    snapshot = plan.sizing_snapshot if isinstance(plan.sizing_snapshot, dict) else {}
    raw_value = snapshot.get("entry_price", signal.entry_reference)
    return positive_finite_decimal(raw_value, "plan entry reference")


async def latest_ticker(session: AsyncSession, symbol: str) -> TickerSnapshot | None:
    return (
        await session.execute(
            select(TickerSnapshot)
            .where(TickerSnapshot.symbol == symbol)
            .order_by(desc(TickerSnapshot.source_time))
            .limit(1)
        )
    ).scalar_one_or_none()


async def latest_spec(
    session: AsyncSession,
    symbol: str,
    *,
    cutoff: datetime,
) -> InstrumentSpecHistory | None:
    return (
        await session.execute(
            select(InstrumentSpecHistory)
            .where(
                InstrumentSpecHistory.symbol == symbol,
                InstrumentSpecHistory.valid_from <= cutoff,
            )
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
    if profile.mode in {"manual", "paper"}:
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
    if profile.mode != "bybit_read_only":
        return (
            Decimal("0"),
            Decimal("0"),
            False,
            {
                "source": "invalid-profile",
                "invalid_profile_mode": profile.mode,
            },
        )
    source_account_id = str(profile.source_account_id or "").strip()
    if not source_account_id:
        return (
            Decimal("0"),
            Decimal("0"),
            False,
            {
                "source": "bybit",
                "missing_source_account_id": True,
            },
        )
    snapshot = (
        await session.execute(
            select(AccountEquitySnapshot)
            .where(AccountEquitySnapshot.account_id == source_account_id)
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




def remaining_trade_risk(
    initial_stress_loss: Decimal, initial_qty: Decimal, remaining_qty: Decimal
) -> Decimal:
    """Return the open portion of actual entry risk after partial closes."""

    risk = nonnegative_finite_decimal(initial_stress_loss, "initial_stress_loss")
    qty = positive_finite_decimal(initial_qty, "initial_qty")
    remaining = nonnegative_finite_decimal(remaining_qty, "remaining_qty")
    if remaining > qty:
        raise ValueError("remaining_qty cannot exceed initial_qty")
    return risk * remaining / qty


def risk_scope_key(profile: CapitalProfile) -> str:
    """Return the serialization/risk scope for a capital profile.

    Manual and paper profiles own independent hypothetical journals. Read-only
    profiles linked to the same exchange account intentionally share one risk
    scope because their accepted plans and journal entries consume the same
    account-level capacity.
    """

    mode = str(getattr(profile, "mode", "")).strip()
    if mode == "bybit_read_only":
        account_id = str(getattr(profile, "source_account_id", "") or "").strip()
        if not account_id:
            raise ValueError("bybit_read_only profile requires source_account_id")
        return f"account:{account_id}"
    if mode in {"manual", "paper"}:
        profile_id = getattr(profile, "id", None)
        if profile_id is None:
            raise ValueError("Capital profile requires id for risk scoping")
        return f"profile:{profile_id}"
    raise ValueError(f"Unsupported capital profile mode: {mode or '<missing>'}")


def execution_plan_scope_clause(profile: CapitalProfile):
    """SQL predicate selecting plans that consume the same risk capacity."""

    mode = str(getattr(profile, "mode", "")).strip()
    if mode == "bybit_read_only":
        account_id = str(getattr(profile, "source_account_id", "") or "").strip()
        if not account_id:
            raise ValueError("bybit_read_only profile requires source_account_id")
        return and_(
            CapitalProfile.mode == "bybit_read_only",
            CapitalProfile.source_account_id == account_id,
        )
    if mode in {"manual", "paper"}:
        profile_id = getattr(profile, "id", None)
        if profile_id is None:
            raise ValueError("Capital profile requires id for risk scoping")
        return ExecutionPlan.profile_id == profile_id
    raise ValueError(f"Unsupported capital profile mode: {mode or '<missing>'}")


async def open_risk_usdt(
    session: AsyncSession,
    *,
    profile: CapitalProfile,
) -> Decimal:
    """Return risk reserved inside the profile's account/profile scope."""

    scope_clause = execution_plan_scope_clause(profile)
    accepted_result = await session.execute(
        select(func.coalesce(func.sum(ExecutionPlan.actual_stress_loss), 0))
        .join(CapitalProfile, ExecutionPlan.profile_id == CapitalProfile.id)
        .where(ExecutionPlan.status == "ACCEPTED", scope_clause)
    )
    trade_result = await session.execute(
        select(func.coalesce(func.sum(ManualTrade.remaining_stress_loss), 0))
        .join(ExecutionPlan, ManualTrade.plan_id == ExecutionPlan.id)
        .join(CapitalProfile, ExecutionPlan.profile_id == CapitalProfile.id)
        .where(ManualTrade.status.in_(["OPEN", "PARTIAL"]), scope_clause)
    )
    accepted_risk = nonnegative_finite_decimal(
        accepted_result.scalar_one(), "accepted_plan_risk"
    )
    trade_risk = nonnegative_finite_decimal(trade_result.scalar_one(), "open_trade_risk")
    return accepted_risk + trade_risk


async def load_acceptance_risk_state(
    session: AsyncSession,
    *,
    profile: CapitalProfile,
    now: datetime,
    max_snapshot_age_seconds: int,
) -> AcceptanceRiskState:
    """Serialize and read acceptance inputs inside one account/profile scope."""

    await acquire_advisory_xact_lock(
        session,
        "execution_risk_accept",
        risk_scope_key(profile),
    )
    current_open_risk = await open_risk_usdt(session, profile=profile)
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


async def reconciliation_issues(
    session: AsyncSession,
    *,
    profile: CapitalProfile,
) -> list[str]:
    """Compare one read-only account snapshot with its account-scoped journal."""

    if profile.mode in {"manual", "paper"}:
        return []
    if profile.mode != "bybit_read_only":
        return [f"Неподдерживаемый режим профиля: {profile.mode}"]
    account_id = str(profile.source_account_id or "").strip()
    if not account_id:
        return ["Для read-only профиля не задан source_account_id"]

    account_snapshot = (
        await session.execute(
            select(AccountEquitySnapshot)
            .where(AccountEquitySnapshot.account_id == account_id)
            .order_by(desc(AccountEquitySnapshot.source_time))
            .limit(1)
        )
    ).scalar_one_or_none()
    if account_snapshot is None:
        return []
    exchange_positions = (
        (
            await session.execute(
                select(PositionSnapshot).where(
                    PositionSnapshot.account_id == account_id,
                    PositionSnapshot.source_time == account_snapshot.source_time,
                )
            )
        )
        .scalars()
        .all()
    )
    journal_rows = (
        (
            await session.execute(
                select(ManualTrade)
                .join(ExecutionPlan, ManualTrade.plan_id == ExecutionPlan.id)
                .join(CapitalProfile, ExecutionPlan.profile_id == CapitalProfile.id)
                .where(
                    ManualTrade.status.in_(["OPEN", "PARTIAL"]),
                    CapitalProfile.mode == "bybit_read_only",
                    CapitalProfile.source_account_id == account_id,
                )
            )
        )
        .scalars()
        .all()
    )
    journal: dict[tuple[str, str], Decimal] = {}
    for row in journal_rows:
        key = (row.symbol, row.direction)
        journal[key] = journal.get(key, Decimal("0")) + Decimal(row.remaining_qty)

    exchange: dict[tuple[str, str], Decimal] = {}
    issues: list[str] = []
    for position in exchange_positions:
        if position.side in {"BUY", "LONG"}:
            direction = "LONG"
        elif position.side in {"SELL", "SHORT"}:
            direction = "SHORT"
        else:
            issues.append(f"Неизвестная сторона биржевой позиции {position.symbol}: {position.side}")
            continue
        key = (position.symbol, direction)
        exchange[key] = exchange.get(key, Decimal("0")) + Decimal(position.qty)

    for key in sorted(set(exchange) | set(journal)):
        symbol, direction = key
        exchange_qty = exchange.get(key)
        journal_qty = journal.get(key)
        if exchange_qty is None:
            issues.append(f"Позиция журнала отсутствует на бирже {symbol} {direction}")
            continue
        if journal_qty is None:
            issues.append(f"Неизвестная биржевая позиция {symbol} {direction}")
            continue
        tolerance = max(
            Decimal("0.00000001"),
            max(abs(exchange_qty), abs(journal_qty)) * Decimal("0.02"),
        )
        if abs(journal_qty - exchange_qty) > tolerance:
            issues.append(f"Расхождение количества {symbol} {direction}")
    return issues


async def create_execution_plan(
    session: AsyncSession,
    *,
    signal: MarketSignal,
    profile: CapitalProfile,
    settings: Settings,
    actor: str = "worker",
    entry_price: Decimal | None = None,
) -> ExecutionPlan:
    await acquire_advisory_xact_lock(
        session,
        "execution-plan-version",
        f"{signal.id}:{profile.id}",
    )
    current_version = (
        await session.execute(
            select(func.coalesce(func.max(ExecutionPlan.version), 0)).where(
                ExecutionPlan.signal_id == signal.id, ExecutionPlan.profile_id == profile.id
            )
        )
    ).scalar_one()
    version = int(current_version) + 1
    now = datetime.now(UTC)
    ticker = await latest_ticker(session, signal.symbol)
    spec = await latest_spec(session, signal.symbol, cutoff=now)
    planning_entry = positive_finite_decimal(
        entry_price if entry_price is not None else signal.entry_reference,
        "planning entry",
    )

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
        issues = await reconciliation_issues(session, profile=profile)
        if issues:
            status_override = "BLOCKED_PORTFOLIO"
            warnings.extend(issues)
    if ticker is None or not ticker_snapshot_is_fresh(
        ticker.source_time,
        now=now,
        max_age_seconds=settings.max_ticker_age_seconds,
    ):
        status_override = "BLOCKED_STALE_DATA"
        warnings.append("Текущая цена устарела или отсутствует")
    if spec is None:
        status_override = "BLOCKED_DATA"
        warnings.append("Спецификация инструмента отсутствует")
    elif not signal_prices_match_tick(signal, tick_size=spec.tick_size):
        status_override = "BLOCKED_DATA"
        warnings.append("Уровни сигнала не соответствуют текущему шагу цены инструмента")

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

    funding_rate = Decimal("0")
    if ticker is not None:
        if ticker.funding_rate is None or ticker.next_funding_time is None:
            if status_override is None:
                status_override = "BLOCKED_DATA"
            warnings.append("Снимок funding отсутствует или неполон")
        else:
            try:
                funding_rate = funding_rate_for_plan(
                    start_time=now,
                    horizon_hours=getattr(
                        signal, "horizon_hours", settings.default_horizon_hours
                    ),
                    next_settlement=ticker.next_funding_time,
                    interval_minutes=(
                        spec.funding_interval_minutes if spec is not None else None
                    ),
                    current_rate=ticker.funding_rate,
                )
            except ValueError as exc:
                if status_override is None:
                    status_override = "BLOCKED_DATA"
                warnings.append(f"Невозможно пересчитать funding для плана: {exc}")

    fee_rate = Decimal(str(signal.fee_rate_round_trip))
    costs = CostScenario(
        fee_rate_round_trip=fee_rate,
        slippage_rate=Decimal(str(signal.slippage_rate)),
        stop_gap_reserve_rate=Decimal(str(settings.stop_gap_reserve_bps / 10000)),
        funding_rate=funding_rate,
    )

    turnover = ticker.turnover_24h if ticker and ticker.turnover_24h else Decimal("0")
    liquidity_cap = max(Decimal("0"), turnover * Decimal("0.0001")) if turnover else None
    open_risk = await open_risk_usdt(session, profile=profile)
    max_total_risk = c_eff * profile.max_total_risk_rate
    remaining_portfolio_risk = max(Decimal("0"), max_total_risk - open_risk)
    try:
        planning_downside_rate = stress_downside_rate(
            planning_entry,
            signal.stop_loss,
            signal.direction,
            costs,
        )
    except ValueError:
        planning_downside_rate = Decimal("0")
    portfolio_notional_cap = (
        remaining_portfolio_risk / planning_downside_rate
        if planning_downside_rate > 0
        else Decimal("0")
    )

    plan_math = calculate_position_plan(
        effective_capital=c_eff,
        risk_rate=profile.risk_rate,
        entry=planning_entry,
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
    plan_upside_rate: Decimal | None = None
    plan_timeout_net_rate: Decimal | None = None
    plan_break_even_tp_probability: Decimal | None = None
    try:
        plan_net_rr, plan_net_ev_r, _, _ = net_rr_and_ev(
            entry=planning_entry,
            stop=signal.stop_loss,
            take_profit=signal.take_profit_1,
            direction=signal.direction,
            costs=costs,
            p_tp=signal.p_tp,
            p_sl=signal.p_sl,
            p_timeout=signal.p_timeout,
        )
        plan_outcomes = net_outcome_rates(
            entry=planning_entry,
            stop=signal.stop_loss,
            take_profit=signal.take_profit_1,
            direction=signal.direction,
            costs=costs,
        )
        plan_upside_rate = plan_outcomes.upside_rate
        plan_timeout_net_rate = plan_outcomes.timeout_net_rate
        plan_break_even_tp_probability = break_even_tp_probability(
            downside_rate=plan_outcomes.downside_rate,
            upside_rate=plan_outcomes.upside_rate,
            timeout_net_rate=plan_outcomes.timeout_net_rate,
            p_timeout=signal.p_timeout,
        )
    except ValueError as exc:
        plan_net_rr = Decimal("0")
        plan_net_ev_r = Decimal("0")
        warnings.append(f"Некорректная геометрия плана: {exc}")
        status_override = "BLOCKED_INVALID_INPUT"

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
    elif plan_net_rr < Decimal(str(settings.min_net_rr)) or plan_net_ev_r < Decimal(str(settings.min_net_ev_r)):
        status = "NO_TRADE"
        warnings.append("Недостаточное преимущество после издержек и risk policy")
    else:
        status = plan_math.status

    liquidation_buffer = Decimal("0")
    if plan_math.status != "BLOCKED_INVALID_INPUT":
        liquidation = assess_liquidation_proximity(
            entry=planning_entry,
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
            "entry_price": str(planning_entry),
            "planning_time": now.isoformat(),
            "economics_schema_version": "tp-sl-timeout-v1",
            "net_rr": str(plan_net_rr),
            "net_ev_r": str(plan_net_ev_r),
            "stress_downside_rate": str(plan_math.stress_downside_rate),
            "upside_rate": str(plan_upside_rate) if plan_upside_rate is not None else None,
            "timeout_net_rate": (
                str(plan_timeout_net_rate) if plan_timeout_net_rate is not None else None
            ),
            "break_even_tp_probability": (
                str(plan_break_even_tp_probability)
                if plan_break_even_tp_probability is not None
                else None
            ),
            "break_even_probability_semantics": (
                "P_SL=1-P_TP-P_TIMEOUT; P_TIMEOUT fixed"
            ),
            "capital": capital_snapshot,
            "instrument": {
                "tick_size": str(spec.tick_size) if spec is not None else None,
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
                "signal_funding_rate_scenario": str(signal.funding_rate_scenario),
                "funding_projection_start": now.isoformat(),
                "funding_rate_per_settlement": (
                    str(ticker.funding_rate)
                    if ticker is not None and ticker.funding_rate is not None
                    else None
                ),
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
        if old_plan and old_plan.status in IMMUTABLE_PLAN_STATUSES:
            continue
        new_plan = await create_execution_plan(
            session, signal=signal, profile=profile, settings=settings, actor=actor
        )
        if old_plan:
            old_plan.status = "SUPERSEDED"
            old_plan.superseded_by_id = new_plan.id
        plans.append(new_plan)
    return plans

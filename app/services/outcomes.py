from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, DecimalException
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.locks import acquire_advisory_xact_lock
from app.db.models import Candle, ExecutionPlan, MarketSignal, PlanOutcome, SignalOutcome
from app.risk.math import (
    finite_decimal,
    funding_cash_flow,
    gross_pnl,
    nonnegative_finite_decimal,
    positive_finite_decimal,
    validate_directional_geometry,
)
from app.services.audit import append_audit_event, publish_outbox
from app.services.market_data import CandleWindow
from app.services.plan_snapshots import (
    plan_entry_price,
    plan_planning_time,
    plan_trading_costs,
)

Direction = Literal["LONG", "SHORT"]
Outcome = Literal["TP", "SL", "TIMEOUT"]
EVALUATION_VERSION = "primary-barrier-intrabar-open-gap-v4"


@dataclass(frozen=True)
class OutcomeBar:
    candle_id: int
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class BarrierEvaluation:
    outcome: Outcome
    exit_price: Decimal
    exit_time: datetime
    source_candle_id: int
    bars_evaluated: int
    ambiguous: bool
    resolution_interval: str = "60"
    intrabar_bars_evaluated: int = 0
    hourly_ambiguous: bool = False


@dataclass(frozen=True)
class PlanOutcomeEstimate:
    valuation_status: Literal[
        "VALUED",
        "NOT_SIZED",
        "FUNDING_UNAVAILABLE",
        "PATH_UNAVAILABLE",
        "INVALID_INPUT",
    ]
    gross_pnl: Decimal
    estimated_trading_costs: Decimal
    estimated_funding_cash_flow: Decimal
    estimated_net_pnl: Decimal
    counterfactual_r: Decimal | None
    validation_error: str | None = None


def _invalid_plan_estimate(reason: str) -> PlanOutcomeEstimate:
    return PlanOutcomeEstimate(
        valuation_status="INVALID_INPUT",
        gross_pnl=Decimal("0"),
        estimated_trading_costs=Decimal("0"),
        estimated_funding_cash_flow=Decimal("0"),
        estimated_net_pnl=Decimal("0"),
        counterfactual_r=None,
        validation_error=reason,
    )


def _path_unavailable_plan_estimate(reason: str) -> PlanOutcomeEstimate:
    return PlanOutcomeEstimate(
        valuation_status="PATH_UNAVAILABLE",
        gross_pnl=Decimal("0"),
        estimated_trading_costs=Decimal("0"),
        estimated_funding_cash_flow=Decimal("0"),
        estimated_net_pnl=Decimal("0"),
        counterfactual_r=None,
        validation_error=reason,
    )


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def evaluate_barrier_outcome(
    bars: list[OutcomeBar],
    *,
    direction: Direction,
    entry: Decimal,
    stop: Decimal,
    take_profit: Decimal,
    window_start: datetime,
    horizon_end: datetime,
    expected_interval: timedelta = timedelta(hours=1),
) -> BarrierEvaluation | None:
    """Resolve the primary TP/SL/TIMEOUT outcome from confirmed hourly bars.

    The evaluator matches the model-label contract: the bar open is resolved first,
    TP1 is the primary take-profit barrier, and a later same-bar TP/SL touch is
    resolved conservatively as SL. TIMEOUT is emitted only when the confirmed candle
    ending exactly at ``horizon_end`` is present; incomplete history remains
    unresolved instead of fabricating an exit.
    """

    _require_aware(window_start, "window_start")
    _require_aware(horizon_end, "horizon_end")
    if horizon_end <= window_start:
        raise ValueError("horizon_end must be later than window_start")
    if expected_interval <= timedelta(0):
        raise ValueError("expected_interval must be positive")
    entry = Decimal(entry)
    stop = Decimal(stop)
    take_profit = Decimal(take_profit)
    validate_directional_geometry(
        direction=direction,
        entry=entry,
        stop=stop,
        take_profit=take_profit,
    )

    ordered = sorted(bars, key=lambda item: (item.open_time, item.close_time, item.candle_id))
    previous_close: datetime = window_start
    for index, item in enumerate(ordered, start=1):
        _require_aware(item.open_time, "bar.open_time")
        _require_aware(item.close_time, "bar.close_time")
        if item.close_time <= item.open_time:
            raise ValueError("Outcome bar close_time must be later than open_time")
        if item.close_time - item.open_time != expected_interval:
            raise ValueError("Outcome bar duration does not match expected interval")
        if item.open_time < previous_close:
            raise ValueError("Outcome bars overlap or are out of order")
        if item.open_time != previous_close:
            return None
        previous_close = item.close_time
        if item.close_time > horizon_end:
            break
        if (
            item.open <= 0
            or item.high <= 0
            or item.low <= 0
            or item.close <= 0
            or item.high < item.low
            or not item.low <= item.open <= item.high
            or not item.low <= item.close <= item.high
        ):
            raise ValueError("Outcome bar contains invalid OHLC prices")

        if direction == "LONG":
            if item.open <= stop:
                return BarrierEvaluation(
                    outcome="SL",
                    exit_price=item.open,
                    exit_time=item.open_time,
                    source_candle_id=item.candle_id,
                    bars_evaluated=index,
                    ambiguous=False,
                )
            if item.open >= take_profit:
                return BarrierEvaluation(
                    outcome="TP",
                    exit_price=take_profit,
                    exit_time=item.open_time,
                    source_candle_id=item.candle_id,
                    bars_evaluated=index,
                    ambiguous=False,
                )
            tp_hit = item.high >= take_profit
            sl_hit = item.low <= stop
        else:
            if item.open >= stop:
                return BarrierEvaluation(
                    outcome="SL",
                    exit_price=item.open,
                    exit_time=item.open_time,
                    source_candle_id=item.candle_id,
                    bars_evaluated=index,
                    ambiguous=False,
                )
            if item.open <= take_profit:
                return BarrierEvaluation(
                    outcome="TP",
                    exit_price=take_profit,
                    exit_time=item.open_time,
                    source_candle_id=item.candle_id,
                    bars_evaluated=index,
                    ambiguous=False,
                )
            tp_hit = item.low <= take_profit
            sl_hit = item.high >= stop

        if tp_hit and sl_hit:
            return BarrierEvaluation(
                outcome="SL",
                exit_price=stop,
                exit_time=item.close_time,
                source_candle_id=item.candle_id,
                bars_evaluated=index,
                ambiguous=True,
            )
        if tp_hit:
            return BarrierEvaluation(
                outcome="TP",
                exit_price=take_profit,
                exit_time=item.close_time,
                source_candle_id=item.candle_id,
                bars_evaluated=index,
                ambiguous=False,
            )
        if sl_hit:
            return BarrierEvaluation(
                outcome="SL",
                exit_price=stop,
                exit_time=item.close_time,
                source_candle_id=item.candle_id,
                bars_evaluated=index,
                ambiguous=False,
            )

    completed = [item for item in ordered if item.close_time == horizon_end]
    if not completed:
        return None
    final = completed[-1]
    return BarrierEvaluation(
        outcome="TIMEOUT",
        exit_price=final.close,
        exit_time=horizon_end,
        source_candle_id=final.candle_id,
        bars_evaluated=ordered.index(final) + 1,
        ambiguous=False,
    )


def evaluate_barrier_outcome_with_intrabar(
    hourly_bars: list[OutcomeBar],
    intrabar_bars: list[OutcomeBar],
    *,
    direction: Direction,
    entry: Decimal,
    stop: Decimal,
    take_profit: Decimal,
    window_start: datetime,
    horizon_end: datetime,
    intrabar_interval_minutes: int,
) -> BarrierEvaluation | None:
    """Resolve an hourly same-bar ambiguity from a complete finer-grained path.

    Non-ambiguous hourly outcomes retain their existing behavior.  When an hourly
    candle touches both TP and SL, the finer path must cover that entire hour with
    contiguous confirmed bars.  Missing data keeps the outcome pending.  If TP and
    SL still occur inside the same finest available bar, the established
    conservative SL rule remains in force.
    """

    if intrabar_interval_minutes <= 0 or 60 % intrabar_interval_minutes != 0:
        raise ValueError("intrabar_interval_minutes must be a positive divisor of 60")
    hourly = evaluate_barrier_outcome(
        hourly_bars,
        direction=direction,
        entry=entry,
        stop=stop,
        take_profit=take_profit,
        window_start=window_start,
        horizon_end=horizon_end,
    )
    if hourly is None or not hourly.ambiguous:
        return hourly

    source_hour = next(
        (item for item in hourly_bars if item.candle_id == hourly.source_candle_id),
        None,
    )
    if source_hour is None:
        raise ValueError("Hourly ambiguity source candle is missing")

    interval = timedelta(minutes=intrabar_interval_minutes)
    ordered = sorted(intrabar_bars, key=lambda item: (item.open_time, item.close_time, item.candle_id))
    previous_close = source_hour.open_time
    selected: list[OutcomeBar] = []
    for item in ordered:
        _require_aware(item.open_time, "intrabar.open_time")
        _require_aware(item.close_time, "intrabar.close_time")
        if item.open_time < source_hour.open_time or item.close_time > source_hour.close_time:
            continue
        if item.close_time - item.open_time != interval:
            raise ValueError("Intrabar duration does not match configured interval")
        if item.open_time != previous_close:
            return None
        selected.append(item)
        previous_close = item.close_time
    if previous_close != source_hour.close_time:
        return None

    intrabar = evaluate_barrier_outcome(
        selected,
        direction=direction,
        entry=entry,
        stop=stop,
        take_profit=take_profit,
        window_start=source_hour.open_time,
        horizon_end=source_hour.close_time,
        expected_interval=interval,
    )
    if intrabar is None:
        return None
    if intrabar.outcome == "TIMEOUT":
        raise ValueError("Complete intrabar path contradicts hourly TP/SL ambiguity")
    return BarrierEvaluation(
        outcome=intrabar.outcome,
        exit_price=intrabar.exit_price,
        exit_time=intrabar.exit_time,
        source_candle_id=intrabar.source_candle_id,
        bars_evaluated=hourly.bars_evaluated,
        ambiguous=intrabar.ambiguous,
        resolution_interval=str(intrabar_interval_minutes),
        intrabar_bars_evaluated=intrabar.bars_evaluated,
        hourly_ambiguous=True,
    )


def estimate_plan_outcome(
    *,
    direction: Direction,
    outcome: Outcome,
    qty: Decimal,
    entry_price: Decimal,
    exit_price: Decimal,
    actual_stress_loss: Decimal,
    fee_rate_round_trip: Decimal,
    slippage_rate: Decimal,
    stop_gap_reserve_rate: Decimal,
    funding_rate: Decimal,
    funding_complete: bool = True,
    stop_price: Decimal | None = None,
) -> PlanOutcomeEstimate:
    """Estimate a counterfactual plan result from its immutable sizing snapshot.

    This is an evaluation estimate, not actual execution P&L. It uses the plan's
    stored fee/slippage/funding assumptions. For an SL outcome, a supplied modeled
    stop lets the evaluator charge only the part of the reserve not already embedded
    in a worse gap exit. An unsized plan receives the market outcome but no fake R.
    Invalid numeric plan inputs are persisted as a zero-valued fail-closed result
    instead of emitting NaN/Infinity or aborting the whole outcome job.
    """

    if direction not in {"LONG", "SHORT"}:
        raise ValueError(f"Unsupported direction: {direction}")
    if outcome not in {"TP", "SL", "TIMEOUT"}:
        raise ValueError(f"Unsupported outcome: {outcome}")

    try:
        qty = nonnegative_finite_decimal(qty, "qty")
        entry_price = positive_finite_decimal(entry_price, "entry_price")
        exit_price = positive_finite_decimal(exit_price, "exit_price")
        actual_stress_loss = nonnegative_finite_decimal(
            actual_stress_loss, "actual_stress_loss"
        )
        fee_rate_round_trip = nonnegative_finite_decimal(
            fee_rate_round_trip, "fee_rate_round_trip"
        )
        slippage_rate = nonnegative_finite_decimal(slippage_rate, "slippage_rate")
        stop_gap_reserve_rate = nonnegative_finite_decimal(
            stop_gap_reserve_rate, "stop_gap_reserve_rate"
        )
        funding_rate = finite_decimal(funding_rate, "funding_rate")
        if stop_price is not None:
            stop_price = positive_finite_decimal(stop_price, "stop_price")
    except ValueError as exc:
        return _invalid_plan_estimate(str(exc))

    if qty == 0:
        return PlanOutcomeEstimate(
            valuation_status="NOT_SIZED",
            gross_pnl=Decimal("0"),
            estimated_trading_costs=Decimal("0"),
            estimated_funding_cash_flow=Decimal("0"),
            estimated_net_pnl=Decimal("0"),
            counterfactual_r=None,
        )

    try:
        entry_notional = qty * entry_price
        exit_notional = qty * exit_price
        gross = gross_pnl(direction, qty, entry_price, exit_price)
        # The stored round-trip rate is two equal taker legs in the current plan
        # contract. Charge each leg against its own executed notional.
        fee_rate_per_leg = fee_rate_round_trip / Decimal("2")
        trading_costs = (entry_notional + exit_notional) * fee_rate_per_leg
        trading_costs += entry_notional * slippage_rate
        if outcome == "SL":
            applied_gap_reserve_rate = stop_gap_reserve_rate
            if stop_price is not None:
                if direction == "LONG":
                    if stop_price >= entry_price:
                        raise ValueError("LONG stop_price must be below entry_price")
                    if exit_price > stop_price:
                        raise ValueError("LONG SL exit_price must not be above stop_price")
                else:
                    if stop_price <= entry_price:
                        raise ValueError("SHORT stop_price must be above entry_price")
                    if exit_price < stop_price:
                        raise ValueError("SHORT SL exit_price must not be below stop_price")
                barrier_downside_rate = abs(entry_price - stop_price) / entry_price
                realized_gross_rate = gross / entry_notional
                embedded_gap_rate = max(
                    Decimal("0"),
                    -realized_gross_rate - barrier_downside_rate,
                )
                applied_gap_reserve_rate = max(
                    Decimal("0"),
                    stop_gap_reserve_rate - embedded_gap_rate,
                )
            trading_costs += entry_notional * applied_gap_reserve_rate
        funding = funding_cash_flow(direction, entry_notional, funding_rate)
        net = gross - trading_costs + funding
        counterfactual_r = (
            net / actual_stress_loss if funding_complete and actual_stress_loss > 0 else None
        )
        for name, value in (
            ("gross_pnl", gross),
            ("estimated_trading_costs", trading_costs),
            ("estimated_funding_cash_flow", funding),
            ("estimated_net_pnl", net),
        ):
            finite_decimal(value, name)
        if counterfactual_r is not None:
            finite_decimal(counterfactual_r, "counterfactual_r")
    except (DecimalException, ValueError) as exc:
        return _invalid_plan_estimate(f"plan outcome arithmetic failed: {exc}")

    return PlanOutcomeEstimate(
        valuation_status="VALUED" if funding_complete else "FUNDING_UNAVAILABLE",
        gross_pnl=gross,
        estimated_trading_costs=trading_costs,
        estimated_funding_cash_flow=funding,
        estimated_net_pnl=net,
        counterfactual_r=counterfactual_r,
    )


def _funding_rate_for_holding_period(
    plan: ExecutionPlan, *, start_time: datetime, exit_time: datetime
) -> tuple[Decimal, bool, dict[str, object]]:
    """Return only settlements crossed by the hypothetical holding period.

    Legacy plans without a complete timeline remain explicitly incomplete. A
    malformed timeline is invalid input and must not silently turn into a numeric
    funding result. Settlement counts are computed arithmetically to avoid long
    loops on corrupted historical timestamps.
    """

    _require_aware(start_time, "start_time")
    _require_aware(exit_time, "exit_time")
    if exit_time < start_time:
        raise ValueError("exit_time must not be earlier than start_time")

    costs = (plan.sizing_snapshot or {}).get("costs") or {}
    required = {
        "funding_rate_per_settlement",
        "funding_next_settlement",
        "funding_interval_minutes",
    }
    if not required.issubset(costs):
        return Decimal("0"), False, {"source": "legacy_plan_snapshot", "settlements": 0}

    raw_rate = costs.get("funding_rate_per_settlement")
    raw_next = costs.get("funding_next_settlement")
    raw_interval = costs.get("funding_interval_minutes")
    if raw_rate is None or raw_next is None or raw_interval is None:
        return Decimal("0"), False, {
            "source": "plan_snapshot_incomplete",
            "settlements": 0,
            "missing": [
                name
                for name, value in (
                    ("funding_rate_per_settlement", raw_rate),
                    ("funding_next_settlement", raw_next),
                    ("funding_interval_minutes", raw_interval),
                )
                if value is None
            ],
        }
    per_settlement = finite_decimal(
        raw_rate,
        "funding_rate_per_settlement",
    )

    try:
        next_settlement = datetime.fromisoformat(str(raw_next).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("funding_next_settlement must be a valid ISO timestamp") from exc
    _require_aware(next_settlement, "funding_next_settlement")
    try:
        interval_minutes = int(raw_interval)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("funding_interval_minutes must be an integer") from exc
    if interval_minutes <= 0:
        raise ValueError("funding_interval_minutes must be positive")
    try:
        interval = timedelta(minutes=interval_minutes)
    except OverflowError as exc:
        raise ValueError("funding_interval_minutes is too large") from exc

    if next_settlement <= start_time:
        elapsed = start_time - next_settlement
        steps = int(elapsed // interval) + 1
        next_settlement += interval * steps

    settlements = 0
    if next_settlement <= exit_time:
        settlements = 1 + int((exit_time - next_settlement) // interval)
    return (
        per_settlement * settlements,
        True,
        {
            "source": "plan_snapshot",
            "settlements": settlements,
            "rate_per_settlement": str(per_settlement),
            "next_settlement": next_settlement.isoformat(),
            "interval_minutes": interval_minutes,
        },
    )




def _plan_valuation_inputs(
    plan: ExecutionPlan, signal: MarketSignal
) -> tuple[Decimal, datetime, str]:
    del signal
    snapshot = plan.sizing_snapshot
    entry_price = plan_entry_price(snapshot)
    valuation_start = plan_planning_time(snapshot)
    return entry_price, valuation_start, "execution_plan.sizing_snapshot"


async def _record_plan_outcome(
    session: AsyncSession,
    *,
    signal: MarketSignal,
    signal_outcome: SignalOutcome,
    plan: ExecutionPlan,
    actor: str,
) -> PlanOutcome:
    # The resolved price path begins at the signal event. A plan can be monetarily
    # valued only when its immutable planning anchor is identical to that event.
    # Reusing earlier price action for a later plan would introduce look-ahead and
    # can attribute a barrier hit that happened before the plan existed.
    exit_price = positive_finite_decimal(signal_outcome.exit_price, "signal_outcome.exit_price")

    try:
        _require_aware(signal.event_time, "signal.event_time")
        _require_aware(signal_outcome.exit_time, "signal_outcome.exit_time")
        validated_qty = nonnegative_finite_decimal(plan.qty, "qty")
        validated_stress_loss = nonnegative_finite_decimal(
            plan.actual_stress_loss, "actual_stress_loss"
        )
        entry_price, valuation_start, valuation_source = _plan_valuation_inputs(plan, signal)
        snapshot_costs = plan_trading_costs(plan.sizing_snapshot)
        fee_rate_round_trip = snapshot_costs.fee_rate_round_trip
        slippage_rate = snapshot_costs.slippage_rate
        stop_gap_reserve_rate = snapshot_costs.stop_gap_reserve_rate
        if valuation_start < signal.event_time:
            raise ValueError("plan.planning_time must not precede signal.event_time")
        if valuation_start > signal.event_time:
            reason = (
                "price path is unavailable from plan.planning_time; "
                "the stored signal outcome starts at signal.event_time"
            )
            funding_rate = Decimal("0")
            funding_details = {
                "source": "path_unavailable",
                "settlements": 0,
                "validation_error": reason,
            }
            estimate = _path_unavailable_plan_estimate(reason)
        else:
            funding_rate, funding_complete, funding_details = _funding_rate_for_holding_period(
                plan, start_time=valuation_start, exit_time=signal_outcome.exit_time
            )
            estimate = estimate_plan_outcome(
                direction=signal.direction,
                outcome=signal_outcome.outcome,
                qty=validated_qty,
                entry_price=entry_price,
                exit_price=exit_price,
                actual_stress_loss=validated_stress_loss,
                fee_rate_round_trip=fee_rate_round_trip,
                slippage_rate=slippage_rate,
                stop_gap_reserve_rate=stop_gap_reserve_rate,
                funding_rate=funding_rate,
                funding_complete=funding_complete,
                stop_price=signal.stop_loss,
            )
    except (DecimalException, TypeError, ValueError, OverflowError) as exc:
        entry_price = positive_finite_decimal(signal.entry_reference, "signal.entry_reference")
        valuation_start = signal.event_time
        valuation_source = "invalid_plan_snapshot_fallback"
        funding_rate = Decimal("0")
        funding_details = {
            "source": "invalid_plan_snapshot",
            "settlements": 0,
            "validation_error": str(exc),
        }
        estimate = _invalid_plan_estimate(str(exc))
        fee_rate_round_trip = slippage_rate = stop_gap_reserve_rate = Decimal("0")

    invalid_input = estimate.valuation_status == "INVALID_INPUT"
    if invalid_input:
        stored_qty = Decimal("0")
        cost_assumptions = {
            "source": "execution_plan.sizing_snapshot.costs",
            "actual_execution_pnl": False,
            "validation_error": estimate.validation_error,
            "funding": funding_details,
            "valuation_start_time": valuation_start.isoformat(),
            "valuation_source": valuation_source,
        }
    else:
        stored_qty = validated_qty
        cost_assumptions = {
            "fee_rate_round_trip": str(fee_rate_round_trip),
            "slippage_rate": str(slippage_rate),
            "stop_gap_reserve_rate": str(stop_gap_reserve_rate),
            "stop_gap_reserve_accounting": "residual_after_realized_gap_v1",
            "stop_price": str(signal.stop_loss),
            "funding_rate": str(funding_rate),
            "funding": funding_details,
            "fee_valuation": "equal_rate_per_leg_on_entry_and_exit_notional",
            "source": "execution_plan.sizing_snapshot.costs",
            "actual_execution_pnl": False,
            "valuation_start_time": valuation_start.isoformat(),
            "valuation_source": valuation_source,
            "price_path_source": (
                "unavailable_after_signal_anchor"
                if estimate.valuation_status == "PATH_UNAVAILABLE"
                else "signal_outcome_from_signal_event_time"
            ),
        }
        if estimate.validation_error is not None:
            cost_assumptions["validation_error"] = estimate.validation_error

    row = PlanOutcome(
        signal_outcome_id=signal_outcome.id,
        plan_id=plan.id,
        plan_version=plan.version,
        outcome=signal_outcome.outcome,
        valuation_status=estimate.valuation_status,
        qty=stored_qty,
        entry_price=entry_price,
        exit_price=exit_price,
        gross_pnl=estimate.gross_pnl,
        estimated_trading_costs=estimate.estimated_trading_costs,
        estimated_funding_cash_flow=estimate.estimated_funding_cash_flow,
        estimated_net_pnl=estimate.estimated_net_pnl,
        counterfactual_r=estimate.counterfactual_r,
        cost_assumptions=cost_assumptions,
        resolved_at=datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    await append_audit_event(
        session,
        event_type="COUNTERFACTUAL_PLAN_OUTCOME_RECORDED",
        entity_type="plan_outcome",
        entity_id=str(row.id),
        actor=actor,
        payload={
            "signal_id": str(signal.id),
            "plan_id": str(plan.id),
            "plan_version": plan.version,
            "outcome": row.outcome,
            "valuation_status": row.valuation_status,
            "estimated_net_pnl": str(row.estimated_net_pnl),
            "counterfactual_r": (
                str(row.counterfactual_r) if row.counterfactual_r is not None else None
            ),
            "validation_error": estimate.validation_error,
        },
    )
    return row


async def find_ambiguous_intrabar_windows(
    session: AsyncSession,
    *,
    market_cutoff: datetime,
    available_cutoff: datetime | None = None,
    batch_size: int = 1000,
    max_windows: int = 100,
) -> list[CandleWindow]:
    """Identify exact hourly windows that require finer-grained reconstruction."""

    _require_aware(market_cutoff, "market_cutoff")
    available_cutoff = available_cutoff or datetime.now(UTC)
    _require_aware(available_cutoff, "available_cutoff")
    if batch_size <= 0 or max_windows <= 0:
        raise ValueError("batch_size and max_windows must be positive")

    candidates = (
        (
            await session.execute(
                select(MarketSignal)
                .outerjoin(SignalOutcome, SignalOutcome.signal_id == MarketSignal.id)
                .where(
                    SignalOutcome.id.is_(None),
                    MarketSignal.event_time < market_cutoff,
                )
                .order_by(MarketSignal.event_time, MarketSignal.id)
                .limit(batch_size)
            )
        )
        .scalars()
        .all()
    )
    unique: dict[tuple[str, datetime, datetime], CandleWindow] = {}
    for signal in candidates:
        horizon_end = signal.event_time + timedelta(hours=signal.horizon_hours)
        candle_cutoff = min(horizon_end, market_cutoff)
        candle_rows = (
            (
                await session.execute(
                    select(Candle)
                    .where(
                        Candle.symbol == signal.symbol,
                        Candle.interval == "60",
                        Candle.price_type == "last",
                        Candle.confirmed.is_(True),
                        Candle.open_time >= signal.event_time,
                        Candle.close_time <= candle_cutoff,
                        Candle.available_at <= available_cutoff,
                    )
                    .order_by(Candle.open_time, Candle.id)
                )
            )
            .scalars()
            .all()
        )
        bars = [
            OutcomeBar(
                candle_id=row.id,
                open_time=row.open_time,
                close_time=row.close_time,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
            )
            for row in candle_rows
        ]
        try:
            evaluation = evaluate_barrier_outcome(
                bars,
                direction=signal.direction,
                entry=signal.entry_reference,
                stop=signal.stop_loss,
                take_profit=signal.take_profit_1,
                window_start=signal.event_time,
                horizon_end=horizon_end,
            )
        except ValueError:
            continue
        if evaluation is None or not evaluation.ambiguous:
            continue
        source = next((row for row in candle_rows if row.id == evaluation.source_candle_id), None)
        if source is None:
            continue
        key = (signal.symbol, source.open_time, source.close_time)
        unique[key] = CandleWindow(
            symbol=signal.symbol,
            start_time=source.open_time,
            end_time=source.close_time,
        )
        if len(unique) >= max_windows:
            break
    return list(unique.values())


async def resolve_counterfactual_outcomes(
    session: AsyncSession,
    *,
    market_cutoff: datetime,
    available_cutoff: datetime | None = None,
    batch_size: int = 1000,
    intrabar_interval: str = "5",
    actor: str = "worker",
) -> dict:
    """Resolve mature signal outcomes and backfill every execution-plan version.

    Only confirmed last-price hourly candles available by ``available_cutoff`` are
    eligible.  Missing horizon data remains pending.  Signal and plan rows are
    append-only and protected by natural uniqueness plus a per-signal transaction
    advisory lock.
    """

    _require_aware(market_cutoff, "market_cutoff")
    available_cutoff = available_cutoff or datetime.now(UTC)
    _require_aware(available_cutoff, "available_cutoff")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    intrabar_interval_minutes = int(intrabar_interval)
    if intrabar_interval_minutes <= 0 or 60 % intrabar_interval_minutes != 0:
        raise ValueError("intrabar_interval must be a positive divisor of 60")

    candidates = (
        (
            await session.execute(
                select(MarketSignal)
                .outerjoin(SignalOutcome, SignalOutcome.signal_id == MarketSignal.id)
                .where(
                    SignalOutcome.id.is_(None),
                    MarketSignal.event_time < market_cutoff,
                )
                .order_by(MarketSignal.event_time, MarketSignal.id)
                .limit(batch_size)
            )
        )
        .scalars()
        .all()
    )
    resolved_count = 0
    pending_count = 0
    invalid: list[dict[str, str]] = []

    for signal in candidates:
        await acquire_advisory_xact_lock(session, "counterfactual_outcome", str(signal.id))
        existing = (
            await session.execute(select(SignalOutcome).where(SignalOutcome.signal_id == signal.id))
        ).scalar_one_or_none()
        if existing is not None:
            continue
        horizon_end = signal.event_time + timedelta(hours=signal.horizon_hours)
        candle_cutoff = min(horizon_end, market_cutoff)
        candle_rows = (
            (
                await session.execute(
                    select(Candle)
                    .where(
                        Candle.symbol == signal.symbol,
                        Candle.interval == "60",
                        Candle.price_type == "last",
                        Candle.confirmed.is_(True),
                        Candle.open_time >= signal.event_time,
                        Candle.close_time <= candle_cutoff,
                        Candle.available_at <= available_cutoff,
                    )
                    .order_by(Candle.open_time, Candle.id)
                )
            )
            .scalars()
            .all()
        )
        bars = [
            OutcomeBar(
                candle_id=row.id,
                open_time=row.open_time,
                close_time=row.close_time,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
            )
            for row in candle_rows
        ]
        try:
            hourly_evaluation = evaluate_barrier_outcome(
                bars,
                direction=signal.direction,
                entry=signal.entry_reference,
                stop=signal.stop_loss,
                take_profit=signal.take_profit_1,
                window_start=signal.event_time,
                horizon_end=horizon_end,
            )
            evaluation = hourly_evaluation
            if hourly_evaluation is not None and hourly_evaluation.ambiguous:
                source_hour = next(
                    (row for row in candle_rows if row.id == hourly_evaluation.source_candle_id),
                    None,
                )
                if source_hour is None:
                    raise ValueError("Hourly ambiguity source candle is missing")
                intrabar_rows = (
                    (
                        await session.execute(
                            select(Candle)
                            .where(
                                Candle.symbol == signal.symbol,
                                Candle.interval == intrabar_interval,
                                Candle.price_type == "last",
                                Candle.confirmed.is_(True),
                                Candle.open_time >= source_hour.open_time,
                                Candle.close_time <= source_hour.close_time,
                                Candle.available_at <= available_cutoff,
                            )
                            .order_by(Candle.open_time, Candle.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                evaluation = evaluate_barrier_outcome_with_intrabar(
                    bars,
                    [
                        OutcomeBar(
                            candle_id=row.id,
                            open_time=row.open_time,
                            close_time=row.close_time,
                            open=row.open,
                            high=row.high,
                            low=row.low,
                            close=row.close,
                        )
                        for row in intrabar_rows
                    ],
                    direction=signal.direction,
                    entry=signal.entry_reference,
                    stop=signal.stop_loss,
                    take_profit=signal.take_profit_1,
                    window_start=signal.event_time,
                    horizon_end=horizon_end,
                    intrabar_interval_minutes=intrabar_interval_minutes,
                )
        except ValueError as exc:
            invalid.append({"signal_id": str(signal.id), "error": str(exc)})
            continue
        if evaluation is None:
            pending_count += 1
            continue

        signal_outcome = SignalOutcome(
            signal_id=signal.id,
            outcome=evaluation.outcome,
            exit_price=evaluation.exit_price,
            exit_time=evaluation.exit_time,
            horizon_end=horizon_end,
            source_candle_id=evaluation.source_candle_id,
            bars_evaluated=evaluation.bars_evaluated,
            ambiguous=evaluation.ambiguous,
            evaluation_version=EVALUATION_VERSION,
            resolved_at=datetime.now(UTC),
            details={
                "price_type": "last",
                "interval": evaluation.resolution_interval,
                "hourly_interval": "60",
                "primary_take_profit": "take_profit_1",
                "same_bar_rule": "SL_within_finest_available_bar",
                "hourly_ambiguous": evaluation.hourly_ambiguous,
                "intrabar_bars_evaluated": evaluation.intrabar_bars_evaluated,
                "market_cutoff": market_cutoff.isoformat(),
                "available_cutoff": available_cutoff.isoformat(),
                "actual_execution_pnl": False,
            },
        )
        session.add(signal_outcome)
        await session.flush()
        await append_audit_event(
            session,
            event_type="COUNTERFACTUAL_SIGNAL_OUTCOME_RESOLVED",
            entity_type="signal_outcome",
            entity_id=str(signal_outcome.id),
            actor=actor,
            payload={
                "signal_id": str(signal.id),
                "symbol": signal.symbol,
                "direction": signal.direction,
                "outcome": signal_outcome.outcome,
                "exit_price": str(signal_outcome.exit_price),
                "exit_time": signal_outcome.exit_time.isoformat(),
                "ambiguous": signal_outcome.ambiguous,
                "evaluation_version": signal_outcome.evaluation_version,
            },
        )
        await publish_outbox(
            session,
            event_type="COUNTERFACTUAL_OUTCOME_RESOLVED",
            aggregate_type="market_signal",
            aggregate_id=str(signal.id),
            payload={"symbol": signal.symbol, "outcome": signal_outcome.outcome},
        )
        resolved_count += 1

    # A plan can be created after the signal outcome (for example after a profile
    # recalculation while the recommendation is still current). Backfill every plan
    # version, but later planning anchors remain PATH_UNAVAILABLE until an exact
    # entry-aligned price path is persisted; never reuse pre-plan signal movement.
    missing_plan_rows = (
        await session.execute(
            select(ExecutionPlan, MarketSignal, SignalOutcome)
            .join(MarketSignal, MarketSignal.id == ExecutionPlan.signal_id)
            .join(SignalOutcome, SignalOutcome.signal_id == MarketSignal.id)
            .outerjoin(PlanOutcome, PlanOutcome.plan_id == ExecutionPlan.id)
            .where(PlanOutcome.id.is_(None))
            .order_by(SignalOutcome.resolved_at, ExecutionPlan.created_at)
            .limit(batch_size)
        )
    ).all()
    plan_count = 0
    invalid_plans: list[dict[str, str]] = []
    for plan, signal, signal_outcome in missing_plan_rows:
        await acquire_advisory_xact_lock(session, "counterfactual_outcome", str(signal.id))
        existing_plan = (
            await session.execute(select(PlanOutcome).where(PlanOutcome.plan_id == plan.id))
        ).scalar_one_or_none()
        if existing_plan is not None:
            continue
        try:
            row = await _record_plan_outcome(
                session,
                signal=signal,
                signal_outcome=signal_outcome,
                plan=plan,
                actor=actor,
            )
        except ValueError as exc:
            invalid_plans.append(
                {
                    "signal_id": str(signal.id),
                    "plan_id": str(plan.id),
                    "error": str(exc),
                }
            )
            continue
        await publish_outbox(
            session,
            event_type="COUNTERFACTUAL_PLAN_OUTCOME_RECORDED",
            aggregate_type="execution_plan",
            aggregate_id=str(plan.id),
            payload={
                "signal_id": str(signal.id),
                "outcome": row.outcome,
                "valuation_status": row.valuation_status,
            },
        )
        plan_count += 1

    return {
        "candidate_signals": len(candidates),
        "signals_resolved": resolved_count,
        "signals_pending": pending_count,
        "invalid_signals": invalid,
        "invalid_plan_outcomes": invalid_plans,
        "plan_outcomes_recorded": plan_count,
        "market_cutoff": market_cutoff.isoformat(),
        "available_cutoff": available_cutoff.isoformat(),
        "intrabar_interval": intrabar_interval,
        "evaluation_version": EVALUATION_VERSION,
    }

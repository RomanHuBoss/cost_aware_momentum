from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal, DecimalException, getcontext
from typing import Literal

getcontext().prec = 36
Direction = Literal["LONG", "SHORT"]


@dataclass(frozen=True)
class CostScenario:
    fee_rate_round_trip: Decimal
    slippage_rate: Decimal
    stop_gap_reserve_rate: Decimal
    funding_rate: Decimal = Decimal("0")


@dataclass(frozen=True)
class InstrumentConstraints:
    qty_step: Decimal
    min_qty: Decimal
    min_notional: Decimal
    max_qty: Decimal | None
    max_leverage: Decimal


@dataclass(frozen=True)
class LiquidationAssessment:
    stop_distance_rate: Decimal
    estimated_liquidation_distance_rate: Decimal
    buffer_rate: Decimal
    stop_beyond_estimated_liquidation: bool
    narrow_buffer: bool


@dataclass(frozen=True)
class PositionPlan:
    status: str
    effective_capital: Decimal
    risk_budget: Decimal
    stress_downside_rate: Decimal
    qty_raw: Decimal
    qty: Decimal
    notional: Decimal
    actual_stress_loss: Decimal
    leverage: int
    margin_estimate: Decimal
    limiting_cap: str | None
    warnings: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            key: str(value) if isinstance(value, Decimal) else value for key, value in asdict(self).items()
        }


def d(value: Decimal | float | int | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def finite_decimal(value: Decimal | float | int | str, name: str) -> Decimal:
    try:
        result = d(value)
    except (DecimalException, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a valid decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


def positive_finite_decimal(value: Decimal | float | int | str, name: str) -> Decimal:
    result = finite_decimal(value, name)
    if result <= 0:
        raise ValueError(f"{name} must be positive")
    return result


def nonnegative_finite_decimal(value: Decimal | float | int | str, name: str) -> Decimal:
    result = finite_decimal(value, name)
    if result < 0:
        raise ValueError(f"{name} cannot be negative")
    return result




def validate_cost_scenario(costs: CostScenario) -> CostScenario:
    """Normalize and validate all monetary-rate inputs before any risk arithmetic."""

    return CostScenario(
        fee_rate_round_trip=nonnegative_finite_decimal(
            costs.fee_rate_round_trip, "fee_rate_round_trip"
        ),
        slippage_rate=nonnegative_finite_decimal(costs.slippage_rate, "slippage_rate"),
        stop_gap_reserve_rate=nonnegative_finite_decimal(
            costs.stop_gap_reserve_rate, "stop_gap_reserve_rate"
        ),
        funding_rate=finite_decimal(costs.funding_rate, "funding_rate"),
    )


def positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    try:
        if Decimal(str(value)) != Decimal(parsed):
            raise ValueError(f"{name} must be a positive integer")
    except (DecimalException, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _safe_positive_finite_decimal(value: object) -> Decimal:
    try:
        result = d(value)  # type: ignore[arg-type]
    except (DecimalException, TypeError, ValueError):
        return Decimal("0")
    return result if result.is_finite() and result > 0 else Decimal("0")


def _blocked_invalid_position_plan(
    *,
    effective_capital: object,
    risk_rate: object,
    leverage: object,
    reason: str,
    limiting_cap: str = "INVALID_INPUT",
) -> PositionPlan:
    safe_capital = _safe_positive_finite_decimal(effective_capital)
    safe_risk_rate = _safe_positive_finite_decimal(risk_rate)
    try:
        safe_risk_budget = safe_capital * safe_risk_rate
    except DecimalException:
        safe_risk_budget = Decimal("0")
    if not safe_risk_budget.is_finite():
        safe_risk_budget = Decimal("0")
    try:
        safe_leverage = max(1, int(leverage))
    except (TypeError, ValueError, OverflowError):
        safe_leverage = 1
    return PositionPlan(
        "BLOCKED_INVALID_INPUT",
        safe_capital,
        safe_risk_budget,
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        safe_leverage,
        Decimal("0"),
        limiting_cap,
        (reason,),
    )


def _direction_sign(direction: Direction) -> Decimal:
    if direction == "LONG":
        return Decimal("1")
    if direction == "SHORT":
        return Decimal("-1")
    raise ValueError(f"Unsupported direction: {direction}")


def _positive_finite_price(value: Decimal | float | int | str, name: str) -> Decimal:
    price = d(value)
    if not price.is_finite() or price <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return price


def validate_directional_geometry(
    *,
    entry: Decimal | float | int | str,
    direction: Direction,
    stop: Decimal | float | int | str | None = None,
    take_profit: Decimal | float | int | str | None = None,
) -> None:
    """Reject inverted or non-finite LONG/SHORT price geometry."""
    entry_price = _positive_finite_price(entry, "entry")
    stop_price = _positive_finite_price(stop, "stop") if stop is not None else None
    take_profit_price = (
        _positive_finite_price(take_profit, "take_profit") if take_profit is not None else None
    )
    _direction_sign(direction)

    if direction == "LONG":
        if stop_price is not None and stop_price >= entry_price:
            raise ValueError("Invalid LONG geometry: expected stop < entry")
        if take_profit_price is not None and take_profit_price <= entry_price:
            raise ValueError("Invalid LONG geometry: expected entry < take_profit")
    else:
        if stop_price is not None and stop_price <= entry_price:
            raise ValueError("Invalid SHORT geometry: expected entry < stop")
        if take_profit_price is not None and take_profit_price >= entry_price:
            raise ValueError("Invalid SHORT geometry: expected take_profit < entry")


def projected_funding_rate(
    *,
    start_time: datetime,
    horizon_hours: int,
    next_settlement: datetime | None,
    interval_minutes: int | None,
    current_rate: Decimal,
) -> Decimal:
    """Conservative cumulative funding-rate scenario over crossed settlements."""
    horizon_value = positive_integer(horizon_hours, "horizon_hours")
    rate = finite_decimal(current_rate, "current_rate")
    if start_time.tzinfo is None or start_time.utcoffset() is None:
        raise ValueError("Funding timestamps must be timezone-aware")
    if next_settlement is None or interval_minutes is None:
        return Decimal("0")
    interval_value = positive_integer(interval_minutes, "interval_minutes")
    if next_settlement.tzinfo is None or next_settlement.utcoffset() is None:
        raise ValueError("Funding timestamps must be timezone-aware")
    interval = timedelta(minutes=interval_value)
    # A settlement exactly at the planning start is already in the past for a
    # position opened after the signal decision. Count only future settlements.
    while next_settlement <= start_time:
        next_settlement += interval
    end_time = start_time + timedelta(hours=horizon_value)
    if next_settlement > end_time:
        return Decimal("0")
    count = 1 + int((end_time - next_settlement).total_seconds() // interval.total_seconds())
    return rate * count


def gross_pnl(direction: Direction, qty: Decimal, entry: Decimal, exit_price: Decimal) -> Decimal:
    sign = _direction_sign(direction)
    return sign * d(qty) * (d(exit_price) - d(entry))


def funding_return_rate(direction: Direction, funding_rate: Decimal | float | int | str) -> Decimal:
    """Signed return from the trader perspective for one funding scenario.

    A positive exchange funding rate is a debit for LONG and a credit for SHORT.
    A negative exchange rate reverses those cash flows.
    """

    return -_direction_sign(direction) * finite_decimal(funding_rate, "funding_rate")


def pretrade_funding_return_rate(
    direction: Direction, funding_rate: Decimal | float | int | str
) -> Decimal:
    """Conservative funding recognized before an exit time is known.

    An adverse projected settlement is charged to the plan. A favorable projected
    settlement is not credited because TP/SL may close the position before the
    funding timestamp. Realized accounting uses :func:`funding_cash_flow` after
    crossed settlements are known.
    """

    return min(Decimal("0"), funding_return_rate(direction, funding_rate))


def funding_cash_flow(direction: Direction, position_value: Decimal, funding_rate: Decimal) -> Decimal:
    """Cash flow from trader perspective. Positive funding means LONG pays and SHORT receives."""
    return d(position_value) * funding_return_rate(direction, funding_rate)


def fee_cash(qty: Decimal, executed_price: Decimal, fee_rate: Decimal) -> Decimal:
    return abs(d(qty) * d(executed_price)) * d(fee_rate)


def normalized_round_trip_fee_rate(
    entry: Decimal, exit_price: Decimal, fee_rate_round_trip: Decimal
) -> Decimal:
    """Return two equal fee legs normalized by entry notional.

    ``fee_rate_round_trip`` is the sum of equal entry and exit fee rates.  The
    exit leg must be charged on the actual exit notional, not on entry notional.
    """

    entry = _positive_finite_price(entry, "entry")
    exit_price = _positive_finite_price(exit_price, "exit_price")
    fee_rate_round_trip = nonnegative_finite_decimal(
        fee_rate_round_trip, "fee_rate_round_trip"
    )
    fee_rate_per_leg = fee_rate_round_trip / Decimal("2")
    return fee_rate_per_leg * (Decimal("1") + exit_price / entry)


def stress_downside_rate(entry: Decimal, stop: Decimal, direction: Direction, costs: CostScenario) -> Decimal:
    costs = validate_cost_scenario(costs)
    validate_directional_geometry(entry=entry, stop=stop, direction=direction)
    entry = d(entry)
    stop = d(stop)
    price_move = (entry - stop) / entry if direction == "LONG" else (stop - entry) / entry
    signed_funding = funding_return_rate(direction, costs.funding_rate)
    adverse_funding = max(Decimal("0"), -signed_funding)
    fee_rate = normalized_round_trip_fee_rate(entry, stop, costs.fee_rate_round_trip)
    return (
        price_move
        + fee_rate
        + costs.slippage_rate
        + costs.stop_gap_reserve_rate
        + adverse_funding
    )


def upside_rate(entry: Decimal, take_profit: Decimal, direction: Direction, costs: CostScenario) -> Decimal:
    costs = validate_cost_scenario(costs)
    validate_directional_geometry(entry=entry, take_profit=take_profit, direction=direction)
    entry = d(entry)
    tp = d(take_profit)
    price_move = (tp - entry) / entry if direction == "LONG" else (entry - tp) / entry
    recognized_funding = pretrade_funding_return_rate(direction, costs.funding_rate)
    fee_rate = normalized_round_trip_fee_rate(entry, tp, costs.fee_rate_round_trip)
    return price_move - fee_rate - costs.slippage_rate + recognized_funding



def validate_probability_simplex(
    p_tp: Decimal | float | int | str,
    p_sl: Decimal | float | int | str,
    p_timeout: Decimal | float | int | str,
    *,
    tolerance: Decimal = Decimal("1e-8"),
) -> tuple[Decimal, Decimal, Decimal]:
    """Return finite probabilities only when they form a valid simplex."""

    values = (
        finite_decimal(p_tp, "p_tp"),
        finite_decimal(p_sl, "p_sl"),
        finite_decimal(p_timeout, "p_timeout"),
    )
    if any(value < 0 or value > 1 for value in values):
        raise ValueError("probabilities must each be within [0, 1]")
    if abs(sum(values, Decimal("0")) - Decimal("1")) > tolerance:
        raise ValueError("probabilities must sum to 1")
    return values

def net_rr_and_ev(
    *,
    entry: Decimal,
    stop: Decimal,
    take_profit: Decimal,
    direction: Direction,
    costs: CostScenario,
    p_tp: float,
    p_sl: float,
    p_timeout: float,
    timeout_return_rate: Decimal = Decimal("-0.002"),
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    validate_directional_geometry(
        entry=entry,
        stop=stop,
        take_profit=take_profit,
        direction=direction,
    )
    downside = stress_downside_rate(entry, stop, direction, costs)
    upside = upside_rate(entry, take_profit, direction, costs)
    rr = Decimal("0") if downside <= 0 else max(Decimal("0"), upside) / downside
    recognized_funding = pretrade_funding_return_rate(direction, costs.funding_rate)
    timeout_gross = finite_decimal(timeout_return_rate, "timeout_return_rate")
    timeout_exit = d(entry) * (
        Decimal("1") + timeout_gross if direction == "LONG" else Decimal("1") - timeout_gross
    )
    timeout_fee_rate = normalized_round_trip_fee_rate(
        entry, timeout_exit, costs.fee_rate_round_trip
    )
    timeout_net = timeout_gross - timeout_fee_rate - costs.slippage_rate + recognized_funding
    sl_net = -downside
    p_tp_value, p_sl_value, p_timeout_value = validate_probability_simplex(
        p_tp, p_sl, p_timeout
    )
    ev_rate = (
        p_tp_value * upside
        + p_sl_value * sl_net
        + p_timeout_value * timeout_net
    )
    ev_r = Decimal("0") if downside <= 0 else ev_rate / downside
    return rr, ev_r, downside, upside


def assess_liquidation_proximity(
    *,
    entry: Decimal | float | int | str,
    stop: Decimal | float | int | str,
    leverage: int,
) -> LiquidationAssessment:
    """Conservative distance check against an approximate isolated liquidation boundary."""

    entry_price = positive_finite_decimal(entry, "entry")
    stop_price = positive_finite_decimal(stop, "stop")
    leverage_value = positive_integer(leverage, "leverage")

    stop_distance = abs(entry_price - stop_price) / entry_price
    estimated_liquidation_distance = Decimal("0.9") / Decimal(leverage_value)
    buffer_rate = max(Decimal("0"), estimated_liquidation_distance - stop_distance)
    return LiquidationAssessment(
        stop_distance_rate=stop_distance,
        estimated_liquidation_distance_rate=estimated_liquidation_distance,
        buffer_rate=buffer_rate,
        stop_beyond_estimated_liquidation=stop_distance >= estimated_liquidation_distance,
        narrow_buffer=buffer_rate < stop_distance,
    )


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    value, step = d(value), d(step)
    if step <= 0:
        raise ValueError("qty_step must be positive")
    units = (value / step).to_integral_value(rounding=ROUND_DOWN)
    return units * step


def calculate_position_plan(
    *,
    effective_capital: Decimal,
    risk_rate: Decimal,
    entry: Decimal,
    stop: Decimal,
    take_profit: Decimal | None = None,
    direction: Direction,
    costs: CostScenario,
    constraints: InstrumentConstraints,
    leverage: int,
    available_margin: Decimal | None = None,
    margin_reserve_rate: Decimal = Decimal("0.25"),
    liquidity_notional_cap: Decimal | None = None,
    portfolio_notional_cap: Decimal | None = None,
    exchange_notional_cap: Decimal | None = None,
    capital_verified: bool = False,
) -> PositionPlan:
    raw_effective_capital = effective_capital
    raw_risk_rate = risk_rate
    raw_leverage = leverage
    warnings: list[str] = []

    try:
        effective_capital = positive_finite_decimal(effective_capital, "effective_capital")
        risk_rate = positive_finite_decimal(risk_rate, "risk_rate")
        entry = positive_finite_decimal(entry, "entry")

        fee_rate = nonnegative_finite_decimal(costs.fee_rate_round_trip, "fee_rate_round_trip")
        slippage_rate = nonnegative_finite_decimal(costs.slippage_rate, "slippage_rate")
        stop_gap_reserve_rate = nonnegative_finite_decimal(
            costs.stop_gap_reserve_rate, "stop_gap_reserve_rate"
        )
        funding_rate = finite_decimal(costs.funding_rate, "funding_rate")
        costs = CostScenario(
            fee_rate_round_trip=fee_rate,
            slippage_rate=slippage_rate,
            stop_gap_reserve_rate=stop_gap_reserve_rate,
            funding_rate=funding_rate,
        )

        qty_step = positive_finite_decimal(constraints.qty_step, "qty_step")
        min_qty = positive_finite_decimal(constraints.min_qty, "min_qty")
        min_notional = positive_finite_decimal(constraints.min_notional, "min_notional")
        max_qty = (
            positive_finite_decimal(constraints.max_qty, "max_qty")
            if constraints.max_qty is not None
            else None
        )
        max_leverage = positive_finite_decimal(constraints.max_leverage, "max_leverage")
        if max_leverage < 1:
            raise ValueError("max_leverage must be at least 1")
        requested_leverage = positive_integer(leverage, "leverage")
        max_leverage_integer = int(max_leverage.to_integral_value(rounding=ROUND_DOWN))
        if max_leverage_integer < 1:
            raise ValueError("max_leverage must allow at least integer leverage 1")
        leverage = min(requested_leverage, max_leverage_integer)
        constraints = InstrumentConstraints(
            qty_step=qty_step,
            min_qty=min_qty,
            min_notional=min_notional,
            max_qty=max_qty,
            max_leverage=max_leverage,
        )

        reserve_rate = finite_decimal(margin_reserve_rate, "margin_reserve_rate")
        if reserve_rate < 0 or reserve_rate >= 1:
            raise ValueError("margin_reserve_rate must be finite and in [0, 1)")
        margin_reserve_rate = reserve_rate
        if available_margin is not None:
            available_margin = nonnegative_finite_decimal(available_margin, "available_margin")
        if liquidity_notional_cap is not None:
            liquidity_notional_cap = nonnegative_finite_decimal(
                liquidity_notional_cap, "liquidity_notional_cap"
            )
        if portfolio_notional_cap is not None:
            portfolio_notional_cap = nonnegative_finite_decimal(
                portfolio_notional_cap, "portfolio_notional_cap"
            )
        if exchange_notional_cap is not None:
            exchange_notional_cap = nonnegative_finite_decimal(
                exchange_notional_cap, "exchange_notional_cap"
            )
    except (DecimalException, TypeError, ValueError, OverflowError) as exc:
        return _blocked_invalid_position_plan(
            effective_capital=raw_effective_capital,
            risk_rate=raw_risk_rate,
            leverage=raw_leverage,
            reason=str(exc),
        )

    try:
        risk_budget = effective_capital * risk_rate
    except DecimalException:
        risk_budget = Decimal("0")
    if not risk_budget.is_finite() or risk_budget <= 0:
        return _blocked_invalid_position_plan(
            effective_capital=effective_capital,
            risk_rate=risk_rate,
            leverage=leverage,
            reason="risk_budget must be positive and finite",
        )

    try:
        validate_directional_geometry(
            entry=entry,
            stop=stop,
            take_profit=take_profit,
            direction=direction,
        )
        downside = stress_downside_rate(entry, stop, direction, costs)
    except (DecimalException, TypeError, ValueError) as exc:
        return _blocked_invalid_position_plan(
            effective_capital=effective_capital,
            risk_rate=risk_rate,
            leverage=leverage,
            reason=str(exc),
            limiting_cap="INVALID_GEOMETRY",
        )
    if not downside.is_finite() or downside <= 0:
        return _blocked_invalid_position_plan(
            effective_capital=effective_capital,
            risk_rate=risk_rate,
            leverage=leverage,
            reason="stress_downside_rate must be positive and finite",
        )

    try:
        risk_notional = positive_finite_decimal(risk_budget / downside, "risk_notional")
        caps: list[tuple[str, Decimal]] = [("RISK", risk_notional)]

        if available_margin is not None:
            free_after_reserve = available_margin * (Decimal("1") - margin_reserve_rate)
            caps.append(
                (
                    "MARGIN",
                    nonnegative_finite_decimal(
                        free_after_reserve * Decimal(leverage), "margin_notional_cap"
                    ),
                )
            )
        if liquidity_notional_cap is not None:
            caps.append(("LIQUIDITY", liquidity_notional_cap))
        if portfolio_notional_cap is not None:
            caps.append(("PORTFOLIO", portfolio_notional_cap))
        if exchange_notional_cap is not None:
            caps.append(("EXCHANGE", exchange_notional_cap))
        if constraints.max_qty is not None:
            caps.append(
                (
                    "EXCHANGE_MAX_QTY",
                    positive_finite_decimal(constraints.max_qty * entry, "exchange_max_qty_notional"),
                )
            )

        limiting_cap, final_notional_raw = min(caps, key=lambda item: item[1])
        qty_raw = nonnegative_finite_decimal(final_notional_raw / entry, "qty_raw")
        qty = floor_to_step(qty_raw, constraints.qty_step)
        notional = nonnegative_finite_decimal(qty * entry, "notional")
        actual_loss = nonnegative_finite_decimal(notional * downside, "actual_stress_loss")
        margin = nonnegative_finite_decimal(notional / Decimal(leverage), "margin_estimate")
    except (DecimalException, TypeError, ValueError, OverflowError) as exc:
        return _blocked_invalid_position_plan(
            effective_capital=effective_capital,
            risk_rate=risk_rate,
            leverage=leverage,
            reason=str(exc),
        )

    if not capital_verified:
        warnings.append("Капитал не подтвержден биржей")

    if qty <= 0 or qty < constraints.min_qty or notional < constraints.min_notional:
        blocked_status = {
            "MARGIN": "BLOCKED_MARGIN",
            "LIQUIDITY": "BLOCKED_LIQUIDITY",
            "PORTFOLIO": "BLOCKED_PORTFOLIO",
        }.get(limiting_cap, "BLOCKED_MIN_SIZE")
        blocked_message = {
            "BLOCKED_MARGIN": "Недостаточно свободной маржи с учетом резерва",
            "BLOCKED_LIQUIDITY": "Безопасный размер не исполняется при допустимой ликвидности",
            "BLOCKED_PORTFOLIO": "Исчерпан общий или кластерный риск портфеля",
        }.get(blocked_status, "Безопасный размер меньше минимального ордера биржи")
        return PositionPlan(
            blocked_status,
            effective_capital,
            risk_budget,
            downside,
            qty_raw,
            qty,
            notional,
            actual_loss,
            leverage,
            margin,
            limiting_cap if blocked_status != "BLOCKED_MIN_SIZE" else "MIN_ORDER",
            tuple(warnings + [blocked_message]),
        )

    if available_margin is not None and margin > available_margin * (Decimal("1") - margin_reserve_rate):
        return PositionPlan(
            "BLOCKED_MARGIN",
            effective_capital,
            risk_budget,
            downside,
            qty_raw,
            qty,
            notional,
            actual_loss,
            leverage,
            margin,
            "MARGIN",
            tuple(warnings + ["Недостаточно свободной маржи с учетом резерва"]),
        )

    if actual_loss > risk_budget + Decimal("0.00000001"):
        raise AssertionError("Position sizing invariant violated: stress loss exceeds risk budget")

    status = "ACTIONABLE" if limiting_cap == "RISK" else "LIMITED"
    if limiting_cap == "LIQUIDITY":
        warnings.append("Размер позиции ограничен доступной ликвидностью")
    elif limiting_cap == "PORTFOLIO":
        warnings.append("Размер позиции ограничен портфельным лимитом")
    elif limiting_cap == "MARGIN":
        warnings.append("Размер позиции ограничен свободной маржой")

    return PositionPlan(
        status,
        effective_capital,
        risk_budget,
        downside,
        qty_raw,
        qty,
        notional,
        actual_loss,
        leverage,
        margin,
        limiting_cap if limiting_cap != "RISK" else None,
        tuple(warnings),
    )

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal, getcontext
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


def projected_funding_rate(
    *,
    start_time: datetime,
    horizon_hours: int,
    next_settlement: datetime | None,
    interval_minutes: int | None,
    current_rate: Decimal,
) -> Decimal:
    """Conservative cumulative funding-rate scenario over crossed settlements."""
    if next_settlement is None or interval_minutes is None or interval_minutes <= 0:
        return Decimal("0")
    if start_time.tzinfo is None or next_settlement.tzinfo is None:
        raise ValueError("Funding timestamps must be timezone-aware")
    interval = timedelta(minutes=interval_minutes)
    while next_settlement < start_time:
        next_settlement += interval
    end_time = start_time + timedelta(hours=horizon_hours)
    if next_settlement > end_time:
        return Decimal("0")
    count = 1 + int((end_time - next_settlement).total_seconds() // interval.total_seconds())
    return d(current_rate) * count


def gross_pnl(direction: Direction, qty: Decimal, entry: Decimal, exit_price: Decimal) -> Decimal:
    sign = Decimal("1") if direction == "LONG" else Decimal("-1")
    return sign * d(qty) * (d(exit_price) - d(entry))


def funding_cash_flow(direction: Direction, position_value: Decimal, funding_rate: Decimal) -> Decimal:
    """Cash flow from trader perspective. Positive funding means LONG pays and SHORT receives."""
    sign = Decimal("1") if direction == "LONG" else Decimal("-1")
    return -sign * d(position_value) * d(funding_rate)


def fee_cash(qty: Decimal, executed_price: Decimal, fee_rate: Decimal) -> Decimal:
    return abs(d(qty) * d(executed_price)) * d(fee_rate)


def stress_downside_rate(entry: Decimal, stop: Decimal, direction: Direction, costs: CostScenario) -> Decimal:
    entry = d(entry)
    stop = d(stop)
    price_move = abs(entry - stop) / entry
    adverse_funding = max(Decimal("0"), costs.funding_rate if direction == "LONG" else -costs.funding_rate)
    return (
        price_move
        + costs.fee_rate_round_trip
        + costs.slippage_rate
        + costs.stop_gap_reserve_rate
        + adverse_funding
    )


def upside_rate(entry: Decimal, take_profit: Decimal, direction: Direction, costs: CostScenario) -> Decimal:
    entry = d(entry)
    tp = d(take_profit)
    price_move = abs(tp - entry) / entry
    adverse_funding = max(Decimal("0"), costs.funding_rate if direction == "LONG" else -costs.funding_rate)
    return price_move - costs.fee_rate_round_trip - costs.slippage_rate - adverse_funding


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
    downside = stress_downside_rate(entry, stop, direction, costs)
    upside = upside_rate(entry, take_profit, direction, costs)
    rr = Decimal("0") if downside <= 0 else max(Decimal("0"), upside) / downside
    adverse_funding = max(Decimal("0"), costs.funding_rate if direction == "LONG" else -costs.funding_rate)
    timeout_net = d(timeout_return_rate) - costs.fee_rate_round_trip - costs.slippage_rate - adverse_funding
    ev_rate = d(p_tp) * upside - d(p_sl) * downside + d(p_timeout) * timeout_net
    ev_r = Decimal("0") if downside <= 0 else ev_rate / downside
    return rr, ev_r, downside, upside


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
    effective_capital = d(effective_capital)
    risk_rate = d(risk_rate)
    entry = d(entry)
    allowed_max_leverage = max(1, int(constraints.max_leverage))
    leverage = int(min(max(1, leverage), allowed_max_leverage))
    warnings: list[str] = []

    downside = stress_downside_rate(entry, stop, direction, costs)
    risk_budget = effective_capital * risk_rate
    if effective_capital <= 0 or risk_budget <= 0 or downside <= 0:
        return PositionPlan(
            "BLOCKED_INVALID_INPUT",
            effective_capital,
            max(Decimal("0"), risk_budget),
            max(Decimal("0"), downside),
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            leverage,
            Decimal("0"),
            "INVALID_INPUT",
            tuple(warnings),
        )

    risk_notional = risk_budget / downside
    caps: list[tuple[str, Decimal]] = [("RISK", risk_notional)]

    if available_margin is not None:
        free_after_reserve = max(Decimal("0"), d(available_margin) * (Decimal("1") - d(margin_reserve_rate)))
        caps.append(("MARGIN", free_after_reserve * d(leverage)))
    if liquidity_notional_cap is not None:
        caps.append(("LIQUIDITY", max(Decimal("0"), d(liquidity_notional_cap))))
    if portfolio_notional_cap is not None:
        caps.append(("PORTFOLIO", max(Decimal("0"), d(portfolio_notional_cap))))
    if exchange_notional_cap is not None:
        caps.append(("EXCHANGE", max(Decimal("0"), d(exchange_notional_cap))))
    if constraints.max_qty is not None:
        caps.append(("EXCHANGE_MAX_QTY", constraints.max_qty * entry))

    limiting_cap, final_notional_raw = min(caps, key=lambda item: item[1])
    qty_raw = final_notional_raw / entry
    qty = floor_to_step(qty_raw, constraints.qty_step)
    notional = qty * entry
    actual_loss = notional * downside
    margin = notional / d(leverage)

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

    if available_margin is not None and margin > d(available_margin) * (
        Decimal("1") - d(margin_reserve_rate)
    ):
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

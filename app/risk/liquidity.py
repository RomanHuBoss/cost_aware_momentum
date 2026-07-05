from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

ORDERBOOK_EXECUTION_SCHEMA_VERSION = "bybit-rest-depth-vwap-fill-v1"

FillStatus = Literal["FULL", "PARTIAL", "NO_FILL"]


@dataclass(frozen=True)
class FillSimulation:
    status: FillStatus
    requested_qty: Decimal
    filled_qty: Decimal
    unfilled_qty: Decimal
    available_qty: Decimal
    available_notional: Decimal
    best_price: Decimal | None
    vwap: Decimal | None
    worst_price: Decimal | None
    impact_bps: Decimal | None
    levels_used: int
    max_impact_bps: Decimal


def _finite_decimal(value: object, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (ArithmeticError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be a finite decimal")
    return result


def _positive_decimal(value: object, field: str) -> Decimal:
    result = _finite_decimal(value, field)
    if result <= 0:
        raise ValueError(f"{field} must be positive")
    return result


def normalize_book_levels(
    levels: Iterable[Sequence[object]],
    *,
    side: Literal["bid", "ask"],
) -> tuple[tuple[Decimal, Decimal], ...]:
    normalized: list[tuple[Decimal, Decimal]] = []
    seen_prices: set[Decimal] = set()
    for index, raw in enumerate(levels):
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            raise ValueError(f"{side} level {index} must contain price and size")
        price = _positive_decimal(raw[0], f"{side} price")
        size = _positive_decimal(raw[1], f"{side} size")
        if price in seen_prices:
            raise ValueError(f"{side} levels contain a duplicate price")
        seen_prices.add(price)
        normalized.append((price, size))

    if not normalized:
        raise ValueError(f"{side} side is empty")
    prices = [price for price, _ in normalized]
    if side == "bid" and prices != sorted(prices, reverse=True):
        raise ValueError("bid levels must be sorted descending")
    if side == "ask" and prices != sorted(prices):
        raise ValueError("ask levels must be sorted ascending")
    return tuple(normalized)


def validate_orderbook_levels(
    *,
    bids: Iterable[Sequence[object]],
    asks: Iterable[Sequence[object]],
) -> tuple[tuple[tuple[Decimal, Decimal], ...], tuple[tuple[Decimal, Decimal], ...]]:
    normalized_bids = normalize_book_levels(bids, side="bid")
    normalized_asks = normalize_book_levels(asks, side="ask")
    if normalized_asks[0][0] < normalized_bids[0][0]:
        raise ValueError("orderbook is crossed")
    return normalized_bids, normalized_asks


def simulate_market_fill(
    *,
    direction: str,
    requested_qty: Decimal,
    bids: Iterable[Sequence[object]],
    asks: Iterable[Sequence[object]],
    max_impact_bps: Decimal,
) -> FillSimulation:
    qty = _positive_decimal(requested_qty, "requested_qty")
    impact_limit = _finite_decimal(max_impact_bps, "max_impact_bps")
    if impact_limit < 0:
        raise ValueError("max_impact_bps must be non-negative")
    normalized_bids, normalized_asks = validate_orderbook_levels(bids=bids, asks=asks)

    if direction == "LONG":
        levels = normalized_asks
        best = levels[0][0]
        boundary = best * (Decimal("1") + impact_limit / Decimal("10000"))
        eligible = tuple((price, size) for price, size in levels if price <= boundary)
    elif direction == "SHORT":
        levels = normalized_bids
        best = levels[0][0]
        boundary = best * (Decimal("1") - impact_limit / Decimal("10000"))
        eligible = tuple((price, size) for price, size in levels if price >= boundary)
    else:
        raise ValueError(f"Unsupported direction: {direction}")

    available_qty = sum((size for _, size in eligible), Decimal("0"))
    available_notional = sum((price * size for price, size in eligible), Decimal("0"))
    remaining = qty
    filled = Decimal("0")
    quote = Decimal("0")
    worst: Decimal | None = None
    levels_used = 0
    for price, size in eligible:
        if remaining <= 0:
            break
        take = min(size, remaining)
        if take <= 0:
            continue
        filled += take
        quote += take * price
        remaining -= take
        worst = price
        levels_used += 1

    if filled == 0:
        return FillSimulation(
            status="NO_FILL",
            requested_qty=qty,
            filled_qty=Decimal("0"),
            unfilled_qty=qty,
            available_qty=available_qty,
            available_notional=available_notional,
            best_price=best,
            vwap=None,
            worst_price=None,
            impact_bps=None,
            levels_used=0,
            max_impact_bps=impact_limit,
        )

    vwap = quote / filled
    if direction == "LONG":
        impact = (vwap / best - Decimal("1")) * Decimal("10000")
    else:
        impact = (Decimal("1") - vwap / best) * Decimal("10000")
    status: FillStatus = "FULL" if filled == qty else "PARTIAL"
    return FillSimulation(
        status=status,
        requested_qty=qty,
        filled_qty=filled,
        unfilled_qty=qty - filled,
        available_qty=available_qty,
        available_notional=available_notional,
        best_price=best,
        vwap=vwap,
        worst_price=worst,
        impact_bps=impact,
        levels_used=levels_used,
        max_impact_bps=impact_limit,
    )

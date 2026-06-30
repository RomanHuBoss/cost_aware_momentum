from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import pandas as pd

Outcome = Literal["TP", "SL", "TIMEOUT"]


@dataclass(frozen=True)
class BarrierOutcome:
    outcome: Outcome
    exit_price: float
    exit_index: int
    ambiguous: bool
    exit_at_open: bool


def _positive_finite(value: object, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"invalid prices: {name} must be positive and finite")
    return parsed


def triple_barrier_outcome(
    future_bars: pd.DataFrame,
    *,
    direction: Literal["LONG", "SHORT"],
    stop: float,
    take_profit: float,
    conservative_ambiguity: bool = True,
) -> BarrierOutcome:
    if direction not in ("LONG", "SHORT"):
        raise ValueError(f"Unsupported direction: {direction}")
    stop = _positive_finite(stop, "stop")
    take_profit = _positive_finite(take_profit, "take_profit")
    if direction == "LONG" and stop >= take_profit:
        raise ValueError("invalid directional geometry: LONG requires stop < take_profit")
    if direction == "SHORT" and take_profit >= stop:
        raise ValueError("invalid directional geometry: SHORT requires take_profit < stop")
    if future_bars.empty:
        raise ValueError("future barrier window cannot be empty")
    required_columns = {"open", "high", "low", "close"}
    missing_columns = sorted(required_columns - set(future_bars.columns))
    if missing_columns:
        raise ValueError(f"future barrier window is missing OHLC columns: {missing_columns}")

    for i, row in enumerate(future_bars.itertuples(index=False)):
        open_price = _positive_finite(row.open, "open")
        high = _positive_finite(row.high, "high")
        low = _positive_finite(row.low, "low")
        close = _positive_finite(row.close, "close")
        if high < low or not low <= open_price <= high or not low <= close <= high:
            raise ValueError("invalid prices: expected low <= open/close <= high")

        # The candle open is the first observable point of the bar. Resolve an
        # opening gap before using unordered intrabar extrema. Favorable TP gaps
        # are capped at the modeled target, while adverse stop gaps use the open
        # because a stop cannot guarantee its trigger price.
        if direction == "LONG":
            if open_price <= stop:
                return BarrierOutcome("SL", open_price, i, False, True)
            if open_price >= take_profit:
                return BarrierOutcome("TP", take_profit, i, False, True)
            tp_hit, sl_hit = high >= take_profit, low <= stop
        else:
            if open_price >= stop:
                return BarrierOutcome("SL", open_price, i, False, True)
            if open_price <= take_profit:
                return BarrierOutcome("TP", take_profit, i, False, True)
            tp_hit, sl_hit = low <= take_profit, high >= stop
        if tp_hit and sl_hit:
            outcome: Outcome = "SL" if conservative_ambiguity else "TP"
            return BarrierOutcome(
                outcome,
                stop if outcome == "SL" else take_profit,
                i,
                True,
                False,
            )
        if tp_hit:
            return BarrierOutcome("TP", take_profit, i, False, False)
        if sl_hit:
            return BarrierOutcome("SL", stop, i, False, False)
    return BarrierOutcome(
        "TIMEOUT",
        _positive_finite(future_bars.iloc[-1]["close"], "close"),
        len(future_bars) - 1,
        False,
        False,
    )

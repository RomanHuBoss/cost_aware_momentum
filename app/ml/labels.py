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

    for i, row in enumerate(future_bars.itertuples(index=False)):
        high = _positive_finite(row.high, "high")
        low = _positive_finite(row.low, "low")
        close = _positive_finite(row.close, "close")
        if high < low or high < close or low > close:
            raise ValueError("invalid prices: expected low <= close <= high")
        if direction == "LONG":
            tp_hit, sl_hit = high >= take_profit, low <= stop
        else:
            tp_hit, sl_hit = low <= take_profit, high >= stop
        if tp_hit and sl_hit:
            outcome: Outcome = "SL" if conservative_ambiguity else "TP"
            return BarrierOutcome(outcome, stop if outcome == "SL" else take_profit, i, True)
        if tp_hit:
            return BarrierOutcome("TP", take_profit, i, False)
        if sl_hit:
            return BarrierOutcome("SL", stop, i, False)
    return BarrierOutcome(
        "TIMEOUT",
        _positive_finite(future_bars.iloc[-1]["close"], "close"),
        len(future_bars) - 1,
        False,
    )

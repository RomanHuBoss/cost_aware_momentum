from __future__ import annotations

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


def triple_barrier_outcome(
    future_bars: pd.DataFrame,
    *,
    direction: Literal["LONG", "SHORT"],
    stop: float,
    take_profit: float,
    conservative_ambiguity: bool = True,
) -> BarrierOutcome:
    if future_bars.empty:
        return BarrierOutcome("TIMEOUT", float("nan"), -1, False)
    for i, row in enumerate(future_bars.itertuples(index=False)):
        high = float(row.high)
        low = float(row.low)
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
    return BarrierOutcome("TIMEOUT", float(future_bars.iloc[-1]["close"]), len(future_bars) - 1, False)

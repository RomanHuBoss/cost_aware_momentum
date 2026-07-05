from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import pandas as pd

INTRAHORIZON_MARGIN_SCHEMA_VERSION = "bybit-mark-price-hourly-isolated-margin-proxy-v1"
INTRAHORIZON_MTM_PATH_SCHEMA_VERSION = "hourly-mark-close-effective-exit-cumulative-return-v1"
DEFAULT_EQUITY_RESERVE_FRACTION = 0.10

Direction = Literal["LONG", "SHORT"]


@dataclass(frozen=True)
class IntrahorizonMarginPath:
    liquidated: bool
    liquidation_index: int | None
    liquidation_at_open: bool
    liquidation_exit_offset_hours: int | None
    liquidation_gross_return_rate: float | None
    maximum_adverse_excursion_rate: float
    maximum_favorable_excursion_rate: float
    minimum_equity_rate: float
    initial_margin_rate: float
    liquidation_equity_reserve_rate: float


def _positive_finite(value: object, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return parsed


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if parsed <= 0 or float(value) != float(parsed):
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _directional_return(direction: Direction, price: float, entry_price: float) -> float:
    if direction == "LONG":
        return price / entry_price - 1.0
    if direction == "SHORT":
        return 1.0 - price / entry_price
    raise ValueError(f"Unsupported direction: {direction}")


def simulate_intrahorizon_margin_path(
    mark_bars: pd.DataFrame,
    *,
    direction: Direction,
    entry_price: float,
    exit_index: int,
    exit_at_open: bool,
    leverage: int,
    equity_reserve_fraction: float = DEFAULT_EQUITY_RESERVE_FRACTION,
    cumulative_adverse_funding_return_at_open_by_bar: Sequence[float] | None = None,
    cumulative_adverse_funding_return_at_close_by_bar: Sequence[float] | None = None,
) -> IntrahorizonMarginPath:
    """Replay conservative intrahorizon margin on hourly mark-price OHLC.

    The simulator deliberately remains an isolated-margin research proxy, not an
    exact exchange liquidation engine. It reserves a fixed fraction of initial
    margin for maintenance/liquidation costs and treats a same-bar liquidation
    touch as occurring before a later unordered last-price TP/SL touch. Funding
    inputs must be cumulative, non-positive directional cash-flow rates known by
    each bar close; favourable future funding is never allowed to prevent a
    liquidation in this conservative path.
    """

    entry = _positive_finite(entry_price, "entry_price")
    leverage_value = _positive_integer(leverage, "leverage")
    reserve_fraction = float(equity_reserve_fraction)
    if not math.isfinite(reserve_fraction) or not 0.0 <= reserve_fraction < 1.0:
        raise ValueError("equity_reserve_fraction must be finite and in [0, 1)")
    if isinstance(exit_index, bool) or not isinstance(exit_index, int) or exit_index < 0:
        raise ValueError("exit_index must be a non-negative integer")
    if not isinstance(exit_at_open, bool):
        raise ValueError("exit_at_open must be boolean")
    if mark_bars.empty or exit_index >= len(mark_bars):
        raise ValueError("mark path must include the modeled exit bar")

    required = {"open", "high", "low", "close"}
    missing = sorted(required - set(mark_bars.columns))
    if missing:
        raise ValueError(f"mark path is missing OHLC columns: {missing}")

    bar_count = exit_index + 1

    def validate_funding_path(values: Sequence[float] | None, *, name: str) -> list[float]:
        if values is None:
            return [0.0] * bar_count
        if len(values) != bar_count:
            raise ValueError(f"{name} funding path length must match the modeled mark path")
        parsed_values: list[float] = []
        previous = 0.0
        for value in values:
            parsed = float(value)
            if not math.isfinite(parsed) or parsed > 0.0:
                raise ValueError(f"{name} cumulative adverse funding must be finite and non-positive")
            if parsed > previous + 1e-15:
                raise ValueError(f"{name} cumulative adverse funding cannot become less adverse")
            parsed_values.append(parsed)
            previous = parsed
        return parsed_values

    funding_at_open = validate_funding_path(cumulative_adverse_funding_return_at_open_by_bar, name="open")
    funding_at_close = validate_funding_path(cumulative_adverse_funding_return_at_close_by_bar, name="close")
    for index, (open_value, close_value) in enumerate(zip(funding_at_open, funding_at_close, strict=True)):
        if close_value > open_value + 1e-15:
            raise ValueError("close funding cannot be less adverse than open funding")
        if index > 0 and not math.isclose(
            open_value, funding_at_close[index - 1], rel_tol=0.0, abs_tol=1e-15
        ):
            raise ValueError("funding path must be continuous across bar boundaries")

    initial_margin_rate = 1.0 / leverage_value
    reserve_rate = initial_margin_rate * reserve_fraction
    maximum_adverse_excursion = 0.0
    maximum_favorable_excursion = 0.0
    minimum_equity = initial_margin_rate

    liquidated = False
    liquidation_index: int | None = None
    liquidation_at_open = False
    liquidation_offset: int | None = None

    for i, row in enumerate(mark_bars.iloc[:bar_count].itertuples(index=False)):
        open_price = _positive_finite(row.open, "open")
        high = _positive_finite(row.high, "high")
        low = _positive_finite(row.low, "low")
        close = _positive_finite(row.close, "close")
        if high < low or not low <= open_price <= high or not low <= close <= high:
            raise ValueError("invalid mark prices: expected low <= open/close <= high")

        open_funding_rate = funding_at_open[i]
        close_funding_rate = funding_at_close[i]
        open_return = _directional_return(direction, open_price, entry)
        maximum_adverse_excursion = max(maximum_adverse_excursion, max(0.0, -open_return))
        maximum_favorable_excursion = max(maximum_favorable_excursion, max(0.0, open_return))
        open_equity = initial_margin_rate + open_return + open_funding_rate
        minimum_equity = min(minimum_equity, open_equity)
        if open_equity <= reserve_rate:
            liquidated = True
            liquidation_index = i
            liquidation_at_open = True
            liquidation_offset = i
            break

        if i == exit_index and exit_at_open:
            break

        adverse_price = low if direction == "LONG" else high
        favorable_price = high if direction == "LONG" else low
        adverse_return = _directional_return(direction, adverse_price, entry)
        favorable_return = _directional_return(direction, favorable_price, entry)
        maximum_adverse_excursion = max(maximum_adverse_excursion, max(0.0, -adverse_return))
        maximum_favorable_excursion = max(maximum_favorable_excursion, max(0.0, favorable_return))
        adverse_equity = initial_margin_rate + adverse_return + open_funding_rate
        minimum_equity = min(minimum_equity, adverse_equity)
        if adverse_equity <= reserve_rate:
            liquidated = True
            liquidation_index = i
            liquidation_at_open = False
            liquidation_offset = i + 1
            break

        close_return = _directional_return(direction, close, entry)
        close_equity = initial_margin_rate + close_return + close_funding_rate
        minimum_equity = min(minimum_equity, close_equity)
        if close_equity <= reserve_rate:
            liquidated = True
            liquidation_index = i
            liquidation_at_open = False
            liquidation_offset = i + 1
            break

    return IntrahorizonMarginPath(
        liquidated=liquidated,
        liquidation_index=liquidation_index,
        liquidation_at_open=liquidation_at_open,
        liquidation_exit_offset_hours=liquidation_offset,
        liquidation_gross_return_rate=(-initial_margin_rate if liquidated else None),
        maximum_adverse_excursion_rate=maximum_adverse_excursion,
        maximum_favorable_excursion_rate=maximum_favorable_excursion,
        minimum_equity_rate=minimum_equity,
        initial_margin_rate=initial_margin_rate,
        liquidation_equity_reserve_rate=reserve_rate,
    )


def build_intrahorizon_mark_to_market_path(
    mark_bars: pd.DataFrame,
    *,
    direction: Direction,
    entry_price: float,
    decision_time: pd.Timestamp,
    exit_time: pd.Timestamp,
    final_gross_return_rate: float,
    cumulative_signed_funding_return_at_close_by_bar: Sequence[float] | None = None,
    final_signed_funding_return_rate: float = 0.0,
) -> list[dict[str, object]]:
    """Build a cumulative hourly mark-to-market path through the effective exit.

    Intermediate points use hourly mark closes. The terminal point is replaced by
    the modeled effective exit (barrier, timeout, gap, or conservative liquidation),
    so the path reconciles exactly to the realized research outcome.
    """

    entry = _positive_finite(entry_price, "entry_price")
    decision = pd.Timestamp(decision_time)
    effective_exit = pd.Timestamp(exit_time)
    if decision.tzinfo is None or effective_exit.tzinfo is None:
        raise ValueError("decision_time and exit_time must be timezone-aware")
    decision = decision.tz_convert("UTC")
    effective_exit = effective_exit.tz_convert("UTC")
    if effective_exit < decision:
        raise ValueError("exit_time must not precede decision_time")
    if decision != decision.floor("h") or effective_exit != effective_exit.floor("h"):
        raise ValueError("mark-to-market path timestamps must be hour-aligned")

    final_gross = float(final_gross_return_rate)
    final_funding = float(final_signed_funding_return_rate)
    if not math.isfinite(final_gross) or not math.isfinite(final_funding):
        raise ValueError("terminal mark-to-market returns must be finite")

    required = {"close_time", "close"}
    missing = sorted(required - set(mark_bars.columns))
    if missing:
        raise ValueError(f"mark-to-market path is missing columns: {missing}")
    frame = mark_bars.copy().reset_index(drop=True)
    frame["close_time"] = pd.to_datetime(frame["close_time"], utc=True, errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    if frame["close_time"].isna().any() or frame["close"].isna().any():
        raise ValueError("mark-to-market path contains invalid close values")
    if not frame["close_time"].is_monotonic_increasing or frame["close_time"].duplicated().any():
        raise ValueError("mark-to-market close times must be unique and chronological")
    if not all(timestamp == timestamp.floor("h") for timestamp in frame["close_time"]):
        raise ValueError("mark-to-market close times must be hour-aligned")
    if not all(_positive_finite(value, "close") for value in frame["close"]):
        raise ValueError("mark-to-market close prices must be positive and finite")

    if cumulative_signed_funding_return_at_close_by_bar is None:
        funding_values = [0.0] * len(frame)
    else:
        if len(cumulative_signed_funding_return_at_close_by_bar) != len(frame):
            raise ValueError("cumulative funding path length must match mark bars")
        funding_values = [float(value) for value in cumulative_signed_funding_return_at_close_by_bar]
        if not all(math.isfinite(value) for value in funding_values):
            raise ValueError("cumulative funding path must be finite")

    records: list[dict[str, object]] = []
    if effective_exit > decision:
        records.append(
            {
                "timestamp": decision.isoformat(),
                "gross_return_rate": 0.0,
                "funding_return_rate": 0.0,
            }
        )
    for row, funding_return in zip(frame.itertuples(index=False), funding_values, strict=True):
        close_time = pd.Timestamp(row.close_time)
        if close_time >= effective_exit:
            break
        if close_time <= decision:
            continue
        records.append(
            {
                "timestamp": close_time.isoformat(),
                "gross_return_rate": float(_directional_return(direction, float(row.close), entry)),
                "funding_return_rate": funding_return,
            }
        )
    records.append(
        {
            "timestamp": effective_exit.isoformat(),
            "gross_return_rate": final_gross,
            "funding_return_rate": final_funding,
        }
    )

    timestamps = [pd.Timestamp(item["timestamp"]) for item in records]
    if len(set(timestamps)) != len(timestamps) or timestamps != sorted(timestamps):
        raise ValueError("mark-to-market path timestamps must be unique and chronological")
    expected = list(pd.date_range(decision, effective_exit, freq="h"))
    if timestamps != expected:
        raise ValueError("mark-to-market path must cover every observed hourly boundary")
    return records

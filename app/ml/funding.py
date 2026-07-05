from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

HISTORICAL_FUNDING_SCHEMA_VERSION = "bybit-settlement-timestamp-replay-v1"


@dataclass(frozen=True)
class FundingAggregate:
    cumulative_rate: float
    settlements: int


@dataclass(frozen=True)
class _SymbolFundingTimeline:
    interval: pd.Timedelta
    timestamps: pd.DatetimeIndex
    rates: np.ndarray
    cumulative_rates: np.ndarray
    timestamp_ns: np.ndarray


class HistoricalFundingTimeline:
    """Validated event-time funding settlement history for research labels.

    Bybit publishes one rate per settlement timestamp.  A position opened after
    ``start_time`` is charged only for events in ``(start_time, end_time]``.
    Completeness is checked against the instrument funding interval and an actual
    settlement anchor at or before the position start; missing expected events
    fail closed instead of being interpreted as zero funding.
    """

    def __init__(
        self,
        funding: pd.DataFrame,
        *,
        interval_minutes: Mapping[str, int],
    ) -> None:
        required = {"symbol", "funding_time", "rate"}
        missing = sorted(required - set(funding.columns))
        if missing:
            raise ValueError(f"Historical funding is missing columns: {missing}")
        if not interval_minutes:
            raise ValueError("Historical funding interval mapping is required")

        frame = funding.loc[:, ["symbol", "funding_time", "rate"]].copy()
        frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
        if frame["symbol"].eq("").any():
            raise ValueError("Historical funding contains an empty symbol")
        frame["funding_time"] = pd.to_datetime(frame["funding_time"], utc=True, errors="coerce")
        if frame["funding_time"].isna().any():
            raise ValueError("Historical funding contains an invalid funding_time")
        frame["rate"] = pd.to_numeric(frame["rate"], errors="coerce")
        if frame["rate"].isna().any() or not np.isfinite(frame["rate"].to_numpy(float)).all():
            raise ValueError("Historical funding rates must be finite")
        duplicated = frame.duplicated(["symbol", "funding_time"], keep=False)
        if duplicated.any():
            duplicate_rates = frame.loc[duplicated].groupby(["symbol", "funding_time"])["rate"].nunique()
            if (duplicate_rates > 1).any():
                raise ValueError("Historical funding contains conflicting duplicate settlements")
            frame = frame.drop_duplicates(["symbol", "funding_time"], keep="first")

        self._timelines: dict[str, _SymbolFundingTimeline] = {}
        normalized_intervals: dict[str, int] = {}
        for raw_symbol, raw_interval in interval_minutes.items():
            symbol = str(raw_symbol).strip().upper()
            if not symbol:
                raise ValueError("Funding interval mapping contains an empty symbol")
            if isinstance(raw_interval, bool):
                raise ValueError(f"Funding interval for {symbol} must be a positive integer")
            try:
                interval = int(raw_interval)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"Funding interval for {symbol} must be a positive integer") from exc
            if interval <= 0 or float(raw_interval) != float(interval):
                raise ValueError(f"Funding interval for {symbol} must be a positive integer")
            normalized_intervals[symbol] = interval

        for symbol, group in frame.sort_values(["symbol", "funding_time"]).groupby("symbol", sort=False):
            interval_value = normalized_intervals.get(symbol)
            if interval_value is None:
                raise ValueError(f"Funding interval is missing for {symbol}")
            timestamps = pd.DatetimeIndex(group["funding_time"])
            rates = group["rate"].to_numpy(float)
            self._timelines[symbol] = _SymbolFundingTimeline(
                interval=pd.Timedelta(interval_value, unit="m"),
                timestamps=timestamps,
                rates=rates,
                cumulative_rates=np.concatenate(([0.0], np.cumsum(rates, dtype=float))),
                timestamp_ns=timestamps.asi8,
            )

        self.interval_minutes = normalized_intervals

    @staticmethod
    def _utc_timestamp(value: datetime | pd.Timestamp, field: str) -> pd.Timestamp:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            raise ValueError(f"{field} must be timezone-aware")
        return timestamp.tz_convert("UTC")

    def aggregate(
        self,
        symbol: str,
        *,
        start_time: datetime | pd.Timestamp,
        end_time: datetime | pd.Timestamp,
    ) -> FundingAggregate:
        normalized_symbol = str(symbol).strip().upper()
        timeline = self._timelines.get(normalized_symbol)
        if timeline is None:
            raise ValueError(f"Historical funding is unavailable for {normalized_symbol}")
        start = self._utc_timestamp(start_time, "funding start_time")
        end = self._utc_timestamp(end_time, "funding end_time")
        if end < start:
            raise ValueError("funding end_time must not precede start_time")

        start_ns = int(start.value)
        end_ns = int(end.value)
        anchor_index = int(np.searchsorted(timeline.timestamp_ns, start_ns, side="right") - 1)
        if anchor_index < 0:
            raise ValueError(
                f"Historical funding for {normalized_symbol} has no settlement anchor at or before {start.isoformat()}"
            )

        anchor = timeline.timestamps[anchor_index]
        expected = anchor + timeline.interval
        while expected <= end:
            expected_ns = int(expected.value)
            found = int(np.searchsorted(timeline.timestamp_ns, expected_ns, side="left"))
            if found >= len(timeline.timestamp_ns) or int(timeline.timestamp_ns[found]) != expected_ns:
                raise ValueError(
                    f"Historical funding for {normalized_symbol} is missing expected settlement {expected.isoformat()}"
                )
            expected += timeline.interval

        left = int(np.searchsorted(timeline.timestamp_ns, start_ns, side="right"))
        right = int(np.searchsorted(timeline.timestamp_ns, end_ns, side="right"))
        cumulative_rate = float(timeline.cumulative_rates[right] - timeline.cumulative_rates[left])
        if not np.isfinite(cumulative_rate):
            raise ValueError("Historical funding cumulative rate is non-finite")
        return FundingAggregate(cumulative_rate=cumulative_rate, settlements=right - left)

    def describe(self) -> dict[str, object]:
        if not self._timelines:
            return {
                "schema": HISTORICAL_FUNDING_SCHEMA_VERSION,
                "symbols": 0,
                "settlements": 0,
                "start_time": None,
                "end_time": None,
            }
        timestamps = [timestamp for item in self._timelines.values() for timestamp in item.timestamps]
        return {
            "schema": HISTORICAL_FUNDING_SCHEMA_VERSION,
            "symbols": len(self._timelines),
            "settlements": int(sum(len(item.timestamps) for item in self._timelines.values())),
            "start_time": min(timestamps).isoformat(),
            "end_time": max(timestamps).isoformat(),
            "interval_source": "instrument_spec_history_latest",
            "event_window": "(entry_time, exit_time]",
        }


def funding_return_rate_for_direction(direction: pd.Series, exchange_rate: pd.Series) -> np.ndarray:
    """Convert exchange funding rates to trader-signed returns.

    Positive exchange funding means LONG pays and SHORT receives.
    """

    rate = pd.to_numeric(exchange_rate, errors="coerce").to_numpy(float)
    if not np.isfinite(rate).all():
        raise ValueError("Historical funding rates must be finite")
    direction_values = direction.astype(str)
    if (~direction_values.isin(["LONG", "SHORT"])).any():
        raise ValueError("Historical funding contains an unsupported direction")
    return np.where(direction_values.eq("LONG"), -rate, rate)

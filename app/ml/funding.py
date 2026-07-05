from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

HISTORICAL_FUNDING_SCHEMA_VERSION = "bybit-settlement-timestamp-replay-v2"
FUNDING_INTERVAL_SCHEDULE_SCHEMA_VERSION = "instrument-spec-point-in-time-v1"


@dataclass(frozen=True)
class FundingAggregate:
    cumulative_rate: float
    settlements: int


@dataclass(frozen=True)
class _SymbolIntervalSchedule:
    valid_from: pd.DatetimeIndex
    valid_from_ns: np.ndarray
    intervals: np.ndarray
    fallback_interval: int | None


@dataclass(frozen=True)
class _SymbolFundingTimeline:
    timestamps: pd.DatetimeIndex
    rates: np.ndarray
    cumulative_rates: np.ndarray
    timestamp_ns: np.ndarray


class FundingIntervalSchedule:
    """Point-in-time funding intervals reconstructed from instrument-spec history.

    ``interval_minutes`` remains a backward-compatible fallback for symbols with
    no historical spec rows.  When historical rows exist, the interval effective
    at the queried timestamp is used.  Times before the first locally observed
    spec row use that symbol's earliest observed interval and are explicitly
    reported as a backward assumption rather than silently using the latest value.
    """

    def __init__(
        self,
        interval_minutes: Mapping[str, int],
        *,
        interval_history: pd.DataFrame | None = None,
    ) -> None:
        normalized_fallback = self._normalize_mapping(interval_minutes)
        history = self._normalize_history(interval_history)
        if not normalized_fallback and history.empty:
            raise ValueError("Historical funding interval mapping or history is required")

        history_symbols = set(history["symbol"].unique()) if not history.empty else set()
        symbols = sorted(set(normalized_fallback) | history_symbols)
        schedules: dict[str, _SymbolIntervalSchedule] = {}
        for symbol in symbols:
            symbol_history = history[history["symbol"].eq(symbol)].sort_values(
                "valid_from", kind="mergesort"
            )
            valid_from = pd.DatetimeIndex(symbol_history["valid_from"])
            intervals = symbol_history["funding_interval_minutes"].to_numpy(dtype=np.int64)
            schedules[symbol] = _SymbolIntervalSchedule(
                valid_from=valid_from,
                valid_from_ns=valid_from.asi8,
                intervals=intervals,
                fallback_interval=normalized_fallback.get(symbol),
            )
        self._schedules = schedules
        self.interval_minutes = {
            symbol: int(schedule.intervals[-1])
            if len(schedule.intervals)
            else int(schedule.fallback_interval or 0)
            for symbol, schedule in schedules.items()
        }

    @staticmethod
    def _normalize_interval(raw_symbol: object, raw_interval: object) -> tuple[str, int]:
        symbol = str(raw_symbol).strip().upper()
        if not symbol:
            raise ValueError("Funding interval contains an empty symbol")
        if isinstance(raw_interval, bool):
            raise ValueError(f"Funding interval for {symbol} must be a positive integer")
        try:
            interval = int(raw_interval)
            numeric = float(raw_interval)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Funding interval for {symbol} must be a positive integer") from exc
        if interval <= 0 or not np.isfinite(numeric) or numeric != float(interval):
            raise ValueError(f"Funding interval for {symbol} must be a positive integer")
        return symbol, interval

    @classmethod
    def _normalize_mapping(cls, values: Mapping[str, int]) -> dict[str, int]:
        normalized: dict[str, int] = {}
        for raw_symbol, raw_interval in values.items():
            symbol, interval = cls._normalize_interval(raw_symbol, raw_interval)
            previous = normalized.get(symbol)
            if previous is not None and previous != interval:
                raise ValueError(f"Funding interval mapping contains conflicting values for {symbol}")
            normalized[symbol] = interval
        return normalized

    @classmethod
    def _normalize_history(cls, history: pd.DataFrame | None) -> pd.DataFrame:
        columns = ["symbol", "valid_from", "funding_interval_minutes"]
        if history is None:
            return pd.DataFrame(columns=columns)
        required = set(columns)
        missing = sorted(required - set(history.columns))
        if missing:
            raise ValueError(f"Funding interval history is missing columns: {missing}")
        frame = history.loc[:, columns].copy()
        if frame.empty:
            return frame
        frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
        if frame["symbol"].eq("").any():
            raise ValueError("Funding interval history contains an empty symbol")
        frame["valid_from"] = pd.to_datetime(frame["valid_from"], utc=True, errors="coerce")
        if frame["valid_from"].isna().any():
            raise ValueError("Funding interval history contains an invalid valid_from")

        normalized_intervals: list[int] = []
        for symbol, raw_interval in zip(
            frame["symbol"], frame["funding_interval_minutes"], strict=True
        ):
            _, interval = cls._normalize_interval(symbol, raw_interval)
            normalized_intervals.append(interval)
        frame["funding_interval_minutes"] = normalized_intervals

        duplicated = frame.duplicated(["symbol", "valid_from"], keep=False)
        if duplicated.any():
            conflicts = (
                frame.loc[duplicated]
                .groupby(["symbol", "valid_from"])["funding_interval_minutes"]
                .nunique()
            )
            if (conflicts > 1).any():
                raise ValueError("Funding interval history contains conflicting point-in-time rows")
            frame = frame.drop_duplicates(["symbol", "valid_from"], keep="first")

        frame = frame.sort_values(["symbol", "valid_from"], kind="mergesort").reset_index(drop=True)
        keep = np.ones(len(frame), dtype=bool)
        for _, indices in frame.groupby("symbol", sort=False).groups.items():
            positions = np.asarray(list(indices), dtype=int)
            values = frame.loc[positions, "funding_interval_minutes"].to_numpy(dtype=np.int64)
            if len(values) > 1:
                keep[positions[1:]] = values[1:] != values[:-1]
        return frame.loc[keep].reset_index(drop=True)

    @staticmethod
    def _utc_timestamp(value: datetime | pd.Timestamp, field: str) -> pd.Timestamp:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            raise ValueError(f"{field} must be timezone-aware")
        return timestamp.tz_convert("UTC")

    def _schedule_for(self, symbol: str) -> tuple[str, _SymbolIntervalSchedule]:
        normalized_symbol = str(symbol).strip().upper()
        schedule = self._schedules.get(normalized_symbol)
        if schedule is None:
            raise ValueError(f"Funding interval is missing for {normalized_symbol}")
        return normalized_symbol, schedule

    def interval_at(self, symbol: str, timestamp: datetime | pd.Timestamp) -> int:
        _, schedule = self._schedule_for(symbol)
        point = self._utc_timestamp(timestamp, "funding interval timestamp")
        if len(schedule.valid_from_ns):
            index = int(np.searchsorted(schedule.valid_from_ns, int(point.value), side="right") - 1)
            if index < 0:
                index = 0
            return int(schedule.intervals[index])
        if schedule.fallback_interval is None:
            raise ValueError(f"Funding interval is missing for {str(symbol).strip().upper()}")
        return int(schedule.fallback_interval)

    def intervals_at(self, symbol: str, timestamps: Sequence[pd.Timestamp] | pd.Series) -> np.ndarray:
        _, schedule = self._schedule_for(symbol)
        points = pd.to_datetime(pd.Series(timestamps), utc=True, errors="coerce")
        if points.isna().any():
            raise ValueError("Funding interval timestamps contain an invalid value")
        if len(schedule.valid_from_ns):
            indices = np.searchsorted(schedule.valid_from_ns, points.astype("int64"), side="right") - 1
            indices = np.maximum(indices, 0)
            return schedule.intervals[indices].astype(float)
        if schedule.fallback_interval is None:
            raise ValueError(f"Funding interval is missing for {str(symbol).strip().upper()}")
        return np.full(len(points), float(schedule.fallback_interval), dtype=float)

    def change_times_between(
        self,
        symbol: str,
        *,
        start_exclusive: pd.Timestamp,
        end_inclusive: pd.Timestamp,
    ) -> pd.DatetimeIndex:
        _, schedule = self._schedule_for(symbol)
        if not len(schedule.valid_from_ns):
            return pd.DatetimeIndex([], tz="UTC")
        left = int(np.searchsorted(schedule.valid_from_ns, int(start_exclusive.value), side="right"))
        right = int(np.searchsorted(schedule.valid_from_ns, int(end_inclusive.value), side="right"))
        return schedule.valid_from[left:right]

    def active_intervals_between(
        self,
        symbol: str,
        *,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> list[int]:
        values = [self.interval_at(symbol, start)]
        for change in self.change_times_between(
            symbol, start_exclusive=start, end_inclusive=end
        ):
            values.append(self.interval_at(symbol, change))
        return values

    def describe(
        self,
        *,
        reference_times: Mapping[str, Sequence[pd.Timestamp] | pd.Series] | None = None,
    ) -> dict[str, object]:
        history_symbols = 0
        history_rows = 0
        interval_changes = 0
        backward_assumption_symbols: list[str] = []
        for symbol, schedule in self._schedules.items():
            if len(schedule.valid_from):
                history_symbols += 1
                history_rows += len(schedule.valid_from)
                interval_changes += max(0, len(schedule.valid_from) - 1)
                if reference_times and symbol in reference_times:
                    points = pd.to_datetime(
                        pd.Series(reference_times[symbol]), utc=True, errors="coerce"
                    )
                    if points.isna().any():
                        raise ValueError("Funding interval reference times contain an invalid value")
                    if not points.empty and points.min() < schedule.valid_from[0]:
                        backward_assumption_symbols.append(symbol)
        return {
            "schema": FUNDING_INTERVAL_SCHEDULE_SCHEMA_VERSION,
            "interval_source": (
                "instrument_spec_history_point_in_time"
                if history_symbols
                else "instrument_spec_history_latest_fallback"
            ),
            "symbols": len(self._schedules),
            "history_symbols": history_symbols,
            "history_rows": history_rows,
            "interval_change_count": interval_changes,
            "backward_assumption_symbols": sorted(backward_assumption_symbols),
            "backward_assumption_count": len(backward_assumption_symbols),
        }


class HistoricalFundingTimeline:
    """Validated event-time funding settlement history for research labels.

    Bybit publishes one rate per settlement timestamp. A position opened after
    ``start_time`` is charged only for events in ``(start_time, end_time]``.
    Completeness is checked against the point-in-time instrument funding interval
    schedule and an actual settlement anchor at or before the position start.
    Missing expected events fail closed instead of being interpreted as zero.
    """

    def __init__(
        self,
        funding: pd.DataFrame,
        *,
        interval_minutes: Mapping[str, int],
        interval_history: pd.DataFrame | None = None,
    ) -> None:
        required = {"symbol", "funding_time", "rate"}
        missing = sorted(required - set(funding.columns))
        if missing:
            raise ValueError(f"Historical funding is missing columns: {missing}")

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

        self._interval_schedule = FundingIntervalSchedule(
            interval_minutes,
            interval_history=interval_history,
        )
        self._timelines: dict[str, _SymbolFundingTimeline] = {}
        for symbol, group in frame.sort_values(["symbol", "funding_time"]).groupby(
            "symbol", sort=False
        ):
            self._interval_schedule.interval_at(symbol, group.iloc[0]["funding_time"])
            timestamps = pd.DatetimeIndex(group["funding_time"])
            rates = group["rate"].to_numpy(float)
            self._timelines[symbol] = _SymbolFundingTimeline(
                timestamps=timestamps,
                rates=rates,
                cumulative_rates=np.concatenate(([0.0], np.cumsum(rates, dtype=float))),
                timestamp_ns=timestamps.asi8,
            )

        self.interval_minutes = dict(self._interval_schedule.interval_minutes)

    @staticmethod
    def _utc_timestamp(value: datetime | pd.Timestamp, field: str) -> pd.Timestamp:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            raise ValueError(f"{field} must be timezone-aware")
        return timestamp.tz_convert("UTC")

    @staticmethod
    def _missing(symbol: str, expected: pd.Timestamp) -> ValueError:
        return ValueError(
            f"Historical funding for {symbol} is missing expected settlement {expected.isoformat()}"
        )

    def _validate_pair(
        self,
        symbol: str,
        previous: pd.Timestamp,
        current: pd.Timestamp,
    ) -> None:
        changes = self._interval_schedule.change_times_between(
            symbol,
            start_exclusive=previous,
            end_inclusive=current,
        )
        previous_interval = pd.Timedelta(
            self._interval_schedule.interval_at(symbol, previous), unit="m"
        )
        if changes.empty:
            expected = previous + previous_interval
            if current != expected:
                if current > expected:
                    raise self._missing(symbol, expected)
                raise ValueError(
                    f"Historical funding for {symbol} has unexpected settlement {current.isoformat()} "
                    f"before {expected.isoformat()}"
                )
            return

        first_change = changes[0]
        old_expected = previous + previous_interval
        if old_expected < first_change and old_expected < current:
            raise self._missing(symbol, old_expected)

        active = self._interval_schedule.active_intervals_between(
            symbol,
            start=previous,
            end=current,
        )
        maximum_gap = pd.Timedelta(max(active), unit="m")
        if current - previous > maximum_gap:
            raise self._missing(symbol, previous + maximum_gap)

    def _validate_tail(
        self,
        symbol: str,
        last: pd.Timestamp,
        end: pd.Timestamp,
    ) -> None:
        if last >= end:
            return
        changes = self._interval_schedule.change_times_between(
            symbol,
            start_exclusive=last,
            end_inclusive=end,
        )
        last_interval = pd.Timedelta(self._interval_schedule.interval_at(symbol, last), unit="m")
        if changes.empty:
            expected = last + last_interval
            if expected <= end:
                raise self._missing(symbol, expected)
            return

        first_change = changes[0]
        old_expected = last + last_interval
        if old_expected < first_change and old_expected <= end:
            raise self._missing(symbol, old_expected)
        active = self._interval_schedule.active_intervals_between(symbol, start=last, end=end)
        maximum_gap = pd.Timedelta(max(active), unit="m")
        if end - last >= maximum_gap:
            raise self._missing(symbol, last + maximum_gap)

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

        right = int(np.searchsorted(timeline.timestamp_ns, end_ns, side="right"))
        covered = timeline.timestamps[anchor_index:right]
        for previous, current in zip(covered[:-1], covered[1:], strict=True):
            self._validate_pair(normalized_symbol, previous, current)
        self._validate_tail(normalized_symbol, covered[-1], end)

        left = int(np.searchsorted(timeline.timestamp_ns, start_ns, side="right"))
        cumulative_rate = float(timeline.cumulative_rates[right] - timeline.cumulative_rates[left])
        if not np.isfinite(cumulative_rate):
            raise ValueError("Historical funding cumulative rate is non-finite")
        return FundingAggregate(cumulative_rate=cumulative_rate, settlements=right - left)

    def describe(self) -> dict[str, object]:
        references = {
            symbol: timeline.timestamps for symbol, timeline in self._timelines.items()
        }
        interval_metadata = self._interval_schedule.describe(reference_times=references)
        schedule_metadata = {
            "funding_interval_schedule_schema": interval_metadata["schema"],
            "interval_source": interval_metadata["interval_source"],
            "interval_history_symbols": interval_metadata["history_symbols"],
            "interval_history_rows": interval_metadata["history_rows"],
            "interval_change_count": interval_metadata["interval_change_count"],
            "interval_backward_assumption_symbols": interval_metadata[
                "backward_assumption_symbols"
            ],
        }
        if not self._timelines:
            return {
                "schema": HISTORICAL_FUNDING_SCHEMA_VERSION,
                "symbols": 0,
                "settlements": 0,
                "start_time": None,
                "end_time": None,
                **schedule_metadata,
            }
        timestamps = [timestamp for item in self._timelines.values() for timestamp in item.timestamps]
        return {
            "schema": HISTORICAL_FUNDING_SCHEMA_VERSION,
            "symbols": len(self._timelines),
            "settlements": int(sum(len(item.timestamps) for item in self._timelines.values())),
            "start_time": min(timestamps).isoformat(),
            "end_time": max(timestamps).isoformat(),
            **schedule_metadata,
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

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pandas as pd


def _utc(value: object | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().replace("Z", "+00:00")
        if not normalized:
            return None
        value = datetime.fromisoformat(normalized)
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if not isinstance(value, datetime):
        raise TypeError(f"Expected datetime-like value, got {type(value)!r}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Training data profile timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class TrainingDataProfile:
    """Compact, deterministic description of the data available to training.

    The profile is stored in every model artifact and registry row.  The background
    trainer compares it with the current PostgreSQL coverage, so an old historical
    backfill or a material universe expansion can trigger retraining even when the
    latest candle timestamp barely changed.
    """

    candle_rows: int
    unique_timestamps: int
    symbol_count: int
    symbols: tuple[str, ...]
    start_time: datetime | None
    end_time: datetime | None
    min_rows_per_symbol: int
    median_rows_per_symbol: float
    max_rows_per_symbol: int
    covered_symbols: int
    coverage_ratio: float
    minimum_rows_for_coverage: int
    symbols_sha256: str
    coverage_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candle_rows": self.candle_rows,
            "unique_timestamps": self.unique_timestamps,
            "symbol_count": self.symbol_count,
            "symbols": list(self.symbols),
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "min_rows_per_symbol": self.min_rows_per_symbol,
            "median_rows_per_symbol": self.median_rows_per_symbol,
            "max_rows_per_symbol": self.max_rows_per_symbol,
            "covered_symbols": self.covered_symbols,
            "coverage_ratio": self.coverage_ratio,
            "minimum_rows_for_coverage": self.minimum_rows_for_coverage,
            "symbols_sha256": self.symbols_sha256,
            "coverage_sha256": self.coverage_sha256,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> TrainingDataProfile | None:
        if not value:
            return None
        try:
            raw_symbols = value.get("symbols", [])
            if not isinstance(raw_symbols, (list, tuple)):
                raise TypeError("symbols must be an array")
            symbols = tuple(sorted(str(item).strip().upper() for item in raw_symbols if item))
            if any(not item for item in symbols) or len(symbols) != len(set(symbols)):
                raise ValueError("symbols must be unique and non-empty")
            candle_rows = int(value["candle_rows"])
            unique_timestamps = int(value["unique_timestamps"])
            symbol_count = int(value.get("symbol_count", len(symbols)))
            start_time = _utc(value.get("start_time"))
            end_time = _utc(value.get("end_time"))
            min_rows = int(value.get("min_rows_per_symbol", 0))
            median_rows = float(value.get("median_rows_per_symbol", 0.0))
            max_rows = int(value.get("max_rows_per_symbol", 0))
            covered_symbols = int(value.get("covered_symbols", 0))
            coverage_ratio = float(value.get("coverage_ratio", 0.0))
            minimum_rows = int(value.get("minimum_rows_for_coverage", 0))
            symbols_sha256 = str(value.get("symbols_sha256") or "").lower()
            coverage_sha256 = str(value.get("coverage_sha256") or "").lower()

            if candle_rows < 0 or unique_timestamps < 0 or symbol_count < 0:
                raise ValueError("profile counts cannot be negative")
            if symbol_count != len(symbols):
                raise ValueError("symbol_count does not match symbols")
            if minimum_rows < 0 or min_rows < 0 or max_rows < 0 or covered_symbols < 0:
                raise ValueError("coverage counts cannot be negative")
            if not math.isfinite(median_rows) or median_rows < 0:
                raise ValueError("median rows must be finite and non-negative")
            if not 0 <= covered_symbols <= symbol_count:
                raise ValueError("covered_symbols is outside symbol_count")
            expected_ratio = covered_symbols / symbol_count if symbol_count else 0.0
            if not math.isfinite(coverage_ratio) or not math.isclose(
                coverage_ratio, expected_ratio, rel_tol=0.0, abs_tol=1e-12
            ):
                raise ValueError("coverage_ratio is inconsistent")
            if symbol_count == 0:
                if (
                    any(
                        (
                            candle_rows,
                            unique_timestamps,
                            min_rows,
                            max_rows,
                            covered_symbols,
                        )
                    )
                    or median_rows != 0.0
                ):
                    raise ValueError("empty profile contains non-zero aggregates")
                if start_time is not None or end_time is not None:
                    raise ValueError("empty profile contains timestamps")
            else:
                if unique_timestamps < 1 or unique_timestamps > candle_rows:
                    raise ValueError("unique_timestamps is inconsistent with candle_rows")
                if min_rows > median_rows or median_rows > max_rows:
                    raise ValueError("row aggregates are inconsistent")
                if candle_rows < min_rows * symbol_count or candle_rows > max_rows * symbol_count:
                    raise ValueError("candle_rows is inconsistent with per-symbol bounds")
                if start_time is None or end_time is None or start_time > end_time:
                    raise ValueError("profile time range is invalid")
            if symbols_sha256 != _digest(symbols):
                raise ValueError("symbols_sha256 mismatch")
            if not re.fullmatch(r"[0-9a-f]{64}", coverage_sha256):
                raise ValueError("coverage_sha256 is invalid")

            return cls(
                candle_rows=candle_rows,
                unique_timestamps=unique_timestamps,
                symbol_count=symbol_count,
                symbols=symbols,
                start_time=start_time,
                end_time=end_time,
                min_rows_per_symbol=min_rows,
                median_rows_per_symbol=median_rows,
                max_rows_per_symbol=max_rows,
                covered_symbols=covered_symbols,
                coverage_ratio=coverage_ratio,
                minimum_rows_for_coverage=minimum_rows,
                symbols_sha256=symbols_sha256,
                coverage_sha256=coverage_sha256,
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            return None


def profile_from_symbol_rows(
    rows: Iterable[tuple[str, int, datetime | None, datetime | None]],
    *,
    unique_timestamps: int,
    minimum_rows_for_coverage: int,
) -> TrainingDataProfile:
    if isinstance(unique_timestamps, bool) or int(unique_timestamps) < 0:
        raise ValueError("unique_timestamps must be a non-negative integer")
    if isinstance(minimum_rows_for_coverage, bool) or int(minimum_rows_for_coverage) < 0:
        raise ValueError("minimum_rows_for_coverage must be a non-negative integer")
    normalized: list[tuple[str, int, datetime | None, datetime | None]] = []
    seen: set[str] = set()
    for symbol, count, start_time, end_time in rows:
        normalized_symbol = str(symbol).strip().upper()
        if not normalized_symbol or int(count) < 0:
            continue
        if normalized_symbol in seen:
            raise ValueError(f"Duplicate symbol in training profile: {normalized_symbol}")
        normalized_start = _utc(start_time)
        normalized_end = _utc(end_time)
        normalized_count = int(count)
        if normalized_count == 0:
            if normalized_start is not None or normalized_end is not None:
                raise ValueError(f"Zero-row symbol {normalized_symbol} cannot contain a time range")
        elif normalized_start is None or normalized_end is None or normalized_start > normalized_end:
            raise ValueError(f"Positive-row symbol {normalized_symbol} requires an ordered time range")
        seen.add(normalized_symbol)
        normalized.append((normalized_symbol, normalized_count, normalized_start, normalized_end))
    normalized.sort(key=lambda item: item[0])
    if not normalized and int(unique_timestamps) != 0:
        raise ValueError("Empty training profile cannot contain unique timestamps")

    symbols = tuple(item[0] for item in normalized)
    counts = [item[1] for item in normalized]
    starts = [item[2] for item in normalized if item[2] is not None]
    ends = [item[3] for item in normalized if item[3] is not None]
    covered_symbols = sum(count >= minimum_rows_for_coverage for count in counts)
    symbol_count = len(symbols)
    coverage_payload = [
        {
            "symbol": symbol,
            "rows": count,
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
        }
        for symbol, count, start, end in normalized
    ]
    return TrainingDataProfile(
        candle_rows=sum(counts),
        unique_timestamps=int(unique_timestamps),
        symbol_count=symbol_count,
        symbols=symbols,
        start_time=min(starts) if starts else None,
        end_time=max(ends) if ends else None,
        min_rows_per_symbol=min(counts, default=0),
        median_rows_per_symbol=float(statistics.median(counts)) if counts else 0.0,
        max_rows_per_symbol=max(counts, default=0),
        covered_symbols=covered_symbols,
        coverage_ratio=(covered_symbols / symbol_count) if symbol_count else 0.0,
        minimum_rows_for_coverage=minimum_rows_for_coverage,
        symbols_sha256=_digest(symbols),
        coverage_sha256=_digest(coverage_payload),
    )


def profile_training_frame(
    candles: pd.DataFrame,
    *,
    label_cutoff: datetime | None,
    minimum_rows_for_coverage: int,
    expected_symbols: Iterable[str] | None = None,
) -> TrainingDataProfile:
    if candles.empty:
        return profile_from_symbol_rows(
            [], unique_timestamps=0, minimum_rows_for_coverage=minimum_rows_for_coverage
        )
    frame = candles.copy()
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
    if label_cutoff is not None:
        frame = frame[frame["open_time"] <= pd.Timestamp(label_cutoff)]
    grouped = frame.groupby("symbol", sort=True)["open_time"].agg(["count", "min", "max"])
    rows = [
        (str(symbol), int(values["count"]), values["min"], values["max"])
        for symbol, values in grouped.iterrows()
    ]
    present = {item[0] for item in rows}
    for symbol in sorted({str(item) for item in (expected_symbols or []) if item} - present):
        rows.append((symbol, 0, None, None))
    return profile_from_symbol_rows(
        rows,
        unique_timestamps=int(frame["open_time"].nunique()),
        minimum_rows_for_coverage=minimum_rows_for_coverage,
    )


def compare_training_profiles(
    current: TrainingDataProfile,
    previous: TrainingDataProfile | None,
    *,
    minimum_new_rows: int,
    minimum_growth_ratio: float,
    minimum_new_symbols: int,
    minimum_universe_change_ratio: float,
) -> dict[str, Any]:
    if previous is None:
        return {
            "material_change": True,
            "reasons": ["active_model_missing_training_data_profile"],
            "current": current.to_dict(),
            "previous": None,
        }

    current_symbols = set(current.symbols)
    previous_symbols = set(previous.symbols)
    added = sorted(current_symbols - previous_symbols)
    removed = sorted(previous_symbols - current_symbols)
    union = current_symbols | previous_symbols
    universe_change_ratio = ((len(added) + len(removed)) / len(union)) if union else 0.0
    row_delta = current.candle_rows - previous.candle_rows
    row_growth_ratio = row_delta / max(previous.candle_rows, 1)
    timestamp_delta = current.unique_timestamps - previous.unique_timestamps
    coverage_delta = current.coverage_ratio - previous.coverage_ratio

    reasons: list[str] = []
    if row_delta >= minimum_new_rows and row_growth_ratio >= minimum_growth_ratio:
        reasons.append("material_historical_row_growth")
    if len(added) >= minimum_new_symbols:
        reasons.append("material_new_symbol_coverage")
    if universe_change_ratio >= minimum_universe_change_ratio and (added or removed):
        reasons.append("material_training_universe_change")

    return {
        "material_change": bool(reasons),
        "reasons": reasons,
        "row_delta": row_delta,
        "row_growth_ratio": row_growth_ratio,
        "timestamp_delta": timestamp_delta,
        "coverage_ratio_delta": coverage_delta,
        "added_symbols": added,
        "removed_symbols": removed,
        "universe_change_ratio": universe_change_ratio,
        "coverage_signature_changed": current.coverage_sha256 != previous.coverage_sha256,
        "current": current.to_dict(),
        "previous": previous.to_dict(),
    }

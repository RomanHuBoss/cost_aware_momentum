from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

FEATURE_NAMES = [
    "ret_1h",
    "ret_3h",
    "ret_6h",
    "ret_12h",
    "ret_24h",
    "ema_distance_12",
    "ema_slope_12",
    "atr_pct_14",
    "volume_z_24",
    "breakout_24",
]
FEATURE_LOOKBACK_HOURS = 24
FEATURE_CONTINUITY_COLUMN = "feature_history_contiguous"
FEATURE_WINDOW_START_COLUMN = "feature_window_start_time"
MARKET_BAR_VALID_COLUMN = "market_bar_valid"
FEATURE_CONTINUITY_FLAG = "NON_CONTIGUOUS_HOURLY_HISTORY"
INVALID_MARKET_BAR_FLAG = "INVALID_MARKET_BAR"
BASELINE_FEATURE_SCHEMA_VERSION = "hourly-core-segmented-v3"
_HOURLY_INTERVAL = pd.Timedelta(1, unit="h")
_PRICE_COLUMNS = ("open", "high", "low", "close")
_FLOW_COLUMNS = ("volume", "turnover")


@dataclass(frozen=True)
class FeatureSnapshot:
    values: dict[str, float]
    quality_flags: tuple[str, ...]


def _market_bar_validity(frame: pd.DataFrame) -> pd.Series:
    numeric = frame[[*_PRICE_COLUMNS, *_FLOW_COLUMNS]].to_numpy(dtype=float)
    finite = pd.Series(np.isfinite(numeric).all(axis=1), index=frame.index)
    prices_positive = frame[list(_PRICE_COLUMNS)].gt(0).all(axis=1)
    flows_nonnegative = frame[list(_FLOW_COLUMNS)].ge(0).all(axis=1)
    coherent_ohlc = (
        frame["high"].ge(frame[["open", "close", "low"]].max(axis=1))
        & frame["low"].le(frame[["open", "close", "high"]].min(axis=1))
    )
    valid_interval = (
        frame["open_time"].notna()
        & frame["close_time"].notna()
        & frame["close_time"].sub(frame["open_time"]).eq(_HOURLY_INTERVAL)
    )
    unique_open_time = ~frame.duplicated(["symbol", "open_time"], keep=False)
    return finite & prices_positive & flows_nonnegative & coherent_ohlc & valid_interval & unique_open_time


def build_feature_frame(candles: pd.DataFrame) -> pd.DataFrame:
    if candles.empty:
        return candles.copy()

    required = {"symbol", "open_time", *_PRICE_COLUMNS, *_FLOW_COLUMNS}
    missing = sorted(required - set(candles.columns))
    if missing:
        raise ValueError(f"Candles are missing required columns: {missing}")

    frame = candles.copy()
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True, errors="coerce")
    if "close_time" in frame.columns:
        frame["close_time"] = pd.to_datetime(frame["close_time"], utc=True, errors="coerce")
    else:
        frame["close_time"] = frame["open_time"] + _HOURLY_INTERVAL
    frame = frame.sort_values(["symbol", "open_time"], kind="mergesort").reset_index(drop=True)
    for column in (*_PRICE_COLUMNS, *_FLOW_COLUMNS):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame[MARKET_BAR_VALID_COLUMN] = _market_bar_validity(frame)
    symbol_group = frame.groupby("symbol", sort=False, group_keys=False)
    previous_valid = symbol_group[MARKET_BAR_VALID_COLUMN].shift(1, fill_value=False).astype(bool)
    hourly_step = symbol_group["open_time"].diff().eq(_HOURLY_INTERVAL)
    segment_break = ~frame[MARKET_BAR_VALID_COLUMN] | ~previous_valid | ~hourly_step
    frame["_feature_segment"] = segment_break.groupby(frame["symbol"], sort=False).cumsum()
    segment_keys = [frame["symbol"], frame["_feature_segment"]]
    segmented = frame.groupby(segment_keys, sort=False, group_keys=False)

    valid_close = frame["close"].where(frame[MARKET_BAR_VALID_COLUMN])
    frame["log_close"] = np.log(valid_close)
    log_group = frame.groupby(segment_keys, sort=False, group_keys=False)["log_close"]
    for hours in (1, 3, 6, 12, 24):
        frame[f"ret_{hours}h"] = log_group.diff(hours)

    frame["ema_12"] = segmented["close"].transform(
        lambda series: series.ewm(span=12, adjust=False).mean()
    )
    frame["ema_12"] = frame["ema_12"].where(frame[MARKET_BAR_VALID_COLUMN])
    frame["ema_distance_12"] = frame["close"] / frame["ema_12"] - 1.0
    ema_group = frame.groupby(segment_keys, sort=False, group_keys=False)["ema_12"]
    frame["ema_slope_12"] = ema_group.pct_change(3, fill_method=None)

    prev_close = segmented["close"].shift(1)
    true_range = pd.concat(
        [
            (frame["high"] - frame["low"]).abs(),
            (frame["high"] - prev_close).abs(),
            (frame["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    true_range = true_range.where(frame[MARKET_BAR_VALID_COLUMN])
    frame["atr_14"] = true_range.groupby(segment_keys, sort=False).transform(
        lambda series: series.rolling(14, min_periods=14).mean()
    )
    frame["atr_pct_14"] = frame["atr_14"] / frame["close"]

    volume_mean = segmented["volume"].transform(
        lambda series: series.rolling(24, min_periods=12).mean()
    )
    volume_std = segmented["volume"].transform(
        lambda series: series.rolling(24, min_periods=12).std(ddof=0)
    )
    frame["volume_z_24"] = (frame["volume"] - volume_mean) / volume_std.replace(0, np.nan)

    rolling_high = segmented["high"].transform(
        lambda series: series.shift(1).rolling(24, min_periods=12).max()
    )
    rolling_low = segmented["low"].transform(
        lambda series: series.shift(1).rolling(24, min_periods=12).min()
    )
    upper = (frame["close"] / rolling_high - 1.0).clip(lower=-0.2, upper=0.2)
    lower = (rolling_low / frame["close"] - 1.0).clip(lower=-0.2, upper=0.2)
    frame["breakout_24"] = upper.where(upper.abs() >= lower.abs(), -lower)

    frame[FEATURE_WINDOW_START_COLUMN] = segmented["open_time"].shift(FEATURE_LOOKBACK_HOURS)
    segment_position = segmented.cumcount()
    frame[FEATURE_CONTINUITY_COLUMN] = (
        frame[MARKET_BAR_VALID_COLUMN]
        & segment_position.ge(FEATURE_LOOKBACK_HOURS)
        & frame[FEATURE_WINDOW_START_COLUMN].eq(
            frame["open_time"] - pd.Timedelta(FEATURE_LOOKBACK_HOURS, unit="h")
        )
    )
    frame.drop(columns=["_feature_segment"], inplace=True)
    return frame


def latest_feature_snapshot(candles: pd.DataFrame) -> FeatureSnapshot:
    frame = build_feature_frame(candles)
    if frame.empty:
        return FeatureSnapshot({}, ("NO_DATA",))

    row = frame.iloc[-1]
    latest_symbol = row["symbol"]
    symbol_frame = frame[frame["symbol"].eq(latest_symbol)]
    latest_open_time = row["open_time"]
    required_start = latest_open_time - pd.Timedelta(FEATURE_LOOKBACK_HOURS, unit="h")
    required_window = symbol_frame[
        symbol_frame["open_time"].between(required_start, latest_open_time, inclusive="both")
    ]
    invalid_required_bar = (
        len(required_window) > 0 and not required_window[MARKET_BAR_VALID_COLUMN].all()
    )

    if not bool(row.get(FEATURE_CONTINUITY_COLUMN, False)):
        flags: list[str] = []
        if invalid_required_bar or not bool(row.get(MARKET_BAR_VALID_COLUMN, False)):
            flags.append(INVALID_MARKET_BAR_FLAG)
        flags.append(FEATURE_CONTINUITY_FLAG)
        if len(symbol_frame) < FEATURE_LOOKBACK_HOURS + 1:
            flags.append("SHORT_HISTORY")
        return FeatureSnapshot({}, tuple(flags))

    values: dict[str, float] = {}
    flags = []
    for name in FEATURE_NAMES:
        value = row.get(name)
        if value is None or not math.isfinite(float(value)):
            values[name] = 0.0
            flags.append(f"MISSING_{name.upper()}")
        else:
            values[name] = float(value)
    if len(symbol_frame) < 50:
        flags.append("SHORT_HISTORY")
    return FeatureSnapshot(values, tuple(flags))

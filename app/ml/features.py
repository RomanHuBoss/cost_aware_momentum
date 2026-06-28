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
FEATURE_CONTINUITY_FLAG = "NON_CONTIGUOUS_HOURLY_HISTORY"
BASELINE_FEATURE_SCHEMA_VERSION = "hourly-core-contiguous-v2"
_HOURLY_INTERVAL = pd.Timedelta(1, unit="h")


@dataclass(frozen=True)
class FeatureSnapshot:
    values: dict[str, float]
    quality_flags: tuple[str, ...]


def build_feature_frame(candles: pd.DataFrame) -> pd.DataFrame:
    if candles.empty:
        return candles.copy()
    frame = candles.copy()
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True, errors="coerce")
    frame = frame.sort_values(["symbol", "open_time"]).copy()
    for column in ("open", "high", "low", "close", "volume", "turnover"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    grouped = frame.groupby("symbol", group_keys=False)
    frame["log_close"] = np.log(frame["close"].clip(lower=1e-18))
    for hours in (1, 3, 6, 12, 24):
        frame[f"ret_{hours}h"] = grouped["log_close"].diff(hours)

    frame["ema_12"] = grouped["close"].transform(lambda s: s.ewm(span=12, adjust=False).mean())
    frame["ema_distance_12"] = frame["close"] / frame["ema_12"] - 1.0
    frame["ema_slope_12"] = grouped["ema_12"].pct_change(3)

    prev_close = grouped["close"].shift(1)
    true_range = pd.concat(
        [
            (frame["high"] - frame["low"]).abs(),
            (frame["high"] - prev_close).abs(),
            (frame["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["atr_14"] = true_range.groupby(frame["symbol"]).transform(
        lambda s: s.rolling(14, min_periods=14).mean()
    )
    frame["atr_pct_14"] = frame["atr_14"] / frame["close"]

    volume_mean = grouped["volume"].transform(lambda s: s.rolling(24, min_periods=12).mean())
    volume_std = grouped["volume"].transform(lambda s: s.rolling(24, min_periods=12).std(ddof=0))
    frame["volume_z_24"] = (frame["volume"] - volume_mean) / volume_std.replace(0, np.nan)

    rolling_high = grouped["high"].transform(lambda s: s.shift(1).rolling(24, min_periods=12).max())
    rolling_low = grouped["low"].transform(lambda s: s.shift(1).rolling(24, min_periods=12).min())
    upper = (frame["close"] / rolling_high - 1.0).clip(lower=-0.2, upper=0.2)
    lower = (rolling_low / frame["close"] - 1.0).clip(lower=-0.2, upper=0.2)
    frame["breakout_24"] = upper.where(upper.abs() >= lower.abs(), -lower)

    frame[FEATURE_WINDOW_START_COLUMN] = grouped["open_time"].shift(FEATURE_LOOKBACK_HOURS)
    frame["_hour_step_valid"] = grouped["open_time"].diff().eq(_HOURLY_INTERVAL).astype(int)
    frame[FEATURE_CONTINUITY_COLUMN] = frame.groupby("symbol", group_keys=False)[
        "_hour_step_valid"
    ].transform(
        lambda s: s.rolling(
            FEATURE_LOOKBACK_HOURS,
            min_periods=FEATURE_LOOKBACK_HOURS,
        )
        .sum()
        .eq(FEATURE_LOOKBACK_HOURS)
    )
    frame[FEATURE_CONTINUITY_COLUMN] &= frame[FEATURE_WINDOW_START_COLUMN].eq(
        frame["open_time"] - pd.Timedelta(FEATURE_LOOKBACK_HOURS, unit="h")
    )
    frame.drop(columns=["_hour_step_valid"], inplace=True)

    return frame


def latest_feature_snapshot(candles: pd.DataFrame) -> FeatureSnapshot:
    frame = build_feature_frame(candles)
    if frame.empty:
        return FeatureSnapshot({}, ("NO_DATA",))
    row = frame.iloc[-1]
    if not bool(row.get(FEATURE_CONTINUITY_COLUMN, False)):
        flags = [FEATURE_CONTINUITY_FLAG]
        if len(frame) < FEATURE_LOOKBACK_HOURS + 1:
            flags.append("SHORT_HISTORY")
        return FeatureSnapshot({}, tuple(flags))

    values: dict[str, float] = {}
    flags: list[str] = []
    for name in FEATURE_NAMES:
        value = row.get(name)
        if value is None or not math.isfinite(float(value)):
            values[name] = 0.0
            flags.append(f"MISSING_{name.upper()}")
        else:
            values[name] = float(value)
    if len(frame) < 50:
        flags.append("SHORT_HISTORY")
    return FeatureSnapshot(values, tuple(flags))

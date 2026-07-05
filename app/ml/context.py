from __future__ import annotations

import math

import numpy as np
import pandas as pd

MARKET_CONTEXT_FEATURE_NAMES = [
    "oi_log_change_1h",
    "oi_log_change_24h",
    "basis_bps",
    "basis_change_1h_bps",
    "settled_funding_rate",
    "funding_age_fraction",
    "turnover_oi_log_ratio",
]
MARKET_CONTEXT_COMPLETE_COLUMN = "market_context_complete"
MARKET_CONTEXT_SCHEMA_VERSION = "hourly-oi-basis-settled-funding-turnover-v1"
MARKET_CONTEXT_AVAILABILITY_SCHEMA = "exchange-event-close-live-receipt-v1"
_HOUR = pd.Timedelta(1, unit="h")
_REQUIRED_SOURCES = [
    "last_price_hourly",
    "mark_price_hourly",
    "index_price_hourly",
    "open_interest_hourly",
    "settled_funding",
]


def _normalise_symbol_column(frame: pd.DataFrame, *, source: str) -> pd.DataFrame:
    if "symbol" not in frame.columns:
        raise ValueError(f"{source} is missing required column: symbol")
    result = frame.copy()
    result["symbol"] = result["symbol"].astype(str).str.strip().str.upper()
    if result["symbol"].eq("").any():
        raise ValueError(f"{source} contains an empty symbol")
    return result


def _normalise_candle_close(
    frame: pd.DataFrame,
    *,
    source: str,
    require_turnover: bool = False,
) -> pd.DataFrame:
    required = {"symbol", "close_time", "close"}
    if require_turnover:
        required.add("turnover")
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{source} is missing required columns: {missing}")
    result = _normalise_symbol_column(frame, source=source)
    result["close_time"] = pd.to_datetime(result["close_time"], utc=True, errors="coerce")
    if result["close_time"].isna().any():
        raise ValueError(f"{source} contains invalid close_time values")
    numeric_columns = ["close", *( ["turnover"] if require_turnover else [])]
    for column in numeric_columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    numeric = result[numeric_columns].to_numpy(dtype=float)
    if not np.isfinite(numeric).all():
        raise ValueError(f"{source} contains non-finite numeric values")
    if result["close"].le(0).any():
        raise ValueError(f"{source} close prices must be positive")
    if require_turnover and result["turnover"].lt(0).any():
        raise ValueError(f"{source} turnover must be non-negative")
    if result.duplicated(["symbol", "close_time"], keep=False).any():
        raise ValueError(f"{source} contains duplicate symbol/close_time rows")
    return result.sort_values(["symbol", "close_time"], kind="mergesort").reset_index(drop=True)


def _normalise_open_interest(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"symbol", "event_time", "value"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"open_interest is missing required columns: {missing}")
    result = _normalise_symbol_column(frame, source="open_interest")
    result["event_time"] = pd.to_datetime(result["event_time"], utc=True, errors="coerce")
    result["value"] = pd.to_numeric(result["value"], errors="coerce")
    if result["event_time"].isna().any():
        raise ValueError("open_interest contains invalid event_time values")
    if not np.isfinite(result["value"].to_numpy(dtype=float)).all() or result["value"].le(0).any():
        raise ValueError("open_interest values must be positive and finite")
    if result.duplicated(["symbol", "event_time"], keep=False).any():
        raise ValueError("open_interest contains duplicate symbol/event_time rows")
    return result.sort_values(["symbol", "event_time"], kind="mergesort").reset_index(drop=True)


def _normalise_funding(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"symbol", "funding_time", "rate"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"funding_history is missing required columns: {missing}")
    result = _normalise_symbol_column(frame, source="funding_history")
    result["funding_time"] = pd.to_datetime(result["funding_time"], utc=True, errors="coerce")
    result["rate"] = pd.to_numeric(result["rate"], errors="coerce")
    if result["funding_time"].isna().any():
        raise ValueError("funding_history contains invalid funding_time values")
    if not np.isfinite(result["rate"].to_numpy(dtype=float)).all():
        raise ValueError("funding_history rates must be finite")
    if result.duplicated(["symbol", "funding_time"], keep=False).any():
        raise ValueError("funding_history contains duplicate symbol/funding_time rows")
    return result.sort_values(["symbol", "funding_time"], kind="mergesort").reset_index(drop=True)


def _shifted_value_lookup(
    frame: pd.DataFrame,
    *,
    time_column: str,
    value_column: str,
    shift: pd.Timedelta,
    output_column: str,
) -> pd.DataFrame:
    result = frame[["symbol", time_column, value_column]].copy()
    result[time_column] = result[time_column] + shift
    return result.rename(columns={value_column: output_column})


def _attach_latest_settled_funding(
    decisions: pd.DataFrame,
    funding: pd.DataFrame,
    *,
    funding_interval_minutes: dict[str, int],
) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    for symbol, group in decisions.groupby("symbol", sort=False):
        ordered = group.sort_values("decision_time", kind="mergesort").copy()
        symbol_funding = funding[funding["symbol"].eq(symbol)][
            ["funding_time", "rate"]
        ].sort_values("funding_time", kind="mergesort")
        if symbol_funding.empty:
            ordered["funding_time"] = pd.NaT
            ordered["settled_funding_rate"] = np.nan
        else:
            ordered = pd.merge_asof(
                ordered,
                symbol_funding.rename(columns={"rate": "settled_funding_rate"}),
                left_on="decision_time",
                right_on="funding_time",
                direction="backward",
                allow_exact_matches=True,
            )
        interval_minutes = funding_interval_minutes.get(str(symbol))
        if isinstance(interval_minutes, bool) or not isinstance(interval_minutes, int) or interval_minutes <= 0:
            ordered["funding_age_fraction"] = np.nan
        else:
            age_minutes = (
                ordered["decision_time"] - ordered["funding_time"]
            ).dt.total_seconds() / 60.0
            ordered["funding_age_fraction"] = age_minutes / float(interval_minutes)
            valid_age = age_minutes.ge(0.0) & age_minutes.le(float(interval_minutes) + 1e-9)
            ordered.loc[~valid_age, ["settled_funding_rate", "funding_age_fraction"]] = np.nan
        pieces.append(ordered)
    if not pieces:
        return decisions.assign(
            funding_time=pd.NaT,
            settled_funding_rate=np.nan,
            funding_age_fraction=np.nan,
        )
    return pd.concat(pieces, ignore_index=True).sort_values(
        ["symbol", "decision_time"], kind="mergesort"
    )


def build_market_context_frame(
    candles: pd.DataFrame,
    *,
    mark_candles: pd.DataFrame,
    index_candles: pd.DataFrame,
    open_interest: pd.DataFrame,
    funding_history: pd.DataFrame,
    funding_interval_minutes: dict[str, int],
) -> pd.DataFrame:
    """Build strict hourly market-context features without future-event leakage.

    Historical research uses exchange event/close timestamps because public history
    endpoints do not reconstruct the local receipt time that would have existed in
    the past. Live inference must pre-filter every input by its recorded receipt
    timestamp before calling this function. Missing exact OI/basis history or a
    missing expected funding settlement leaves the row incomplete; no zero or
    forward-fill fallback is applied.
    """

    decision_candles = _normalise_candle_close(
        candles,
        source="last_price_hourly",
        require_turnover=True,
    )
    mark = _normalise_candle_close(mark_candles, source="mark_price_hourly")
    index = _normalise_candle_close(index_candles, source="index_price_hourly")
    oi = _normalise_open_interest(open_interest)
    funding = _normalise_funding(funding_history)

    decisions = decision_candles[["symbol", "close_time", "turnover"]].rename(
        columns={"close_time": "decision_time"}
    )
    mark_values = mark[["symbol", "close_time", "close"]].rename(
        columns={"close_time": "decision_time", "close": "mark_close"}
    )
    index_values = index[["symbol", "close_time", "close"]].rename(
        columns={"close_time": "decision_time", "close": "index_close"}
    )
    result = decisions.merge(
        mark_values,
        how="left",
        on=["symbol", "decision_time"],
        validate="one_to_one",
    ).merge(
        index_values,
        how="left",
        on=["symbol", "decision_time"],
        validate="one_to_one",
    )
    result["basis_bps"] = (result["mark_close"] / result["index_close"] - 1.0) * 10_000.0
    basis_previous = _shifted_value_lookup(
        result,
        time_column="decision_time",
        value_column="basis_bps",
        shift=_HOUR,
        output_column="basis_bps_previous_1h",
    )
    result = result.merge(
        basis_previous,
        how="left",
        on=["symbol", "decision_time"],
        validate="one_to_one",
    )
    result["basis_change_1h_bps"] = result["basis_bps"] - result["basis_bps_previous_1h"]

    oi_current = oi[["symbol", "event_time", "value"]].rename(
        columns={"event_time": "decision_time", "value": "open_interest"}
    )
    oi_previous_1h = _shifted_value_lookup(
        oi,
        time_column="event_time",
        value_column="value",
        shift=_HOUR,
        output_column="open_interest_previous_1h",
    ).rename(columns={"event_time": "decision_time"})
    oi_previous_24h = _shifted_value_lookup(
        oi,
        time_column="event_time",
        value_column="value",
        shift=pd.Timedelta(24, unit="h"),
        output_column="open_interest_previous_24h",
    ).rename(columns={"event_time": "decision_time"})
    result = result.merge(
        oi_current,
        how="left",
        on=["symbol", "decision_time"],
        validate="one_to_one",
    ).merge(
        oi_previous_1h,
        how="left",
        on=["symbol", "decision_time"],
        validate="one_to_one",
    ).merge(
        oi_previous_24h,
        how="left",
        on=["symbol", "decision_time"],
        validate="one_to_one",
    )
    result["oi_log_change_1h"] = np.log(
        result["open_interest"] / result["open_interest_previous_1h"]
    )
    result["oi_log_change_24h"] = np.log(
        result["open_interest"] / result["open_interest_previous_24h"]
    )

    result = _attach_latest_settled_funding(
        result,
        funding,
        funding_interval_minutes=funding_interval_minutes,
    )
    open_interest_notional = result["open_interest"] * result["index_close"]
    result["turnover_oi_log_ratio"] = np.log1p(result["turnover"]) - np.log1p(
        open_interest_notional
    )

    feature_matrix = result[MARKET_CONTEXT_FEATURE_NAMES].to_numpy(dtype=float)
    finite = np.isfinite(feature_matrix).all(axis=1)
    result[MARKET_CONTEXT_COMPLETE_COLUMN] = finite
    result.attrs["market_context"] = {
        "schema": MARKET_CONTEXT_SCHEMA_VERSION,
        "availability_schema": MARKET_CONTEXT_AVAILABILITY_SCHEMA,
        "historical_receipt_time_reconstructed": False,
        "required_sources": list(_REQUIRED_SOURCES),
        "features": list(MARKET_CONTEXT_FEATURE_NAMES),
        "rows": int(len(result)),
        "complete_rows": int(finite.sum()),
        "incomplete_rows": int((~finite).sum()),
    }
    return result.sort_values(["symbol", "decision_time"], kind="mergesort").reset_index(drop=True)


def validate_market_context_values(values: dict[str, object]) -> dict[str, float]:
    validated: dict[str, float] = {}
    for name in MARKET_CONTEXT_FEATURE_NAMES:
        raw = values.get(name)
        if isinstance(raw, bool):
            raise ValueError(f"market context feature {name} must be finite")
        try:
            value = float(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"market context feature {name} must be finite") from exc
        if not math.isfinite(value):
            raise ValueError(f"market context feature {name} must be finite")
        validated[name] = value
    return validated

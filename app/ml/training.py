from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.ml.features import (
    FEATURE_CONTINUITY_COLUMN,
    FEATURE_LOOKBACK_HOURS,
    FEATURE_NAMES,
    FEATURE_WINDOW_START_COLUMN,
    MARKET_BAR_VALID_COLUMN,
    build_feature_frame,
)
from app.ml.labels import triple_barrier_outcome

OUTCOME_CLASSES = np.array(["TP", "SL", "TIMEOUT"])
MODEL_FEATURE_NAMES = [*FEATURE_NAMES, "scenario_direction"]
DEFAULT_STOP_ATR_MULTIPLIER = 1.15
DEFAULT_TP_ATR_MULTIPLIER = 2.20
MODEL_FEATURE_SCHEMA_VERSION = "hourly-barrier-contiguous-v3"
HOURLY_CONTINUITY_SCHEMA = "strict-hourly-v1"
LABEL_PATH_SCHEMA_VERSION = "ohlc-open-first-stop-gap-v1"
TEMPORAL_SPLIT_SCHEMA_VERSION = "decision-and-label-end-purged-v3"
POLICY_METRIC_SCHEMA = "exit-time-open-gap-horizon-independent-cohort-v8"


class TemporalCalibratedBarrierModel:
    """Direction-conditional TP/SL/TIMEOUT classifier with later-window sigmoid calibration.

    The model never emits NO TRADE.  It estimates the outcome distribution for a
    hypothetical LONG or SHORT scenario.  Cost/risk/policy code decides whether
    either scenario is tradable.
    """

    classes_ = OUTCOME_CLASSES.copy()

    def __init__(self, model_type: str = "logistic") -> None:
        if model_type == "logistic":
            self.base = Pipeline(
                [
                    ("scale", StandardScaler()),
                    (
                        "classifier",
                        LogisticRegression(
                            max_iter=3000,
                            class_weight="balanced",
                            random_state=42,
                        ),
                    ),
                ]
            )
        elif model_type == "hist_gradient_boosting":
            self.base = HistGradientBoostingClassifier(
                max_iter=300,
                learning_rate=0.05,
                max_leaf_nodes=31,
                l2_regularization=1.0,
                class_weight="balanced",
                random_state=42,
            )
        else:
            raise ValueError(f"Unsupported model_type: {model_type}")
        self.model_type = model_type
        self.calibrators: dict[str, LogisticRegression] = {}

    @staticmethod
    def _logit(probability: np.ndarray) -> np.ndarray:
        clipped = np.clip(probability, 1e-6, 1 - 1e-6)
        return np.log(clipped / (1 - clipped)).reshape(-1, 1)

    @staticmethod
    def _with_direction_interactions(x: np.ndarray) -> np.ndarray:
        """Add feature×direction terms required by a pooled LONG/SHORT linear model."""

        values = np.asarray(x, dtype=float)
        if values.ndim != 2 or values.shape[1] < 2:
            raise ValueError("Expected a 2D feature matrix ending with scenario_direction")
        direction = values[:, -1:]
        interactions = values[:, :-1] * direction
        return np.column_stack([values, interactions])

    def fit(self, x_train: np.ndarray, y_train: np.ndarray, x_cal: np.ndarray, y_cal: np.ndarray):
        train_classes = set(np.asarray(y_train, dtype=str))
        cal_classes = set(np.asarray(y_cal, dtype=str))
        required = set(self.classes_)
        if not required.issubset(train_classes) or not required.issubset(cal_classes):
            raise ValueError("Training and calibration windows must each contain TP, SL and TIMEOUT outcomes")

        self.base.fit(self._with_direction_interactions(x_train), y_train)
        raw = self._base_probabilities(x_cal)
        self.calibrators = {}
        for index, label in enumerate(self.classes_):
            binary = (np.asarray(y_cal, dtype=str) == label).astype(int)
            calibrator = LogisticRegression(max_iter=1000, random_state=42)
            calibrator.fit(self._logit(raw[:, index]), binary)
            self.calibrators[label] = calibrator
        return self

    def _base_probabilities(self, x: np.ndarray) -> np.ndarray:
        probabilities = self.base.predict_proba(self._with_direction_interactions(x))
        base_classes = [str(item) for item in self.base.classes_]
        mapping = {label: probabilities[:, index] for index, label in enumerate(base_classes)}
        missing = [label for label in self.classes_ if label not in mapping]
        if missing:
            raise ValueError(f"Model is missing required outcome classes: {missing}")
        return np.column_stack([mapping[label] for label in self.classes_])

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        raw = self._base_probabilities(x)
        if not self.calibrators:
            raise RuntimeError("Model has not been calibrated")
        calibrated = np.column_stack(
            [
                self.calibrators[label].predict_proba(self._logit(raw[:, index]))[:, 1]
                for index, label in enumerate(self.classes_)
            ]
        )
        totals = calibrated.sum(axis=1, keepdims=True)
        return calibrated / np.where(totals <= 0, 1.0, totals)

    def predict(self, x: np.ndarray) -> np.ndarray:
        probabilities = self.predict_proba(x)
        return self.classes_[np.argmax(probabilities, axis=1)]


@dataclass(frozen=True)
class DatasetSplit:
    x_train: np.ndarray
    y_train: np.ndarray
    x_cal: np.ndarray
    y_cal: np.ndarray
    x_test: np.ndarray
    y_test: np.ndarray
    test_meta: pd.DataFrame


@dataclass(frozen=True)
class PolicyEvaluationConfig:
    fee_rate_round_trip: float
    slippage_rate: float
    stop_gap_reserve_rate: float
    min_net_rr: float
    min_net_ev_r: float
    timeout_return_rate: float = -0.002
    horizon_hours: int | None = None


def minimum_hourly_history_timestamps_for_quality_gate(
    *,
    horizon_hours: int,
    minimum_holdout_rows: int,
    minimum_holdout_span_hours: int,
) -> int:
    """Return the theoretical minimum raw hourly timestamps for the split/gate.

    The calculation mirrors :func:`chronological_split` for one continuously
    sampled symbol. Each decision timestamp emits the required LONG/SHORT pair,
    the final 15% window starts after the horizon-sized embargo, and feature/label
    construction consumes the 24-hour feature warm-up plus the future horizon.

    This is a necessary precondition, not a promise that gapped or invalid market
    data will produce a valid candidate. Those cases remain fail-closed later.
    """

    values = {
        "horizon_hours": horizon_hours,
        "minimum_holdout_rows": minimum_holdout_rows,
        "minimum_holdout_span_hours": minimum_holdout_span_hours,
    }
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise TypeError(f"{name} must be an integer")
        if int(value) <= 0:
            raise ValueError(f"{name} must be positive")

    horizon = int(horizon_hours)
    required_test_timestamps = max(
        int(np.ceil(int(minimum_holdout_rows) / 2)),
        int(minimum_holdout_span_hours) + 1,
        45,  # chronological_split requires at least 90 LONG/SHORT test rows
    )

    labeled_timestamps = 300
    while True:
        train_index = int(labeled_timestamps * 0.70)
        calibration_index = int(labeled_timestamps * 0.85)
        train_timestamps = train_index - horizon
        calibration_timestamps = calibration_index - train_index - 2 * horizon
        test_timestamps = labeled_timestamps - calibration_index - horizon
        if (
            train_timestamps >= 45
            and calibration_timestamps >= 45
            and test_timestamps >= required_test_timestamps
        ):
            return labeled_timestamps + FEATURE_LOOKBACK_HOURS + horizon
        labeled_timestamps += 1


def make_barrier_dataset(
    candles: pd.DataFrame,
    horizon: int = 8,
    *,
    stop_atr_multiplier: float = DEFAULT_STOP_ATR_MULTIPLIER,
    tp_atr_multiplier: float = DEFAULT_TP_ATR_MULTIPLIER,
) -> pd.DataFrame:
    """Build point-in-time LONG/SHORT scenarios from strict hourly windows.

    Every feature row must have a complete 24-hour lookback and every label must
    use exactly the next ``horizon`` hourly candles. Missing or duplicated bars
    invalidate only the affected timestamps instead of silently stretching the
    economic meaning of row-based returns, rolling statistics, or labels.

    Hourly OHLC cannot reveal the order of TP/SL touches within one bar, therefore
    ambiguous bars are resolved conservatively as SL. A future lower-timeframe
    implementation can replace this fallback without changing the model contract.
    """

    if isinstance(horizon, bool) or not isinstance(horizon, (int, np.integer)) or horizon <= 0:
        raise ValueError("horizon must be a positive integer")
    for name, value in {
        "stop_atr_multiplier": stop_atr_multiplier,
        "tp_atr_multiplier": tp_atr_multiplier,
    }.items():
        parsed = float(value)
        if not np.isfinite(parsed) or parsed <= 0:
            raise ValueError(f"{name} must be positive and finite")
    frame = build_feature_frame(candles).sort_values(["symbol", "open_time"]).reset_index(drop=True)
    rows: list[dict] = []
    diagnostics: dict[str, int | str] = {
        "schema": HOURLY_CONTINUITY_SCHEMA,
        "feature_lookback_hours": FEATURE_LOOKBACK_HOURS,
        "label_horizon_hours": int(horizon),
        "candidate_timestamps": 0,
        "labeled_timestamps": 0,
        "skipped_feature_gap_timestamps": 0,
        "skipped_label_gap_timestamps": 0,
        "skipped_invalid_label_bar_timestamps": 0,
        "skipped_incomplete_direction_pair_timestamps": 0,
    }
    hourly = pd.Timedelta(1, unit="h")

    for symbol, group in frame.groupby("symbol", sort=False):
        group = group.reset_index(drop=True)
        if len(group) <= horizon:
            continue
        diagnostics["candidate_timestamps"] += len(group) - horizon
        for index in range(0, len(group) - horizon):
            current = group.iloc[index]
            if not bool(current.get(FEATURE_CONTINUITY_COLUMN, False)):
                diagnostics["skipped_feature_gap_timestamps"] += 1
                continue

            future = group.iloc[index + 1 : index + 1 + horizon][
                [
                    "open_time",
                    "close_time",
                    "open",
                    "high",
                    "low",
                    "close",
                    MARKET_BAR_VALID_COLUMN,
                ]
            ]
            if len(future) < horizon:
                continue
            source_open_time = current["open_time"]
            decision_time = current["close_time"]
            if pd.isna(decision_time) or decision_time - source_open_time != hourly:
                diagnostics["skipped_feature_gap_timestamps"] += 1
                continue
            expected_times = pd.date_range(
                start=decision_time,
                periods=horizon,
                freq=hourly,
            )
            actual_times = pd.DatetimeIndex(future["open_time"])
            actual_close_times = pd.DatetimeIndex(future["close_time"])
            expected_close_times = expected_times + hourly
            if not actual_times.equals(expected_times) or not actual_close_times.equals(
                expected_close_times
            ):
                diagnostics["skipped_label_gap_timestamps"] += 1
                continue
            if not future[MARKET_BAR_VALID_COLUMN].all():
                diagnostics["skipped_invalid_label_bar_timestamps"] += 1
                continue

            values = [current.get(name) for name in FEATURE_NAMES]
            if any(value is None or not np.isfinite(float(value)) for value in values):
                continue
            entry = float(current["close"])
            atr = float(current.get("atr_14", np.nan))
            if not np.isfinite(entry) or entry <= 0 or not np.isfinite(atr) or atr <= 0:
                continue
            label_end_time = future.iloc[-1]["close_time"]

            direction_rows: list[dict] = []
            for direction, direction_code in (("LONG", 1.0), ("SHORT", -1.0)):
                if direction == "LONG":
                    stop = entry - atr * stop_atr_multiplier
                    take_profit = entry + atr * tp_atr_multiplier
                    sign = 1.0
                else:
                    stop = entry + atr * stop_atr_multiplier
                    take_profit = entry - atr * tp_atr_multiplier
                    sign = -1.0
                if stop <= 0 or take_profit <= 0:
                    direction_rows = []
                    break
                result = triple_barrier_outcome(
                    future,
                    direction=direction,
                    stop=stop,
                    take_profit=take_profit,
                    conservative_ambiguity=True,
                )
                realized_return = sign * (float(result.exit_price) - entry) / entry
                row = {name: float(current[name]) for name in FEATURE_NAMES}
                row.update(
                    {
                        "scenario_direction": direction_code,
                        "open_time": source_open_time,
                        "source_open_time": source_open_time,
                        "decision_time": decision_time,
                        "feature_window_start_time": current[FEATURE_WINDOW_START_COLUMN],
                        "source_label_end_open_time": future.iloc[-1]["open_time"],
                        "label_end_time": label_end_time,
                        "symbol": symbol,
                        "direction": direction,
                        "target": result.outcome,
                        "ambiguous": bool(result.ambiguous),
                        "exit_index": int(result.exit_index),
                        "exit_at_open": bool(result.exit_at_open),
                        "realized_gross_return": float(realized_return),
                        "barrier_upside_rate": float(abs(take_profit - entry) / entry),
                        "barrier_downside_rate": float(abs(entry - stop) / entry),
                    }
                )
                direction_rows.append(row)
            if len(direction_rows) == 2:
                rows.extend(direction_rows)
                diagnostics["labeled_timestamps"] += 1
            else:
                diagnostics["skipped_incomplete_direction_pair_timestamps"] += 1

    dataset = pd.DataFrame.from_records(rows)
    dataset.attrs["hourly_continuity"] = diagnostics
    dataset.attrs["label_path_schema"] = LABEL_PATH_SCHEMA_VERSION
    return dataset


def validate_directional_scenario_pairs(frame: pd.DataFrame, *, context: str) -> None:
    """Require one LONG and one SHORT row for every decision-time/symbol cohort."""

    required_columns = {"decision_time", "symbol", "direction"}
    missing_columns = sorted(required_columns - set(frame.columns))
    if missing_columns:
        raise ValueError(f"{context} is missing directional-pair columns: {missing_columns}")
    if frame.empty:
        return

    invalid_groups = 0
    for directions in frame.groupby(
        ["decision_time", "symbol"], dropna=False, sort=False
    )["direction"]:
        values = [str(value) for value in directions[1]]
        if len(values) != 2 or set(values) != {"LONG", "SHORT"}:
            invalid_groups += 1
    if invalid_groups:
        raise ValueError(
            f"{context} requires exactly one LONG and one SHORT per decision_time/symbol; "
            f"found {invalid_groups} incomplete or duplicated cohort(s)"
        )


def validate_policy_evaluation_metadata(
    frame: pd.DataFrame,
    *,
    context: str,
    horizon_hours: int | None = None,
    require_barrier_return_consistency: bool = False,
) -> pd.DataFrame:
    """Validate all directional rows before ranking can hide a corrupt scenario."""

    required_columns = {
        "decision_time",
        "symbol",
        "direction",
        "target",
        "exit_index",
        "exit_at_open",
        "realized_gross_return",
        "barrier_upside_rate",
        "barrier_downside_rate",
    }
    missing_columns = sorted(required_columns - set(frame.columns))
    if missing_columns:
        raise ValueError(f"{context} metadata is missing columns: {missing_columns}")

    result = frame.copy().reset_index(drop=True)
    result["decision_time"] = pd.to_datetime(
        result["decision_time"], utc=True, errors="coerce"
    )
    if result["decision_time"].isna().any():
        raise ValueError(f"{context} contains invalid decision_time")
    if (~result["direction"].isin(["LONG", "SHORT"])).any():
        raise ValueError(f"{context} contains an unsupported direction")
    if (~result["target"].astype(str).isin([str(value) for value in OUTCOME_CLASSES])).any():
        raise ValueError(f"{context} target contains an unsupported outcome")
    validate_directional_scenario_pairs(result, context=context)

    exit_index = pd.to_numeric(result["exit_index"], errors="coerce")
    if (
        exit_index.isna().any()
        or not np.isfinite(exit_index.to_numpy(float)).all()
        or (exit_index < 0).any()
        or not np.allclose(exit_index, np.floor(exit_index))
    ):
        raise ValueError(f"{context} exit_index must contain non-negative integers")
    if horizon_hours is not None:
        if horizon_hours <= 0:
            raise ValueError("horizon_hours must be positive")
        if (exit_index >= horizon_hours).any():
            raise ValueError(f"{context} exit_index must be within the configured label horizon")
    result["exit_index"] = exit_index.astype(int)
    valid_open_flags = result["exit_at_open"].map(
        lambda value: isinstance(value, (bool, np.bool_))
    )
    if not valid_open_flags.all():
        raise ValueError(f"{context} exit_at_open must contain booleans")
    result["exit_at_open"] = result["exit_at_open"].astype(bool)
    target = result["target"].astype(str)
    if (target.eq("TIMEOUT") & result["exit_at_open"]).any():
        raise ValueError(f"{context} TIMEOUT cannot exit at bar open")
    exit_offset_hours = result["exit_index"] + (~result["exit_at_open"]).astype(int)
    result["exit_time"] = result["decision_time"] + pd.to_timedelta(
        exit_offset_hours, unit="h"
    )

    numeric_columns = [
        "realized_gross_return",
        "barrier_upside_rate",
        "barrier_downside_rate",
    ]
    for column in numeric_columns:
        values = pd.to_numeric(result[column], errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy(float)).all():
            raise ValueError(f"{context} {column} must be finite")
        result[column] = values.astype(float)
    if (result[["barrier_upside_rate", "barrier_downside_rate"]] <= 0).any().any():
        raise ValueError(f"{context} barrier rates must be positive")

    is_long = result["direction"].eq("LONG")
    tp_exit_ratio = np.where(
        is_long,
        1.0 + result["barrier_upside_rate"],
        1.0 - result["barrier_upside_rate"],
    )
    sl_exit_ratio = np.where(
        is_long,
        1.0 - result["barrier_downside_rate"],
        1.0 + result["barrier_downside_rate"],
    )
    realized_exit_ratio = np.where(
        is_long,
        1.0 + result["realized_gross_return"],
        1.0 - result["realized_gross_return"],
    )
    if (tp_exit_ratio <= 0).any() or (sl_exit_ratio <= 0).any() or (realized_exit_ratio <= 0).any():
        raise ValueError(f"{context} produced a non-positive exit notional ratio")

    if require_barrier_return_consistency:
        tolerance = 1e-10 + 1e-7 * result[
            ["barrier_upside_rate", "barrier_downside_rate"]
        ].max(axis=1)
        # Generated TP labels execute at the exact modeled barrier. SL may be
        # worse than the barrier because a gap can jump through the stop. TIMEOUT
        # must remain strictly inside both barriers; otherwise its label is false.
        tp_mismatch = target.eq("TP") & (
            (result["realized_gross_return"] - result["barrier_upside_rate"]).abs()
            > tolerance
        )
        sl_mismatch = target.eq("SL") & (
            result["realized_gross_return"]
            > -result["barrier_downside_rate"] + tolerance
        )
        timeout_mismatch = target.eq("TIMEOUT") & (
            (result["realized_gross_return"] >= result["barrier_upside_rate"] - tolerance)
            | (
                result["realized_gross_return"]
                <= -result["barrier_downside_rate"] + tolerance
            )
        )
        if tp_mismatch.any() or sl_mismatch.any() or timeout_mismatch.any():
            raise ValueError(f"{context} realized outcome is inconsistent with its barrier")

    if "label_end_time" in result.columns:
        label_end = pd.to_datetime(result["label_end_time"], utc=True, errors="coerce")
        if label_end.isna().any() or (result["exit_time"] > label_end).any():
            raise ValueError(f"{context} exit_time exceeds label availability")
        if horizon_hours is not None:
            expected_label_end = result["decision_time"] + pd.to_timedelta(
                horizon_hours, unit="h"
            )
            if not label_end.equals(expected_label_end):
                raise ValueError(
                    f"{context} label_end_time does not match the configured label horizon"
                )
        result["label_end_time"] = label_end
    return result


def filter_single_active_trade_per_symbol(
    trades: pd.DataFrame,
    *,
    context: str,
) -> tuple[pd.DataFrame, int]:
    """Apply the live one-active-plan-per-symbol constraint to research trades.

    A modeled exit at a timestamp releases the symbol before a new decision at
    that same timestamp. Candidates that arrive strictly before the prior
    modeled exit are excluded without extending the active interval.
    """

    required_columns = {"decision_time", "exit_time", "symbol"}
    missing_columns = sorted(required_columns - set(trades.columns))
    if missing_columns:
        raise ValueError(f"{context} is missing overlap columns: {missing_columns}")
    if trades.empty:
        return trades.copy().reset_index(drop=True), 0

    ordered = trades.copy()
    ordered["decision_time"] = pd.to_datetime(
        ordered["decision_time"], utc=True, errors="coerce"
    )
    ordered["exit_time"] = pd.to_datetime(
        ordered["exit_time"], utc=True, errors="coerce"
    )
    if ordered[["decision_time", "exit_time"]].isna().any().any():
        raise ValueError(f"{context} contains invalid overlap timestamps")
    if (ordered["exit_time"] < ordered["decision_time"]).any():
        raise ValueError(f"{context} contains an exit before its decision")
    if ordered["symbol"].isna().any() or ordered["symbol"].astype(str).str.strip().eq("").any():
        raise ValueError(f"{context} contains an invalid symbol")

    ordered = ordered.sort_values(
        ["decision_time", "symbol", "exit_time"], kind="mergesort"
    )
    active_until: dict[str, pd.Timestamp] = {}
    accepted_indexes: list[object] = []
    blocked = 0
    for index, row in ordered.iterrows():
        symbol = str(row["symbol"])
        decision_time = pd.Timestamp(row["decision_time"])
        exit_time = pd.Timestamp(row["exit_time"])
        prior_exit = active_until.get(symbol)
        if prior_exit is not None and decision_time < prior_exit:
            blocked += 1
            continue
        accepted_indexes.append(index)
        active_until[symbol] = exit_time

    accepted = ordered.loc[accepted_indexes].sort_values(
        ["decision_time", "symbol"], kind="mergesort"
    )
    return accepted.reset_index(drop=True), blocked


def chronological_split(frame: pd.DataFrame, purge_rows: int = 12) -> DatasetSplit:
    """Split whole timestamps while purging samples by their actual label end time.

    ``purge_rows`` remains the post-boundary embargo in hours for backward-compatible
    hourly research semantics.  Label overlap is controlled independently through the
    explicit ``label_end_time`` emitted by :func:`make_barrier_dataset`, so missing or
    irregular candles cannot make a nominal N-hour purge shorter than the data used by
    an N-bar label.
    """

    if isinstance(purge_rows, bool) or not isinstance(purge_rows, (int, np.integer)):
        raise TypeError("purge_rows must be an integer number of hours")
    purge_hours = int(purge_rows)
    if purge_hours < 0:
        raise ValueError("purge_rows must be non-negative")

    required_columns = {"decision_time", "label_end_time", "exit_at_open"}
    missing_columns = sorted(required_columns - set(frame.columns))
    if missing_columns:
        raise ValueError(f"Chronological split requires columns: {missing_columns}")

    frame = frame.copy()
    frame["decision_time"] = pd.to_datetime(
        frame["decision_time"], utc=True, errors="coerce"
    )
    frame["label_end_time"] = pd.to_datetime(
        frame["label_end_time"], utc=True, errors="coerce"
    )
    if frame[["decision_time", "label_end_time"]].isna().any().any():
        raise ValueError("Chronological split contains invalid decision_time or label_end_time")
    if (frame["label_end_time"] <= frame["decision_time"]).any():
        raise ValueError("Every label_end_time must be later than its decision_time")
    valid_open_flags = frame["exit_at_open"].map(
        lambda value: isinstance(value, (bool, np.bool_))
    )
    if not valid_open_flags.all():
        raise ValueError("Chronological split exit_at_open must contain booleans")
    frame["exit_at_open"] = frame["exit_at_open"].astype(bool)
    validate_directional_scenario_pairs(frame, context="Chronological split")

    frame = frame.sort_values(["decision_time", "symbol", "direction"]).reset_index(drop=True)
    unique_times = pd.Index(frame["decision_time"].drop_duplicates().sort_values())
    n_times = len(unique_times)
    if n_times < 300:
        raise ValueError("At least 300 unique labeled timestamps are required")
    train_index = int(n_times * 0.70)
    cal_index = int(n_times * 0.85)
    train_boundary = unique_times[train_index]
    cal_boundary = unique_times[cal_index]
    embargo = pd.Timedelta(purge_hours, unit="h")

    train = frame[frame["label_end_time"] < train_boundary]
    cal = frame[
        (frame["decision_time"] >= train_boundary + embargo)
        & (frame["label_end_time"] < cal_boundary)
    ]
    test = frame[frame["decision_time"] >= cal_boundary + embargo]
    if min(len(train), len(cal), len(test)) < 90:
        raise ValueError("Chronological split produced an undersized window")
    if train["decision_time"].max() >= cal["decision_time"].min():
        raise AssertionError("Train/calibration windows overlap")
    if cal["decision_time"].max() >= test["decision_time"].min():
        raise AssertionError("Calibration/final-holdout windows overlap")
    if train["label_end_time"].max() >= cal["decision_time"].min():
        raise AssertionError("Train labels overlap calibration features")
    if cal["label_end_time"].max() >= test["decision_time"].min():
        raise AssertionError("Calibration labels overlap final-holdout features")

    meta_columns = [
        "decision_time",
        "open_time",
        "label_end_time",
        "symbol",
        "direction",
        "target",
        "ambiguous",
        "exit_index",
        "exit_at_open",
        "realized_gross_return",
        "barrier_upside_rate",
        "barrier_downside_rate",
    ]
    return DatasetSplit(
        train[MODEL_FEATURE_NAMES].to_numpy(float),
        train["target"].to_numpy(),
        cal[MODEL_FEATURE_NAMES].to_numpy(float),
        cal["target"].to_numpy(),
        test[MODEL_FEATURE_NAMES].to_numpy(float),
        test["target"].to_numpy(),
        test[meta_columns].reset_index(drop=True),
    )


def _expected_calibration_error(y_true: np.ndarray, probabilities: np.ndarray, bins: int = 10) -> float:
    errors: list[float] = []
    weights: list[float] = []
    edges = np.linspace(0.0, 1.0, bins + 1)
    for lower, upper in zip(edges[:-1], edges[1:], strict=True):
        mask = (probabilities >= lower) & (
            (probabilities < upper) if upper < 1.0 else (probabilities <= upper)
        )
        if not mask.any():
            continue
        errors.append(abs(float(probabilities[mask].mean()) - float(y_true[mask].mean())))
        weights.append(float(mask.mean()))
    return float(np.dot(errors, weights)) if weights else 0.0


def validate_outcome_probability_matrix(
    probabilities: np.ndarray,
    classes: np.ndarray | list[str],
    *,
    expected_rows: int | None = None,
) -> tuple[np.ndarray, dict[str, int]]:
    """Validate and index an exact TP/SL/TIMEOUT probability simplex."""

    labels = [str(label) for label in classes]
    if len(labels) != len(set(labels)):
        raise ValueError("Model outcome classes must be unique")
    required = [str(label) for label in OUTCOME_CLASSES]
    if sorted(labels) != sorted(required):
        raise ValueError(f"Model must declare exactly the required outcome classes: {required}")

    values = np.asarray(probabilities, dtype=float)
    if values.ndim != 2 or values.shape[1] != len(labels):
        raise ValueError("probability matrix shape does not match declared classes")
    if expected_rows is not None and values.shape[0] != expected_rows:
        raise ValueError("probability rows do not match expected observations")
    if not np.isfinite(values).all():
        raise ValueError("probability matrix contains non-finite values")
    if ((values < 0.0) | (values > 1.0)).any():
        raise ValueError("probability matrix contains values outside [0, 1]")
    if not np.allclose(values.sum(axis=1), 1.0, rtol=1e-7, atol=1e-9):
        raise ValueError("probability rows must sum to 1")
    return values, {label: labels.index(label) for label in required}


def _ordered_multiclass_log_loss(
    y_true: np.ndarray, probabilities: np.ndarray, classes: np.ndarray
) -> float:
    """Calculate multiclass log loss without reordering declared probability columns."""

    targets = np.asarray(y_true, dtype=str)
    values, class_to_index = validate_outcome_probability_matrix(
        probabilities, classes, expected_rows=len(targets)
    )
    unknown = sorted(set(targets) - set(class_to_index))
    if unknown:
        raise ValueError(f"Targets contain unknown outcome classes: {unknown}")

    true_indexes = np.fromiter(
        (class_to_index[label] for label in targets),
        dtype=int,
        count=len(targets),
    )
    true_probabilities = values[np.arange(len(targets)), true_indexes]
    epsilon = np.finfo(float).eps
    return float(-np.mean(np.log(np.clip(true_probabilities, epsilon, 1.0))))

def _class_prior_probabilities(y_train: np.ndarray, classes: np.ndarray, rows: int) -> np.ndarray:
    labels = np.asarray(classes, dtype=str)
    targets = np.asarray(y_train, dtype=str)
    priors = np.asarray([(targets == label).mean() for label in labels], dtype=float)
    if not np.isfinite(priors).all() or priors.sum() <= 0:
        raise ValueError("Training targets cannot produce valid class-prior probabilities")
    priors /= priors.sum()
    return np.tile(priors, (rows, 1))


def _holdout_time_bounds(test_meta: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp, float]:
    if "decision_time" not in test_meta.columns:
        raise ValueError("Holdout metadata is missing decision_time")
    decision_times = pd.to_datetime(test_meta["decision_time"], utc=True, errors="coerce")
    if decision_times.empty or decision_times.isna().any():
        raise ValueError("Holdout metadata contains invalid decision_time")
    start = decision_times.min()
    end = decision_times.max()
    span_hours = float((end - start).total_seconds() / 3600.0)
    if not np.isfinite(span_hours) or span_hours < 0:
        raise ValueError("Holdout decision-time span must be finite and non-negative")
    return start, end, span_hours


def _count_horizon_separated_cohorts(
    decision_times: pd.Series,
    *,
    horizon_hours: int,
) -> int:
    """Count non-overlapping label windows using a deterministic greedy schedule."""

    if isinstance(horizon_hours, bool) or not isinstance(
        horizon_hours, (int, np.integer)
    ):
        raise TypeError("horizon_hours must be an integer")
    if int(horizon_hours) <= 0:
        raise ValueError("horizon_hours must be positive")
    values = pd.to_datetime(decision_times, utc=True, errors="coerce")
    if values.isna().any():
        raise ValueError("Policy cohorts contain invalid decision_time")
    unique_times = sorted(pd.Timestamp(value) for value in values.unique())
    next_eligible: pd.Timestamp | None = None
    count = 0
    separation = pd.to_timedelta(int(horizon_hours), unit="h")
    for decision_time in unique_times:
        if next_eligible is not None and decision_time < next_eligible:
            continue
        count += 1
        next_eligible = decision_time + separation
    return count


def evaluate_model(model: TemporalCalibratedBarrierModel, split: DatasetSplit) -> dict:
    probabilities = model.predict_proba(split.x_test)
    predicted = model.predict(split.x_test)
    y = np.asarray(split.y_test, dtype=str)
    classes = np.asarray(model.classes_, dtype=str)
    calibrated_log_loss = _ordered_multiclass_log_loss(y, probabilities, classes)
    prior_probabilities = _class_prior_probabilities(split.y_train, classes, len(y))
    class_prior_log_loss = _ordered_multiclass_log_loss(y, prior_probabilities, classes)
    class_to_index = {label: index for index, label in enumerate(classes)}
    y_index = np.array([class_to_index[label] for label in y])
    one_hot = np.eye(len(classes))[y_index]
    holdout_start, holdout_end, holdout_span_hours = _holdout_time_bounds(split.test_meta)

    metrics: dict[str, object] = {
        "classification_metric_schema": "ordered-probability-v2",
        "rows": int(len(y)),
        "holdout_start_time": holdout_start.isoformat(),
        "holdout_end_time": holdout_end.isoformat(),
        "holdout_span_hours": holdout_span_hours,
        "holdout_unique_timestamps": int(
            pd.to_datetime(split.test_meta["decision_time"], utc=True).nunique()
        ),
        "accuracy": float(accuracy_score(y, predicted)),
        "log_loss": calibrated_log_loss,
        "class_prior_log_loss": class_prior_log_loss,
        "log_loss_skill_vs_prior": class_prior_log_loss - calibrated_log_loss,
        "uniform_log_loss": float(np.log(len(classes))),
        "multiclass_brier": float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1))),
        "ambiguous_rate": float(split.test_meta["ambiguous"].mean()),
        "class_distribution": {label: float((y == label).mean()) for label in classes},
    }

    base_probability_loader = getattr(model, "_base_probabilities", None)
    if callable(base_probability_loader):
        raw_probabilities = base_probability_loader(split.x_test)
        raw_log_loss = _ordered_multiclass_log_loss(y, raw_probabilities, classes)
        metrics["raw_log_loss"] = raw_log_loss
        metrics["calibration_log_loss_improvement"] = raw_log_loss - calibrated_log_loss
    for index, label in enumerate(classes):
        binary = (y == label).astype(int)
        metrics[f"brier_{label.lower()}"] = float(brier_score_loss(binary, probabilities[:, index]))
        metrics[f"ece_{label.lower()}"] = _expected_calibration_error(binary, probabilities[:, index])
    try:
        metrics["auc_ovr_macro"] = float(
            roc_auc_score(one_hot, probabilities, multi_class="ovr", average="macro")
        )
    except ValueError:
        metrics["auc_ovr_macro"] = None
    return metrics


def evaluate_policy_model(
    model: TemporalCalibratedBarrierModel,
    split: DatasetSplit,
    config: PolicyEvaluationConfig,
    *,
    horizon_hours: int | None = None,
) -> dict[str, object]:
    """Evaluate the live policy with horizon-separated capital sleeves.

    Hourly decisions with an H-hour holding horizon overlap economically. Each
    decision cohort therefore receives only 1/H of portfolio capital before its
    exit-time contribution is aggregated. This matches the backtest capital
    convention and prevents overlapping positions from being treated as H fully
    funded independent bets.
    """

    resolved_horizon = horizon_hours if horizon_hours is not None else config.horizon_hours
    if resolved_horizon is None:
        if "label_end_time" not in split.test_meta.columns:
            raise ValueError("horizon_hours is required when label_end_time is unavailable")
        decisions = pd.to_datetime(split.test_meta["decision_time"], utc=True, errors="coerce")
        label_ends = pd.to_datetime(split.test_meta["label_end_time"], utc=True, errors="coerce")
        horizon_values = (label_ends - decisions).dt.total_seconds() / 3600.0
        if (
            decisions.isna().any()
            or label_ends.isna().any()
            or horizon_values.empty
            or not np.isfinite(horizon_values.to_numpy(float)).all()
            or (horizon_values <= 0).any()
            or not np.allclose(horizon_values, np.floor(horizon_values))
            or horizon_values.nunique() != 1
        ):
            raise ValueError("Unable to infer one positive integer horizon from holdout metadata")
        resolved_horizon = int(horizon_values.iloc[0])
    if (
        isinstance(resolved_horizon, bool)
        or not isinstance(resolved_horizon, (int, np.integer))
        or resolved_horizon <= 0
    ):
        raise ValueError("horizon_hours must be a positive integer")
    resolved_horizon = int(resolved_horizon)

    config_values = {
        "fee_rate_round_trip": config.fee_rate_round_trip,
        "slippage_rate": config.slippage_rate,
        "stop_gap_reserve_rate": config.stop_gap_reserve_rate,
        "min_net_rr": config.min_net_rr,
        "min_net_ev_r": config.min_net_ev_r,
        "timeout_return_rate": config.timeout_return_rate,
    }
    for name, value in config_values.items():
        if not np.isfinite(float(value)):
            raise ValueError(f"{name} must be finite")
    for name in ("fee_rate_round_trip", "slippage_rate", "stop_gap_reserve_rate", "min_net_rr"):
        if float(config_values[name]) < 0:
            raise ValueError(f"{name} must be non-negative")

    probabilities, class_to_index = validate_outcome_probability_matrix(
        model.predict_proba(split.x_test),
        model.classes_,
        expected_rows=len(split.test_meta),
    )
    meta = validate_policy_evaluation_metadata(
        split.test_meta,
        context="Policy evaluation",
        horizon_hours=resolved_horizon,
        require_barrier_return_consistency=True,
    )
    for label in OUTCOME_CLASSES:
        meta[f"p_{str(label).lower()}"] = probabilities[:, class_to_index[str(label)]]

    fee_rate_per_leg = config.fee_rate_round_trip / 2.0
    is_long = meta["direction"].eq("LONG")
    tp_exit_ratio = np.where(
        is_long,
        1.0 + meta["barrier_upside_rate"],
        1.0 - meta["barrier_upside_rate"],
    )
    sl_exit_ratio = np.where(
        is_long,
        1.0 - meta["barrier_downside_rate"],
        1.0 + meta["barrier_downside_rate"],
    )
    timeout_exit_ratio = np.where(
        is_long,
        1.0 + config.timeout_return_rate,
        1.0 - config.timeout_return_rate,
    )
    realized_exit_ratio = np.where(
        is_long,
        1.0 + meta["realized_gross_return"],
        1.0 - meta["realized_gross_return"],
    )
    if (
        (tp_exit_ratio <= 0).any()
        or (sl_exit_ratio <= 0).any()
        or (timeout_exit_ratio <= 0).any()
        or (realized_exit_ratio <= 0).any()
    ):
        raise ValueError("Policy evaluation produced a non-positive exit notional ratio")
    tp_fee_rate = fee_rate_per_leg * (1.0 + tp_exit_ratio)
    sl_fee_rate = fee_rate_per_leg * (1.0 + sl_exit_ratio)
    timeout_fee_rate = fee_rate_per_leg * (1.0 + timeout_exit_ratio)
    meta["net_upside_rate"] = (
        meta["barrier_upside_rate"] - tp_fee_rate - config.slippage_rate
    )
    meta["stress_downside_rate"] = (
        meta["barrier_downside_rate"]
        + sl_fee_rate
        + config.slippage_rate
        + config.stop_gap_reserve_rate
    )
    meta["timeout_net_rate"] = (
        config.timeout_return_rate - timeout_fee_rate - config.slippage_rate
    )
    meta["realized_fee_rate"] = fee_rate_per_leg * (1.0 + realized_exit_ratio)
    target = meta["target"].astype(str)
    embedded_stop_gap = np.where(
        target.eq("SL"),
        np.maximum(
            -meta["realized_gross_return"] - meta["barrier_downside_rate"],
            0.0,
        ),
        0.0,
    )
    meta["realized_stop_gap_reserve_rate"] = np.where(
        target.eq("SL"),
        np.maximum(config.stop_gap_reserve_rate - embedded_stop_gap, 0.0),
        0.0,
    )
    meta["realized_net_rate"] = (
        meta["realized_gross_return"]
        - meta["realized_fee_rate"]
        - config.slippage_rate
        - meta["realized_stop_gap_reserve_rate"]
    )
    meta["net_rr"] = np.where(
        meta["stress_downside_rate"] > 0,
        np.maximum(meta["net_upside_rate"], 0.0) / meta["stress_downside_rate"],
        0.0,
    )
    meta["expected_net_rate"] = (
        meta["p_tp"] * meta["net_upside_rate"]
        - meta["p_sl"] * meta["stress_downside_rate"]
        + meta["p_timeout"] * meta["timeout_net_rate"]
    )
    meta["expected_ev_r"] = np.where(
        meta["stress_downside_rate"] > 0,
        meta["expected_net_rate"] / meta["stress_downside_rate"],
        0.0,
    )
    meta["direction_tiebreak"] = is_long.astype(int)

    selected = (
        meta.sort_values(
            ["decision_time", "symbol", "expected_ev_r", "net_rr", "direction_tiebreak"],
            ascending=[True, True, False, False, False],
            kind="mergesort",
        )
        .groupby(["decision_time", "symbol"], as_index=False)
        .head(1)
        .sort_values(["decision_time", "symbol"], kind="mergesort")
        .reset_index(drop=True)
    )
    selected["actionable"] = (selected["net_rr"] >= config.min_net_rr) & (
        selected["expected_ev_r"] >= config.min_net_ev_r
    )
    actionable_trades = selected[selected["actionable"]].copy()
    trades, overlap_blocked_trades = filter_single_active_trade_per_symbol(
        actionable_trades,
        context="Policy evaluation",
    )

    empty_metrics: dict[str, object] = {
        "policy_metric_schema": POLICY_METRIC_SCHEMA,
        "policy_horizon_hours": resolved_horizon,
        "policy_capital_sleeves": resolved_horizon,
        "policy_candidates": int(len(selected)),
        "policy_actionable_candidates": int(len(actionable_trades)),
        "policy_overlap_blocked_trades": int(overlap_blocked_trades),
        "policy_trades": 0,
        "policy_cohorts": 0,
        "policy_independent_cohorts": 0,
        "policy_trade_rate": 0.0,
        "policy_mean_expected_ev_r": None,
        "policy_realized_mean_r": None,
        "policy_realized_total_r": 0.0,
        "policy_win_rate": None,
        "policy_profit_factor": None,
        "policy_profit_factor_unbounded": False,
        "policy_gross_gain_r": 0.0,
        "policy_gross_loss_r": 0.0,
        "policy_max_drawdown_r": 0.0,
        "policy_event_periods": 0,
    }
    if trades.empty:
        return empty_metrics

    outcome = trades["target"].astype(str)
    if (~outcome.isin(OUTCOME_CLASSES)).any():
        raise ValueError("Policy evaluation target contains an unsupported outcome")
    trades["realized_r"] = np.where(
        trades["stress_downside_rate"] > 0,
        trades["realized_net_rate"] / trades["stress_downside_rate"],
        0.0,
    )
    cohort_size = trades.groupby("decision_time")["realized_r"].transform("size")
    trades["realized_r_contribution"] = (
        trades["realized_r"] / cohort_size / resolved_horizon
    )
    cohort_metrics = trades.groupby("decision_time", sort=True).agg(
        realized_mean_r=("realized_r", "mean"),
        expected_mean_ev_r=("expected_ev_r", "mean"),
    )
    exit_r = trades.groupby("exit_time", sort=True)["realized_r_contribution"].sum()
    trade_contributions = trades["realized_r_contribution"]
    gains = float(trade_contributions[trade_contributions > 0].sum())
    losses = float(-trade_contributions[trade_contributions < 0].sum())
    profit_factor = gains / losses if losses > 0 else None
    profit_factor_unbounded = losses == 0.0 and gains > 0.0
    cumulative_r = np.concatenate(([0.0], exit_r.cumsum().to_numpy(float)))
    running_peak = np.maximum.accumulate(cumulative_r)
    drawdown = running_peak - cumulative_r

    return {
        "policy_metric_schema": POLICY_METRIC_SCHEMA,
        "policy_horizon_hours": resolved_horizon,
        "policy_capital_sleeves": resolved_horizon,
        "policy_candidates": int(len(selected)),
        "policy_actionable_candidates": int(len(actionable_trades)),
        "policy_overlap_blocked_trades": int(overlap_blocked_trades),
        "policy_trades": int(len(trades)),
        "policy_cohorts": int(len(cohort_metrics)),
        "policy_independent_cohorts": _count_horizon_separated_cohorts(
            trades["decision_time"], horizon_hours=resolved_horizon
        ),
        "policy_trade_rate": float(len(trades) / len(selected)) if len(selected) else 0.0,
        "policy_mean_expected_ev_r": float(cohort_metrics["expected_mean_ev_r"].mean()),
        "policy_realized_mean_r": float(cohort_metrics["realized_mean_r"].mean()),
        "policy_realized_total_r": float(exit_r.sum()),
        "policy_win_rate": float((exit_r > 0).mean()),
        "policy_trade_mean_r": float(trades["realized_r"].mean()),
        "policy_trade_win_rate": float((trades["realized_r"] > 0).mean()),
        "policy_profit_factor": float(profit_factor) if profit_factor is not None else None,
        "policy_profit_factor_unbounded": profit_factor_unbounded,
        "policy_gross_gain_r": gains,
        "policy_gross_loss_r": losses,
        "policy_max_drawdown_r": float(drawdown.max()) if len(drawdown) else 0.0,
        "policy_event_periods": int(len(exit_r)),
    }

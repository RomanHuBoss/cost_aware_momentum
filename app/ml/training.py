from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.ml.context import (
    MARKET_CONTEXT_AVAILABILITY_SCHEMA,
    MARKET_CONTEXT_COMPLETE_COLUMN,
    MARKET_CONTEXT_FEATURE_NAMES,
    MARKET_CONTEXT_SCHEMA_VERSION,
    build_market_context_frame,
)
from app.ml.drift import PRODUCTION_DRIFT_CALIBRATION_COHORT_SCHEMA
from app.ml.features import (
    FEATURE_CONTINUITY_COLUMN,
    FEATURE_LOOKBACK_HOURS,
    FEATURE_NAMES,
    FEATURE_WINDOW_START_COLUMN,
    MARKET_BAR_VALID_COLUMN,
    build_feature_frame,
)
from app.ml.funding import (
    HISTORICAL_FUNDING_SCHEMA_VERSION,
    HistoricalFundingTimeline,
    funding_return_rate_for_direction,
)
from app.ml.labels import triple_barrier_outcome
from app.ml.mtm import (
    DEFAULT_EQUITY_RESERVE_FRACTION,
    INTRAHORIZON_MARGIN_SCHEMA_VERSION,
    simulate_intrahorizon_margin_path,
)

OUTCOME_CLASSES = np.array(["TP", "SL", "TIMEOUT"])
MODEL_BASE_FEATURE_NAMES = [*FEATURE_NAMES, *MARKET_CONTEXT_FEATURE_NAMES]
MODEL_FEATURE_NAMES = [*MODEL_BASE_FEATURE_NAMES, "scenario_direction"]
DEFAULT_STOP_ATR_MULTIPLIER = 1.15
DEFAULT_TP_ATR_MULTIPLIER = 2.20
MODEL_FEATURE_SCHEMA_VERSION = "hourly-barrier-market-context-v5"
MARKET_CONTEXT_ABLATION_SCHEMA_VERSION = "same-split-zeroed-context-v1"
HOURLY_CONTINUITY_SCHEMA = "strict-hourly-v1"
LABEL_PATH_SCHEMA_VERSION = "decision-open-directional-spread-entry-ohlc-path-v3"
ENTRY_EXECUTION_MODEL_SCHEMA = "directional-half-spread-on-next-hour-open-v1"
TEMPORAL_SPLIT_SCHEMA_VERSION = "final-holdout-plus-expanding-walk-forward-v4"
WALK_FORWARD_SCHEMA_VERSION = "expanding-train-rolling-calibration-purged-v1"
DEFAULT_WALK_FORWARD_FOLDS = 3
MIN_WALK_FORWARD_POSITIVE_FRACTION = 2.0 / 3.0
POLICY_METRIC_SCHEMA = "decision-open-directional-spread-entry-funding-mark-mtm-liquidation-cohort-v16"
POLICY_UNCERTAINTY_SCHEMA = "all-horizon-phases-circular-moving-block-v2"
HOUR_NS = 3_600_000_000_000
TIMEOUT_RETURN_SCHEMA_VERSION = "training-direction-median-r-v1"
MIN_TIMEOUT_SAMPLES_PER_DIRECTION = 5


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
        self.timeout_return_r_by_direction: dict[str, float] = {}
        self.timeout_return_sample_count_by_direction: dict[str, int] = {}

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

    def fit(
        self,
        x_train: np.ndarray,
        y_train: np.ndarray,
        x_cal: np.ndarray,
        y_cal: np.ndarray,
        *,
        timeout_return_r_train: np.ndarray | None = None,
    ):
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
        if timeout_return_r_train is not None:
            self._fit_timeout_return_estimator(
                x_train=x_train,
                y_train=y_train,
                timeout_return_r_train=timeout_return_r_train,
            )
        return self

    def _fit_timeout_return_estimator(
        self,
        *,
        x_train: np.ndarray,
        y_train: np.ndarray,
        timeout_return_r_train: np.ndarray,
    ) -> None:
        features = np.asarray(x_train, dtype=float)
        targets = np.asarray(y_train, dtype=str)
        returns_r = np.asarray(timeout_return_r_train, dtype=float)
        if features.ndim != 2 or features.shape[1] != len(MODEL_FEATURE_NAMES):
            raise ValueError("Timeout return estimator received an invalid feature matrix")
        if returns_r.ndim != 1 or len(returns_r) != len(features):
            raise ValueError("Timeout return R values must align with training rows")
        timeout_mask = targets == "TIMEOUT"
        if not np.isfinite(returns_r[timeout_mask]).all():
            raise ValueError("Timeout return R values must be finite for TIMEOUT rows")

        upper_bound = DEFAULT_TP_ATR_MULTIPLIER / DEFAULT_STOP_ATR_MULTIPLIER
        tolerance = 1e-8
        estimates: dict[str, float] = {}
        counts: dict[str, int] = {}
        for direction, code in (("LONG", 1.0), ("SHORT", -1.0)):
            direction_mask = np.isclose(features[:, -1], code, rtol=0.0, atol=1e-12)
            selected = returns_r[timeout_mask & direction_mask]
            if len(selected) < MIN_TIMEOUT_SAMPLES_PER_DIRECTION:
                raise ValueError(
                    "Training window must contain at least "
                    f"{MIN_TIMEOUT_SAMPLES_PER_DIRECTION} TIMEOUT rows for {direction}"
                )
            if (selected < -1.0 - tolerance).any() or (selected > upper_bound + tolerance).any():
                raise ValueError("TIMEOUT return R lies outside the configured barrier support")
            estimates[direction] = float(np.median(selected))
            counts[direction] = int(len(selected))
        self.timeout_return_r_by_direction = estimates
        self.timeout_return_sample_count_by_direction = counts

    def predict_timeout_return_r(self, x: np.ndarray) -> np.ndarray:
        estimates = getattr(self, "timeout_return_r_by_direction", {})
        if set(estimates) != {"LONG", "SHORT"}:
            raise RuntimeError("Model has no validated conditional TIMEOUT return estimator")
        values = np.asarray(x, dtype=float)
        if values.ndim != 2 or values.shape[1] != len(MODEL_FEATURE_NAMES):
            raise ValueError("Expected model features ending with scenario_direction")
        direction = values[:, -1]
        is_long = np.isclose(direction, 1.0, rtol=0.0, atol=1e-12)
        is_short = np.isclose(direction, -1.0, rtol=0.0, atol=1e-12)
        if not np.all(is_long | is_short):
            raise ValueError("scenario_direction must be exactly +1 or -1")
        return np.where(is_long, estimates["LONG"], estimates["SHORT"]).astype(float)

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
    train_meta: pd.DataFrame | None = None
    cal_meta: pd.DataFrame | None = None


def zero_market_context_split(split: DatasetSplit) -> DatasetSplit:
    context_indexes = [MODEL_FEATURE_NAMES.index(name) for name in MARKET_CONTEXT_FEATURE_NAMES]

    def zeroed(values: np.ndarray) -> np.ndarray:
        result = np.asarray(values, dtype=float).copy()
        result[:, context_indexes] = 0.0
        return result

    return DatasetSplit(
        x_train=zeroed(split.x_train),
        y_train=split.y_train.copy(),
        x_cal=zeroed(split.x_cal),
        y_cal=split.y_cal.copy(),
        x_test=zeroed(split.x_test),
        y_test=split.y_test.copy(),
        test_meta=split.test_meta.copy(),
        train_meta=split.train_meta.copy() if split.train_meta is not None else None,
        cal_meta=split.cal_meta.copy() if split.cal_meta is not None else None,
    )


@dataclass(frozen=True)
class PolicyEvaluationConfig:
    fee_rate_round_trip: float
    slippage_rate: float
    stop_gap_reserve_rate: float
    min_net_rr: float
    min_net_ev_r: float
    timeout_return_rate: float = -0.002
    horizon_hours: int | None = None
    bootstrap_samples: int = 2000
    confidence_level: float = 0.95
    research_leverage: int = 3
    liquidation_equity_reserve_fraction: float = DEFAULT_EQUITY_RESERVE_FRACTION
    require_intrahorizon_margin: bool = False


def timeout_return_r_targets(meta: pd.DataFrame) -> np.ndarray:
    """Return direction-signed TIMEOUT gross returns in stop-risk units.

    Non-TIMEOUT rows receive zero because the estimator filters them by target.
    The denominator is the contemporaneous gross stop distance, so the learned
    expectation scales to the current ATR barrier geometry at inference time.
    """

    required = {"target", "realized_gross_return", "barrier_downside_rate"}
    missing = sorted(required - set(meta.columns))
    if missing:
        raise ValueError(f"TIMEOUT return targets are missing columns: {missing}")
    realized = pd.to_numeric(meta["realized_gross_return"], errors="coerce").to_numpy(float)
    downside = pd.to_numeric(meta["barrier_downside_rate"], errors="coerce").to_numpy(float)
    if not np.isfinite(realized).all() or not np.isfinite(downside).all() or (downside <= 0).any():
        raise ValueError("TIMEOUT return targets require finite returns and positive barriers")
    result = np.zeros(len(meta), dtype=float)
    timeout_mask = meta["target"].astype(str).eq("TIMEOUT").to_numpy()
    result[timeout_mask] = realized[timeout_mask] / downside[timeout_mask]
    return result


def minimum_hourly_history_timestamps_for_quality_gate(
    *,
    horizon_hours: int,
    minimum_holdout_rows: int,
    minimum_holdout_span_hours: int,
) -> int:
    """Return the theoretical minimum raw hourly timestamps for the split/gate.

    The calculation mirrors the final :func:`chronological_split` and the
    required expanding walk-forward development folds for one continuously sampled
    symbol. Each decision timestamp emits the required LONG/SHORT pair, all
    calibration/test boundaries are purged by the horizon, and feature/label
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
        development_timestamps = calibration_index
        walk_forward_block = development_timestamps // (DEFAULT_WALK_FORWARD_FOLDS + 3)
        walk_forward_initial_train = (
            development_timestamps - (DEFAULT_WALK_FORWARD_FOLDS + 1) * walk_forward_block
        )
        walk_forward_ready = walk_forward_block >= 45 + 2 * horizon and walk_forward_initial_train >= max(
            90, 45 + horizon
        )
        if (
            train_timestamps >= 45
            and calibration_timestamps >= 45
            and test_timestamps >= required_test_timestamps
            and walk_forward_ready
        ):
            return labeled_timestamps + FEATURE_LOOKBACK_HOURS + horizon
        labeled_timestamps += 1


def make_barrier_dataset(
    candles: pd.DataFrame,
    horizon: int = 8,
    *,
    stop_atr_multiplier: float = DEFAULT_STOP_ATR_MULTIPLIER,
    tp_atr_multiplier: float = DEFAULT_TP_ATR_MULTIPLIER,
    entry_spread_bps: float = 0.0,
    funding_history: pd.DataFrame | None = None,
    funding_interval_minutes: dict[str, int] | None = None,
    funding_interval_history: pd.DataFrame | None = None,
    require_funding_timeline: bool = False,
    mark_candles: pd.DataFrame | None = None,
    require_mark_timeline: bool = False,
    index_candles: pd.DataFrame | None = None,
    open_interest: pd.DataFrame | None = None,
    require_market_context: bool = False,
    liquidation_leverage: int = 3,
    liquidation_equity_reserve_fraction: float = DEFAULT_EQUITY_RESERVE_FRACTION,
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
    try:
        parsed_entry_spread_bps = float(entry_spread_bps)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("entry_spread_bps must be non-negative and finite") from exc
    if not np.isfinite(parsed_entry_spread_bps) or parsed_entry_spread_bps < 0:
        raise ValueError("entry_spread_bps must be non-negative and finite")
    funding_timeline: HistoricalFundingTimeline | None = None
    if funding_history is not None:
        funding_timeline = HistoricalFundingTimeline(
            funding_history,
            interval_minutes=funding_interval_minutes or {},
            interval_history=funding_interval_history,
        )
    elif require_funding_timeline:
        raise ValueError("Historical funding timeline is required for research training")

    if (
        isinstance(liquidation_leverage, bool)
        or not isinstance(liquidation_leverage, (int, np.integer))
        or liquidation_leverage <= 0
    ):
        raise ValueError("liquidation_leverage must be a positive integer")
    liquidation_leverage = int(liquidation_leverage)
    reserve_fraction = float(liquidation_equity_reserve_fraction)
    if not np.isfinite(reserve_fraction) or not 0.0 <= reserve_fraction < 1.0:
        raise ValueError("liquidation_equity_reserve_fraction must be finite and in [0, 1)")

    mark_groups: dict[str, pd.DataFrame] = {}
    if mark_candles is not None:
        required_mark_columns = {"symbol", "open_time", "close_time", "open", "high", "low", "close"}
        missing_mark_columns = sorted(required_mark_columns - set(mark_candles.columns))
        if missing_mark_columns:
            raise ValueError(f"Historical mark candles are missing columns: {missing_mark_columns}")
        mark_frame = mark_candles.loc[:, sorted(required_mark_columns)].copy()
        mark_frame["symbol"] = mark_frame["symbol"].astype(str).str.strip().str.upper()
        mark_frame["open_time"] = pd.to_datetime(mark_frame["open_time"], utc=True, errors="coerce")
        mark_frame["close_time"] = pd.to_datetime(mark_frame["close_time"], utc=True, errors="coerce")
        if mark_frame[["open_time", "close_time"]].isna().any().any():
            raise ValueError("Historical mark candles contain invalid timestamps")
        if mark_frame.duplicated(["symbol", "open_time"], keep=False).any():
            raise ValueError("Historical mark candles contain duplicate symbol/open_time rows")
        for column in ("open", "high", "low", "close"):
            mark_frame[column] = pd.to_numeric(mark_frame[column], errors="coerce")
        if (
            mark_frame[["open", "high", "low", "close"]].isna().any().any()
            or not np.isfinite(mark_frame[["open", "high", "low", "close"]].to_numpy(float)).all()
        ):
            raise ValueError("Historical mark candle prices must be finite")
        mark_groups = {
            str(symbol): group.sort_values("open_time").set_index("open_time", drop=False)
            for symbol, group in mark_frame.groupby("symbol", sort=False)
        }
    elif require_mark_timeline:
        raise ValueError("Historical mark-price timeline is required for margin-path research")

    context_frame: pd.DataFrame | None = None
    context_metadata: dict[str, object]
    context_inputs = (mark_candles, index_candles, open_interest, funding_history)
    if all(item is not None for item in context_inputs):
        context_frame = build_market_context_frame(
            candles,
            mark_candles=mark_candles,
            index_candles=index_candles,
            open_interest=open_interest,
            funding_history=funding_history,
            funding_interval_minutes=funding_interval_minutes or {},
            funding_interval_history=funding_interval_history,
        )
        context_metadata = dict(context_frame.attrs.get("market_context") or {})
    elif require_market_context:
        missing = [
            name
            for name, value in {
                "mark_candles": mark_candles,
                "index_candles": index_candles,
                "open_interest": open_interest,
                "funding_history": funding_history,
            }.items()
            if value is None
        ]
        raise ValueError(f"Point-in-time market context is required; missing: {missing}")
    else:
        context_metadata = {
            "schema": MARKET_CONTEXT_SCHEMA_VERSION,
            "availability_schema": MARKET_CONTEXT_AVAILABILITY_SCHEMA,
            "status": "not_requested_test_compatibility",
            "required": False,
            "features": list(MARKET_CONTEXT_FEATURE_NAMES),
        }

    frame = build_feature_frame(candles).sort_values(["symbol", "open_time"]).reset_index(drop=True)
    if context_frame is not None:
        context_values = context_frame[[
            "symbol",
            "decision_time",
            *MARKET_CONTEXT_FEATURE_NAMES,
            MARKET_CONTEXT_COMPLETE_COLUMN,
        ]].copy()
        frame = frame.merge(
            context_values,
            how="left",
            left_on=["symbol", "close_time"],
            right_on=["symbol", "decision_time"],
            validate="one_to_one",
        )
    else:
        for name in MARKET_CONTEXT_FEATURE_NAMES:
            frame[name] = 0.0
        frame[MARKET_CONTEXT_COMPLETE_COLUMN] = True

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
        "skipped_incomplete_funding_timeline_timestamps": 0,
        "skipped_incomplete_mark_timeline_timestamps": 0,
        "skipped_incomplete_market_context_timestamps": 0,
        "liquidation_path_timestamps": 0,
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
            if not actual_times.equals(expected_times) or not actual_close_times.equals(expected_close_times):
                diagnostics["skipped_label_gap_timestamps"] += 1
                continue
            if not future[MARKET_BAR_VALID_COLUMN].all():
                diagnostics["skipped_invalid_label_bar_timestamps"] += 1
                continue

            mark_future: pd.DataFrame | None = None
            if mark_groups:
                mark_group = mark_groups.get(str(symbol).strip().upper())
                if mark_group is None or not set(expected_times).issubset(mark_group.index):
                    diagnostics["skipped_incomplete_mark_timeline_timestamps"] += 1
                    continue
                mark_future = mark_group.loc[
                    expected_times,
                    [
                        "open_time",
                        "close_time",
                        "open",
                        "high",
                        "low",
                        "close",
                    ],
                ].copy()
                if not pd.DatetimeIndex(mark_future["open_time"]).equals(
                    expected_times
                ) or not pd.DatetimeIndex(mark_future["close_time"]).equals(expected_close_times):
                    diagnostics["skipped_incomplete_mark_timeline_timestamps"] += 1
                    continue
            elif require_mark_timeline:
                diagnostics["skipped_incomplete_mark_timeline_timestamps"] += 1
                continue

            if not bool(current.get(MARKET_CONTEXT_COMPLETE_COLUMN, False)):
                diagnostics["skipped_incomplete_market_context_timestamps"] += 1
                continue
            values = [current.get(name) for name in MODEL_BASE_FEATURE_NAMES]
            if any(value is None or not np.isfinite(float(value)) for value in values):
                diagnostics["skipped_incomplete_market_context_timestamps"] += 1
                continue
            # A signal can only be acted on after the source candle has closed.
            # Hourly OHLC exposes a last-trade/open proxy rather than executable
            # bid/ask. Production enters LONG at ask and SHORT at bid, therefore
            # apply half of a configured full-spread stress in the adverse
            # direction instead of centering both labels on one frictionless open.
            entry_mid_proxy = float(future.iloc[0]["open"])
            half_spread_rate = parsed_entry_spread_bps / 20000.0
            atr_pct = float(current.get("atr_pct_14", np.nan))
            if (
                not np.isfinite(entry_mid_proxy)
                or entry_mid_proxy <= 0
                or not np.isfinite(atr_pct)
                or atr_pct <= 0
            ):
                continue
            label_end_time = future.iloc[-1]["close_time"]

            direction_rows: list[dict] = []
            for direction, direction_code in (("LONG", 1.0), ("SHORT", -1.0)):
                entry = entry_mid_proxy * (
                    1.0 + half_spread_rate if direction == "LONG" else 1.0 - half_spread_rate
                )
                atr = entry * atr_pct
                if not np.isfinite(entry) or entry <= 0 or not np.isfinite(atr) or atr <= 0:
                    direction_rows = []
                    break
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
                execution_path = future.copy()
                first_index = execution_path.index[0]
                execution_path.loc[first_index, "open"] = entry
                execution_path.loc[first_index, "high"] = max(
                    float(execution_path.loc[first_index, "high"]), entry
                )
                execution_path.loc[first_index, "low"] = min(
                    float(execution_path.loc[first_index, "low"]), entry
                )
                result = triple_barrier_outcome(
                    execution_path,
                    direction=direction,
                    stop=stop,
                    take_profit=take_profit,
                    conservative_ambiguity=True,
                )
                realized_return = sign * (float(result.exit_price) - entry) / entry
                exit_offset_hours = int(result.exit_index) + (0 if result.exit_at_open else 1)
                exit_time = decision_time + pd.Timedelta(exit_offset_hours, unit="h")
                funding_values: dict[str, float | int | bool] = {}
                realized_funding = None
                if funding_timeline is not None:
                    try:
                        horizon_funding = funding_timeline.aggregate(
                            symbol, start_time=decision_time, end_time=label_end_time
                        )
                        realized_funding = funding_timeline.aggregate(
                            symbol, start_time=decision_time, end_time=exit_time
                        )
                    except ValueError:
                        direction_rows = []
                        break
                    funding_values = {
                        "historical_funding_timeline_complete": True,
                        "historical_funding_horizon_rate": horizon_funding.cumulative_rate,
                        "historical_funding_horizon_settlements": horizon_funding.settlements,
                        "historical_funding_realized_rate": realized_funding.cumulative_rate,
                        "historical_funding_realized_settlements": realized_funding.settlements,
                    }

                margin_values: dict[str, float | int | bool | pd.Timestamp | None] = {}
                if mark_future is not None:
                    adverse_funding_at_open: list[float] = []
                    adverse_funding_at_close: list[float] = []
                    running_adverse_funding = 0.0
                    if funding_timeline is not None:
                        try:
                            for mark_row in mark_future.iloc[: result.exit_index + 1].itertuples(index=False):
                                open_funding = funding_timeline.aggregate(
                                    symbol,
                                    start_time=decision_time,
                                    end_time=mark_row.open_time,
                                )
                                close_funding = funding_timeline.aggregate(
                                    symbol,
                                    start_time=decision_time,
                                    end_time=mark_row.close_time,
                                )
                                signed_open_funding = (
                                    -open_funding.cumulative_rate
                                    if direction == "LONG"
                                    else open_funding.cumulative_rate
                                )
                                signed_close_funding = (
                                    -close_funding.cumulative_rate
                                    if direction == "LONG"
                                    else close_funding.cumulative_rate
                                )
                                open_adverse = min(running_adverse_funding, signed_open_funding, 0.0)
                                close_adverse = min(open_adverse, signed_close_funding, 0.0)
                                adverse_funding_at_open.append(open_adverse)
                                adverse_funding_at_close.append(close_adverse)
                                running_adverse_funding = close_adverse
                        except ValueError:
                            direction_rows = []
                            break
                    else:
                        adverse_funding_at_open = [0.0] * (result.exit_index + 1)
                        adverse_funding_at_close = [0.0] * (result.exit_index + 1)

                    margin_path = simulate_intrahorizon_margin_path(
                        mark_future[["open", "high", "low", "close"]],
                        direction=direction,
                        entry_price=entry,
                        exit_index=result.exit_index,
                        exit_at_open=bool(result.exit_at_open),
                        leverage=liquidation_leverage,
                        equity_reserve_fraction=reserve_fraction,
                        cumulative_adverse_funding_return_at_open_by_bar=(adverse_funding_at_open),
                        cumulative_adverse_funding_return_at_close_by_bar=(adverse_funding_at_close),
                    )
                    effective_exit_index = (
                        int(margin_path.liquidation_index)
                        if margin_path.liquidated and margin_path.liquidation_index is not None
                        else int(result.exit_index)
                    )
                    effective_exit_at_open = (
                        bool(margin_path.liquidation_at_open)
                        if margin_path.liquidated
                        else bool(result.exit_at_open)
                    )
                    effective_exit_offset = (
                        int(margin_path.liquidation_exit_offset_hours)
                        if margin_path.liquidated and margin_path.liquidation_exit_offset_hours is not None
                        else exit_offset_hours
                    )
                    effective_exit_time = decision_time + pd.Timedelta(effective_exit_offset, unit="h")
                    effective_realized_return = (
                        float(margin_path.liquidation_gross_return_rate)
                        if margin_path.liquidated and margin_path.liquidation_gross_return_rate is not None
                        else float(realized_return)
                    )
                    effective_funding_rate = (
                        realized_funding.cumulative_rate if realized_funding is not None else 0.0
                    )
                    effective_funding_settlements = (
                        realized_funding.settlements if realized_funding is not None else 0
                    )
                    if margin_path.liquidated and funding_timeline is not None:
                        try:
                            liquidation_funding = funding_timeline.aggregate(
                                symbol,
                                start_time=decision_time,
                                end_time=effective_exit_time,
                            )
                        except ValueError:
                            direction_rows = []
                            break
                        effective_funding_rate = liquidation_funding.cumulative_rate
                        effective_funding_settlements = liquidation_funding.settlements
                    margin_values = {
                        "intrahorizon_margin_path_complete": True,
                        "intrahorizon_margin_schema": INTRAHORIZON_MARGIN_SCHEMA_VERSION,
                        "research_leverage": liquidation_leverage,
                        "liquidation_equity_reserve_fraction": reserve_fraction,
                        "mark_max_adverse_excursion_rate": margin_path.maximum_adverse_excursion_rate,
                        "mark_max_favorable_excursion_rate": margin_path.maximum_favorable_excursion_rate,
                        "mark_minimum_equity_rate": margin_path.minimum_equity_rate,
                        "mark_liquidated": bool(margin_path.liquidated),
                        "mark_liquidation_index": margin_path.liquidation_index,
                        "mark_liquidation_at_open": bool(margin_path.liquidation_at_open),
                        "mark_liquidation_gross_return_rate": margin_path.liquidation_gross_return_rate,
                        "margin_path_exit_index": effective_exit_index,
                        "margin_path_exit_at_open": effective_exit_at_open,
                        "margin_path_exit_time": effective_exit_time,
                        "margin_path_realized_gross_return": effective_realized_return,
                        "historical_funding_margin_path_rate": effective_funding_rate,
                        "historical_funding_margin_path_settlements": effective_funding_settlements,
                    }
                row = {name: float(current[name]) for name in MODEL_BASE_FEATURE_NAMES}
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
                        "entry_mid_proxy": float(entry_mid_proxy),
                        "entry_price": float(entry),
                        "entry_spread_bps": parsed_entry_spread_bps,
                        "entry_price_source": "next_hour_open_directional_half_spread_stress",
                        "target": result.outcome,
                        "ambiguous": bool(result.ambiguous),
                        "exit_index": int(result.exit_index),
                        "exit_at_open": bool(result.exit_at_open),
                        "realized_gross_return": float(realized_return),
                        "barrier_upside_rate": float(abs(take_profit - entry) / entry),
                        "barrier_downside_rate": float(abs(entry - stop) / entry),
                        **funding_values,
                        **margin_values,
                    }
                )
                direction_rows.append(row)
            if len(direction_rows) == 2:
                rows.extend(direction_rows)
                diagnostics["labeled_timestamps"] += 1
            else:
                diagnostics["skipped_incomplete_direction_pair_timestamps"] += 1
                if funding_timeline is not None:
                    diagnostics["skipped_incomplete_funding_timeline_timestamps"] += 1
            if len(direction_rows) == 2 and mark_future is not None:
                diagnostics["liquidation_path_timestamps"] += 1

    dataset = pd.DataFrame.from_records(rows)
    dataset.attrs["hourly_continuity"] = diagnostics
    dataset.attrs["market_context"] = context_metadata
    dataset.attrs["label_path_schema"] = LABEL_PATH_SCHEMA_VERSION
    dataset.attrs["historical_funding_timeline"] = (
        funding_timeline.describe()
        if funding_timeline is not None
        else {
            "schema": None,
            "required": bool(require_funding_timeline),
            "status": "not_provided",
        }
    )
    dataset.attrs["intrahorizon_margin_path"] = {
        "schema": INTRAHORIZON_MARGIN_SCHEMA_VERSION if mark_candles is not None else None,
        "required": bool(require_mark_timeline),
        "status": "complete" if mark_candles is not None else "not_provided",
        "mark_price_source": "bybit_hourly_mark_price_ohlc",
        "research_leverage": liquidation_leverage,
        "equity_reserve_fraction": reserve_fraction,
        "same_bar_ordering": "liquidation_before_unordered_last_price_exit",
        "liquidation_loss": "full_initial_margin",
    }
    dataset.attrs["entry_execution_model"] = {
        "schema": ENTRY_EXECUTION_MODEL_SCHEMA,
        "entry_spread_bps": parsed_entry_spread_bps,
        "residual_limitations": [
            "historical_bid_ask_unavailable",
            "operator_latency_unmodeled",
            "historical_depth_and_partial_fill_unmodeled",
        ],
    }
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
    for directions in frame.groupby(["decision_time", "symbol"], dropna=False, sort=False)["direction"]:
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
    result["decision_time"] = pd.to_datetime(result["decision_time"], utc=True, errors="coerce")
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
    valid_open_flags = result["exit_at_open"].map(lambda value: isinstance(value, (bool, np.bool_)))
    if not valid_open_flags.all():
        raise ValueError(f"{context} exit_at_open must contain booleans")
    result["exit_at_open"] = result["exit_at_open"].astype(bool)
    target = result["target"].astype(str)
    if (target.eq("TIMEOUT") & result["exit_at_open"]).any():
        raise ValueError(f"{context} TIMEOUT cannot exit at bar open")
    exit_offset_hours = result["exit_index"] + (~result["exit_at_open"]).astype(int)
    result["exit_time"] = result["decision_time"] + pd.to_timedelta(exit_offset_hours, unit="h")

    numeric_columns = [
        "realized_gross_return",
        "barrier_upside_rate",
        "barrier_downside_rate",
    ]
    if "entry_price" in result.columns:
        numeric_columns.append("entry_price")
    for column in numeric_columns:
        values = pd.to_numeric(result[column], errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy(float)).all():
            raise ValueError(f"{context} {column} must be finite")
        result[column] = values.astype(float)
    if (result[["barrier_upside_rate", "barrier_downside_rate"]] <= 0).any().any():
        raise ValueError(f"{context} barrier rates must be positive")
    if "entry_price" in result.columns and (result["entry_price"] <= 0).any():
        raise ValueError(f"{context} entry_price must be positive")

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
        tolerance = 1e-10 + 1e-7 * result[["barrier_upside_rate", "barrier_downside_rate"]].max(axis=1)
        # Generated TP labels execute at the exact modeled barrier. SL may be
        # worse than the barrier because a gap can jump through the stop. TIMEOUT
        # must remain strictly inside both barriers; otherwise its label is false.
        tp_mismatch = target.eq("TP") & (
            (result["realized_gross_return"] - result["barrier_upside_rate"]).abs() > tolerance
        )
        sl_mismatch = target.eq("SL") & (
            result["realized_gross_return"] > -result["barrier_downside_rate"] + tolerance
        )
        timeout_mismatch = target.eq("TIMEOUT") & (
            (result["realized_gross_return"] >= result["barrier_upside_rate"] - tolerance)
            | (result["realized_gross_return"] <= -result["barrier_downside_rate"] + tolerance)
        )
        if tp_mismatch.any() or sl_mismatch.any() or timeout_mismatch.any():
            raise ValueError(f"{context} realized outcome is inconsistent with its barrier")

    if "label_end_time" in result.columns:
        label_end = pd.to_datetime(result["label_end_time"], utc=True, errors="coerce")
        if label_end.isna().any() or (result["exit_time"] > label_end).any():
            raise ValueError(f"{context} exit_time exceeds label availability")
        if horizon_hours is not None:
            expected_label_end = result["decision_time"] + pd.to_timedelta(horizon_hours, unit="h")
            if not label_end.equals(expected_label_end):
                raise ValueError(f"{context} label_end_time does not match the configured label horizon")
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
    ordered["decision_time"] = pd.to_datetime(ordered["decision_time"], utc=True, errors="coerce")
    ordered["exit_time"] = pd.to_datetime(ordered["exit_time"], utc=True, errors="coerce")
    if ordered[["decision_time", "exit_time"]].isna().any().any():
        raise ValueError(f"{context} contains invalid overlap timestamps")
    if (ordered["exit_time"] < ordered["decision_time"]).any():
        raise ValueError(f"{context} contains an exit before its decision")
    if ordered["symbol"].isna().any() or ordered["symbol"].astype(str).str.strip().eq("").any():
        raise ValueError(f"{context} contains an invalid symbol")

    ordered = ordered.sort_values(["decision_time", "symbol", "exit_time"], kind="mergesort")
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

    accepted = ordered.loc[accepted_indexes].sort_values(["decision_time", "symbol"], kind="mergesort")
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
    frame["decision_time"] = pd.to_datetime(frame["decision_time"], utc=True, errors="coerce")
    frame["label_end_time"] = pd.to_datetime(frame["label_end_time"], utc=True, errors="coerce")
    if frame[["decision_time", "label_end_time"]].isna().any().any():
        raise ValueError("Chronological split contains invalid decision_time or label_end_time")
    if (frame["label_end_time"] <= frame["decision_time"]).any():
        raise ValueError("Every label_end_time must be later than its decision_time")
    valid_open_flags = frame["exit_at_open"].map(lambda value: isinstance(value, (bool, np.bool_)))
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
        (frame["decision_time"] >= train_boundary + embargo) & (frame["label_end_time"] < cal_boundary)
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

    return _dataset_split_from_frames(train, cal, test)


def _dataset_split_from_frames(
    train: pd.DataFrame,
    cal: pd.DataFrame,
    test: pd.DataFrame,
) -> DatasetSplit:
    train = train.copy()
    cal = cal.copy()
    test = test.copy()
    for frame in (train, cal, test):
        missing_core = [name for name in FEATURE_NAMES if name not in frame.columns]
        if missing_core:
            raise ValueError(f"Temporal split is missing core features: {missing_core}")
        # Hand-built legacy unit fixtures may omit context. Production candidate
        # construction requires complete point-in-time context before this split.
        for name in MARKET_CONTEXT_FEATURE_NAMES:
            if name not in frame.columns:
                frame[name] = 0.0
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
    if "entry_price" in test.columns:
        meta_columns.insert(5, "entry_price")
    missing = [
        column
        for column in meta_columns
        if column not in train.columns or column not in cal.columns or column not in test.columns
    ]
    if missing:
        raise ValueError(f"Temporal split metadata is missing columns: {sorted(set(missing))}")
    return DatasetSplit(
        train[MODEL_FEATURE_NAMES].to_numpy(float),
        train["target"].to_numpy(),
        cal[MODEL_FEATURE_NAMES].to_numpy(float),
        cal["target"].to_numpy(),
        test[MODEL_FEATURE_NAMES].to_numpy(float),
        test["target"].to_numpy(),
        test[meta_columns].reset_index(drop=True),
        train[meta_columns].reset_index(drop=True),
        cal[meta_columns].reset_index(drop=True),
    )


def expanding_walk_forward_splits(
    frame: pd.DataFrame,
    *,
    folds: int = DEFAULT_WALK_FORWARD_FOLDS,
    purge_hours: int = 12,
) -> list[DatasetSplit]:
    """Build purged expanding-train/rolling-calibration walk-forward folds.

    The final untouched holdout is constructed separately by
    :func:`chronological_split`. This function is intended for the development
    region that ends strictly before that final holdout. Each successive fold
    expands the training window by the prior test block, rolls calibration
    forward, and evaluates on a later non-overlapping test block. Boundaries are
    whole decision timestamps and all label-end overlap is purged.
    """

    if isinstance(folds, bool) or not isinstance(folds, (int, np.integer)):
        raise TypeError("walk-forward folds must be an integer")
    folds = int(folds)
    if folds < 2 or folds > 8:
        raise ValueError("walk-forward folds must be between 2 and 8")
    if isinstance(purge_hours, bool) or not isinstance(purge_hours, (int, np.integer)):
        raise TypeError("purge_hours must be an integer number of hours")
    purge_hours = int(purge_hours)
    if purge_hours < 0:
        raise ValueError("purge_hours must be non-negative")

    required_columns = {"decision_time", "label_end_time", "exit_at_open"}
    missing_columns = sorted(required_columns - set(frame.columns))
    if missing_columns:
        raise ValueError(f"Walk-forward split requires columns: {missing_columns}")

    ordered = frame.copy()
    ordered["decision_time"] = pd.to_datetime(ordered["decision_time"], utc=True, errors="coerce")
    ordered["label_end_time"] = pd.to_datetime(ordered["label_end_time"], utc=True, errors="coerce")
    if ordered[["decision_time", "label_end_time"]].isna().any().any():
        raise ValueError("Walk-forward split contains invalid temporal metadata")
    if (ordered["label_end_time"] <= ordered["decision_time"]).any():
        raise ValueError("Walk-forward label_end_time must be later than decision_time")
    valid_open_flags = ordered["exit_at_open"].map(lambda value: isinstance(value, (bool, np.bool_)))
    if not valid_open_flags.all():
        raise ValueError("Walk-forward exit_at_open must contain booleans")
    ordered["exit_at_open"] = ordered["exit_at_open"].astype(bool)
    validate_directional_scenario_pairs(ordered, context="Walk-forward split")
    ordered = ordered.sort_values(["decision_time", "symbol", "direction"], kind="mergesort").reset_index(
        drop=True
    )

    unique_times = pd.Index(ordered["decision_time"].drop_duplicates().sort_values())
    n_times = len(unique_times)
    block_size = n_times // (folds + 3)
    initial_train_times = n_times - (folds + 1) * block_size
    minimum_block_times = 45 + 2 * purge_hours
    minimum_initial_train_times = max(90, 45 + purge_hours)
    if block_size < minimum_block_times or initial_train_times < minimum_initial_train_times:
        raise ValueError(
            "Insufficient history for walk-forward validation after purge: "
            f"each rolling block requires at least {minimum_block_times} timestamps "
            f"and the initial training region at least {minimum_initial_train_times}"
        )

    embargo = pd.Timedelta(purge_hours, unit="h")
    terminal_boundary = ordered["label_end_time"].max() + pd.Timedelta(nanoseconds=1)
    results: list[DatasetSplit] = []
    previous_test_end: pd.Timestamp | None = None
    for fold_index in range(folds):
        train_boundary_index = initial_train_times + fold_index * block_size
        test_boundary_index = train_boundary_index + block_size
        test_end_index = test_boundary_index + block_size
        train_boundary = pd.Timestamp(unique_times[train_boundary_index])
        test_boundary = pd.Timestamp(unique_times[test_boundary_index])
        test_end_boundary = (
            pd.Timestamp(unique_times[test_end_index]) if test_end_index < n_times else terminal_boundary
        )

        train = ordered[ordered["label_end_time"] < train_boundary]
        cal = ordered[
            (ordered["decision_time"] >= train_boundary + embargo)
            & (ordered["label_end_time"] < test_boundary)
        ]
        test = ordered[
            (ordered["decision_time"] >= test_boundary + embargo)
            & (ordered["label_end_time"] < test_end_boundary)
        ]
        if min(len(train), len(cal), len(test)) < 90:
            raise ValueError(f"Walk-forward fold {fold_index + 1} produced an undersized window")
        if train["label_end_time"].max() >= cal["decision_time"].min():
            raise AssertionError("Walk-forward train labels overlap calibration features")
        if cal["label_end_time"].max() >= test["decision_time"].min():
            raise AssertionError("Walk-forward calibration labels overlap test features")
        current_test_start = pd.Timestamp(test["decision_time"].min())
        current_test_end = pd.Timestamp(test["decision_time"].max())
        if previous_test_end is not None and current_test_start <= previous_test_end:
            raise AssertionError("Walk-forward test windows overlap")
        previous_test_end = current_test_end
        results.append(_dataset_split_from_frames(train, cal, test))
    return results


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


def _ordered_multiclass_log_loss(y_true: np.ndarray, probabilities: np.ndarray, classes: np.ndarray) -> float:
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


def _validated_policy_cohort_series(cohorts: pd.Series) -> pd.Series:
    if not isinstance(cohorts.index, pd.DatetimeIndex):
        decision_times = pd.to_datetime(cohorts.index, utc=True, errors="coerce")
    else:
        decision_times = pd.to_datetime(cohorts.index, utc=True, errors="coerce")
    values = pd.to_numeric(cohorts, errors="coerce").to_numpy(float)
    if decision_times.isna().any() or not np.isfinite(values).all():
        raise ValueError("Policy cohorts contain invalid decision_time or return")
    ordered = pd.Series(values, index=decision_times).sort_index(kind="mergesort")
    if ordered.index.has_duplicates:
        raise ValueError("Policy cohorts must have unique decision_time values")
    return ordered


def _horizon_separated_phase_series(
    cohorts: pd.Series,
    *,
    horizon_hours: int,
) -> dict[int, pd.Series]:
    """Partition hourly decisions into every non-overlapping horizon phase.

    A horizon-H label overlaps the following H-1 hourly labels.  Selecting only
    the first greedy sequence makes uncertainty depend on the arbitrary first
    holdout timestamp.  Epoch-hour phases cover every decision exactly once;
    observations inside each phase are at least H hours apart.
    """

    if isinstance(horizon_hours, bool) or not isinstance(horizon_hours, (int, np.integer)):
        raise TypeError("horizon_hours must be an integer")
    if int(horizon_hours) <= 0:
        raise ValueError("horizon_hours must be positive")
    resolved_horizon = int(horizon_hours)
    ordered = _validated_policy_cohort_series(cohorts)
    epoch_hours = ordered.index.asi8 // HOUR_NS
    phases: dict[int, pd.Series] = {}
    for phase in range(resolved_horizon):
        selected = ordered[(epoch_hours % resolved_horizon) == phase]
        if selected.empty:
            continue
        separation_hours = selected.index.to_series().diff().dt.total_seconds() / 3600.0
        if (separation_hours.dropna() < resolved_horizon).any():
            raise ValueError("Policy phase contains overlapping label windows")
        phases[phase] = selected
    return phases


def _horizon_separated_cohort_series(
    cohorts: pd.Series,
    *,
    horizon_hours: int,
) -> pd.Series:
    """Compatibility view of the earliest populated non-overlapping phase."""

    phases = _horizon_separated_phase_series(cohorts, horizon_hours=horizon_hours)
    return phases[min(phases)] if phases else _validated_policy_cohort_series(cohorts)


def _policy_mean_r_bootstrap(
    independent_returns: np.ndarray,
    *,
    samples: int,
    confidence_level: float,
) -> tuple[float, float, int]:
    """Return mean and one-sided moving-block bootstrap lower confidence bound."""

    values = np.asarray(independent_returns, dtype=float)
    if values.ndim != 1 or len(values) < 2 or not np.isfinite(values).all():
        raise ValueError("At least two finite independent policy returns are required")
    if isinstance(samples, bool) or not isinstance(samples, (int, np.integer)) or samples < 500:
        raise ValueError("bootstrap_samples must be an integer of at least 500")
    if not np.isfinite(confidence_level) or not 0.80 <= confidence_level < 1.0:
        raise ValueError("confidence_level must be in [0.80, 1.0)")

    block_length = max(1, min(len(values), int(np.ceil(np.sqrt(len(values))))))
    blocks_per_sample = int(np.ceil(len(values) / block_length))
    rng = np.random.default_rng(20260704)
    starts = rng.integers(0, len(values), size=(int(samples), blocks_per_sample))
    offsets = np.arange(block_length)
    indexes = (starts[..., None] + offsets) % len(values)
    resampled = values[indexes.reshape(int(samples), -1)[:, : len(values)]]
    bootstrap_means = resampled.mean(axis=1)
    lower_bound = float(np.quantile(bootstrap_means, 1.0 - confidence_level))
    return float(values.mean()), lower_bound, block_length


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
    timeout_estimates = getattr(model, "timeout_return_r_by_direction", {})
    timeout_counts = getattr(model, "timeout_return_sample_count_by_direction", {})
    if set(timeout_estimates) == {"LONG", "SHORT"}:
        metrics["timeout_return_schema_version"] = TIMEOUT_RETURN_SCHEMA_VERSION
        metrics["timeout_return_r_by_direction"] = {
            direction: float(timeout_estimates[direction]) for direction in ("LONG", "SHORT")
        }
        metrics["timeout_return_samples_by_direction"] = {
            direction: int(timeout_counts.get(direction, 0)) for direction in ("LONG", "SHORT")
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


def historical_funding_components(
    meta: pd.DataFrame,
    *,
    context: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, str | None]:
    required = {
        "historical_funding_timeline_complete",
        "historical_funding_horizon_rate",
        "historical_funding_horizon_settlements",
        "historical_funding_realized_rate",
        "historical_funding_realized_settlements",
    }
    if not required.issubset(meta.columns):
        zeros = np.zeros(len(meta), dtype=float)
        return zeros, zeros, zeros, None
    if not meta["historical_funding_timeline_complete"].map(bool).all():
        raise ValueError(f"{context} contains an incomplete historical funding timeline")
    for column in (
        "historical_funding_horizon_rate",
        "historical_funding_realized_rate",
    ):
        values = pd.to_numeric(meta[column], errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy(float)).all():
            raise ValueError(f"{context} {column} must be finite")
        meta[column] = values.astype(float)
    for column in (
        "historical_funding_horizon_settlements",
        "historical_funding_realized_settlements",
    ):
        values = pd.to_numeric(meta[column], errors="coerce")
        if (
            values.isna().any()
            or not np.isfinite(values.to_numpy(float)).all()
            or (values < 0).any()
            or not np.allclose(values, np.floor(values))
        ):
            raise ValueError(f"{context} {column} must contain non-negative integers")
        meta[column] = values.astype(int)
    if (
        meta["historical_funding_realized_settlements"] > meta["historical_funding_horizon_settlements"]
    ).any():
        raise ValueError(f"{context} realized funding settlements exceed the horizon")

    horizon_signed = funding_return_rate_for_direction(
        meta["direction"], meta["historical_funding_horizon_rate"]
    )
    realized_signed = funding_return_rate_for_direction(
        meta["direction"], meta["historical_funding_realized_rate"]
    )
    recognized_horizon = np.minimum(horizon_signed, 0.0)
    adverse_horizon = np.maximum(-recognized_horizon, 0.0)
    return recognized_horizon, adverse_horizon, realized_signed, HISTORICAL_FUNDING_SCHEMA_VERSION


def apply_intrahorizon_margin_path(
    meta: pd.DataFrame,
    *,
    context: str,
    require: bool,
    expected_leverage: int,
    expected_equity_reserve_fraction: float,
) -> tuple[pd.DataFrame, str | None]:
    """Validate and apply realized-only mark-price liquidation evidence.

    Future mark paths never participate in direction ranking or expected EV. This
    helper only replaces realized exit time, gross return and settlement window
    after the ex-ante policy inputs have already been constructed.
    """

    required = {
        "intrahorizon_margin_path_complete",
        "intrahorizon_margin_schema",
        "research_leverage",
        "liquidation_equity_reserve_fraction",
        "mark_max_adverse_excursion_rate",
        "mark_max_favorable_excursion_rate",
        "mark_minimum_equity_rate",
        "mark_liquidated",
        "margin_path_exit_index",
        "margin_path_exit_at_open",
        "margin_path_exit_time",
        "margin_path_realized_gross_return",
        "historical_funding_margin_path_rate",
        "historical_funding_margin_path_settlements",
    }
    missing = sorted(required - set(meta.columns))
    result = meta.copy()
    if missing:
        if require:
            raise ValueError(f"{context} metadata is missing intrahorizon margin columns: {missing}")
        result["effective_realized_gross_return"] = result["realized_gross_return"]
        result["mark_liquidated"] = False
        return result, None

    if not result["intrahorizon_margin_path_complete"].map(bool).all():
        raise ValueError(f"{context} contains an incomplete intrahorizon margin path")
    schemas = set(result["intrahorizon_margin_schema"].astype(str))
    if schemas != {INTRAHORIZON_MARGIN_SCHEMA_VERSION}:
        raise ValueError(f"{context} contains an incompatible intrahorizon margin schema")

    leverage_values = pd.to_numeric(result["research_leverage"], errors="coerce")
    if (
        leverage_values.isna().any()
        or not np.isfinite(leverage_values.to_numpy(float)).all()
        or (leverage_values <= 0).any()
        or not np.allclose(leverage_values, np.floor(leverage_values))
        or not (leverage_values.astype(int) == int(expected_leverage)).all()
    ):
        raise ValueError(f"{context} research leverage does not match policy configuration")
    reserve_values = pd.to_numeric(result["liquidation_equity_reserve_fraction"], errors="coerce")
    if (
        reserve_values.isna().any()
        or not np.isfinite(reserve_values.to_numpy(float)).all()
        or not np.allclose(
            reserve_values.to_numpy(float),
            float(expected_equity_reserve_fraction),
            rtol=0.0,
            atol=1e-12,
        )
    ):
        raise ValueError(f"{context} liquidation reserve does not match policy configuration")

    for column in (
        "mark_max_adverse_excursion_rate",
        "mark_max_favorable_excursion_rate",
        "mark_minimum_equity_rate",
        "margin_path_realized_gross_return",
        "historical_funding_margin_path_rate",
    ):
        values = pd.to_numeric(result[column], errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy(float)).all():
            raise ValueError(f"{context} {column} must be finite")
        result[column] = values.astype(float)
    if (result[["mark_max_adverse_excursion_rate", "mark_max_favorable_excursion_rate"]] < 0).any().any():
        raise ValueError(f"{context} mark-price excursions must be non-negative")

    valid_liquidated = result["mark_liquidated"].map(lambda value: isinstance(value, (bool, np.bool_)))
    valid_open = result["margin_path_exit_at_open"].map(lambda value: isinstance(value, (bool, np.bool_)))
    if not valid_liquidated.all() or not valid_open.all():
        raise ValueError(f"{context} margin path flags must be booleans")
    result["mark_liquidated"] = result["mark_liquidated"].astype(bool)
    result["margin_path_exit_at_open"] = result["margin_path_exit_at_open"].astype(bool)

    effective_index = pd.to_numeric(result["margin_path_exit_index"], errors="coerce")
    if (
        effective_index.isna().any()
        or not np.isfinite(effective_index.to_numpy(float)).all()
        or (effective_index < 0).any()
        or not np.allclose(effective_index, np.floor(effective_index))
        or (effective_index.astype(int) > result["exit_index"]).any()
    ):
        raise ValueError(f"{context} margin path exit index is invalid")
    effective_index = effective_index.astype(int)
    effective_time = pd.to_datetime(result["margin_path_exit_time"], utc=True, errors="coerce")
    expected_time = result["decision_time"] + pd.to_timedelta(
        effective_index + (~result["margin_path_exit_at_open"]).astype(int), unit="h"
    )
    if effective_time.isna().any() or not effective_time.equals(expected_time):
        raise ValueError(f"{context} margin path exit time is inconsistent")
    if (effective_time > result["exit_time"]).any():
        raise ValueError(f"{context} margin path exit occurs after the label exit")

    settlement_counts = pd.to_numeric(result["historical_funding_margin_path_settlements"], errors="coerce")
    if (
        settlement_counts.isna().any()
        or not np.isfinite(settlement_counts.to_numpy(float)).all()
        or (settlement_counts < 0).any()
        or not np.allclose(settlement_counts, np.floor(settlement_counts))
    ):
        raise ValueError(f"{context} margin path settlements must be non-negative integers")
    settlement_counts = settlement_counts.astype(int)
    if (
        "historical_funding_horizon_settlements" in result.columns
        and (settlement_counts > result["historical_funding_horizon_settlements"]).any()
    ):
        raise ValueError(f"{context} margin path settlements exceed the horizon")

    expected_liquidation_return = -1.0 / int(expected_leverage)
    liquidated = result["mark_liquidated"]
    if not np.allclose(
        result.loc[liquidated, "margin_path_realized_gross_return"],
        expected_liquidation_return,
        rtol=0.0,
        atol=1e-12,
    ):
        raise ValueError(f"{context} liquidation loss does not equal full initial margin")
    if not np.allclose(
        result.loc[~liquidated, "margin_path_realized_gross_return"],
        result.loc[~liquidated, "realized_gross_return"],
        rtol=1e-10,
        atol=1e-12,
    ):
        raise ValueError(f"{context} non-liquidated realized return was rewritten")
    if not effective_time.loc[~liquidated].equals(result.loc[~liquidated, "exit_time"]):
        raise ValueError(f"{context} non-liquidated exit time was rewritten")

    result["effective_realized_gross_return"] = result["margin_path_realized_gross_return"]
    result["exit_time"] = effective_time
    result["historical_funding_realized_rate"] = result["historical_funding_margin_path_rate"]
    result["historical_funding_realized_settlements"] = settlement_counts
    return result, INTRAHORIZON_MARGIN_SCHEMA_VERSION


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
        "liquidation_equity_reserve_fraction": config.liquidation_equity_reserve_fraction,
    }
    for name, value in config_values.items():
        if not np.isfinite(float(value)):
            raise ValueError(f"{name} must be finite")
    for name in ("fee_rate_round_trip", "slippage_rate", "stop_gap_reserve_rate", "min_net_rr"):
        if float(config_values[name]) < 0:
            raise ValueError(f"{name} must be non-negative")
    if (
        isinstance(config.research_leverage, bool)
        or not isinstance(config.research_leverage, (int, np.integer))
        or config.research_leverage <= 0
    ):
        raise ValueError("research_leverage must be a positive integer")
    if not 0.0 <= float(config.liquidation_equity_reserve_fraction) < 1.0:
        raise ValueError("liquidation_equity_reserve_fraction must be in [0, 1)")
    if not isinstance(config.require_intrahorizon_margin, bool):
        raise ValueError("require_intrahorizon_margin must be boolean")

    if (
        isinstance(config.bootstrap_samples, bool)
        or not isinstance(config.bootstrap_samples, (int, np.integer))
        or config.bootstrap_samples < 500
    ):
        raise ValueError("bootstrap_samples must be an integer of at least 500")
    if not np.isfinite(config.confidence_level) or not 0.80 <= config.confidence_level < 1.0:
        raise ValueError("confidence_level must be in [0.80, 1.0)")

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

    meta, intrahorizon_margin_schema = apply_intrahorizon_margin_path(
        meta,
        context="Policy evaluation",
        require=config.require_intrahorizon_margin,
        expected_leverage=int(config.research_leverage),
        expected_equity_reserve_fraction=float(config.liquidation_equity_reserve_fraction),
    )

    timeout_predictor = getattr(model, "predict_timeout_return_r", None)
    if callable(timeout_predictor):
        timeout_return_r = np.asarray(timeout_predictor(split.x_test), dtype=float)
        if timeout_return_r.ndim != 1 or len(timeout_return_r) != len(meta):
            raise ValueError("Conditional TIMEOUT return estimates must align with holdout rows")
        if not np.isfinite(timeout_return_r).all():
            raise ValueError("Conditional TIMEOUT return estimates must be finite")
        support_upper = meta["barrier_upside_rate"] / meta["barrier_downside_rate"]
        bounded_timeout_return_r = np.minimum(
            np.maximum(timeout_return_r, -1.0),
            support_upper.to_numpy(float),
        )
        meta["timeout_return_r"] = bounded_timeout_return_r
        meta["timeout_gross_return_rate"] = bounded_timeout_return_r * meta["barrier_downside_rate"]
        timeout_return_source = TIMEOUT_RETURN_SCHEMA_VERSION
    else:
        meta["timeout_return_r"] = np.where(
            meta["barrier_downside_rate"] > 0,
            config.timeout_return_rate / meta["barrier_downside_rate"],
            0.0,
        )
        meta["timeout_gross_return_rate"] = config.timeout_return_rate
        timeout_return_source = "fixed-config-fallback"

    fee_rate_per_leg = config.fee_rate_round_trip / 2.0
    (
        historical_horizon_recognized_funding,
        historical_horizon_adverse_funding,
        realized_funding,
        historical_funding_schema,
    ) = historical_funding_components(meta, context="Policy evaluation")
    # Actual future settlement rates are valid realized-cost evidence, but they
    # were not available at decision time and therefore must never influence
    # direction selection, actionability, or expected EV. A point-in-time
    # funding forecast can be added separately when historical forecast
    # snapshots exist.
    recognized_funding = np.zeros(len(meta), dtype=float)
    adverse_funding = np.zeros(len(meta), dtype=float)
    meta["historical_funding_horizon_recognized_rate"] = historical_horizon_recognized_funding
    meta["historical_funding_horizon_adverse_rate"] = historical_horizon_adverse_funding
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
        1.0 + meta["timeout_gross_return_rate"],
        1.0 - meta["timeout_gross_return_rate"],
    )
    realized_exit_ratio = np.where(
        is_long,
        1.0 + meta["effective_realized_gross_return"],
        1.0 - meta["effective_realized_gross_return"],
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
        meta["barrier_upside_rate"] - tp_fee_rate - config.slippage_rate + recognized_funding
    )
    meta["stress_downside_rate"] = (
        meta["barrier_downside_rate"]
        + sl_fee_rate
        + config.slippage_rate
        + config.stop_gap_reserve_rate
        + adverse_funding
    )
    meta["timeout_net_rate"] = (
        meta["timeout_gross_return_rate"] - timeout_fee_rate - config.slippage_rate + recognized_funding
    )
    meta["realized_fee_rate"] = fee_rate_per_leg * (1.0 + realized_exit_ratio)
    target = meta["target"].astype(str)
    embedded_stop_gap = np.where(
        target.eq("SL"),
        np.maximum(
            -meta["effective_realized_gross_return"] - meta["barrier_downside_rate"],
            0.0,
        ),
        0.0,
    )
    meta["unused_stop_gap_reserve_rate"] = np.where(
        target.eq("SL"),
        np.maximum(config.stop_gap_reserve_rate - embedded_stop_gap, 0.0),
        0.0,
    )
    # The reserve is a sizing/stress allowance, not a cash flow.  Any actual
    # gap through the stop is already present in realized_gross_return.
    meta["realized_net_rate"] = (
        meta["effective_realized_gross_return"]
        - meta["realized_fee_rate"]
        - config.slippage_rate
        + realized_funding
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
    selected_outcomes = selected["target"].astype(str).to_numpy()
    if not np.isin(selected_outcomes, OUTCOME_CLASSES).all():
        raise ValueError("Policy-selected calibration target contains an unsupported outcome")
    selected_probabilities = selected[["p_tp", "p_sl", "p_timeout"]].to_numpy(float)
    selected_log_loss = _ordered_multiclass_log_loss(
        selected_outcomes,
        selected_probabilities,
        OUTCOME_CLASSES,
    )
    selected_indexes = np.array(
        [{label: index for index, label in enumerate(OUTCOME_CLASSES)}[label] for label in selected_outcomes],
        dtype=int,
    )
    selected_one_hot = np.eye(len(OUTCOME_CLASSES), dtype=float)[selected_indexes]
    selected_multiclass_brier = float(
        np.mean(np.sum((selected_probabilities - selected_one_hot) ** 2, axis=1))
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
        "historical_funding_schema": historical_funding_schema,
        "policy_funding_timeline_complete": historical_funding_schema is not None,
        "policy_expected_funding_source": "none-no-point-in-time-forecast",
        "policy_realized_funding_source": historical_funding_schema,
        "policy_intrahorizon_margin_schema": intrahorizon_margin_schema,
        "policy_intrahorizon_margin_complete": intrahorizon_margin_schema is not None,
        "policy_research_leverage": int(config.research_leverage),
        "policy_liquidation_equity_reserve_fraction": float(config.liquidation_equity_reserve_fraction),
        "policy_liquidation_events": 0,
        "policy_liquidation_rate": 0.0,
        "policy_mark_max_adverse_excursion_mean": None,
        "policy_mark_max_adverse_excursion_max": None,
        "policy_mark_max_favorable_excursion_mean": None,
        "policy_mark_minimum_equity_rate_min": None,
        "policy_timeout_return_schema": timeout_return_source,
        "policy_horizon_hours": resolved_horizon,
        "policy_capital_sleeves": resolved_horizon,
        "policy_candidates": int(len(selected)),
        "policy_actionable_candidates": int(len(actionable_trades)),
        "policy_selected_calibration_schema": PRODUCTION_DRIFT_CALIBRATION_COHORT_SCHEMA,
        "policy_selected_calibration_rows": int(len(selected)),
        "policy_selected_log_loss": float(selected_log_loss),
        "policy_selected_multiclass_brier": selected_multiclass_brier,
        "policy_overlap_blocked_trades": int(overlap_blocked_trades),
        "policy_trades": 0,
        "policy_cohorts": 0,
        "policy_independent_cohorts": 0,
        "policy_horizon_phase_count": 0,
        "policy_horizon_phase_expected": resolved_horizon,
        "policy_independent_mean_r": None,
        "policy_mean_r_lcb": None,
        "policy_mean_r_confidence_level": float(config.confidence_level),
        "policy_mean_r_bootstrap_samples": int(config.bootstrap_samples),
        "policy_mean_r_bootstrap_block_length": 0,
        "policy_mean_r_uncertainty_schema": POLICY_UNCERTAINTY_SCHEMA,
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
    liquidation_events = int(trades["mark_liquidated"].sum()) if intrahorizon_margin_schema else 0
    liquidation_rate = float(liquidation_events / len(trades)) if len(trades) else 0.0
    trades["realized_r"] = np.where(
        trades["stress_downside_rate"] > 0,
        trades["realized_net_rate"] / trades["stress_downside_rate"],
        0.0,
    )
    cohort_size = trades.groupby("decision_time")["realized_r"].transform("size")
    trades["realized_r_contribution"] = trades["realized_r"] / cohort_size / resolved_horizon
    cohort_metrics = trades.groupby("decision_time", sort=True).agg(
        realized_mean_r=("realized_r", "mean"),
        expected_mean_ev_r=("expected_ev_r", "mean"),
    )
    horizon_phases = _horizon_separated_phase_series(
        cohort_metrics["realized_mean_r"],
        horizon_hours=resolved_horizon,
    )
    phase_count = len(horizon_phases)
    independent_cohort_count = min(len(values) for values in horizon_phases.values()) if horizon_phases else 0
    phase_means: list[float] = []
    phase_lower_bounds: list[float] = []
    phase_block_lengths: list[int] = []
    if phase_count == resolved_horizon and independent_cohort_count >= 2:
        # Balance the phases to the same recent sample length so no phase gains
        # more influence merely because the holdout starts or ends mid-cycle.
        for values in horizon_phases.values():
            balanced = values.iloc[-independent_cohort_count:].to_numpy(float)
            phase_mean, phase_lcb, phase_block_length = _policy_mean_r_bootstrap(
                balanced,
                samples=config.bootstrap_samples,
                confidence_level=config.confidence_level,
            )
            phase_means.append(phase_mean)
            phase_lower_bounds.append(phase_lcb)
            phase_block_lengths.append(phase_block_length)
        independent_mean_r = float(min(phase_means))
        policy_mean_r_lcb = float(min(phase_lower_bounds))
        bootstrap_block_length = int(max(phase_block_lengths))
    else:
        independent_mean_r = (
            float(min(values.mean() for values in horizon_phases.values())) if horizon_phases else None
        )
        policy_mean_r_lcb = None
        bootstrap_block_length = 0
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
        "historical_funding_schema": historical_funding_schema,
        "policy_funding_timeline_complete": historical_funding_schema is not None,
        "policy_expected_funding_source": "none-no-point-in-time-forecast",
        "policy_realized_funding_source": historical_funding_schema,
        "policy_intrahorizon_margin_schema": intrahorizon_margin_schema,
        "policy_intrahorizon_margin_complete": intrahorizon_margin_schema is not None,
        "policy_research_leverage": int(config.research_leverage),
        "policy_liquidation_equity_reserve_fraction": float(config.liquidation_equity_reserve_fraction),
        "policy_liquidation_events": liquidation_events,
        "policy_liquidation_rate": liquidation_rate,
        "policy_timeout_return_schema": timeout_return_source,
        "policy_horizon_hours": resolved_horizon,
        "policy_capital_sleeves": resolved_horizon,
        "policy_candidates": int(len(selected)),
        "policy_actionable_candidates": int(len(actionable_trades)),
        "policy_selected_calibration_schema": PRODUCTION_DRIFT_CALIBRATION_COHORT_SCHEMA,
        "policy_selected_calibration_rows": int(len(selected)),
        "policy_selected_log_loss": float(selected_log_loss),
        "policy_selected_multiclass_brier": selected_multiclass_brier,
        "policy_overlap_blocked_trades": int(overlap_blocked_trades),
        "policy_trades": int(len(trades)),
        "policy_cohorts": int(len(cohort_metrics)),
        "policy_independent_cohorts": int(independent_cohort_count),
        "policy_horizon_phase_count": int(phase_count),
        "policy_horizon_phase_expected": resolved_horizon,
        "policy_independent_mean_r": independent_mean_r,
        "policy_mean_r_lcb": policy_mean_r_lcb,
        "policy_mean_r_confidence_level": float(config.confidence_level),
        "policy_mean_r_bootstrap_samples": int(config.bootstrap_samples),
        "policy_mean_r_bootstrap_block_length": int(bootstrap_block_length),
        "policy_mean_r_uncertainty_schema": POLICY_UNCERTAINTY_SCHEMA,
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
        "policy_mark_max_adverse_excursion_mean": (
            float(trades["mark_max_adverse_excursion_rate"].mean()) if intrahorizon_margin_schema else None
        ),
        "policy_mark_max_adverse_excursion_max": (
            float(trades["mark_max_adverse_excursion_rate"].max()) if intrahorizon_margin_schema else None
        ),
        "policy_mark_max_favorable_excursion_mean": (
            float(trades["mark_max_favorable_excursion_rate"].mean()) if intrahorizon_margin_schema else None
        ),
        "policy_mark_minimum_equity_rate_min": (
            float(trades["mark_minimum_equity_rate"].min()) if intrahorizon_margin_schema else None
        ),
    }

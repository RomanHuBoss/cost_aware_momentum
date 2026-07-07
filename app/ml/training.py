from __future__ import annotations

import math
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
    INTRAHORIZON_MTM_PATH_SCHEMA_VERSION,
    build_intrahorizon_mark_to_market_path,
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
ENTRY_EXECUTION_MODEL_SCHEMA = "decision-close-zone-next-hour-open-directional-half-spread-v2"
TEMPORAL_SPLIT_SCHEMA_VERSION = "final-holdout-plus-expanding-walk-forward-v4"
WALK_FORWARD_SCHEMA_VERSION = "expanding-train-rolling-calibration-purged-v1"
DEFAULT_WALK_FORWARD_FOLDS = 3
MIN_WALK_FORWARD_POSITIVE_FRACTION = 2.0 / 3.0
POLICY_METRIC_SCHEMA = "decision-close-zone-directional-spread-entry-funding-mark-mtm-liquidation-cohort-v25"
POLICY_ACTIONABLE_CALIBRATION_SCHEMA = "actionable-policy-trades-final-holdout-v1"
POLICY_DIRECTION_ROBUSTNESS_SCHEMA = "actionable-policy-direction-opportunity-cohort-v1"
POLICY_DIRECTION_MIN_TRADES = 5
POLICY_DIRECTIONS = ("LONG", "SHORT")
POLICY_INTERACTION_ROBUSTNESS_SCHEMA = "symbol-direction-regime-supported-cells-sparse-pool-jackknife-v2"
POLICY_INTERACTION_SPARSE_JACKKNIFE_SCHEMA = "leave-one-sparse-interaction-cell-out-v1"
POLICY_INTERACTION_MIN_TRADES = 5
POLICY_SYMBOL_ROBUSTNESS_SCHEMA = "leave-one-symbol-out-opportunity-cohort-v1"
POLICY_CLUSTER_ROBUSTNESS_SCHEMA = (
    "absolute-correlation-components-leave-one-cluster-out-opportunity-cohort-v1"
)
POLICY_CLUSTER_CORRELATION_THRESHOLD = 0.70
POLICY_CLUSTER_MIN_SHARED_ACTIVE_OBSERVATIONS = 8
POLICY_REGIME_ROBUSTNESS_SCHEMA = "decision-time-development-quantile-market-regimes-v1"
POLICY_REGIME_VOLATILITY_QUANTILE = 0.75
POLICY_REGIME_TREND_SCORE_THRESHOLD = 1.0
POLICY_REGIME_MIN_TRADES = 5
POLICY_REGIME_NAMES = ("DOWNTREND", "RANGE", "UPTREND", "HIGH_VOLATILITY")
POLICY_UNCERTAINTY_SCHEMA = "observed-opportunity-zero-return-all-horizon-phases-circular-moving-block-v3"
HOUR_NS = 3_600_000_000_000
TIMEOUT_RETURN_SCHEMA_VERSION = "training-direction-median-r-v1"
MIN_TIMEOUT_SAMPLES_PER_DIRECTION = 5
POLICY_EXPECTED_FUNDING_SOURCE = "none-no-point-in-time-forecast"

HISTORICAL_FUNDING_POLICY_METADATA_COLUMNS = (
    "historical_funding_timeline_complete",
    "historical_funding_horizon_rate",
    "historical_funding_horizon_settlements",
    "historical_funding_realized_rate",
    "historical_funding_realized_settlements",
)
INTRAHORIZON_MTM_POLICY_METADATA_COLUMNS = (
    "intrahorizon_mark_to_market_path_complete",
    "intrahorizon_mark_to_market_schema",
    "intrahorizon_mark_to_market_path",
)
INTRAHORIZON_MARGIN_POLICY_METADATA_COLUMNS = (
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
)
POLICY_PATH_METADATA_COLUMNS = (
    *HISTORICAL_FUNDING_POLICY_METADATA_COLUMNS,
    *INTRAHORIZON_MARGIN_POLICY_METADATA_COLUMNS,
    *INTRAHORIZON_MTM_POLICY_METADATA_COLUMNS,
)


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
    risk_rate: float = 0.0035
    max_total_open_risk_rate: float = 0.02
    margin_reserve_rate: float = 0.20
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
    entry_zone_atr_fraction: float = 0.12,
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
    try:
        parsed_entry_zone_atr_fraction = float(entry_zone_atr_fraction)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("entry_zone_atr_fraction must be finite and in (0, 1]") from exc
    if (
        not np.isfinite(parsed_entry_zone_atr_fraction)
        or not 0.0 < parsed_entry_zone_atr_fraction <= 1.0
    ):
        raise ValueError("entry_zone_atr_fraction must be finite and in (0, 1]")
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
        "skipped_entry_zone_timestamps": 0,
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
            decision_entry_anchor = float(current.get("close", np.nan))
            half_spread_rate = parsed_entry_spread_bps / 20000.0
            atr_pct = float(current.get("atr_pct_14", np.nan))
            if (
                not np.isfinite(entry_mid_proxy)
                or entry_mid_proxy <= 0
                or not np.isfinite(decision_entry_anchor)
                or decision_entry_anchor <= 0
                or not np.isfinite(atr_pct)
                or atr_pct <= 0
            ):
                continue
            entry_zone_half = (
                decision_entry_anchor * atr_pct * parsed_entry_zone_atr_fraction
            )
            entry_zone_low = decision_entry_anchor - entry_zone_half
            entry_zone_high = decision_entry_anchor + entry_zone_half
            stressed_long_entry = entry_mid_proxy * (1.0 + half_spread_rate)
            stressed_short_entry = entry_mid_proxy * (1.0 - half_spread_rate)
            if not (
                entry_zone_low <= stressed_long_entry <= entry_zone_high
                and entry_zone_low <= stressed_short_entry <= entry_zone_high
            ):
                diagnostics["skipped_entry_zone_timestamps"] += 1
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
                    signed_funding_at_close: list[float] = []
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
                                signed_funding_at_close.append(float(signed_close_funding))
                                running_adverse_funding = close_adverse
                        except ValueError:
                            direction_rows = []
                            break
                    else:
                        adverse_funding_at_open = [0.0] * (result.exit_index + 1)
                        adverse_funding_at_close = [0.0] * (result.exit_index + 1)
                        signed_funding_at_close = [0.0] * (result.exit_index + 1)

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
                    effective_signed_funding_rate = (
                        -float(effective_funding_rate)
                        if direction == "LONG"
                        else float(effective_funding_rate)
                    )
                    mark_to_market_path = build_intrahorizon_mark_to_market_path(
                        mark_future.iloc[: result.exit_index + 1][["close_time", "close"]],
                        direction=direction,
                        entry_price=entry,
                        decision_time=decision_time,
                        exit_time=effective_exit_time,
                        final_gross_return_rate=effective_realized_return,
                        cumulative_signed_funding_return_at_close_by_bar=(
                            signed_funding_at_close
                        ),
                        final_signed_funding_return_rate=effective_signed_funding_rate,
                    )
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
                        "intrahorizon_mark_to_market_path_complete": True,
                        "intrahorizon_mark_to_market_schema": (
                            INTRAHORIZON_MTM_PATH_SCHEMA_VERSION
                        ),
                        "intrahorizon_mark_to_market_path": mark_to_market_path,
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
                        "decision_entry_anchor": float(decision_entry_anchor),
                        "entry_zone_low": float(entry_zone_low),
                        "entry_zone_high": float(entry_zone_high),
                        "entry_zone_atr_fraction": parsed_entry_zone_atr_fraction,
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
        "mark_to_market_path_schema": (
            INTRAHORIZON_MTM_PATH_SCHEMA_VERSION if mark_candles is not None else None
        ),
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
        "entry_zone_atr_fraction": parsed_entry_zone_atr_fraction,
        "decision_anchor_source": "confirmed_decision_candle_close",
        "entry_price_source": "next_hour_open_directional_half_spread_stress",
        "residual_limitations": [
            "historical_bid_ask_unavailable",
            "operator_latency_within_zone_unmodeled",
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
    for entry_column in (
        "entry_price",
        "decision_entry_anchor",
        "entry_zone_low",
        "entry_zone_high",
        "entry_zone_atr_fraction",
    ):
        if entry_column in test.columns:
            meta_columns.insert(5, entry_column)
    for column in POLICY_PATH_METADATA_COLUMNS:
        present = [column in frame.columns for frame in (train, cal, test)]
        if any(present) and not all(present):
            raise ValueError(
                f"Temporal split policy metadata column {column!r} is not present in every window"
            )
        if all(present):
            meta_columns.append(column)
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


def _policy_calibration_metrics(frame: pd.DataFrame, *, context: str) -> dict[str, float | int | None]:
    required = {"target", "p_tp", "p_sl", "p_timeout"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{context} is missing calibration columns: {missing}")
    if frame.empty:
        return {"rows": 0, "log_loss": None, "multiclass_brier": None}

    outcomes = frame["target"].astype(str).to_numpy()
    if not np.isin(outcomes, OUTCOME_CLASSES).all():
        raise ValueError(f"{context} target contains an unsupported outcome")
    probabilities = frame[["p_tp", "p_sl", "p_timeout"]].to_numpy(float)
    log_loss = _ordered_multiclass_log_loss(outcomes, probabilities, OUTCOME_CLASSES)
    class_to_index = {label: index for index, label in enumerate(OUTCOME_CLASSES)}
    indexes = np.asarray([class_to_index[label] for label in outcomes], dtype=int)
    one_hot = np.eye(len(OUTCOME_CLASSES), dtype=float)[indexes]
    return {
        "rows": int(len(frame)),
        "log_loss": float(log_loss),
        "multiclass_brier": float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1))),
    }


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




def _policy_direction_robustness(
    trades: pd.DataFrame,
    opportunity_times: pd.DatetimeIndex,
) -> dict[str, object]:
    """Evaluate exact actionable economics and calibration by selected direction.

    Each direction is recomputed on the complete observed opportunity clock. Hours
    where that direction produced no accepted trade remain zero-return cohorts, so
    a profitable opposite side cannot mask a systematically harmful LONG or SHORT
    policy.
    """

    if opportunity_times.empty or opportunity_times.isna().any() or opportunity_times.has_duplicates:
        raise ValueError("Policy direction robustness requires unique valid opportunity times")
    required = {
        "direction",
        "decision_time",
        "realized_r",
        "target",
        "p_tp",
        "p_sl",
        "p_timeout",
    }
    missing = sorted(required - set(trades.columns))
    if missing:
        raise ValueError(f"Policy direction robustness is missing trade columns: {missing}")
    frame = trades.copy()
    frame["direction"] = frame["direction"].astype(str).str.strip().str.upper()
    frame["decision_time"] = pd.to_datetime(frame["decision_time"], utc=True, errors="coerce")
    frame["realized_r"] = pd.to_numeric(frame["realized_r"], errors="coerce")
    if (
        frame["decision_time"].isna().any()
        or frame["realized_r"].isna().any()
        or not np.isfinite(frame["realized_r"].to_numpy(float)).all()
        or (~frame["direction"].isin(POLICY_DIRECTIONS)).any()
        or not set(frame["decision_time"]).issubset(set(opportunity_times))
    ):
        raise ValueError("Policy direction trade evidence is invalid")

    total_trades = int(len(frame))
    entries: list[dict[str, object]] = []
    for direction in POLICY_DIRECTIONS:
        direction_trades = frame[frame["direction"].eq(direction)].copy()
        trade_cohorts = (
            int(direction_trades["decision_time"].nunique()) if len(direction_trades) else 0
        )
        if len(direction_trades):
            cohort_returns = direction_trades.groupby("decision_time", sort=True)["realized_r"].mean()
            realized_mean = float(cohort_returns.reindex(opportunity_times, fill_value=0.0).mean())
        else:
            realized_mean = 0.0
        calibration = _policy_calibration_metrics(
            direction_trades,
            context=f"Policy actionable calibration for {direction}",
        )
        entries.append(
            {
                "direction": direction,
                "opportunities": int(len(opportunity_times)),
                "trade_cohorts": trade_cohorts,
                "no_trade_cohorts": int(len(opportunity_times) - trade_cohorts),
                "trades": int(len(direction_trades)),
                "trade_fraction": (
                    float(len(direction_trades) / total_trades) if total_trades else 0.0
                ),
                "realized_mean_r": realized_mean,
                "calibration_rows": int(calibration["rows"]),
                "log_loss": calibration["log_loss"],
                "multiclass_brier": calibration["multiclass_brier"],
            }
        )
    traded = [item for item in entries if int(item["trades"]) > 0]
    return {
        "schema": POLICY_DIRECTION_ROBUSTNESS_SCHEMA,
        "minimum_trades_per_traded_direction": POLICY_DIRECTION_MIN_TRADES,
        "opportunity_count": int(len(opportunity_times)),
        "trade_count": total_trades,
        "direction_count": len(entries),
        "traded_direction_count": len(traded),
        "worst_traded_direction_mean_r": (
            float(min(item["realized_mean_r"] for item in traded)) if traded else None
        ),
        "worst_traded_direction_log_loss": (
            float(max(item["log_loss"] for item in traded)) if traded else None
        ),
        "worst_traded_direction_multiclass_brier": (
            float(max(item["multiclass_brier"] for item in traded)) if traded else None
        ),
        "directions": entries,
    }


def validate_policy_direction_robustness(
    evidence: object,
    *,
    policy_trades: int,
    policy_cohorts: int,
) -> dict[str, object]:
    """Validate immutable per-direction evidence and exact arithmetic."""

    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in (policy_trades, policy_cohorts)
    ):
        raise ValueError("Policy direction counts must be non-negative integers")
    if (
        not isinstance(evidence, dict)
        or evidence.get("schema") != POLICY_DIRECTION_ROBUSTNESS_SCHEMA
    ):
        raise ValueError("Policy direction robustness evidence is required")
    if evidence.get("minimum_trades_per_traded_direction") != POLICY_DIRECTION_MIN_TRADES:
        raise ValueError("Policy direction minimum trade contract mismatch")
    count_keys = ("opportunity_count", "trade_count", "direction_count", "traded_direction_count")
    counts: dict[str, int] = {}
    for key in count_keys:
        raw = evidence.get(key)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise ValueError("Policy direction count evidence is invalid")
        counts[key] = raw
    if (
        counts["opportunity_count"] != policy_cohorts
        or counts["trade_count"] != policy_trades
        or counts["direction_count"] != len(POLICY_DIRECTIONS)
    ):
        raise ValueError("Policy direction totals mismatch policy metrics")
    raw_entries = evidence.get("directions")
    if not isinstance(raw_entries, list) or len(raw_entries) != len(POLICY_DIRECTIONS):
        raise ValueError("Policy direction entries are invalid")

    normalized: list[dict[str, object]] = []
    total_trades = traded_count = 0
    for expected_direction, item in zip(POLICY_DIRECTIONS, raw_entries, strict=True):
        if not isinstance(item, dict) or item.get("direction") != expected_direction:
            raise ValueError("Policy direction entries are not in canonical order")
        integers: dict[str, int] = {}
        for key in (
            "opportunities",
            "trade_cohorts",
            "no_trade_cohorts",
            "trades",
            "calibration_rows",
        ):
            raw = item.get(key)
            if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
                raise ValueError("Policy direction entry count is invalid")
            integers[key] = raw
        if integers["opportunities"] != policy_cohorts:
            raise ValueError("Policy direction opportunity clock mismatch")
        if integers["trade_cohorts"] > integers["opportunities"]:
            raise ValueError("Policy direction trade cohorts exceed opportunities")
        if integers["no_trade_cohorts"] != integers["opportunities"] - integers["trade_cohorts"]:
            raise ValueError("Policy direction no-trade cohorts are inconsistent")
        if integers["trade_cohorts"] > integers["trades"]:
            raise ValueError("Policy direction trade cohorts exceed trades")
        if integers["calibration_rows"] != integers["trades"]:
            raise ValueError("Policy direction calibration rows mismatch trades")

        raw_fraction = item.get("trade_fraction")
        raw_mean = item.get("realized_mean_r")
        if isinstance(raw_fraction, bool) or isinstance(raw_mean, bool):
            raise ValueError("Policy direction metric is invalid")
        try:
            fraction = float(raw_fraction)
            realized_mean = float(raw_mean)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Policy direction metric is invalid") from exc
        expected_fraction = integers["trades"] / policy_trades if policy_trades else 0.0
        if (
            not math.isfinite(fraction)
            or not math.isclose(fraction, expected_fraction, rel_tol=1e-9, abs_tol=1e-12)
            or not math.isfinite(realized_mean)
        ):
            raise ValueError("Policy direction metric is inconsistent")

        log_loss = item.get("log_loss")
        brier = item.get("multiclass_brier")
        if integers["trades"] > 0:
            resolved_metrics: list[float] = []
            for raw in (log_loss, brier):
                if isinstance(raw, bool):
                    raise ValueError("Policy direction calibration metric is invalid")
                try:
                    value = float(raw)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ValueError("Policy direction calibration metric is invalid") from exc
                if not math.isfinite(value) or value < 0.0:
                    raise ValueError("Policy direction calibration metric is invalid")
                resolved_metrics.append(value)
            log_loss, brier = resolved_metrics
            traded_count += 1
        elif (
            log_loss is not None
            or brier is not None
            or not math.isclose(realized_mean, 0.0, abs_tol=1e-12)
        ):
            raise ValueError("Non-traded policy direction contains non-empty outcomes")

        total_trades += integers["trades"]
        normalized.append(
            {
                "direction": expected_direction,
                **integers,
                "trade_fraction": fraction,
                "realized_mean_r": realized_mean,
                "log_loss": log_loss,
                "multiclass_brier": brier,
            }
        )
    if total_trades != policy_trades or traded_count != counts["traded_direction_count"]:
        raise ValueError("Policy direction entry totals are inconsistent")

    traded = [item for item in normalized if int(item["trades"]) > 0]
    summaries = {
        "worst_traded_direction_mean_r": min(
            (float(item["realized_mean_r"]) for item in traded), default=None
        ),
        "worst_traded_direction_log_loss": max(
            (float(item["log_loss"]) for item in traded), default=None
        ),
        "worst_traded_direction_multiclass_brier": max(
            (float(item["multiclass_brier"]) for item in traded), default=None
        ),
    }
    for key, expected in summaries.items():
        raw = evidence.get(key)
        if expected is None:
            if raw is not None:
                raise ValueError("Policy direction summary must be empty without trades")
        else:
            if isinstance(raw, bool):
                raise ValueError("Policy direction summary is invalid")
            try:
                actual = float(raw)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("Policy direction summary is invalid") from exc
            if (
                not math.isfinite(actual)
                or not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12)
            ):
                raise ValueError("Policy direction summary is inconsistent")
    return {
        "schema": POLICY_DIRECTION_ROBUSTNESS_SCHEMA,
        "minimum_trades_per_traded_direction": POLICY_DIRECTION_MIN_TRADES,
        "opportunity_count": policy_cohorts,
        "trade_count": policy_trades,
        "direction_count": counts["direction_count"],
        "traded_direction_count": counts["traded_direction_count"],
        **summaries,
        "directions": normalized,
    }

def _development_high_volatility_atr_pct_threshold(split: DatasetSplit) -> float:
    """Derive the high-volatility cutoff from development data only."""

    atr_index = MODEL_FEATURE_NAMES.index("atr_pct_14")
    values = np.asarray(split.x_train, dtype=float)
    if values.ndim != 2:
        raise ValueError("Development feature matrix is invalid for regime classification")
    if values.shape[1] != len(MODEL_FEATURE_NAMES):
        if split.train_meta is not None:
            raise ValueError("Development feature matrix is invalid for regime classification")
        fallback_meta = split.test_meta
        if "barrier_downside_rate" not in fallback_meta.columns:
            raise ValueError("Development feature matrix is invalid for regime classification")
        fallback = pd.to_numeric(
            fallback_meta["barrier_downside_rate"], errors="coerce"
        ).to_numpy(float) / DEFAULT_STOP_ATR_MULTIPLIER
        if len(fallback) == 0 or not np.isfinite(fallback).all() or (fallback <= 0.0).any():
            raise ValueError("Legacy policy fixture cannot derive a valid ATR regime reference")
        return float(np.quantile(fallback, POLICY_REGIME_VOLATILITY_QUANTILE))
    atr_values = values[:, atr_index]
    valid_atr = len(atr_values) > 0 and np.isfinite(atr_values).all() and (atr_values > 0.0).all()
    if not valid_atr:
        if split.train_meta is not None:
            raise ValueError("Development ATR percentages must be finite and positive")
        fallback_meta = split.test_meta
        if "barrier_downside_rate" not in fallback_meta.columns:
            raise ValueError("Development ATR percentages must be finite and positive")
        fallback = pd.to_numeric(fallback_meta["barrier_downside_rate"], errors="coerce").to_numpy(float)
        fallback = fallback / DEFAULT_STOP_ATR_MULTIPLIER
        if not np.isfinite(fallback).all() or (fallback <= 0.0).any():
            raise ValueError("Legacy policy fixture cannot derive a valid ATR regime reference")
        return float(np.quantile(fallback, POLICY_REGIME_VOLATILITY_QUANTILE))

    if split.train_meta is not None and len(split.train_meta) == len(atr_values):
        frame = split.train_meta.loc[:, ["decision_time", "symbol"]].copy()
        frame["decision_time"] = pd.to_datetime(frame["decision_time"], utc=True, errors="coerce")
        frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
        frame["atr_pct_14"] = atr_values
        if frame["decision_time"].isna().any() or (frame["symbol"] == "").any():
            raise ValueError("Development regime metadata is invalid")
        per_symbol = frame.groupby(["decision_time", "symbol"], sort=True)["atr_pct_14"].agg(
            ["min", "max"]
        )
        if not np.allclose(per_symbol["min"], per_symbol["max"], rtol=1e-10, atol=1e-12):
            raise ValueError("Directional development rows disagree on ATR regime feature")
        reference = per_symbol["min"].groupby(level="decision_time", sort=True).median().to_numpy(float)
    else:
        reference = atr_values
    threshold = float(np.quantile(reference, POLICY_REGIME_VOLATILITY_QUANTILE))
    if not math.isfinite(threshold) or threshold <= 0.0:
        raise ValueError("Development high-volatility threshold is invalid")
    return threshold


def _policy_market_regime_frame(
    *,
    selected: pd.DataFrame,
    opportunity_times: pd.DatetimeIndex,
    development_high_volatility_atr_pct_threshold: float,
) -> pd.DataFrame:
    """Return one ex-ante market regime for every observed decision time."""

    threshold = float(development_high_volatility_atr_pct_threshold)
    if not math.isfinite(threshold) or threshold <= 0.0:
        raise ValueError("Policy regime volatility threshold must be finite and positive")
    if opportunity_times.empty or opportunity_times.isna().any() or opportunity_times.has_duplicates:
        raise ValueError("Policy regime robustness requires unique valid opportunity times")
    required_selected = {"decision_time", "regime_ret_24h", "regime_atr_pct_14"}
    missing_selected = sorted(required_selected - set(selected.columns))
    if missing_selected:
        raise ValueError(f"Policy regime robustness is missing opportunity columns: {missing_selected}")
    opportunities = selected.loc[:, sorted(required_selected)].copy()
    opportunities["decision_time"] = pd.to_datetime(
        opportunities["decision_time"], utc=True, errors="coerce"
    )
    opportunities["regime_ret_24h"] = pd.to_numeric(
        opportunities["regime_ret_24h"], errors="coerce"
    )
    opportunities["regime_atr_pct_14"] = pd.to_numeric(
        opportunities["regime_atr_pct_14"], errors="coerce"
    )
    if (
        opportunities["decision_time"].isna().any()
        or opportunities[["regime_ret_24h", "regime_atr_pct_14"]].isna().any().any()
        or not np.isfinite(
            opportunities[["regime_ret_24h", "regime_atr_pct_14"]].to_numpy(float)
        ).all()
        or (opportunities["regime_atr_pct_14"] <= 0.0).any()
    ):
        raise ValueError("Policy regime opportunity evidence is invalid")
    market = opportunities.groupby("decision_time", sort=True).agg(
        market_ret_24h=("regime_ret_24h", "median"),
        market_atr_pct_14=("regime_atr_pct_14", "median"),
    )
    market = market.reindex(opportunity_times)
    if market.isna().any().any():
        raise ValueError("Policy regime opportunity clock does not match selected evidence")
    trend_score = market["market_ret_24h"] / market["market_atr_pct_14"]
    regime = pd.Series("RANGE", index=market.index, dtype="object")
    regime.loc[trend_score >= POLICY_REGIME_TREND_SCORE_THRESHOLD] = "UPTREND"
    regime.loc[trend_score <= -POLICY_REGIME_TREND_SCORE_THRESHOLD] = "DOWNTREND"
    regime.loc[market["market_atr_pct_14"] >= threshold] = "HIGH_VOLATILITY"
    market["regime"] = regime
    return market


def _policy_regime_robustness(
    *,
    selected: pd.DataFrame,
    trades: pd.DataFrame,
    opportunity_times: pd.DatetimeIndex,
    development_high_volatility_atr_pct_threshold: float,
) -> dict[str, object]:
    """Evaluate economics and calibration within ex-ante decision-time regimes."""

    threshold = float(development_high_volatility_atr_pct_threshold)
    market = _policy_market_regime_frame(
        selected=selected,
        opportunity_times=opportunity_times,
        development_high_volatility_atr_pct_threshold=threshold,
    )

    required_trade = {"decision_time", "realized_r", "target", "p_tp", "p_sl", "p_timeout"}
    missing_trade = sorted(required_trade - set(trades.columns))
    if missing_trade:
        raise ValueError(f"Policy regime robustness is missing trade columns: {missing_trade}")
    trade_frame = trades.copy()
    trade_frame["decision_time"] = pd.to_datetime(
        trade_frame["decision_time"], utc=True, errors="coerce"
    )
    trade_frame["realized_r"] = pd.to_numeric(trade_frame["realized_r"], errors="coerce")
    if (
        trade_frame["decision_time"].isna().any()
        or trade_frame["realized_r"].isna().any()
        or not np.isfinite(trade_frame["realized_r"].to_numpy(float)).all()
        or not set(trade_frame["decision_time"]).issubset(set(opportunity_times))
    ):
        raise ValueError("Policy regime trade evidence is invalid")
    trade_frame = trade_frame.merge(
        market[["regime"]], left_on="decision_time", right_index=True, how="left", validate="many_to_one"
    )
    if trade_frame["regime"].isna().any():
        raise ValueError("Policy regime classification is missing for a trade")

    total_trades = int(len(trade_frame))
    entries: list[dict[str, object]] = []
    for regime_name in POLICY_REGIME_NAMES:
        regime_times = market.index[market["regime"].eq(regime_name)]
        if len(regime_times) == 0:
            continue
        regime_trades = trade_frame[trade_frame["regime"].eq(regime_name)].copy()
        trade_cohorts = int(regime_trades["decision_time"].nunique()) if len(regime_trades) else 0
        if len(regime_trades):
            cohort_returns = regime_trades.groupby("decision_time", sort=True)["realized_r"].mean()
            realized_mean = float(cohort_returns.reindex(regime_times, fill_value=0.0).mean())
        else:
            realized_mean = 0.0
        calibration = _policy_calibration_metrics(
            regime_trades,
            context=f"Policy actionable calibration for {regime_name}",
        )
        entries.append(
            {
                "regime": regime_name,
                "opportunities": int(len(regime_times)),
                "trade_cohorts": trade_cohorts,
                "no_trade_cohorts": int(len(regime_times) - trade_cohorts),
                "trades": int(len(regime_trades)),
                "trade_fraction": float(len(regime_trades) / total_trades) if total_trades else 0.0,
                "realized_mean_r": realized_mean,
                "calibration_rows": int(calibration["rows"]),
                "log_loss": calibration["log_loss"],
                "multiclass_brier": calibration["multiclass_brier"],
            }
        )
    traded = [item for item in entries if int(item["trades"]) > 0]
    return {
        "schema": POLICY_REGIME_ROBUSTNESS_SCHEMA,
        "volatility_quantile": POLICY_REGIME_VOLATILITY_QUANTILE,
        "development_high_volatility_atr_pct_threshold": threshold,
        "trend_score_threshold": POLICY_REGIME_TREND_SCORE_THRESHOLD,
        "minimum_trades_per_traded_regime": POLICY_REGIME_MIN_TRADES,
        "opportunity_count": int(len(opportunity_times)),
        "trade_count": total_trades,
        "regime_count": len(entries),
        "traded_regime_count": len(traded),
        "worst_traded_regime_mean_r": (
            float(min(item["realized_mean_r"] for item in traded)) if traded else None
        ),
        "worst_traded_regime_log_loss": (
            float(max(item["log_loss"] for item in traded)) if traded else None
        ),
        "worst_traded_regime_multiclass_brier": (
            float(max(item["multiclass_brier"] for item in traded)) if traded else None
        ),
        "regimes": entries,
    }


def validate_policy_regime_robustness(
    evidence: object,
    *,
    policy_trades: int,
    policy_cohorts: int,
) -> dict[str, object]:
    """Validate immutable regime evidence and all arithmetic relationships."""

    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (policy_trades, policy_cohorts)):
        raise ValueError("Policy regime counts must be non-negative integers")
    if not isinstance(evidence, dict) or evidence.get("schema") != POLICY_REGIME_ROBUSTNESS_SCHEMA:
        raise ValueError("Policy regime robustness evidence is required")
    for key, expected in (
        ("volatility_quantile", POLICY_REGIME_VOLATILITY_QUANTILE),
        ("trend_score_threshold", POLICY_REGIME_TREND_SCORE_THRESHOLD),
    ):
        raw = evidence.get(key)
        if isinstance(raw, bool):
            raise ValueError("Policy regime parameter is invalid")
        try:
            value = float(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Policy regime parameter is invalid") from exc
        if not math.isfinite(value) or not math.isclose(value, expected, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("Policy regime parameter mismatch")
    raw_threshold = evidence.get("development_high_volatility_atr_pct_threshold")
    try:
        threshold = float(raw_threshold)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Policy regime volatility threshold is invalid") from exc
    if isinstance(raw_threshold, bool) or not math.isfinite(threshold) or threshold <= 0.0:
        raise ValueError("Policy regime volatility threshold is invalid")
    if evidence.get("minimum_trades_per_traded_regime") != POLICY_REGIME_MIN_TRADES:
        raise ValueError("Policy regime minimum trade contract mismatch")
    count_keys = ("opportunity_count", "trade_count", "regime_count", "traded_regime_count")
    counts: dict[str, int] = {}
    for key in count_keys:
        raw = evidence.get(key)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise ValueError("Policy regime count evidence is invalid")
        counts[key] = raw
    if counts["opportunity_count"] != policy_cohorts or counts["trade_count"] != policy_trades:
        raise ValueError("Policy regime totals mismatch policy metrics")
    raw_entries = evidence.get("regimes")
    if not isinstance(raw_entries, list) or len(raw_entries) != counts["regime_count"]:
        raise ValueError("Policy regime entries are invalid")
    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    total_opportunities = total_trades = traded_count = 0
    for item in raw_entries:
        if not isinstance(item, dict):
            raise ValueError("Policy regime entry is invalid")
        regime_name = item.get("regime")
        if regime_name not in POLICY_REGIME_NAMES or regime_name in seen:
            raise ValueError("Policy regime name is invalid or duplicated")
        seen.add(str(regime_name))
        integers: dict[str, int] = {}
        for key in ("opportunities", "trade_cohorts", "no_trade_cohorts", "trades", "calibration_rows"):
            raw = item.get(key)
            if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
                raise ValueError("Policy regime entry count is invalid")
            integers[key] = raw
        if integers["opportunities"] <= 0:
            raise ValueError("Policy regime must contain at least one opportunity")
        if integers["trade_cohorts"] > integers["opportunities"]:
            raise ValueError("Policy regime trade cohorts exceed opportunities")
        if integers["no_trade_cohorts"] != integers["opportunities"] - integers["trade_cohorts"]:
            raise ValueError("Policy regime no-trade cohorts are inconsistent")
        if integers["trade_cohorts"] > integers["trades"]:
            raise ValueError("Policy regime trade cohorts exceed trades")
        if integers["calibration_rows"] != integers["trades"]:
            raise ValueError("Policy regime calibration rows mismatch trades")
        raw_fraction = item.get("trade_fraction")
        raw_mean = item.get("realized_mean_r")
        if isinstance(raw_fraction, bool) or isinstance(raw_mean, bool):
            raise ValueError("Policy regime metric is invalid")
        try:
            fraction = float(raw_fraction)
            realized_mean = float(raw_mean)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Policy regime metric is invalid") from exc
        expected_fraction = integers["trades"] / policy_trades if policy_trades else 0.0
        if (
            not math.isfinite(fraction)
            or not math.isclose(fraction, expected_fraction, rel_tol=1e-9, abs_tol=1e-12)
            or not math.isfinite(realized_mean)
        ):
            raise ValueError("Policy regime metric is inconsistent")
        log_loss = item.get("log_loss")
        brier = item.get("multiclass_brier")
        if integers["trades"] > 0:
            resolved_metrics: list[float] = []
            for raw in (log_loss, brier):
                if isinstance(raw, bool):
                    raise ValueError("Policy regime calibration metric is invalid")
                try:
                    value = float(raw)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ValueError("Policy regime calibration metric is invalid") from exc
                if not math.isfinite(value) or value < 0.0:
                    raise ValueError("Policy regime calibration metric is invalid")
                resolved_metrics.append(value)
            log_loss, brier = resolved_metrics
            traded_count += 1
        else:
            if log_loss is not None or brier is not None or not math.isclose(realized_mean, 0.0, abs_tol=1e-12):
                raise ValueError("Non-traded policy regime contains non-empty outcomes")
        total_opportunities += integers["opportunities"]
        total_trades += integers["trades"]
        normalized.append(
            {
                "regime": regime_name,
                **integers,
                "trade_fraction": fraction,
                "realized_mean_r": realized_mean,
                "log_loss": log_loss,
                "multiclass_brier": brier,
            }
        )
    expected_order = [name for name in POLICY_REGIME_NAMES if name in seen]
    if [item["regime"] for item in normalized] != expected_order:
        raise ValueError("Policy regime entries are not in canonical order")
    if total_opportunities != policy_cohorts or total_trades != policy_trades or traded_count != counts["traded_regime_count"]:
        raise ValueError("Policy regime entry totals are inconsistent")
    traded = [item for item in normalized if int(item["trades"]) > 0]
    summaries = {
        "worst_traded_regime_mean_r": min((float(item["realized_mean_r"]) for item in traded), default=None),
        "worst_traded_regime_log_loss": max((float(item["log_loss"]) for item in traded), default=None),
        "worst_traded_regime_multiclass_brier": max((float(item["multiclass_brier"]) for item in traded), default=None),
    }
    for key, expected in summaries.items():
        raw = evidence.get(key)
        if expected is None:
            if raw is not None:
                raise ValueError("Policy regime summary must be empty without trades")
        else:
            if isinstance(raw, bool):
                raise ValueError("Policy regime summary is invalid")
            try:
                actual = float(raw)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("Policy regime summary is invalid") from exc
            if not math.isfinite(actual) or not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12):
                raise ValueError("Policy regime summary is inconsistent")
    return {
        "schema": POLICY_REGIME_ROBUSTNESS_SCHEMA,
        "volatility_quantile": POLICY_REGIME_VOLATILITY_QUANTILE,
        "development_high_volatility_atr_pct_threshold": threshold,
        "trend_score_threshold": POLICY_REGIME_TREND_SCORE_THRESHOLD,
        "minimum_trades_per_traded_regime": POLICY_REGIME_MIN_TRADES,
        "opportunity_count": policy_cohorts,
        "trade_count": policy_trades,
        "regime_count": counts["regime_count"],
        "traded_regime_count": counts["traded_regime_count"],
        **summaries,
        "regimes": normalized,
    }


def _policy_interaction_robustness(
    *,
    selected: pd.DataFrame,
    trades: pd.DataFrame,
    opportunity_times: pd.DatetimeIndex,
    development_high_volatility_atr_pct_threshold: float,
) -> dict[str, object]:
    """Evaluate symbol × direction × regime cells without tiny-cell multiplicity.

    Cells with at least ``POLICY_INTERACTION_MIN_TRADES`` are evaluated
    separately.  Smaller cells are pooled into one preregistered sparse tail, so
    sparse policies do not create dozens of underpowered tests while their
    combined economics and calibration remain fail-closed evidence.
    """

    market = _policy_market_regime_frame(
        selected=selected,
        opportunity_times=opportunity_times,
        development_high_volatility_atr_pct_threshold=(
            development_high_volatility_atr_pct_threshold
        ),
    )
    required = {
        "symbol",
        "direction",
        "decision_time",
        "realized_r",
        "target",
        "p_tp",
        "p_sl",
        "p_timeout",
    }
    missing = sorted(required - set(trades.columns))
    if missing:
        raise ValueError(f"Policy interaction robustness is missing trade columns: {missing}")
    frame = trades.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame["direction"] = frame["direction"].astype(str).str.strip().str.upper()
    frame["decision_time"] = pd.to_datetime(frame["decision_time"], utc=True, errors="coerce")
    frame["realized_r"] = pd.to_numeric(frame["realized_r"], errors="coerce")
    if (
        frame["decision_time"].isna().any()
        or frame["realized_r"].isna().any()
        or not np.isfinite(frame["realized_r"].to_numpy(float)).all()
        or (frame["symbol"] == "").any()
        or (~frame["direction"].isin(POLICY_DIRECTIONS)).any()
        or not set(frame["decision_time"]).issubset(set(opportunity_times))
    ):
        raise ValueError("Policy interaction trade evidence is invalid")
    frame = frame.merge(
        market[["regime"]],
        left_on="decision_time",
        right_index=True,
        how="left",
        validate="many_to_one",
    )
    if frame["regime"].isna().any():
        raise ValueError("Policy interaction regime classification is missing for a trade")

    direction_order = {name: index for index, name in enumerate(POLICY_DIRECTIONS)}
    regime_order = {name: index for index, name in enumerate(POLICY_REGIME_NAMES)}
    grouped: list[tuple[tuple[str, str, str], pd.DataFrame]] = []
    for key, cell in frame.groupby(["symbol", "direction", "regime"], sort=False):
        symbol, direction, regime = (str(value) for value in key)
        grouped.append(((symbol, direction, regime), cell.copy()))
    grouped.sort(
        key=lambda item: (
            item[0][0],
            direction_order[item[0][1]],
            regime_order[item[0][2]],
        )
    )

    total_trades = int(len(frame))
    entries: list[dict[str, object]] = []
    sparse_indexes: list[object] = []
    for (symbol, direction, regime), cell in grouped:
        trade_count = int(len(cell))
        support = (
            "SUPPORTED" if trade_count >= POLICY_INTERACTION_MIN_TRADES else "SPARSE"
        )
        calibration = _policy_calibration_metrics(
            cell,
            context=f"Policy interaction calibration for {symbol}/{direction}/{regime}",
        )
        entries.append(
            {
                "symbol": symbol,
                "direction": direction,
                "regime": regime,
                "support": support,
                "trades": trade_count,
                "trade_fraction": (
                    float(trade_count / total_trades) if total_trades else 0.0
                ),
                "realized_trade_mean_r": float(cell["realized_r"].mean()),
                "calibration_rows": int(calibration["rows"]),
                "log_loss": calibration["log_loss"],
                "multiclass_brier": calibration["multiclass_brier"],
            }
        )
        if support == "SPARSE":
            sparse_indexes.extend(cell.index.tolist())

    supported = [item for item in entries if item["support"] == "SUPPORTED"]
    sparse = [item for item in entries if item["support"] == "SPARSE"]
    sparse_frame = frame.loc[sparse_indexes].copy() if sparse_indexes else frame.iloc[0:0].copy()
    sparse_pool: dict[str, object] | None = None
    if len(sparse_frame):
        calibration = _policy_calibration_metrics(
            sparse_frame,
            context="Policy interaction sparse-pool calibration",
        )
        leave_one_cell_out: list[dict[str, object]] = []
        for omitted in sparse:
            omitted_symbol = str(omitted["symbol"])
            omitted_direction = str(omitted["direction"])
            omitted_regime = str(omitted["regime"])
            residual = sparse_frame.loc[
                ~(
                    (sparse_frame["symbol"] == omitted_symbol)
                    & (sparse_frame["direction"] == omitted_direction)
                    & (sparse_frame["regime"] == omitted_regime)
                )
            ].copy()
            residual_trades = int(len(residual))
            residual_calibration = (
                _policy_calibration_metrics(
                    residual,
                    context=(
                        "Policy interaction sparse-pool leave-one-cell-out calibration "
                        f"without {omitted_symbol}/{omitted_direction}/{omitted_regime}"
                    ),
                )
                if residual_trades
                else None
            )
            leave_one_cell_out.append(
                {
                    "omitted_symbol": omitted_symbol,
                    "omitted_direction": omitted_direction,
                    "omitted_regime": omitted_regime,
                    "omitted_trades": int(omitted["trades"]),
                    "residual_trades": residual_trades,
                    "residual_trade_fraction_of_sparse_pool": float(
                        residual_trades / len(sparse_frame)
                    ),
                    "residual_realized_trade_mean_r": (
                        float(residual["realized_r"].mean())
                        if residual_trades
                        else None
                    ),
                    "calibration_rows": residual_trades,
                    "log_loss": (
                        residual_calibration["log_loss"]
                        if residual_calibration is not None
                        else None
                    ),
                    "multiclass_brier": (
                        residual_calibration["multiclass_brier"]
                        if residual_calibration is not None
                        else None
                    ),
                }
            )
        nonempty_residuals = [
            item for item in leave_one_cell_out if int(item["residual_trades"]) > 0
        ]
        sparse_pool = {
            "cell_count": len(sparse),
            "trades": int(len(sparse_frame)),
            "trade_fraction": float(len(sparse_frame) / total_trades),
            "realized_trade_mean_r": float(sparse_frame["realized_r"].mean()),
            "calibration_rows": int(calibration["rows"]),
            "log_loss": calibration["log_loss"],
            "multiclass_brier": calibration["multiclass_brier"],
            "jackknife_schema": POLICY_INTERACTION_SPARSE_JACKKNIFE_SCHEMA,
            "minimum_residual_trades": POLICY_INTERACTION_MIN_TRADES,
            "leave_one_cell_out_count": len(leave_one_cell_out),
            "minimum_leave_one_cell_out_residual_trades": min(
                int(item["residual_trades"]) for item in leave_one_cell_out
            ),
            "worst_leave_one_cell_out_mean_r": (
                float(
                    min(
                        float(item["residual_realized_trade_mean_r"])
                        for item in nonempty_residuals
                    )
                )
                if nonempty_residuals
                else None
            ),
            "worst_leave_one_cell_out_log_loss": (
                float(max(float(item["log_loss"]) for item in nonempty_residuals))
                if nonempty_residuals
                else None
            ),
            "worst_leave_one_cell_out_multiclass_brier": (
                float(
                    max(float(item["multiclass_brier"]) for item in nonempty_residuals)
                )
                if nonempty_residuals
                else None
            ),
            "leave_one_cell_out": leave_one_cell_out,
        }
    tested_buckets: list[dict[str, object]] = [*supported]
    if sparse_pool is not None:
        tested_buckets.append(sparse_pool)
    return {
        "schema": POLICY_INTERACTION_ROBUSTNESS_SCHEMA,
        "minimum_trades_per_supported_cell": POLICY_INTERACTION_MIN_TRADES,
        "trade_count": total_trades,
        "observed_cell_count": len(entries),
        "supported_cell_count": len(supported),
        "sparse_cell_count": len(sparse),
        "supported_trade_count": sum(int(item["trades"]) for item in supported),
        "sparse_trade_count": sum(int(item["trades"]) for item in sparse),
        "tested_bucket_count": len(tested_buckets),
        "worst_tested_bucket_mean_r": (
            float(min(item["realized_trade_mean_r"] for item in tested_buckets))
            if tested_buckets
            else None
        ),
        "worst_tested_bucket_log_loss": (
            float(max(item["log_loss"] for item in tested_buckets))
            if tested_buckets
            else None
        ),
        "worst_tested_bucket_multiclass_brier": (
            float(max(item["multiclass_brier"] for item in tested_buckets))
            if tested_buckets
            else None
        ),
        "cells": entries,
        "sparse_pool": sparse_pool,
    }


def validate_policy_interaction_robustness(
    evidence: object,
    *,
    policy_trades: int,
) -> dict[str, object]:
    """Validate immutable interaction-cell evidence and pooled sparse arithmetic."""

    if isinstance(policy_trades, bool) or not isinstance(policy_trades, int) or policy_trades < 0:
        raise ValueError("Policy interaction trade count must be a non-negative integer")
    if (
        not isinstance(evidence, dict)
        or evidence.get("schema") != POLICY_INTERACTION_ROBUSTNESS_SCHEMA
    ):
        raise ValueError("Policy interaction robustness evidence is required")
    if evidence.get("minimum_trades_per_supported_cell") != POLICY_INTERACTION_MIN_TRADES:
        raise ValueError("Policy interaction minimum trade contract mismatch")

    count_keys = (
        "trade_count",
        "observed_cell_count",
        "supported_cell_count",
        "sparse_cell_count",
        "supported_trade_count",
        "sparse_trade_count",
        "tested_bucket_count",
    )
    counts: dict[str, int] = {}
    for key in count_keys:
        raw = evidence.get(key)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise ValueError("Policy interaction count evidence is invalid")
        counts[key] = raw
    if counts["trade_count"] != policy_trades:
        raise ValueError("Policy interaction trade total mismatch")

    raw_cells = evidence.get("cells")
    if not isinstance(raw_cells, list) or len(raw_cells) != counts["observed_cell_count"]:
        raise ValueError("Policy interaction cell entries are invalid")
    direction_order = {name: index for index, name in enumerate(POLICY_DIRECTIONS)}
    regime_order = {name: index for index, name in enumerate(POLICY_REGIME_NAMES)}
    normalized: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in raw_cells:
        if not isinstance(item, dict):
            raise ValueError("Policy interaction cell is invalid")
        symbol = str(item.get("symbol", "")).strip().upper()
        direction = str(item.get("direction", "")).strip().upper()
        regime = str(item.get("regime", "")).strip().upper()
        key = (symbol, direction, regime)
        if (
            not symbol
            or item.get("symbol") != symbol
            or direction not in POLICY_DIRECTIONS
            or regime not in POLICY_REGIME_NAMES
            or key in seen
        ):
            raise ValueError("Policy interaction cell key is invalid or duplicated")
        seen.add(key)
        raw_trades = item.get("trades")
        raw_rows = item.get("calibration_rows")
        if (
            isinstance(raw_trades, bool)
            or not isinstance(raw_trades, int)
            or raw_trades <= 0
            or isinstance(raw_rows, bool)
            or not isinstance(raw_rows, int)
            or raw_rows != raw_trades
        ):
            raise ValueError("Policy interaction cell count is invalid")
        expected_support = (
            "SUPPORTED" if raw_trades >= POLICY_INTERACTION_MIN_TRADES else "SPARSE"
        )
        if item.get("support") != expected_support:
            raise ValueError("Policy interaction cell support classification is invalid")
        raw_fraction = item.get("trade_fraction")
        raw_mean = item.get("realized_trade_mean_r")
        try:
            fraction = float(raw_fraction)
            realized_mean = float(raw_mean)
            log_loss = float(item.get("log_loss"))
            brier = float(item.get("multiclass_brier"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Policy interaction cell metric is invalid") from exc
        expected_fraction = raw_trades / policy_trades if policy_trades else 0.0
        if (
            isinstance(raw_fraction, bool)
            or isinstance(raw_mean, bool)
            or not all(math.isfinite(value) for value in (fraction, realized_mean, log_loss, brier))
            or log_loss < 0.0
            or brier < 0.0
            or not math.isclose(fraction, expected_fraction, rel_tol=1e-9, abs_tol=1e-12)
        ):
            raise ValueError("Policy interaction cell metric is inconsistent")
        normalized.append(
            {
                "symbol": symbol,
                "direction": direction,
                "regime": regime,
                "support": expected_support,
                "trades": raw_trades,
                "trade_fraction": fraction,
                "realized_trade_mean_r": realized_mean,
                "calibration_rows": raw_rows,
                "log_loss": log_loss,
                "multiclass_brier": brier,
            }
        )
    expected_order = sorted(
        seen,
        key=lambda item: (item[0], direction_order[item[1]], regime_order[item[2]]),
    )
    if [(item["symbol"], item["direction"], item["regime"]) for item in normalized] != expected_order:
        raise ValueError("Policy interaction cells are not in canonical order")

    supported = [item for item in normalized if item["support"] == "SUPPORTED"]
    sparse = [item for item in normalized if item["support"] == "SPARSE"]
    computed = {
        "observed_cell_count": len(normalized),
        "supported_cell_count": len(supported),
        "sparse_cell_count": len(sparse),
        "supported_trade_count": sum(int(item["trades"]) for item in supported),
        "sparse_trade_count": sum(int(item["trades"]) for item in sparse),
    }
    if sum(int(item["trades"]) for item in normalized) != policy_trades:
        raise ValueError("Policy interaction cell trade totals are inconsistent")
    for key, value in computed.items():
        if counts[key] != value:
            raise ValueError("Policy interaction cell summaries are inconsistent")

    raw_pool = evidence.get("sparse_pool")
    sparse_pool: dict[str, object] | None = None
    if sparse:
        if not isinstance(raw_pool, dict):
            raise ValueError("Policy interaction sparse pool is required")
        raw_cell_count = raw_pool.get("cell_count")
        raw_trades = raw_pool.get("trades")
        raw_rows = raw_pool.get("calibration_rows")
        if (
            raw_cell_count != len(sparse)
            or raw_trades != counts["sparse_trade_count"]
            or raw_rows != counts["sparse_trade_count"]
        ):
            raise ValueError("Policy interaction sparse pool counts are inconsistent")
        try:
            fraction = float(raw_pool.get("trade_fraction"))
            realized_mean = float(raw_pool.get("realized_trade_mean_r"))
            log_loss = float(raw_pool.get("log_loss"))
            brier = float(raw_pool.get("multiclass_brier"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Policy interaction sparse pool metric is invalid") from exc
        expected_fraction = counts["sparse_trade_count"] / policy_trades if policy_trades else 0.0
        weighted_mean = sum(
            float(item["realized_trade_mean_r"]) * int(item["trades"]) for item in sparse
        ) / counts["sparse_trade_count"]
        weighted_log_loss = sum(
            float(item["log_loss"]) * int(item["trades"]) for item in sparse
        ) / counts["sparse_trade_count"]
        weighted_brier = sum(
            float(item["multiclass_brier"]) * int(item["trades"]) for item in sparse
        ) / counts["sparse_trade_count"]
        if (
            not all(math.isfinite(value) for value in (fraction, realized_mean, log_loss, brier))
            or log_loss < 0.0
            or brier < 0.0
            or not math.isclose(fraction, expected_fraction, rel_tol=1e-9, abs_tol=1e-12)
            or not math.isclose(realized_mean, weighted_mean, rel_tol=1e-9, abs_tol=1e-12)
            or not math.isclose(log_loss, weighted_log_loss, rel_tol=1e-9, abs_tol=1e-12)
            or not math.isclose(brier, weighted_brier, rel_tol=1e-9, abs_tol=1e-12)
        ):
            raise ValueError("Policy interaction sparse pool metric is inconsistent")
        if raw_pool.get("jackknife_schema") != POLICY_INTERACTION_SPARSE_JACKKNIFE_SCHEMA:
            raise ValueError("Policy interaction sparse leave-one-cell-out schema is invalid")
        if raw_pool.get("minimum_residual_trades") != POLICY_INTERACTION_MIN_TRADES:
            raise ValueError("Policy interaction sparse leave-one-cell-out minimum is invalid")
        raw_leave_one = raw_pool.get("leave_one_cell_out")
        if not isinstance(raw_leave_one, list) or len(raw_leave_one) != len(sparse):
            raise ValueError("Policy interaction sparse leave-one-cell-out evidence is required")
        if raw_pool.get("leave_one_cell_out_count") != len(sparse):
            raise ValueError("Policy interaction sparse leave-one-cell-out count is invalid")
        normalized_leave_one: list[dict[str, object]] = []
        for omitted, raw_result in zip(sparse, raw_leave_one, strict=True):
            if not isinstance(raw_result, dict):
                raise ValueError("Policy interaction sparse leave-one-cell-out entry is invalid")
            omitted_key = (
                str(omitted["symbol"]),
                str(omitted["direction"]),
                str(omitted["regime"]),
            )
            raw_key = (
                raw_result.get("omitted_symbol"),
                raw_result.get("omitted_direction"),
                raw_result.get("omitted_regime"),
            )
            if raw_key != omitted_key or raw_result.get("omitted_trades") != omitted["trades"]:
                raise ValueError("Policy interaction sparse leave-one-cell-out key is invalid")
            raw_residual_trades = raw_result.get("residual_trades")
            raw_rows = raw_result.get("calibration_rows")
            expected_residual_trades = counts["sparse_trade_count"] - int(omitted["trades"])
            if (
                isinstance(raw_residual_trades, bool)
                or not isinstance(raw_residual_trades, int)
                or raw_residual_trades != expected_residual_trades
                or raw_rows != expected_residual_trades
            ):
                raise ValueError("Policy interaction sparse leave-one-cell-out counts are inconsistent")
            try:
                residual_fraction = float(
                    raw_result.get("residual_trade_fraction_of_sparse_pool")
                )
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(
                    "Policy interaction sparse leave-one-cell-out fraction is invalid"
                ) from exc
            expected_residual_fraction = (
                expected_residual_trades / counts["sparse_trade_count"]
            )
            if (
                not math.isfinite(residual_fraction)
                or not math.isclose(
                    residual_fraction,
                    expected_residual_fraction,
                    rel_tol=1e-9,
                    abs_tol=1e-12,
                )
            ):
                raise ValueError(
                    "Policy interaction sparse leave-one-cell-out fraction is inconsistent"
                )
            residual_cells = [item for item in sparse if item is not omitted]
            if expected_residual_trades == 0:
                if any(
                    raw_result.get(key) is not None
                    for key in (
                        "residual_realized_trade_mean_r",
                        "log_loss",
                        "multiclass_brier",
                    )
                ):
                    raise ValueError(
                        "Policy interaction sparse leave-one-cell-out empty residual is invalid"
                    )
                residual_mean = residual_log_loss = residual_brier = None
            else:
                try:
                    residual_mean = float(raw_result.get("residual_realized_trade_mean_r"))
                    residual_log_loss = float(raw_result.get("log_loss"))
                    residual_brier = float(raw_result.get("multiclass_brier"))
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ValueError(
                        "Policy interaction sparse leave-one-cell-out metric is invalid"
                    ) from exc
                expected_residual_mean = sum(
                    float(item["realized_trade_mean_r"]) * int(item["trades"])
                    for item in residual_cells
                ) / expected_residual_trades
                expected_residual_log_loss = sum(
                    float(item["log_loss"]) * int(item["trades"])
                    for item in residual_cells
                ) / expected_residual_trades
                expected_residual_brier = sum(
                    float(item["multiclass_brier"]) * int(item["trades"])
                    for item in residual_cells
                ) / expected_residual_trades
                if (
                    not all(
                        math.isfinite(value)
                        for value in (residual_mean, residual_log_loss, residual_brier)
                    )
                    or residual_log_loss < 0.0
                    or residual_brier < 0.0
                    or not math.isclose(
                        residual_mean,
                        expected_residual_mean,
                        rel_tol=1e-9,
                        abs_tol=1e-12,
                    )
                    or not math.isclose(
                        residual_log_loss,
                        expected_residual_log_loss,
                        rel_tol=1e-9,
                        abs_tol=1e-12,
                    )
                    or not math.isclose(
                        residual_brier,
                        expected_residual_brier,
                        rel_tol=1e-9,
                        abs_tol=1e-12,
                    )
                ):
                    raise ValueError(
                        "Policy interaction sparse leave-one-cell-out metric is inconsistent"
                    )
            normalized_leave_one.append(
                {
                    "omitted_symbol": omitted_key[0],
                    "omitted_direction": omitted_key[1],
                    "omitted_regime": omitted_key[2],
                    "omitted_trades": int(omitted["trades"]),
                    "residual_trades": expected_residual_trades,
                    "residual_trade_fraction_of_sparse_pool": residual_fraction,
                    "residual_realized_trade_mean_r": residual_mean,
                    "calibration_rows": expected_residual_trades,
                    "log_loss": residual_log_loss,
                    "multiclass_brier": residual_brier,
                }
            )
        minimum_residual_trades = min(
            int(item["residual_trades"]) for item in normalized_leave_one
        )
        if raw_pool.get("minimum_leave_one_cell_out_residual_trades") != minimum_residual_trades:
            raise ValueError("Policy interaction sparse leave-one-cell-out minimum is inconsistent")
        nonempty_residuals = [
            item for item in normalized_leave_one if int(item["residual_trades"]) > 0
        ]
        jackknife_summaries = {
            "worst_leave_one_cell_out_mean_r": (
                min(
                    float(item["residual_realized_trade_mean_r"])
                    for item in nonempty_residuals
                )
                if nonempty_residuals
                else None
            ),
            "worst_leave_one_cell_out_log_loss": (
                max(float(item["log_loss"]) for item in nonempty_residuals)
                if nonempty_residuals
                else None
            ),
            "worst_leave_one_cell_out_multiclass_brier": (
                max(float(item["multiclass_brier"]) for item in nonempty_residuals)
                if nonempty_residuals
                else None
            ),
        }
        for key, expected in jackknife_summaries.items():
            raw = raw_pool.get(key)
            if expected is None:
                if raw is not None:
                    raise ValueError(
                        "Policy interaction sparse leave-one-cell-out summary is invalid"
                    )
                continue
            try:
                actual = float(raw)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(
                    "Policy interaction sparse leave-one-cell-out summary is invalid"
                ) from exc
            if (
                isinstance(raw, bool)
                or not math.isfinite(actual)
                or not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12)
            ):
                raise ValueError(
                    "Policy interaction sparse leave-one-cell-out summary is inconsistent"
                )
        sparse_pool = {
            "cell_count": len(sparse),
            "trades": counts["sparse_trade_count"],
            "trade_fraction": fraction,
            "realized_trade_mean_r": realized_mean,
            "calibration_rows": counts["sparse_trade_count"],
            "log_loss": log_loss,
            "multiclass_brier": brier,
            "jackknife_schema": POLICY_INTERACTION_SPARSE_JACKKNIFE_SCHEMA,
            "minimum_residual_trades": POLICY_INTERACTION_MIN_TRADES,
            "leave_one_cell_out_count": len(normalized_leave_one),
            "minimum_leave_one_cell_out_residual_trades": minimum_residual_trades,
            **jackknife_summaries,
            "leave_one_cell_out": normalized_leave_one,
        }
    elif raw_pool is not None:
        raise ValueError("Policy interaction sparse pool must be empty without sparse cells")

    tested_buckets: list[dict[str, object]] = [*supported]
    if sparse_pool is not None:
        tested_buckets.append(sparse_pool)
    if counts["tested_bucket_count"] != len(tested_buckets):
        raise ValueError("Policy interaction tested bucket count is inconsistent")
    summaries = {
        "worst_tested_bucket_mean_r": (
            min((float(item["realized_trade_mean_r"]) for item in tested_buckets), default=None)
        ),
        "worst_tested_bucket_log_loss": (
            max((float(item["log_loss"]) for item in tested_buckets), default=None)
        ),
        "worst_tested_bucket_multiclass_brier": (
            max((float(item["multiclass_brier"]) for item in tested_buckets), default=None)
        ),
    }
    for key, expected in summaries.items():
        raw = evidence.get(key)
        if expected is None:
            if raw is not None:
                raise ValueError("Policy interaction summary must be empty without trades")
            continue
        try:
            actual = float(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Policy interaction summary is invalid") from exc
        if (
            isinstance(raw, bool)
            or not math.isfinite(actual)
            or not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12)
        ):
            raise ValueError("Policy interaction summary is inconsistent")
    return {
        "schema": POLICY_INTERACTION_ROBUSTNESS_SCHEMA,
        "minimum_trades_per_supported_cell": POLICY_INTERACTION_MIN_TRADES,
        **counts,
        **summaries,
        "cells": normalized,
        "sparse_pool": sparse_pool,
    }


def _policy_symbol_robustness(
    trades: pd.DataFrame,
    opportunity_times: pd.DatetimeIndex,
) -> dict[str, object]:
    """Measure whether final-holdout edge survives removal of any one traded symbol.

    The counterfactual preserves the exact observed opportunity clock, including
    zero-return no-trade hours, and recomputes equal weighting among the remaining
    simultaneous trades. A positive aggregate result that turns non-positive after
    removing one symbol is not considered cross-symbol robust.
    """

    if opportunity_times.empty or opportunity_times.isna().any():
        raise ValueError("Policy symbol robustness requires valid opportunity times")
    if trades.empty:
        return {
            "schema": POLICY_SYMBOL_ROBUSTNESS_SCHEMA,
            "symbol_count": 0,
            "trade_count": 0,
            "max_symbol_trade_fraction": 0.0,
            "leave_one_symbol_out_mean_r_min": None,
            "symbols": [],
        }

    required = {"symbol", "decision_time", "realized_r"}
    missing = sorted(required - set(trades.columns))
    if missing:
        raise ValueError(f"Policy symbol robustness is missing columns: {missing}")
    frame = trades.loc[:, ["symbol", "decision_time", "realized_r"]].copy()
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame["decision_time"] = pd.to_datetime(frame["decision_time"], utc=True, errors="coerce")
    frame["realized_r"] = pd.to_numeric(frame["realized_r"], errors="coerce")
    if (
        (frame["symbol"] == "").any()
        or frame["decision_time"].isna().any()
        or frame["realized_r"].isna().any()
        or not np.isfinite(frame["realized_r"].to_numpy(float)).all()
    ):
        raise ValueError("Policy symbol robustness contains invalid trade evidence")

    total_trades = int(len(frame))
    entries: list[dict[str, object]] = []
    for symbol in sorted(frame["symbol"].unique()):
        symbol_trades = int(frame["symbol"].eq(symbol).sum())
        remaining = frame[~frame["symbol"].eq(symbol)]
        if remaining.empty:
            leave_one_out_mean = 0.0
        else:
            remaining_cohorts = remaining.groupby("decision_time", sort=True)["realized_r"].mean()
            remaining_cohorts.index = pd.to_datetime(remaining_cohorts.index, utc=True, errors="coerce")
            if remaining_cohorts.index.isna().any() or remaining_cohorts.index.has_duplicates:
                raise ValueError("Policy symbol robustness produced invalid cohort evidence")
            leave_one_out_mean = float(
                remaining_cohorts.reindex(opportunity_times, fill_value=0.0).mean()
            )
        entries.append(
            {
                "symbol": str(symbol),
                "trades": symbol_trades,
                "trade_fraction": float(symbol_trades / total_trades),
                "leave_one_symbol_out_policy_mean_r": leave_one_out_mean,
            }
        )

    return {
        "schema": POLICY_SYMBOL_ROBUSTNESS_SCHEMA,
        "symbol_count": len(entries),
        "trade_count": total_trades,
        "max_symbol_trade_fraction": float(max(item["trade_fraction"] for item in entries)),
        "leave_one_symbol_out_mean_r_min": float(
            min(item["leave_one_symbol_out_policy_mean_r"] for item in entries)
        ),
        "symbols": entries,
    }


def _policy_cluster_robustness(
    trades: pd.DataFrame,
    opportunity_times: pd.DatetimeIndex,
) -> dict[str, object]:
    """Test whether policy edge survives removal of correlated symbol components.

    Symbols are connected when their realized-R series have absolute Pearson
    correlation at or above the immutable threshold on at least the configured
    number of timestamps where both symbols traded. Connected components form
    deterministic dependence clusters. Each counterfactual removes a whole
    component while preserving the exact observed opportunity clock and
    reweighting the remaining simultaneous trades.
    """

    if opportunity_times.empty or opportunity_times.isna().any():
        raise ValueError("Policy cluster robustness requires valid opportunity times")
    if opportunity_times.has_duplicates:
        raise ValueError("Policy cluster robustness opportunity times must be unique")
    if trades.empty:
        return {
            "schema": POLICY_CLUSTER_ROBUSTNESS_SCHEMA,
            "correlation_threshold": POLICY_CLUSTER_CORRELATION_THRESHOLD,
            "minimum_shared_active_observations": (
                POLICY_CLUSTER_MIN_SHARED_ACTIVE_OBSERVATIONS
            ),
            "symbol_count": 0,
            "cluster_count": 0,
            "trade_count": 0,
            "max_cluster_trade_fraction": 0.0,
            "leave_one_cluster_out_mean_r_min": None,
            "clusters": [],
        }

    required = {"symbol", "decision_time", "realized_r"}
    missing = sorted(required - set(trades.columns))
    if missing:
        raise ValueError(f"Policy cluster robustness is missing columns: {missing}")
    frame = trades.loc[:, ["symbol", "decision_time", "realized_r"]].copy()
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame["decision_time"] = pd.to_datetime(frame["decision_time"], utc=True, errors="coerce")
    frame["realized_r"] = pd.to_numeric(frame["realized_r"], errors="coerce")
    if (
        (frame["symbol"] == "").any()
        or frame["decision_time"].isna().any()
        or frame["realized_r"].isna().any()
        or not np.isfinite(frame["realized_r"].to_numpy(float)).all()
        or frame.duplicated(["decision_time", "symbol"]).any()
    ):
        raise ValueError("Policy cluster robustness contains invalid trade evidence")

    symbols = sorted(frame["symbol"].unique())
    returns = (
        frame.pivot(index="decision_time", columns="symbol", values="realized_r")
        .reindex(opportunity_times)
        .fillna(0.0)
    )
    active = (
        frame.assign(active=1.0)
        .pivot(index="decision_time", columns="symbol", values="active")
        .reindex(opportunity_times)
        .fillna(0.0)
    )
    adjacency: dict[str, set[str]] = {symbol: set() for symbol in symbols}
    for left_index, left in enumerate(symbols):
        for right in symbols[left_index + 1 :]:
            jointly_active = (active[left] > 0.0) & (active[right] > 0.0)
            shared = int(jointly_active.sum())
            if shared < POLICY_CLUSTER_MIN_SHARED_ACTIVE_OBSERVATIONS:
                continue
            left_values = returns.loc[jointly_active, left].to_numpy(float)
            right_values = returns.loc[jointly_active, right].to_numpy(float)
            if np.std(left_values) <= 0.0 or np.std(right_values) <= 0.0:
                continue
            correlation = float(np.corrcoef(left_values, right_values)[0, 1])
            if math.isfinite(correlation) and abs(correlation) >= POLICY_CLUSTER_CORRELATION_THRESHOLD:
                adjacency[left].add(right)
                adjacency[right].add(left)

    components: list[list[str]] = []
    unseen = set(symbols)
    while unseen:
        seed = min(unseen)
        stack = [seed]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            unseen.discard(current)
            stack.extend(sorted(adjacency[current] - component, reverse=True))
        components.append(sorted(component))
    components.sort(key=lambda values: tuple(values))

    total_trades = int(len(frame))
    clusters: list[dict[str, object]] = []
    for index, component in enumerate(components, start=1):
        in_cluster = frame["symbol"].isin(component)
        cluster_trades = int(in_cluster.sum())
        remaining = frame[~in_cluster]
        if remaining.empty:
            leave_one_out_mean = 0.0
        else:
            remaining_cohorts = remaining.groupby("decision_time", sort=True)["realized_r"].mean()
            remaining_cohorts.index = pd.to_datetime(
                remaining_cohorts.index, utc=True, errors="coerce"
            )
            if remaining_cohorts.index.isna().any() or remaining_cohorts.index.has_duplicates:
                raise ValueError("Policy cluster robustness produced invalid cohort evidence")
            leave_one_out_mean = float(
                remaining_cohorts.reindex(opportunity_times, fill_value=0.0).mean()
            )
        clusters.append(
            {
                "cluster_id": f"cluster-{index:03d}",
                "symbols": component,
                "trades": cluster_trades,
                "trade_fraction": float(cluster_trades / total_trades),
                "leave_one_cluster_out_policy_mean_r": leave_one_out_mean,
            }
        )

    return {
        "schema": POLICY_CLUSTER_ROBUSTNESS_SCHEMA,
        "correlation_threshold": POLICY_CLUSTER_CORRELATION_THRESHOLD,
        "minimum_shared_active_observations": POLICY_CLUSTER_MIN_SHARED_ACTIVE_OBSERVATIONS,
        "symbol_count": len(symbols),
        "cluster_count": len(clusters),
        "trade_count": total_trades,
        "max_cluster_trade_fraction": float(
            max(item["trade_fraction"] for item in clusters)
        ),
        "leave_one_cluster_out_mean_r_min": float(
            min(item["leave_one_cluster_out_policy_mean_r"] for item in clusters)
        ),
        "clusters": clusters,
    }


def validate_policy_cluster_robustness(
    evidence: object,
    *,
    policy_trades: int,
) -> dict[str, object]:
    """Validate immutable dependence-cluster jackknife evidence and arithmetic."""

    if isinstance(policy_trades, bool) or not isinstance(policy_trades, int) or policy_trades < 0:
        raise ValueError("policy_trades must be a non-negative integer")
    if not isinstance(evidence, dict):
        raise ValueError("Policy cluster robustness evidence is required")
    if evidence.get("schema") != POLICY_CLUSTER_ROBUSTNESS_SCHEMA:
        raise ValueError("Policy cluster robustness schema mismatch")

    raw_threshold = evidence.get("correlation_threshold")
    raw_min_shared = evidence.get("minimum_shared_active_observations")
    if isinstance(raw_threshold, bool) or isinstance(raw_min_shared, bool):
        raise ValueError("Policy cluster robustness configuration is invalid")
    try:
        threshold = float(raw_threshold)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Policy cluster robustness correlation threshold is invalid") from exc
    if (
        not math.isfinite(threshold)
        or not math.isclose(
            threshold, POLICY_CLUSTER_CORRELATION_THRESHOLD, rel_tol=0.0, abs_tol=1e-12
        )
        or not isinstance(raw_min_shared, int)
        or raw_min_shared != POLICY_CLUSTER_MIN_SHARED_ACTIVE_OBSERVATIONS
    ):
        raise ValueError("Policy cluster robustness configuration mismatch")

    symbol_count = evidence.get("symbol_count")
    cluster_count = evidence.get("cluster_count")
    trade_count = evidence.get("trade_count")
    clusters = evidence.get("clusters")
    if (
        isinstance(symbol_count, bool)
        or not isinstance(symbol_count, int)
        or symbol_count < 0
        or isinstance(cluster_count, bool)
        or not isinstance(cluster_count, int)
        or cluster_count < 0
        or isinstance(trade_count, bool)
        or not isinstance(trade_count, int)
        or trade_count < 0
        or trade_count != policy_trades
        or not isinstance(clusters, list)
        or len(clusters) != cluster_count
    ):
        raise ValueError("Policy cluster robustness count evidence is inconsistent")

    if policy_trades == 0:
        if symbol_count != 0 or cluster_count != 0 or clusters:
            raise ValueError("Policy cluster robustness is non-empty without trades")
        if evidence.get("leave_one_cluster_out_mean_r_min") is not None:
            raise ValueError("Policy cluster leave-one-out mean must be empty without trades")
        raw_max_fraction = evidence.get("max_cluster_trade_fraction")
        if isinstance(raw_max_fraction, bool):
            raise ValueError("Policy cluster maximum trade fraction is invalid")
        try:
            max_fraction = float(raw_max_fraction)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Policy cluster maximum trade fraction is invalid") from exc
        if not math.isfinite(max_fraction) or not math.isclose(max_fraction, 0.0, abs_tol=1e-12):
            raise ValueError("Policy cluster maximum trade fraction is invalid")
        return {
            "schema": POLICY_CLUSTER_ROBUSTNESS_SCHEMA,
            "correlation_threshold": threshold,
            "minimum_shared_active_observations": raw_min_shared,
            "symbol_count": 0,
            "cluster_count": 0,
            "trade_count": 0,
            "max_cluster_trade_fraction": 0.0,
            "leave_one_cluster_out_mean_r_min": None,
            "clusters": [],
        }

    normalized: list[dict[str, object]] = []
    seen_symbols: set[str] = set()
    total_trades = 0
    for expected_index, item in enumerate(clusters, start=1):
        if not isinstance(item, dict):
            raise ValueError("Policy cluster robustness cluster entry is invalid")
        expected_id = f"cluster-{expected_index:03d}"
        if item.get("cluster_id") != expected_id:
            raise ValueError("Policy cluster robustness cluster ids are invalid")
        raw_symbols = item.get("symbols")
        if not isinstance(raw_symbols, list) or not raw_symbols:
            raise ValueError("Policy cluster robustness symbols are invalid")
        symbols: list[str] = []
        for raw_symbol in raw_symbols:
            symbol = raw_symbol.strip().upper() if isinstance(raw_symbol, str) else ""
            if not symbol or raw_symbol != symbol or symbol in seen_symbols:
                raise ValueError("Policy cluster robustness symbols overlap or are invalid")
            seen_symbols.add(symbol)
            symbols.append(symbol)
        if symbols != sorted(symbols):
            raise ValueError("Policy cluster robustness symbols must be sorted")
        trades = item.get("trades")
        if isinstance(trades, bool) or not isinstance(trades, int) or trades <= 0:
            raise ValueError("Policy cluster robustness trade count is invalid")
        total_trades += trades
        raw_fraction = item.get("trade_fraction")
        raw_leave_one_out = item.get("leave_one_cluster_out_policy_mean_r")
        if isinstance(raw_fraction, bool) or isinstance(raw_leave_one_out, bool):
            raise ValueError("Policy cluster robustness metric is invalid")
        try:
            fraction = float(raw_fraction)
            leave_one_out = float(raw_leave_one_out)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Policy cluster robustness metric is invalid") from exc
        if (
            not math.isfinite(fraction)
            or not 0.0 < fraction <= 1.0
            or not math.isclose(fraction, trades / policy_trades, rel_tol=1e-9, abs_tol=1e-12)
            or not math.isfinite(leave_one_out)
        ):
            raise ValueError("Policy cluster robustness metric is inconsistent")
        normalized.append(
            {
                "cluster_id": expected_id,
                "symbols": symbols,
                "trades": trades,
                "trade_fraction": fraction,
                "leave_one_cluster_out_policy_mean_r": leave_one_out,
            }
        )

    if (
        len(seen_symbols) != symbol_count
        or total_trades != policy_trades
        or [item["symbols"] for item in normalized]
        != sorted([item["symbols"] for item in normalized], key=lambda values: tuple(values))
    ):
        raise ValueError("Policy cluster robustness symbols or totals are inconsistent")
    expected_max_fraction = max(float(item["trade_fraction"]) for item in normalized)
    expected_min_leave_one_out = min(
        float(item["leave_one_cluster_out_policy_mean_r"]) for item in normalized
    )
    raw_max_fraction = evidence.get("max_cluster_trade_fraction")
    raw_min_leave_one_out = evidence.get("leave_one_cluster_out_mean_r_min")
    if isinstance(raw_max_fraction, bool) or isinstance(raw_min_leave_one_out, bool):
        raise ValueError("Policy cluster robustness summary is invalid")
    try:
        max_fraction = float(raw_max_fraction)
        min_leave_one_out = float(raw_min_leave_one_out)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Policy cluster robustness summary is invalid") from exc
    if (
        not math.isfinite(max_fraction)
        or not math.isfinite(min_leave_one_out)
        or not math.isclose(max_fraction, expected_max_fraction, rel_tol=1e-9, abs_tol=1e-12)
        or not math.isclose(
            min_leave_one_out, expected_min_leave_one_out, rel_tol=1e-9, abs_tol=1e-12
        )
    ):
        raise ValueError("Policy cluster robustness summary is inconsistent")

    return {
        "schema": POLICY_CLUSTER_ROBUSTNESS_SCHEMA,
        "correlation_threshold": threshold,
        "minimum_shared_active_observations": raw_min_shared,
        "symbol_count": symbol_count,
        "cluster_count": cluster_count,
        "trade_count": trade_count,
        "max_cluster_trade_fraction": max_fraction,
        "leave_one_cluster_out_mean_r_min": min_leave_one_out,
        "clusters": normalized,
    }


def validate_policy_symbol_robustness(
    evidence: object,
    *,
    policy_trades: int,
) -> dict[str, object]:
    """Validate immutable per-symbol jackknife evidence and its arithmetic."""

    if isinstance(policy_trades, bool) or not isinstance(policy_trades, int) or policy_trades < 0:
        raise ValueError("policy_trades must be a non-negative integer")
    if not isinstance(evidence, dict):
        raise ValueError("Policy symbol robustness evidence is required")
    if evidence.get("schema") != POLICY_SYMBOL_ROBUSTNESS_SCHEMA:
        raise ValueError("Policy symbol robustness schema mismatch")

    symbol_count = evidence.get("symbol_count")
    trade_count = evidence.get("trade_count")
    entries = evidence.get("symbols")
    if (
        isinstance(symbol_count, bool)
        or not isinstance(symbol_count, int)
        or symbol_count < 0
        or isinstance(trade_count, bool)
        or not isinstance(trade_count, int)
        or trade_count < 0
        or trade_count != policy_trades
        or not isinstance(entries, list)
        or len(entries) != symbol_count
    ):
        raise ValueError("Policy symbol robustness count evidence is inconsistent")

    if policy_trades == 0:
        if symbol_count != 0 or entries:
            raise ValueError("Policy symbol robustness is non-empty without trades")
        if evidence.get("leave_one_symbol_out_mean_r_min") is not None:
            raise ValueError("Policy symbol robustness leave-one-out mean must be empty without trades")
        raw_max_fraction = evidence.get("max_symbol_trade_fraction")
        if isinstance(raw_max_fraction, bool):
            raise ValueError("Policy symbol robustness maximum trade fraction is invalid")
        try:
            max_fraction = float(raw_max_fraction)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Policy symbol robustness maximum trade fraction is invalid") from exc
        if not math.isfinite(max_fraction) or not math.isclose(max_fraction, 0.0, abs_tol=1e-12):
            raise ValueError("Policy symbol robustness maximum trade fraction is invalid")
        return {
            "schema": POLICY_SYMBOL_ROBUSTNESS_SCHEMA,
            "symbol_count": 0,
            "trade_count": 0,
            "max_symbol_trade_fraction": 0.0,
            "leave_one_symbol_out_mean_r_min": None,
            "symbols": [],
        }

    normalized_entries: list[dict[str, object]] = []
    seen: set[str] = set()
    total = 0
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("Policy symbol robustness symbol entry is invalid")
        raw_symbol = item.get("symbol")
        symbol = raw_symbol.strip().upper() if isinstance(raw_symbol, str) else ""
        if not symbol or raw_symbol != symbol or symbol in seen:
            raise ValueError("Policy symbol robustness symbols must be unique normalized values")
        seen.add(symbol)
        trades = item.get("trades")
        if isinstance(trades, bool) or not isinstance(trades, int) or trades <= 0:
            raise ValueError("Policy symbol robustness trade count is invalid")
        total += trades
        raw_fraction = item.get("trade_fraction")
        raw_leave_one_out = item.get("leave_one_symbol_out_policy_mean_r")
        if isinstance(raw_fraction, bool) or isinstance(raw_leave_one_out, bool):
            raise ValueError("Policy symbol robustness metric is invalid")
        try:
            fraction = float(raw_fraction)
            leave_one_out = float(raw_leave_one_out)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Policy symbol robustness metric is invalid") from exc
        if (
            not math.isfinite(fraction)
            or not 0.0 < fraction <= 1.0
            or not math.isclose(
                fraction, trades / policy_trades, rel_tol=1e-9, abs_tol=1e-12
            )
            or not math.isfinite(leave_one_out)
        ):
            raise ValueError("Policy symbol robustness metric is inconsistent")
        normalized_entries.append(
            {
                "symbol": symbol,
                "trades": trades,
                "trade_fraction": fraction,
                "leave_one_symbol_out_policy_mean_r": leave_one_out,
            }
        )

    if total != policy_trades or [item["symbol"] for item in normalized_entries] != sorted(seen):
        raise ValueError("Policy symbol robustness symbols or totals are inconsistent")
    expected_max_fraction = max(float(item["trade_fraction"]) for item in normalized_entries)
    expected_min_leave_one_out = min(
        float(item["leave_one_symbol_out_policy_mean_r"]) for item in normalized_entries
    )
    raw_max_fraction = evidence.get("max_symbol_trade_fraction")
    raw_min_leave_one_out = evidence.get("leave_one_symbol_out_mean_r_min")
    if isinstance(raw_max_fraction, bool) or isinstance(raw_min_leave_one_out, bool):
        raise ValueError("Policy symbol robustness summary is invalid")
    try:
        max_fraction = float(raw_max_fraction)
        min_leave_one_out = float(raw_min_leave_one_out)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Policy symbol robustness summary is invalid") from exc
    if (
        not math.isfinite(max_fraction)
        or not math.isfinite(min_leave_one_out)
        or not math.isclose(max_fraction, expected_max_fraction, rel_tol=1e-9, abs_tol=1e-12)
        or not math.isclose(
            min_leave_one_out, expected_min_leave_one_out, rel_tol=1e-9, abs_tol=1e-12
        )
    ):
        raise ValueError("Policy symbol robustness summary is inconsistent")

    return {
        "schema": POLICY_SYMBOL_ROBUSTNESS_SCHEMA,
        "symbol_count": symbol_count,
        "trade_count": trade_count,
        "max_symbol_trade_fraction": max_fraction,
        "leave_one_symbol_out_mean_r_min": min_leave_one_out,
        "symbols": normalized_entries,
    }


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


def validate_intrahorizon_mark_to_market_path(
    meta: pd.DataFrame,
    *,
    context: str,
    require: bool,
) -> tuple[pd.DataFrame, str | None]:
    """Validate cumulative hourly mark/funding evidence through effective exit."""

    required = set(INTRAHORIZON_MTM_POLICY_METADATA_COLUMNS)
    missing = sorted(required - set(meta.columns))
    result = meta.copy()
    if missing:
        if require:
            raise ValueError(
                f"{context} metadata is missing intrahorizon mark-to-market columns: {missing}"
            )
        return result, None

    complete = result["intrahorizon_mark_to_market_path_complete"].map(
        lambda value: isinstance(value, (bool, np.bool_)) and bool(value)
    )
    if not complete.all():
        raise ValueError(f"{context} contains an incomplete intrahorizon mark-to-market path")
    schemas = set(result["intrahorizon_mark_to_market_schema"].astype(str))
    if schemas != {INTRAHORIZON_MTM_PATH_SCHEMA_VERSION}:
        raise ValueError(f"{context} contains an incompatible intrahorizon mark-to-market schema")

    normalized_paths: list[list[dict[str, object]]] = []
    for row in result.to_dict(orient="records"):
        raw_path = row["intrahorizon_mark_to_market_path"]
        if not isinstance(raw_path, list) or not raw_path:
            raise ValueError(f"{context} intrahorizon mark-to-market path must be a non-empty list")

        records: list[dict[str, object]] = []
        timestamps: list[pd.Timestamp] = []
        for item in raw_path:
            if not isinstance(item, dict) or set(item) != {
                "timestamp",
                "gross_return_rate",
                "funding_return_rate",
            }:
                raise ValueError(f"{context} intrahorizon mark-to-market record is invalid")
            timestamp = pd.to_datetime(item["timestamp"], utc=True, errors="coerce")
            gross = pd.to_numeric(item["gross_return_rate"], errors="coerce")
            funding = pd.to_numeric(item["funding_return_rate"], errors="coerce")
            if pd.isna(timestamp) or pd.isna(gross) or pd.isna(funding):
                raise ValueError(f"{context} intrahorizon mark-to-market record is invalid")
            gross_value = float(gross)
            funding_value = float(funding)
            if not np.isfinite(gross_value) or not np.isfinite(funding_value):
                raise ValueError(f"{context} intrahorizon mark-to-market returns must be finite")
            point = pd.Timestamp(timestamp)
            if point != point.floor("h"):
                raise ValueError(f"{context} intrahorizon mark-to-market times must be hour-aligned")
            timestamps.append(point)
            records.append(
                {
                    "timestamp": point.isoformat(),
                    "gross_return_rate": gross_value,
                    "funding_return_rate": funding_value,
                }
            )

        decision = pd.Timestamp(row["decision_time"])
        effective_exit = pd.Timestamp(row["exit_time"])
        if decision.tzinfo is None or effective_exit.tzinfo is None:
            raise ValueError(f"{context} decision and exit times must be timezone-aware")
        decision = decision.tz_convert("UTC")
        effective_exit = effective_exit.tz_convert("UTC")
        expected_timestamps = list(pd.date_range(decision, effective_exit, freq="h"))
        if timestamps != expected_timestamps:
            raise ValueError(
                f"{context} intrahorizon mark-to-market path must cover every observed hour"
            )
        if effective_exit > decision and (
            abs(float(records[0]["gross_return_rate"])) > 1e-12
            or abs(float(records[0]["funding_return_rate"])) > 1e-12
        ):
            raise ValueError(f"{context} intrahorizon mark-to-market path must start at zero")

        terminal_gross = float(records[-1]["gross_return_rate"])
        expected_gross = float(row["effective_realized_gross_return"])
        if not np.isclose(terminal_gross, expected_gross, rtol=1e-10, atol=1e-12):
            raise ValueError(f"{context} intrahorizon mark-to-market gross return does not reconcile")
        raw_funding = float(row.get("historical_funding_realized_rate", 0.0))
        direction = str(row["direction"])
        if direction not in {"LONG", "SHORT"}:
            raise ValueError(f"{context} intrahorizon mark-to-market direction is invalid")
        expected_funding = -raw_funding if direction == "LONG" else raw_funding
        terminal_funding = float(records[-1]["funding_return_rate"])
        if not np.isclose(terminal_funding, expected_funding, rtol=1e-10, atol=1e-12):
            raise ValueError(
                f"{context} intrahorizon mark-to-market funding return does not reconcile"
            )
        normalized_paths.append(records)

    result["intrahorizon_mark_to_market_path"] = normalized_paths
    return result, INTRAHORIZON_MTM_PATH_SCHEMA_VERSION


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

    required = set(INTRAHORIZON_MARGIN_POLICY_METADATA_COLUMNS)
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
    test_features = np.asarray(split.x_test, dtype=float)
    if test_features.ndim != 2 or test_features.shape[0] != len(meta):
        raise ValueError("Policy evaluation feature matrix does not align with holdout metadata")
    if test_features.shape[1] == len(MODEL_FEATURE_NAMES):
        regime_ret_24h = test_features[:, MODEL_FEATURE_NAMES.index("ret_24h")].copy()
        regime_atr_pct_14 = test_features[:, MODEL_FEATURE_NAMES.index("atr_pct_14")].copy()
    elif split.train_meta is None:
        regime_ret_24h = np.zeros(len(meta), dtype=float)
        regime_atr_pct_14 = (
            meta["barrier_downside_rate"].to_numpy(float) / DEFAULT_STOP_ATR_MULTIPLIER
        )
    else:
        raise ValueError("Policy evaluation feature matrix does not contain the current schema")
    invalid_regime_features = (
        ~np.isfinite(regime_ret_24h)
        | ~np.isfinite(regime_atr_pct_14)
        | (regime_atr_pct_14 <= 0.0)
    )
    if invalid_regime_features.any():
        if split.train_meta is not None:
            raise ValueError("Policy regime features must be finite with positive ATR")
        fallback_atr = meta["barrier_downside_rate"].to_numpy(float) / DEFAULT_STOP_ATR_MULTIPLIER
        if not np.isfinite(fallback_atr).all() or (fallback_atr <= 0.0).any():
            raise ValueError("Legacy policy fixture cannot derive valid regime features")
        regime_atr_pct_14 = fallback_atr
        regime_ret_24h = np.where(np.isfinite(regime_ret_24h), regime_ret_24h, 0.0)
    meta["regime_ret_24h"] = regime_ret_24h
    meta["regime_atr_pct_14"] = regime_atr_pct_14
    development_high_volatility_atr_pct_threshold = (
        _development_high_volatility_atr_pct_threshold(split)
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
    selected_calibration = _policy_calibration_metrics(
        selected,
        context="Policy-selected calibration",
    )
    selected_log_loss = selected_calibration["log_loss"]
    selected_multiclass_brier = selected_calibration["multiclass_brier"]
    if selected_log_loss is None or selected_multiclass_brier is None:
        raise ValueError("Policy-selected calibration requires at least one row")
    selected["actionable"] = (selected["net_rr"] >= config.min_net_rr) & (
        selected["expected_ev_r"] >= config.min_net_ev_r
    )
    actionable_trades = selected[selected["actionable"]].copy()
    trades, overlap_blocked_trades = filter_single_active_trade_per_symbol(
        actionable_trades,
        context="Policy evaluation",
    )
    actionable_calibration = _policy_calibration_metrics(
        trades,
        context="Policy actionable calibration",
    )

    opportunity_times = pd.DatetimeIndex(
        pd.to_datetime(selected["decision_time"], utc=True, errors="coerce")
        .drop_duplicates()
        .sort_values(kind="mergesort")
    )
    if opportunity_times.empty or opportunity_times.isna().any():
        raise ValueError("Policy evaluation requires valid observed decision cohorts")

    trades = trades.copy()
    if trades.empty:
        trades["realized_r"] = pd.Series(index=trades.index, dtype=float)
        trades["realized_r_contribution"] = pd.Series(index=trades.index, dtype=float)
        trade_cohort_metrics = pd.DataFrame(
            columns=["realized_mean_r", "expected_mean_ev_r"],
            index=pd.DatetimeIndex([], name="decision_time"),
            dtype=float,
        )
        liquidation_events = 0
        liquidation_rate = 0.0
    else:
        outcome = trades["target"].astype(str)
        if (~outcome.isin(OUTCOME_CLASSES)).any():
            raise ValueError("Policy evaluation target contains an unsupported outcome")
        liquidation_events = int(trades["mark_liquidated"].sum()) if intrahorizon_margin_schema else 0
        liquidation_rate = float(liquidation_events / len(trades))
        trades["realized_r"] = np.where(
            trades["stress_downside_rate"] > 0,
            trades["realized_net_rate"] / trades["stress_downside_rate"],
            0.0,
        )
        cohort_size = trades.groupby("decision_time")["realized_r"].transform("size")
        trades["realized_r_contribution"] = trades["realized_r"] / cohort_size / resolved_horizon
        trade_cohort_metrics = trades.groupby("decision_time", sort=True).agg(
            realized_mean_r=("realized_r", "mean"),
            expected_mean_ev_r=("expected_ev_r", "mean"),
        )
        trade_cohort_metrics.index = pd.to_datetime(
            trade_cohort_metrics.index,
            utc=True,
            errors="coerce",
        )
        if trade_cohort_metrics.index.isna().any():
            raise ValueError("Policy trade cohorts contain invalid decision_time")

    # Policy inference is defined on every observed decision cohort. A cohort
    # where all directions are rejected has a known strategy return of zero.
    # Dropping these hours conditions inference on the policy's own selection,
    # overstates sparse-policy evidence and makes phase coverage trade-dependent.
    # Reindex only to observed opportunities; missing market hours are not invented.
    cohort_metrics = trade_cohort_metrics.reindex(opportunity_times, fill_value=0.0)
    cohort_metrics.index.name = "decision_time"
    trade_cohort_count = int(len(trade_cohort_metrics))
    opportunity_cohort_count = int(len(cohort_metrics))
    no_trade_cohort_count = opportunity_cohort_count - trade_cohort_count
    direction_robustness = _policy_direction_robustness(trades, opportunity_times)
    symbol_robustness = _policy_symbol_robustness(trades, opportunity_times)
    cluster_robustness = _policy_cluster_robustness(trades, opportunity_times)
    regime_robustness = _policy_regime_robustness(
        selected=selected,
        trades=trades,
        opportunity_times=opportunity_times,
        development_high_volatility_atr_pct_threshold=(
            development_high_volatility_atr_pct_threshold
        ),
    )
    interaction_robustness = _policy_interaction_robustness(
        selected=selected,
        trades=trades,
        opportunity_times=opportunity_times,
        development_high_volatility_atr_pct_threshold=(
            development_high_volatility_atr_pct_threshold
        ),
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

    if trades.empty:
        exit_r = pd.Series(dtype=float)
        trade_contributions = pd.Series(dtype=float)
    else:
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
        "policy_expected_funding_source": POLICY_EXPECTED_FUNDING_SOURCE,
        "policy_realized_funding_source": historical_funding_schema,
        "policy_intrahorizon_margin_schema": intrahorizon_margin_schema,
        "policy_intrahorizon_margin_complete": intrahorizon_margin_schema is not None,
        "policy_research_leverage": int(config.research_leverage),
        "policy_liquidation_equity_reserve_fraction": float(config.liquidation_equity_reserve_fraction),
        "policy_liquidation_events": liquidation_events,
        "policy_liquidation_rate": liquidation_rate,
        "policy_mark_max_adverse_excursion_mean": (
            float(trades["mark_max_adverse_excursion_rate"].mean())
            if intrahorizon_margin_schema and len(trades)
            else None
        ),
        "policy_mark_max_adverse_excursion_max": (
            float(trades["mark_max_adverse_excursion_rate"].max())
            if intrahorizon_margin_schema and len(trades)
            else None
        ),
        "policy_mark_max_favorable_excursion_mean": (
            float(trades["mark_max_favorable_excursion_rate"].mean())
            if intrahorizon_margin_schema and len(trades)
            else None
        ),
        "policy_mark_minimum_equity_rate_min": (
            float(trades["mark_minimum_equity_rate"].min())
            if intrahorizon_margin_schema and len(trades)
            else None
        ),
        "policy_timeout_return_schema": timeout_return_source,
        "policy_horizon_hours": resolved_horizon,
        "policy_capital_sleeves": resolved_horizon,
        "policy_candidates": int(len(selected)),
        "policy_actionable_candidates": int(len(actionable_trades)),
        "policy_selected_calibration_schema": PRODUCTION_DRIFT_CALIBRATION_COHORT_SCHEMA,
        "policy_selected_calibration_rows": int(len(selected)),
        "policy_selected_log_loss": float(selected_log_loss),
        "policy_selected_multiclass_brier": selected_multiclass_brier,
        "policy_actionable_calibration_schema": POLICY_ACTIONABLE_CALIBRATION_SCHEMA,
        "policy_actionable_calibration_rows": int(actionable_calibration["rows"]),
        "policy_actionable_log_loss": actionable_calibration["log_loss"],
        "policy_actionable_multiclass_brier": actionable_calibration["multiclass_brier"],
        "policy_overlap_blocked_trades": int(overlap_blocked_trades),
        "policy_trades": int(len(trades)),
        "policy_direction_robustness": direction_robustness,
        "policy_symbol_robustness": symbol_robustness,
        "policy_cluster_robustness": cluster_robustness,
        "policy_regime_robustness": regime_robustness,
        "policy_interaction_robustness": interaction_robustness,
        "policy_cohorts": opportunity_cohort_count,
        "policy_trade_cohorts": trade_cohort_count,
        "policy_no_trade_cohorts": no_trade_cohort_count,
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
        "policy_win_rate": float((exit_r > 0).mean()) if len(exit_r) else 0.0,
        "policy_opportunity_win_rate": float((cohort_metrics["realized_mean_r"] > 0).mean()),
        "policy_trade_mean_r": float(trades["realized_r"].mean()) if len(trades) else None,
        "policy_trade_win_rate": float((trades["realized_r"] > 0).mean()) if len(trades) else None,
        "policy_profit_factor": float(profit_factor) if profit_factor is not None else None,
        "policy_profit_factor_unbounded": profit_factor_unbounded,
        "policy_gross_gain_r": gains,
        "policy_gross_loss_r": losses,
        "policy_max_drawdown_r": float(drawdown.max()) if len(drawdown) else 0.0,
        "policy_event_periods": int(len(exit_r)),
    }

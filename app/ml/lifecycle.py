from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import joblib
import pandas as pd
from sqlalchemy import desc, func, select, update

from app.config import Settings, get_settings
from app.db.engine import SessionFactory
from app.db.models import (
    Candle,
    FundingRate,
    InstrumentSpecHistory,
    ModelRegistry,
    OpenInterest,
    TickerSnapshot,
)
from app.json_utils import json_compatible
from app.ml.context import (
    MARKET_CONTEXT_AVAILABILITY_SCHEMA,
    MARKET_CONTEXT_SCHEMA_VERSION,
)
from app.ml.data_profile import (
    TrainingDataProfile,
    profile_from_symbol_rows,
    profile_training_frame,
)
from app.ml.drift import (
    PRODUCTION_DRIFT_CALIBRATION_COHORT_SCHEMA,
    PRODUCTION_DRIFT_REFERENCE_SCHEMA,
    build_production_drift_reference,
    validate_production_drift_reference,
)
from app.ml.funding import (
    FUNDING_INTERVAL_SCHEDULE_SCHEMA_VERSION,
    HISTORICAL_FUNDING_SCHEMA_VERSION,
)
from app.ml.mtm import (
    DEFAULT_EQUITY_RESERVE_FRACTION,
    INTRAHORIZON_MARGIN_SCHEMA_VERSION,
)
from app.ml.runtime import ModelRuntime
from app.ml.training import (
    DEFAULT_STOP_ATR_MULTIPLIER,
    DEFAULT_TP_ATR_MULTIPLIER,
    DEFAULT_WALK_FORWARD_FOLDS,
    ENTRY_EXECUTION_MODEL_SCHEMA,
    LABEL_PATH_SCHEMA_VERSION,
    MARKET_CONTEXT_ABLATION_SCHEMA_VERSION,
    MIN_WALK_FORWARD_POSITIVE_FRACTION,
    MODEL_BASE_FEATURE_NAMES,
    MODEL_FEATURE_NAMES,
    MODEL_FEATURE_SCHEMA_VERSION,
    POLICY_METRIC_SCHEMA,
    POLICY_UNCERTAINTY_SCHEMA,
    TEMPORAL_SPLIT_SCHEMA_VERSION,
    TIMEOUT_RETURN_SCHEMA_VERSION,
    WALK_FORWARD_SCHEMA_VERSION,
    PolicyEvaluationConfig,
    TemporalCalibratedBarrierModel,
    chronological_split,
    evaluate_model,
    evaluate_policy_model,
    expanding_walk_forward_splits,
    make_barrier_dataset,
    timeout_return_r_targets,
    zero_market_context_split,
)
from app.services.audit import append_audit_event, publish_outbox
from app.services.model_promotion import (
    build_experiment_policy_binding,
    evaluate_experiment_promotion_gate,
    experiment_policy_binding_from_settings,
    require_experiment_policy_binding,
    require_passed_experiment_promotion_gate,
)


@dataclass(frozen=True)
class IncumbentSnapshot:
    version: str
    model_type: str
    artifact_path: str | None
    artifact_sha256: str | None
    training_end: datetime | None

    @property
    def is_artifact_model(self) -> bool:
        return self.model_type != "deterministic_baseline" and bool(self.artifact_path)


@dataclass(frozen=True)
class ModelCandidate:
    path: Path
    version: str
    model_type: str
    horizon: int
    training_start: datetime
    training_end: datetime
    dataset_rows: int
    unique_timestamps: int
    symbol_count: int
    symbol_sample: tuple[str, ...]
    training_data_profile: TrainingDataProfile
    metrics: dict[str, Any]
    incumbent_metrics: dict[str, Any] | None
    incumbent_version: str | None
    feature_schema_version: str = MODEL_FEATURE_SCHEMA_VERSION


@dataclass(frozen=True)
class TrainingMarketData:
    candles: pd.DataFrame
    mark_candles: pd.DataFrame
    index_candles: pd.DataFrame
    open_interest: pd.DataFrame
    funding: pd.DataFrame
    funding_interval_minutes: dict[str, int]
    funding_interval_history: pd.DataFrame

MODEL_ACTIVATION_QUALITY_GATE_SCHEMA = "model-activation-quality-gate-v1"


def require_passed_quality_gate(quality_gate: dict[str, Any] | None) -> dict[str, Any]:
    """Return a normalized gate snapshot or fail closed before activation.

    Activation is a state-changing safety boundary.  A missing gate, a failed
    gate, or a contradictory ``passed=True`` record with non-empty reasons must
    never be interpreted as approval.
    """

    if not isinstance(quality_gate, dict):
        raise RuntimeError("Model activation requires a persisted passed quality gate")
    reasons = quality_gate.get("reasons")
    if not isinstance(reasons, list) or any(not isinstance(item, str) or not item for item in reasons):
        raise RuntimeError("Model activation quality gate has invalid reasons evidence")
    passed = quality_gate.get("passed")
    if passed is not True or reasons:
        detail = ", ".join(reasons) if reasons else "gate_not_passed"
        raise RuntimeError(f"Model activation quality gate did not pass: {detail}")
    return json_compatible(
        {
            "schema": MODEL_ACTIVATION_QUALITY_GATE_SCHEMA,
            "passed": True,
            "reasons": [],
            "gate": quality_gate,
        }
    )


def policy_evaluation_config(settings: Settings) -> PolicyEvaluationConfig:
    return PolicyEvaluationConfig(
        fee_rate_round_trip=settings.fee_rate_taker * 2,
        slippage_rate=settings.base_slippage_bps / 10000,
        stop_gap_reserve_rate=settings.stop_gap_reserve_bps / 10000,
        min_net_rr=settings.min_net_rr,
        min_net_ev_r=settings.min_net_ev_r,
        timeout_return_rate=settings.timeout_gross_return_rate,
        horizon_hours=settings.default_horizon_hours,
        bootstrap_samples=settings.auto_train_policy_bootstrap_samples,
        confidence_level=settings.auto_train_policy_confidence_level,
        research_leverage=settings.default_leverage,
        liquidation_equity_reserve_fraction=DEFAULT_EQUITY_RESERVE_FRACTION,
        require_intrahorizon_margin=True,
    )


def _as_datetime(value: object) -> datetime:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if not isinstance(value, datetime):
        raise TypeError(f"Expected datetime-like value, got {type(value)!r}")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def _select_training_symbols(
    session,
    symbols: list[str] | tuple[str, ...] | None,
    *,
    max_symbols: int,
    interval: str,
) -> list[str]:
    selected_symbols = list(dict.fromkeys(str(item).upper() for item in (symbols or []) if item))
    if selected_symbols or max_symbols <= 0:
        return selected_symbols

    ranked_tickers = select(
        TickerSnapshot.symbol.label("symbol"),
        TickerSnapshot.turnover_24h.label("turnover_24h"),
        func.row_number()
        .over(
            partition_by=TickerSnapshot.symbol,
            order_by=TickerSnapshot.source_time.desc(),
        )
        .label("row_number"),
    ).subquery()
    selected_symbols = list(
        (
            await session.execute(
                select(ranked_tickers.c.symbol)
                .where(ranked_tickers.c.row_number == 1)
                .order_by(desc(ranked_tickers.c.turnover_24h).nullslast())
                .limit(max_symbols)
            )
        ).scalars()
    )
    if selected_symbols:
        return selected_symbols
    return list(
        (
            await session.execute(
                select(Candle.symbol)
                .where(
                    Candle.interval == interval,
                    Candle.price_type == "last",
                    Candle.confirmed.is_(True),
                )
                .distinct()
                .order_by(Candle.symbol)
                .limit(max_symbols)
            )
        ).scalars()
    )


async def _latest_training_candle_time(
    session,
    *,
    selected_symbols: list[str],
    interval: str,
) -> datetime | None:
    query = select(func.max(Candle.open_time)).where(
        Candle.interval == interval,
        Candle.price_type == "last",
        Candle.confirmed.is_(True),
    )
    if selected_symbols:
        query = query.where(Candle.symbol.in_(selected_symbols))
    return (await session.execute(query)).scalar_one_or_none()


async def load_training_data_profile(
    symbols: list[str] | tuple[str, ...] | None,
    *,
    lookback_days: int | None,
    max_symbols: int,
    horizon: int,
    minimum_rows_for_coverage: int,
    interval: str = "60",
) -> TrainingDataProfile:
    async with SessionFactory() as session:
        selected_symbols = await _select_training_symbols(
            session, symbols, max_symbols=max_symbols, interval=interval
        )
        latest = await _latest_training_candle_time(
            session, selected_symbols=selected_symbols, interval=interval
        )
        if latest is None:
            return profile_from_symbol_rows(
                [], unique_timestamps=0, minimum_rows_for_coverage=minimum_rows_for_coverage
            )
        label_cutoff = latest - timedelta(hours=horizon)
        lookback_cutoff = (
            latest - timedelta(days=lookback_days) if lookback_days and lookback_days > 0 else None
        )
        filters = [
            Candle.interval == interval,
            Candle.price_type == "last",
            Candle.confirmed.is_(True),
            Candle.open_time <= label_cutoff,
        ]
        if selected_symbols:
            filters.append(Candle.symbol.in_(selected_symbols))
        if lookback_cutoff is not None:
            filters.append(Candle.open_time >= lookback_cutoff)

        grouped = (
            await session.execute(
                select(
                    Candle.symbol,
                    func.count(Candle.id),
                    func.min(Candle.open_time),
                    func.max(Candle.open_time),
                )
                .where(*filters)
                .group_by(Candle.symbol)
                .order_by(Candle.symbol)
            )
        ).all()
        if selected_symbols:
            grouped_by_symbol = {str(row[0]): row for row in grouped}
            grouped = [grouped_by_symbol.get(symbol, (symbol, 0, None, None)) for symbol in selected_symbols]
        unique_timestamps = int(
            (
                await session.execute(select(func.count(func.distinct(Candle.open_time))).where(*filters))
            ).scalar_one()
            or 0
        )
    return profile_from_symbol_rows(
        grouped,
        unique_timestamps=unique_timestamps,
        minimum_rows_for_coverage=minimum_rows_for_coverage,
    )


async def load_training_market_data(
    symbols: list[str] | tuple[str, ...] | None,
    *,
    lookback_days: int | None = None,
    max_symbols: int = 0,
    interval: str = "60",
) -> TrainingMarketData:
    async with SessionFactory() as session:
        selected_symbols = await _select_training_symbols(
            session, symbols, max_symbols=max_symbols, interval=interval
        )
        latest = await _latest_training_candle_time(
            session, selected_symbols=selected_symbols, interval=interval
        )
        cutoff = None
        if latest is not None and lookback_days and lookback_days > 0:
            cutoff = latest - timedelta(days=lookback_days)

        query = select(Candle).where(
            Candle.interval == interval,
            Candle.price_type == "last",
            Candle.confirmed.is_(True),
        )
        if selected_symbols:
            query = query.where(Candle.symbol.in_(selected_symbols))
        if cutoff is not None:
            query = query.where(Candle.open_time >= cutoff)
        candle_rows = (await session.execute(query.order_by(Candle.open_time, Candle.symbol))).scalars().all()

        mark_query = select(Candle).where(
            Candle.interval == interval,
            Candle.price_type == "mark",
            Candle.confirmed.is_(True),
        )
        if selected_symbols:
            mark_query = mark_query.where(Candle.symbol.in_(selected_symbols))
        if cutoff is not None:
            mark_query = mark_query.where(Candle.open_time >= cutoff)
        mark_rows = (
            (await session.execute(mark_query.order_by(Candle.open_time, Candle.symbol))).scalars().all()
        )

        index_query = select(Candle).where(
            Candle.interval == interval,
            Candle.price_type == "index",
            Candle.confirmed.is_(True),
        )
        if selected_symbols:
            index_query = index_query.where(Candle.symbol.in_(selected_symbols))
        if cutoff is not None:
            index_query = index_query.where(Candle.open_time >= cutoff)
        index_rows = (
            (await session.execute(index_query.order_by(Candle.open_time, Candle.symbol))).scalars().all()
        )

        spec_query = select(InstrumentSpecHistory).order_by(
            InstrumentSpecHistory.symbol,
            desc(InstrumentSpecHistory.valid_from),
        )
        if selected_symbols:
            spec_query = spec_query.where(InstrumentSpecHistory.symbol.in_(selected_symbols))
        spec_rows = (await session.execute(spec_query)).scalars().all()
        funding_intervals: dict[str, int] = {}
        funding_interval_history_records: list[dict[str, object]] = []
        for row in spec_rows:
            if row.funding_interval_minutes is None:
                continue
            interval_minutes = int(row.funding_interval_minutes)
            if interval_minutes <= 0:
                continue
            symbol = str(row.symbol).strip().upper()
            funding_interval_history_records.append(
                {
                    "symbol": symbol,
                    "valid_from": row.valid_from,
                    "funding_interval_minutes": interval_minutes,
                }
            )
            if symbol not in funding_intervals:
                funding_intervals[symbol] = interval_minutes

        funding_rows: list[FundingRate] = []
        open_interest_rows: list[OpenInterest] = []
        if candle_rows:
            earliest_candle = min(row.open_time for row in candle_rows)
            latest_candle_close = max(row.close_time for row in candle_rows)
            oi_query = select(OpenInterest).where(
                OpenInterest.interval == "1h",
                OpenInterest.event_time >= earliest_candle - timedelta(hours=24),
                OpenInterest.event_time <= latest_candle_close,
            )
            if selected_symbols:
                oi_query = oi_query.where(OpenInterest.symbol.in_(selected_symbols))
            open_interest_rows = (
                (await session.execute(oi_query.order_by(OpenInterest.event_time, OpenInterest.symbol)))
                .scalars()
                .all()
            )
            historical_intervals = [
                int(item["funding_interval_minutes"])
                for item in funding_interval_history_records
            ]
            max_interval = max([*funding_intervals.values(), *historical_intervals], default=1440)
            funding_query = select(FundingRate).where(
                FundingRate.funding_time >= earliest_candle - timedelta(minutes=max_interval),
                FundingRate.funding_time <= latest_candle_close,
            )
            if selected_symbols:
                funding_query = funding_query.where(FundingRate.symbol.in_(selected_symbols))
            funding_rows = (
                (await session.execute(funding_query.order_by(FundingRate.funding_time, FundingRate.symbol)))
                .scalars()
                .all()
            )

    candles = pd.DataFrame(
        [
            {
                "symbol": row.symbol,
                "open_time": row.open_time,
                "close_time": row.close_time,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume),
                "turnover": float(row.turnover),
            }
            for row in candle_rows
        ]
    )
    mark_candles = pd.DataFrame(
        [
            {
                "symbol": row.symbol,
                "open_time": row.open_time,
                "close_time": row.close_time,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
            }
            for row in mark_rows
        ]
    )
    index_candles = pd.DataFrame(
        [
            {
                "symbol": row.symbol,
                "open_time": row.open_time,
                "close_time": row.close_time,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
            }
            for row in index_rows
        ]
    )
    open_interest = pd.DataFrame(
        [
            {
                "symbol": row.symbol,
                "event_time": row.event_time,
                "available_at": row.available_at,
                "value": float(row.value),
            }
            for row in open_interest_rows
        ]
    )
    funding = pd.DataFrame(
        [
            {
                "symbol": row.symbol,
                "funding_time": row.funding_time,
                "available_at": row.available_at,
                "rate": float(row.rate),
            }
            for row in funding_rows
        ]
    )
    funding_interval_history = pd.DataFrame.from_records(
        funding_interval_history_records,
        columns=["symbol", "valid_from", "funding_interval_minutes"],
    )
    return TrainingMarketData(
        candles=candles,
        mark_candles=mark_candles,
        index_candles=index_candles,
        open_interest=open_interest,
        funding=funding,
        funding_interval_minutes=funding_intervals,
        funding_interval_history=funding_interval_history,
    )


async def load_training_candles(
    symbols: list[str] | tuple[str, ...] | None,
    *,
    lookback_days: int | None = None,
    max_symbols: int = 0,
    interval: str = "60",
) -> pd.DataFrame:
    return (
        await load_training_market_data(
            symbols,
            lookback_days=lookback_days,
            max_symbols=max_symbols,
            interval=interval,
        )
    ).candles


def incumbent_from_registry(model: ModelRegistry | None) -> IncumbentSnapshot | None:
    if model is None:
        return None
    return IncumbentSnapshot(
        version=model.version,
        model_type=model.model_type,
        artifact_path=model.artifact_path,
        artifact_sha256=model.artifact_sha256,
        training_end=model.training_end,
    )


def evaluate_market_context_ablation(
    split,
    *,
    model_type: str,
) -> dict[str, Any]:
    if split.train_meta is None:
        raise ValueError("Market-context ablation requires training metadata")
    core_split = zero_market_context_split(split)
    core_model = TemporalCalibratedBarrierModel(model_type).fit(
        core_split.x_train,
        core_split.y_train,
        core_split.x_cal,
        core_split.y_cal,
        timeout_return_r_train=timeout_return_r_targets(core_split.train_meta),
    )
    core_metrics = evaluate_model(core_model, core_split)
    return {
        "schema": MARKET_CONTEXT_ABLATION_SCHEMA_VERSION,
        "method": "same-temporal-split-context-columns-zeroed-and-refit",
        "core_log_loss": float(core_metrics["log_loss"]),
        "core_multiclass_brier": float(core_metrics["multiclass_brier"]),
    }


def evaluate_walk_forward_validation(
    dataset: pd.DataFrame,
    final_split,
    *,
    horizon: int,
    model_type: str,
    policy_config: PolicyEvaluationConfig | None,
    folds: int = DEFAULT_WALK_FORWARD_FOLDS,
) -> dict[str, Any]:
    """Train fresh models across purged expanding walk-forward folds.

    The development region ends before the final untouched holdout. Models are
    refit and recalibrated independently in every fold, so the result measures
    temporal stability rather than repeatedly scoring one model on several slices.
    """

    if final_split.test_meta is None or final_split.test_meta.empty:
        raise ValueError("Final holdout metadata is required for walk-forward validation")
    final_holdout_times = pd.to_datetime(final_split.test_meta["decision_time"], utc=True, errors="coerce")
    if final_holdout_times.isna().any():
        raise ValueError("Final holdout contains invalid decision_time values")
    final_holdout_start = final_holdout_times.min()

    label_end_times = pd.to_datetime(dataset["label_end_time"], utc=True, errors="coerce")
    if label_end_times.isna().any():
        raise ValueError("Dataset contains invalid label_end_time values")
    development = dataset[label_end_times < final_holdout_start].copy()
    fold_splits = expanding_walk_forward_splits(
        development,
        folds=folds,
        purge_hours=horizon,
    )

    fold_results: list[dict[str, Any]] = []
    for fold_index, fold_split in enumerate(fold_splits, start=1):
        if fold_split.train_meta is None or fold_split.cal_meta is None:
            raise RuntimeError("Walk-forward split did not expose train/calibration metadata")
        fold_model = TemporalCalibratedBarrierModel(model_type).fit(
            fold_split.x_train,
            fold_split.y_train,
            fold_split.x_cal,
            fold_split.y_cal,
            timeout_return_r_train=timeout_return_r_targets(fold_split.train_meta),
        )
        fold_metrics = evaluate_model(fold_model, fold_split)
        fold_ablation = evaluate_market_context_ablation(
            fold_split,
            model_type=model_type,
        )
        fold_metrics["market_context_ablation_schema"] = MARKET_CONTEXT_ABLATION_SCHEMA_VERSION
        fold_metrics["market_context_core_log_loss"] = fold_ablation["core_log_loss"]
        fold_metrics["market_context_core_multiclass_brier"] = fold_ablation[
            "core_multiclass_brier"
        ]
        fold_metrics["market_context_log_loss_benefit"] = (
            float(fold_ablation["core_log_loss"]) - float(fold_metrics["log_loss"])
        )
        if policy_config is not None:
            fold_metrics.update(
                evaluate_policy_model(
                    fold_model,
                    fold_split,
                    policy_config,
                    horizon_hours=horizon,
                )
            )
        train_times = pd.to_datetime(fold_split.train_meta["decision_time"], utc=True, errors="raise")
        cal_times = pd.to_datetime(fold_split.cal_meta["decision_time"], utc=True, errors="raise")
        fold_results.append(
            json_compatible(
                {
                    "fold": fold_index,
                    "train_rows": int(len(fold_split.y_train)),
                    "calibration_rows": int(len(fold_split.y_cal)),
                    "test_rows": int(len(fold_split.y_test)),
                    "train_start_time": train_times.min().isoformat(),
                    "train_end_time": train_times.max().isoformat(),
                    "calibration_start_time": cal_times.min().isoformat(),
                    "calibration_end_time": cal_times.max().isoformat(),
                    "test_start_time": fold_metrics["holdout_start_time"],
                    "test_end_time": fold_metrics["holdout_end_time"],
                    **fold_metrics,
                }
            )
        )

    skills = [float(item["log_loss_skill_vs_prior"]) for item in fold_results]
    log_losses = [float(item["log_loss"]) for item in fold_results]
    briers = [float(item["multiclass_brier"]) for item in fold_results]
    policy_means = [
        float(value) for item in fold_results if (value := item.get("policy_realized_mean_r")) is not None
    ]
    positive_skill_folds = sum(value > 0.0 for value in skills)
    positive_policy_folds = sum(value > 0.0 for value in policy_means)
    completed = len(fold_results)
    return json_compatible(
        {
            "walk_forward_schema": WALK_FORWARD_SCHEMA_VERSION,
            "walk_forward_folds_requested": int(folds),
            "walk_forward_folds_completed": completed,
            "walk_forward_final_holdout_start_time": (final_holdout_start.isoformat()),
            "walk_forward_log_loss_mean": float(sum(log_losses) / completed),
            "walk_forward_log_loss_max": float(max(log_losses)),
            "walk_forward_multiclass_brier_mean": float(sum(briers) / completed),
            "walk_forward_multiclass_brier_max": float(max(briers)),
            "walk_forward_log_loss_skill_mean": float(sum(skills) / completed),
            "walk_forward_log_loss_skill_min": float(min(skills)),
            "walk_forward_positive_skill_folds": int(positive_skill_folds),
            "walk_forward_positive_skill_fraction": float(positive_skill_folds / completed),
            "walk_forward_policy_positive_mean_r_folds": int(positive_policy_folds),
            "walk_forward_policy_positive_mean_r_fraction": (
                float(positive_policy_folds / completed) if policy_config is not None else None
            ),
            "walk_forward_policy_realized_mean_r_mean": (
                float(sum(policy_means) / len(policy_means)) if policy_means else None
            ),
            "walk_forward_policy_realized_mean_r_min": (float(min(policy_means)) if policy_means else None),
            "walk_forward_market_context_noninferior_folds": int(
                sum(float(item["market_context_log_loss_benefit"]) >= -0.005 for item in fold_results)
            ),
            "walk_forward_market_context_positive_folds": int(
                sum(float(item["market_context_log_loss_benefit"]) > 0.0 for item in fold_results)
            ),
            "walk_forward_fold_results": fold_results,
        }
    )


def build_model_candidate(
    candles: pd.DataFrame,
    *,
    mark_candles: pd.DataFrame | None = None,
    index_candles: pd.DataFrame | None = None,
    open_interest: pd.DataFrame | None = None,
    horizon: int,
    model_type: str,
    model_dir: Path,
    entry_spread_bps: float = 0.0,
    funding_history: pd.DataFrame | None = None,
    funding_interval_minutes: dict[str, int] | None = None,
    funding_interval_history: pd.DataFrame | None = None,
    version: str | None = None,
    output: Path | None = None,
    incumbent: IncumbentSnapshot | None = None,
    source: str = "manual",
    minimum_rows_for_coverage: int = 300,
    policy_config: PolicyEvaluationConfig | None = None,
    expected_symbols: list[str] | tuple[str, ...] | None = None,
) -> ModelCandidate:
    if candles.empty:
        raise RuntimeError("No confirmed hourly candles are available for model training")

    dataset = make_barrier_dataset(
        candles,
        horizon=horizon,
        entry_spread_bps=entry_spread_bps,
        funding_history=funding_history,
        funding_interval_minutes=funding_interval_minutes,
        funding_interval_history=funding_interval_history,
        require_funding_timeline=True,
        mark_candles=mark_candles,
        require_mark_timeline=True,
        index_candles=index_candles,
        open_interest=open_interest,
        require_market_context=True,
        liquidation_leverage=(policy_config.research_leverage if policy_config is not None else 3),
        liquidation_equity_reserve_fraction=(
            policy_config.liquidation_equity_reserve_fraction
            if policy_config is not None
            else DEFAULT_EQUITY_RESERVE_FRACTION
        ),
    )
    if dataset.empty:
        raise RuntimeError("No direction-specific barrier labels could be built from PostgreSQL candles")
    split = chronological_split(dataset, purge_rows=horizon)
    if split.train_meta is None:
        raise RuntimeError("Chronological split did not expose training metadata")

    model = TemporalCalibratedBarrierModel(model_type).fit(
        split.x_train,
        split.y_train,
        split.x_cal,
        split.y_cal,
        timeout_return_r_train=timeout_return_r_targets(split.train_meta),
    )
    metrics = evaluate_model(model, split)
    ablation = evaluate_market_context_ablation(split, model_type=model_type)
    metrics["market_context_ablation"] = {
        **ablation,
        "enriched_log_loss": float(metrics["log_loss"]),
        "enriched_multiclass_brier": float(metrics["multiclass_brier"]),
        "log_loss_benefit": float(ablation["core_log_loss"]) - float(metrics["log_loss"]),
        "multiclass_brier_benefit": (
            float(ablation["core_multiclass_brier"]) - float(metrics["multiclass_brier"])
        ),
        "noninferiority_tolerance": 0.005,
    }
    label_data_end = _as_datetime(dataset.label_end_time.max())
    metrics["temporal_split_schema"] = TEMPORAL_SPLIT_SCHEMA_VERSION
    metrics["feature_schema_version"] = MODEL_FEATURE_SCHEMA_VERSION
    metrics["label_path_schema_version"] = LABEL_PATH_SCHEMA_VERSION
    metrics["entry_execution_model"] = json_compatible(dataset.attrs.get("entry_execution_model") or {})
    metrics["historical_funding_timeline"] = json_compatible(
        dataset.attrs.get("historical_funding_timeline") or {}
    )
    metrics["intrahorizon_margin_path"] = json_compatible(dataset.attrs.get("intrahorizon_margin_path") or {})
    metrics["market_context"] = json_compatible(dataset.attrs.get("market_context") or {})
    metrics["hourly_continuity"] = json_compatible(dataset.attrs.get("hourly_continuity") or {})
    metrics["label_data_end"] = label_data_end.isoformat()
    if policy_config is not None:
        metrics.update(evaluate_policy_model(model, split, policy_config, horizon_hours=horizon))
        metrics["promotion_policy_binding"] = build_experiment_policy_binding(
            entry_spread_bps=entry_spread_bps,
            research_leverage=policy_config.research_leverage,
            liquidation_equity_reserve_fraction=(
                policy_config.liquidation_equity_reserve_fraction
            ),
            round_trip_cost_bps=policy_config.fee_rate_round_trip * 10000.0,
            slippage_bps=policy_config.slippage_rate * 10000.0,
            stop_gap_reserve_bps=policy_config.stop_gap_reserve_rate * 10000.0,
            funding_rate_override=0.0,
            timeout_return_rate_override=None,
            minimum_net_rr=policy_config.min_net_rr,
            minimum_net_ev_r=policy_config.min_net_ev_r,
        )
    policy_candidates = int(metrics.get("policy_candidates") or 0)
    policy_actionable_candidates = int(metrics.get("policy_actionable_candidates") or 0)
    actionability_rate = (
        float(policy_actionable_candidates / policy_candidates) if policy_candidates > 0 else 0.0
    )
    calibration_reference = None
    calibration_cohort_schema = None
    if policy_config is not None:
        calibration_reference = {
            "rows": metrics.get("policy_selected_calibration_rows"),
            "log_loss": metrics.get("policy_selected_log_loss"),
            "multiclass_brier": metrics.get("policy_selected_multiclass_brier"),
        }
        calibration_cohort_schema = str(metrics.get("policy_selected_calibration_schema") or "")
    metrics["production_drift_reference"] = json_compatible(
        build_production_drift_reference(
            split.x_test[:, : len(MODEL_BASE_FEATURE_NAMES)],
            model.predict_proba(split.x_test),
            split.y_test,
            feature_names=MODEL_BASE_FEATURE_NAMES,
            classes=[str(item) for item in model.classes_],
            actionability_rate=actionability_rate,
            min_net_rr=(policy_config.min_net_rr if policy_config is not None else 0.0),
            min_net_ev_r=(policy_config.min_net_ev_r if policy_config is not None else 0.0),
            calibration_reference=calibration_reference,
            **(
                {"calibration_cohort_schema": calibration_cohort_schema}
                if calibration_cohort_schema is not None
                else {}
            ),
        )
    )
    metrics.update(
        evaluate_walk_forward_validation(
            dataset,
            split,
            horizon=horizon,
            model_type=model_type,
            policy_config=policy_config,
        )
    )

    incumbent_metrics: dict[str, Any] | None = None
    if incumbent and incumbent.is_artifact_model:
        try:
            runtime = ModelRuntime(Path(incumbent.artifact_path or ""), allow_baseline=False)
            runtime.load(
                expected_sha256=incumbent.artifact_sha256,
                expected_version=incumbent.version,
                source="training_benchmark",
            )
            if runtime.horizon_hours != horizon or runtime.bundle is None:
                incumbent_metrics = {
                    "comparison_skipped": "incumbent_horizon_mismatch",
                    "incumbent_horizon_hours": runtime.horizon_hours,
                }
            elif not (
                math.isclose(
                    runtime.stop_atr_multiplier,
                    DEFAULT_STOP_ATR_MULTIPLIER,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
                and math.isclose(
                    runtime.tp_atr_multiplier,
                    DEFAULT_TP_ATR_MULTIPLIER,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
                and math.isclose(
                    runtime.entry_spread_bps,
                    entry_spread_bps,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
                and policy_config is not None
                and runtime.research_leverage == policy_config.research_leverage
                and math.isclose(
                    runtime.liquidation_equity_reserve_fraction,
                    policy_config.liquidation_equity_reserve_fraction,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
            ):
                incumbent_metrics = {
                    "comparison_skipped": "incumbent_execution_geometry_mismatch",
                    "candidate_stop_atr_multiplier": DEFAULT_STOP_ATR_MULTIPLIER,
                    "candidate_tp_atr_multiplier": DEFAULT_TP_ATR_MULTIPLIER,
                    "candidate_entry_spread_bps": float(entry_spread_bps),
                    "incumbent_stop_atr_multiplier": runtime.stop_atr_multiplier,
                    "incumbent_tp_atr_multiplier": runtime.tp_atr_multiplier,
                    "incumbent_entry_spread_bps": runtime.entry_spread_bps,
                    "candidate_research_leverage": (
                        policy_config.research_leverage if policy_config is not None else None
                    ),
                    "incumbent_research_leverage": runtime.research_leverage,
                    "candidate_liquidation_equity_reserve_fraction": (
                        policy_config.liquidation_equity_reserve_fraction
                        if policy_config is not None
                        else None
                    ),
                    "incumbent_liquidation_equity_reserve_fraction": (
                        runtime.liquidation_equity_reserve_fraction
                    ),
                }
            else:
                incumbent_metrics = evaluate_model(runtime.bundle["model"], split)
                if policy_config is not None:
                    incumbent_metrics.update(
                        evaluate_policy_model(
                            runtime.bundle["model"],
                            split,
                            policy_config,
                            horizon_hours=horizon,
                        )
                    )
        except Exception as exc:
            incumbent_metrics = {
                "comparison_skipped": "incumbent_load_or_evaluation_failed",
                "error": str(exc),
            }

    created_at = datetime.now(UTC)
    generated_version = version or (f"barrier-{model_type}-h{horizon}-{created_at:%Y%m%dT%H%M%SZ}")
    target = (output or model_dir / f"{generated_version}.joblib").expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    training_start = _as_datetime(dataset.decision_time.min())
    training_end = _as_datetime(dataset.decision_time.max())
    unique_timestamps = int(dataset["decision_time"].nunique())
    symbol_values = tuple(sorted(str(item) for item in dataset["symbol"].unique()))
    training_data_profile = profile_training_frame(
        candles,
        label_cutoff=_as_datetime(dataset.source_open_time.max()),
        minimum_rows_for_coverage=minimum_rows_for_coverage,
        expected_symbols=expected_symbols,
    )
    bundle = {
        "task": "barrier_outcome_v1",
        "model": model,
        "model_type": model_type,
        "version": generated_version,
        "calibration_version": f"sigmoid-ovr-{generated_version}",
        "feature_names": MODEL_FEATURE_NAMES,
        "feature_schema_version": MODEL_FEATURE_SCHEMA_VERSION,
        "market_context_schema": MARKET_CONTEXT_SCHEMA_VERSION,
        "market_context_availability_schema": MARKET_CONTEXT_AVAILABILITY_SCHEMA,
        "market_context": metrics["market_context"],
        "market_context_ablation_schema": MARKET_CONTEXT_ABLATION_SCHEMA_VERSION,
        "production_drift_reference": metrics["production_drift_reference"],
        "label_path_schema_version": LABEL_PATH_SCHEMA_VERSION,
        "entry_spread_bps": float(entry_spread_bps),
        "entry_execution_model": metrics["entry_execution_model"],
        "historical_funding_schema": HISTORICAL_FUNDING_SCHEMA_VERSION,
        "historical_funding_timeline": metrics["historical_funding_timeline"],
        "intrahorizon_margin_schema": INTRAHORIZON_MARGIN_SCHEMA_VERSION,
        "intrahorizon_margin_path": metrics["intrahorizon_margin_path"],
        "research_leverage": (policy_config.research_leverage if policy_config is not None else 3),
        "liquidation_equity_reserve_fraction": (
            policy_config.liquidation_equity_reserve_fraction
            if policy_config is not None
            else DEFAULT_EQUITY_RESERVE_FRACTION
        ),
        "temporal_split_schema": TEMPORAL_SPLIT_SCHEMA_VERSION,
        "walk_forward_schema": WALK_FORWARD_SCHEMA_VERSION,
        "timeout_return_schema_version": TIMEOUT_RETURN_SCHEMA_VERSION,
        "label_data_end": label_data_end.isoformat(),
        "horizon_hours": horizon,
        "stop_atr_multiplier": DEFAULT_STOP_ATR_MULTIPLIER,
        "tp_atr_multiplier": DEFAULT_TP_ATR_MULTIPLIER,
        "metrics": metrics,
        "hourly_continuity": metrics["hourly_continuity"],
        "training_start": training_start.isoformat(),
        "training_end": training_end.isoformat(),
        "dataset_rows": int(len(dataset)),
        "unique_timestamps": unique_timestamps,
        "symbol_count": len(symbol_values),
        "symbol_sample": list(symbol_values[:25]),
        "symbols": list(symbol_values),
        "training_data_profile": training_data_profile.to_dict(),
        "source": source,
        "created_at": created_at.isoformat(),
    }

    temporary = target.with_suffix(target.suffix + f".{uuid4().hex}.tmp")
    try:
        joblib.dump(bundle, temporary)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)

    return ModelCandidate(
        path=target,
        version=generated_version,
        model_type=model_type,
        horizon=horizon,
        training_start=training_start,
        training_end=training_end,
        dataset_rows=int(len(dataset)),
        unique_timestamps=unique_timestamps,
        symbol_count=len(symbol_values),
        symbol_sample=symbol_values[:25],
        training_data_profile=training_data_profile,
        metrics=metrics,
        incumbent_metrics=incumbent_metrics,
        incumbent_version=incumbent.version if incumbent else None,
    )


def evaluate_quality_gate(candidate: ModelCandidate, settings: Settings) -> dict[str, Any]:
    metrics = candidate.metrics
    reasons: list[str] = []

    def finite_or_none(value: object) -> float | None:
        if value is None:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return parsed if math.isfinite(parsed) else None

    def required_metric(name: str) -> tuple[float | None, float]:
        value = finite_or_none(metrics.get(name))
        if value is None:
            reasons.append(f"missing_or_non_finite_{name}")
            return None, math.inf
        return value, value

    def nonnegative_int_metric(name: str) -> int:
        value = finite_or_none(metrics.get(name))
        if value is None or value < 0 or not float(value).is_integer():
            reasons.append(f"missing_or_invalid_{name}")
            return 0
        return int(value)

    rows = nonnegative_int_metric("rows")
    holdout_span_value, holdout_span_check = required_metric("holdout_span_hours")
    log_loss_value, log_loss_check = required_metric("log_loss")
    class_prior_log_loss_value, _ = required_metric("class_prior_log_loss")
    log_loss_skill_value, log_loss_skill_check = required_metric("log_loss_skill_vs_prior")
    brier_value, brier_check = required_metric("multiclass_brier")
    ece_pairs = [
        required_metric("ece_tp"),
        required_metric("ece_sl"),
        required_metric("ece_timeout"),
    ]
    ece_values = [value for value, _ in ece_pairs]
    max_ece = (
        max(value for value in ece_values if value is not None)
        if all(value is not None for value in ece_values)
        else None
    )
    max_ece_check = max(check for _, check in ece_pairs)

    entry_execution_model = metrics.get("entry_execution_model")
    entry_execution_schema = (
        entry_execution_model.get("schema") if isinstance(entry_execution_model, dict) else None
    )
    entry_spread_bps = finite_or_none(
        entry_execution_model.get("entry_spread_bps") if isinstance(entry_execution_model, dict) else None
    )
    if entry_execution_schema != ENTRY_EXECUTION_MODEL_SCHEMA:
        reasons.append("invalid_entry_execution_model_schema")
    if entry_spread_bps is None or entry_spread_bps < 0.0:
        reasons.append("missing_or_invalid_entry_spread_bps")
    elif not math.isclose(
        entry_spread_bps,
        settings.model_entry_spread_bps,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        reasons.append("entry_spread_bps_mismatch")

    funding_timeline = metrics.get("historical_funding_timeline")
    funding_schema = funding_timeline.get("schema") if isinstance(funding_timeline, dict) else None
    funding_symbols = finite_or_none(
        funding_timeline.get("symbols") if isinstance(funding_timeline, dict) else None
    )
    funding_settlements = finite_or_none(
        funding_timeline.get("settlements") if isinstance(funding_timeline, dict) else None
    )
    if funding_schema != HISTORICAL_FUNDING_SCHEMA_VERSION:
        reasons.append("invalid_historical_funding_schema")
    if funding_symbols is None or funding_symbols < 1 or not funding_symbols.is_integer():
        reasons.append("missing_historical_funding_symbols")
    if funding_settlements is None or funding_settlements < 1 or not funding_settlements.is_integer():
        reasons.append("missing_historical_funding_settlements")
    if metrics.get("historical_funding_schema") != HISTORICAL_FUNDING_SCHEMA_VERSION:
        reasons.append("policy_historical_funding_schema_mismatch")
    if metrics.get("policy_funding_timeline_complete") is not True:
        reasons.append("policy_historical_funding_timeline_incomplete")
    if metrics.get("policy_expected_funding_source") != "none-no-point-in-time-forecast":
        reasons.append("policy_expected_funding_lookahead_risk")
    if metrics.get("policy_realized_funding_source") != HISTORICAL_FUNDING_SCHEMA_VERSION:
        reasons.append("policy_realized_funding_source_mismatch")
    funding_interval_schedule_schema = (
        funding_timeline.get("funding_interval_schedule_schema")
        if isinstance(funding_timeline, dict)
        else None
    )
    funding_interval_source = (
        funding_timeline.get("interval_source") if isinstance(funding_timeline, dict) else None
    )
    funding_interval_history_symbols = finite_or_none(
        funding_timeline.get("interval_history_symbols")
        if isinstance(funding_timeline, dict)
        else None
    )
    if funding_interval_schedule_schema != FUNDING_INTERVAL_SCHEDULE_SCHEMA_VERSION:
        reasons.append("invalid_funding_interval_schedule_schema")
    if funding_interval_source != "instrument_spec_history_point_in_time":
        reasons.append("funding_interval_history_not_point_in_time")
    if (
        funding_interval_history_symbols is None
        or funding_symbols is None
        or funding_interval_history_symbols < funding_symbols
    ):
        reasons.append("incomplete_funding_interval_history_symbols")

    market_context = metrics.get("market_context")
    context_schema = market_context.get("schema") if isinstance(market_context, dict) else None
    context_availability_schema = (
        market_context.get("availability_schema") if isinstance(market_context, dict) else None
    )
    if context_schema != MARKET_CONTEXT_SCHEMA_VERSION:
        reasons.append("invalid_market_context_schema")
    if context_availability_schema != MARKET_CONTEXT_AVAILABILITY_SCHEMA:
        reasons.append("invalid_market_context_availability_schema")
    if not isinstance(market_context, dict) or market_context.get(
        "historical_receipt_time_reconstructed"
    ) is not False:
        reasons.append("invalid_market_context_receipt_semantics")
    if not isinstance(market_context, dict) or market_context.get(
        "funding_interval_schedule_schema"
    ) != FUNDING_INTERVAL_SCHEDULE_SCHEMA_VERSION:
        reasons.append("invalid_market_context_funding_interval_schedule_schema")
    if not isinstance(market_context, dict) or market_context.get(
        "funding_interval_source"
    ) != "instrument_spec_history_point_in_time":
        reasons.append("market_context_funding_interval_history_not_point_in_time")

    context_ablation = metrics.get("market_context_ablation")
    ablation_schema = (
        context_ablation.get("schema") if isinstance(context_ablation, dict) else None
    )
    ablation_benefit = finite_or_none(
        context_ablation.get("log_loss_benefit")
        if isinstance(context_ablation, dict)
        else None
    )
    ablation_tolerance = finite_or_none(
        context_ablation.get("noninferiority_tolerance")
        if isinstance(context_ablation, dict)
        else None
    )
    if ablation_schema != MARKET_CONTEXT_ABLATION_SCHEMA_VERSION:
        reasons.append("invalid_market_context_ablation_schema")
    if ablation_benefit is None or ablation_tolerance is None or ablation_tolerance < 0:
        reasons.append("invalid_market_context_ablation_evidence")
    elif ablation_benefit < -ablation_tolerance:
        reasons.append("market_context_ablation_regression")
    context_noninferior_folds = finite_or_none(
        metrics.get("walk_forward_market_context_noninferior_folds")
    )
    if (
        context_noninferior_folds is None
        or not context_noninferior_folds.is_integer()
        or int(context_noninferior_folds) < 2
    ):
        reasons.append("market_context_walk_forward_instability")

    drift_reference = metrics.get("production_drift_reference")
    try:
        validated_drift_reference = validate_production_drift_reference(drift_reference)
    except (TypeError, ValueError):
        validated_drift_reference = None
        reasons.append("invalid_production_drift_reference")
    if (
        validated_drift_reference is not None
        and validated_drift_reference.get("schema") != PRODUCTION_DRIFT_REFERENCE_SCHEMA
    ):
        reasons.append("invalid_production_drift_reference_schema")
    if (
        validated_drift_reference is not None
        and (validated_drift_reference.get("calibration") or {}).get("schema")
        != PRODUCTION_DRIFT_CALIBRATION_COHORT_SCHEMA
    ):
        reasons.append("invalid_production_drift_calibration_cohort")

    margin_path = metrics.get("intrahorizon_margin_path")
    margin_schema = margin_path.get("schema") if isinstance(margin_path, dict) else None
    margin_status = margin_path.get("status") if isinstance(margin_path, dict) else None
    margin_leverage = finite_or_none(
        margin_path.get("research_leverage") if isinstance(margin_path, dict) else None
    )
    margin_reserve = finite_or_none(
        margin_path.get("equity_reserve_fraction") if isinstance(margin_path, dict) else None
    )
    if margin_schema != INTRAHORIZON_MARGIN_SCHEMA_VERSION:
        reasons.append("invalid_intrahorizon_margin_schema")
    if margin_status != "complete":
        reasons.append("intrahorizon_margin_path_incomplete")
    if (
        margin_leverage is None
        or not margin_leverage.is_integer()
        or int(margin_leverage) != settings.default_leverage
    ):
        reasons.append("intrahorizon_research_leverage_mismatch")
    if margin_reserve is None or not math.isclose(
        margin_reserve,
        DEFAULT_EQUITY_RESERVE_FRACTION,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        reasons.append("intrahorizon_liquidation_reserve_mismatch")
    if metrics.get("policy_intrahorizon_margin_schema") != INTRAHORIZON_MARGIN_SCHEMA_VERSION:
        reasons.append("policy_intrahorizon_margin_schema_mismatch")
    if metrics.get("policy_intrahorizon_margin_complete") is not True:
        reasons.append("policy_intrahorizon_margin_incomplete")
    policy_research_leverage = finite_or_none(metrics.get("policy_research_leverage"))
    if (
        policy_research_leverage is None
        or not policy_research_leverage.is_integer()
        or int(policy_research_leverage) != settings.default_leverage
    ):
        reasons.append("policy_research_leverage_mismatch")
    policy_reserve = finite_or_none(metrics.get("policy_liquidation_equity_reserve_fraction"))
    if policy_reserve is None or not math.isclose(
        policy_reserve,
        DEFAULT_EQUITY_RESERVE_FRACTION,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        reasons.append("policy_liquidation_reserve_mismatch")
    policy_liquidation_events = nonnegative_int_metric("policy_liquidation_events")
    policy_liquidation_rate = finite_or_none(metrics.get("policy_liquidation_rate"))
    if policy_liquidation_rate is None or not 0.0 <= policy_liquidation_rate <= 1.0:
        reasons.append("missing_or_invalid_policy_liquidation_rate")

    walk_forward_schema = metrics.get("walk_forward_schema")
    walk_forward_requested = finite_or_none(metrics.get("walk_forward_folds_requested"))
    walk_forward_completed = finite_or_none(metrics.get("walk_forward_folds_completed"))
    walk_forward_results = metrics.get("walk_forward_fold_results")
    walk_forward_positive_skill_folds = 0
    walk_forward_positive_policy_folds = 0
    walk_forward_skill_fraction = 0.0
    walk_forward_policy_fraction = 0.0
    walk_forward_max_log_loss: float | None = None
    walk_forward_max_brier: float | None = None
    valid_walk_forward = True
    if walk_forward_schema != WALK_FORWARD_SCHEMA_VERSION:
        reasons.append("invalid_walk_forward_schema")
        valid_walk_forward = False
    if (
        walk_forward_requested is None
        or not walk_forward_requested.is_integer()
        or int(walk_forward_requested) != DEFAULT_WALK_FORWARD_FOLDS
    ):
        reasons.append("invalid_walk_forward_fold_count")
        valid_walk_forward = False
    if (
        walk_forward_completed is None
        or not walk_forward_completed.is_integer()
        or int(walk_forward_completed) != DEFAULT_WALK_FORWARD_FOLDS
    ):
        reasons.append("incomplete_walk_forward_validation")
        valid_walk_forward = False
    if not isinstance(walk_forward_results, list) or len(walk_forward_results) != DEFAULT_WALK_FORWARD_FOLDS:
        reasons.append("invalid_walk_forward_fold_results")
        valid_walk_forward = False
        walk_forward_results = []

    prior_test_end: pd.Timestamp | None = None
    fold_log_losses: list[float] = []
    fold_briers: list[float] = []
    for expected_fold, fold_result in enumerate(walk_forward_results, start=1):
        if not isinstance(fold_result, dict):
            valid_walk_forward = False
            continue
        fold_number = finite_or_none(fold_result.get("fold"))
        fold_rows = finite_or_none(fold_result.get("test_rows"))
        fold_log_loss = finite_or_none(fold_result.get("log_loss"))
        fold_prior_log_loss = finite_or_none(fold_result.get("class_prior_log_loss"))
        fold_skill = finite_or_none(fold_result.get("log_loss_skill_vs_prior"))
        fold_brier = finite_or_none(fold_result.get("multiclass_brier"))
        fold_policy_mean = finite_or_none(fold_result.get("policy_realized_mean_r"))
        try:
            fold_test_start = pd.Timestamp(fold_result.get("test_start_time"))
            fold_test_end = pd.Timestamp(fold_result.get("test_end_time"))
            temporal_valid = (
                fold_test_start.tzinfo is not None
                and fold_test_end.tzinfo is not None
                and fold_test_start <= fold_test_end
                and (prior_test_end is None or fold_test_start > prior_test_end)
            )
        except (TypeError, ValueError):
            temporal_valid = False
            fold_test_end = prior_test_end
        if not temporal_valid:
            valid_walk_forward = False
        else:
            prior_test_end = fold_test_end
        if (
            fold_number is None
            or not fold_number.is_integer()
            or int(fold_number) != expected_fold
            or fold_rows is None
            or not fold_rows.is_integer()
            or fold_rows < 90
            or fold_log_loss is None
            or fold_prior_log_loss is None
            or fold_skill is None
            or fold_brier is None
            or fold_policy_mean is None
        ):
            valid_walk_forward = False
            continue
        if not math.isclose(
            fold_prior_log_loss - fold_log_loss,
            fold_skill,
            rel_tol=1e-7,
            abs_tol=1e-9,
        ):
            valid_walk_forward = False
        fold_log_losses.append(fold_log_loss)
        fold_briers.append(fold_brier)
        walk_forward_positive_skill_folds += int(fold_skill > 0.0)
        walk_forward_positive_policy_folds += int(fold_policy_mean > 0.0)

    if not valid_walk_forward:
        reasons.append("invalid_walk_forward_evidence")
    if len(fold_log_losses) == DEFAULT_WALK_FORWARD_FOLDS:
        walk_forward_max_log_loss = max(fold_log_losses)
        walk_forward_max_brier = max(fold_briers)
        walk_forward_skill_fraction = walk_forward_positive_skill_folds / DEFAULT_WALK_FORWARD_FOLDS
        walk_forward_policy_fraction = walk_forward_positive_policy_folds / DEFAULT_WALK_FORWARD_FOLDS
        if walk_forward_max_log_loss > settings.auto_train_max_log_loss:
            reasons.append("walk_forward_log_loss_above_limit")
        if walk_forward_max_brier > settings.auto_train_max_multiclass_brier:
            reasons.append("walk_forward_multiclass_brier_above_limit")
        if walk_forward_skill_fraction < MIN_WALK_FORWARD_POSITIVE_FRACTION:
            reasons.append("walk_forward_skill_stability_below_minimum")
        if walk_forward_policy_fraction < MIN_WALK_FORWARD_POSITIVE_FRACTION:
            reasons.append("walk_forward_policy_stability_below_minimum")

    class_distribution = metrics.get("class_distribution")
    required_classes = {"TP", "SL", "TIMEOUT"}
    distribution_values: list[float] = []
    valid_distribution = isinstance(class_distribution, dict) and set(class_distribution) == required_classes
    if valid_distribution:
        for label in ("TP", "SL", "TIMEOUT"):
            value = finite_or_none(class_distribution.get(label))
            if value is None or not 0.0 <= value <= 1.0:
                valid_distribution = False
                break
            distribution_values.append(value)
    if valid_distribution and not math.isclose(sum(distribution_values), 1.0, rel_tol=1e-7, abs_tol=1e-9):
        valid_distribution = False
    if not valid_distribution:
        reasons.append("invalid_holdout_class_distribution")
        min_class_fraction = 0.0
    else:
        min_class_fraction = min(distribution_values)
    policy_candidates = nonnegative_int_metric("policy_candidates")
    policy_trades = nonnegative_int_metric("policy_trades")
    if policy_liquidation_events > policy_trades:
        reasons.append("policy_liquidation_events_exceed_trades")
    if (
        policy_liquidation_rate is not None
        and policy_trades > 0
        and not math.isclose(
            policy_liquidation_rate,
            policy_liquidation_events / policy_trades,
            rel_tol=1e-9,
            abs_tol=1e-12,
        )
    ):
        reasons.append("inconsistent_policy_liquidation_rate")
    if policy_trades == 0 and policy_liquidation_rate not in (None, 0.0):
        reasons.append("nonzero_policy_liquidation_rate_without_trades")
    policy_trade_rate = finite_or_none(metrics.get("policy_trade_rate"))
    valid_policy_trade_rate = policy_trade_rate is not None and 0.0 <= policy_trade_rate <= 1.0
    if policy_trade_rate is None:
        reasons.append("missing_or_non_finite_policy_trade_rate")
    elif not valid_policy_trade_rate:
        reasons.append("invalid_policy_trade_rate")
    if policy_trades > policy_candidates:
        reasons.append("policy_trades_exceed_candidates")
    if valid_policy_trade_rate:
        expected_policy_trade_rate = policy_trades / policy_candidates if policy_candidates else 0.0
        if not math.isclose(
            policy_trade_rate,
            expected_policy_trade_rate,
            rel_tol=1e-7,
            abs_tol=1e-12,
        ):
            reasons.append("inconsistent_policy_trade_rate")
    policy_cohorts = nonnegative_int_metric("policy_cohorts")
    policy_trade_cohorts = nonnegative_int_metric("policy_trade_cohorts")
    policy_no_trade_cohorts = nonnegative_int_metric("policy_no_trade_cohorts")
    if policy_cohorts > policy_candidates:
        reasons.append("policy_cohorts_exceed_candidates")
    if policy_trade_cohorts > policy_cohorts:
        reasons.append("policy_trade_cohorts_exceed_cohorts")
    if policy_trade_cohorts > policy_trades:
        reasons.append("policy_trade_cohorts_exceed_trades")
    if policy_no_trade_cohorts != policy_cohorts - policy_trade_cohorts:
        reasons.append("inconsistent_policy_no_trade_cohorts")
    if policy_candidates > 0 and policy_cohorts == 0:
        reasons.append("missing_policy_opportunity_cohorts")
    policy_independent_cohorts = nonnegative_int_metric("policy_independent_cohorts")
    policy_horizon_phase_count = nonnegative_int_metric("policy_horizon_phase_count")
    policy_horizon_phase_expected = nonnegative_int_metric("policy_horizon_phase_expected")
    policy_independent_mean_r = finite_or_none(metrics.get("policy_independent_mean_r"))
    policy_mean_r_lcb = finite_or_none(metrics.get("policy_mean_r_lcb"))
    policy_confidence_level = finite_or_none(metrics.get("policy_mean_r_confidence_level"))
    policy_bootstrap_samples = nonnegative_int_metric("policy_mean_r_bootstrap_samples")
    policy_bootstrap_block_length = nonnegative_int_metric("policy_mean_r_bootstrap_block_length")
    if metrics.get("policy_mean_r_uncertainty_schema") != POLICY_UNCERTAINTY_SCHEMA:
        reasons.append("invalid_policy_mean_r_uncertainty_schema")
    if policy_independent_cohorts > 0 and policy_independent_mean_r is None:
        reasons.append("missing_or_non_finite_policy_independent_mean_r")
    if policy_independent_cohorts > 1 and policy_mean_r_lcb is None:
        reasons.append("missing_or_non_finite_policy_mean_r_lcb")
    if policy_confidence_level is None or not math.isclose(
        policy_confidence_level,
        settings.auto_train_policy_confidence_level,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        reasons.append("policy_mean_r_confidence_level_mismatch")
    if policy_bootstrap_samples != settings.auto_train_policy_bootstrap_samples:
        reasons.append("policy_mean_r_bootstrap_samples_mismatch")
    if (
        policy_independent_cohorts > 1
        and not 1 <= policy_bootstrap_block_length <= policy_independent_cohorts
    ):
        reasons.append("invalid_policy_mean_r_bootstrap_block_length")
    if (
        policy_mean_r_lcb is not None
        and policy_independent_mean_r is not None
        and policy_mean_r_lcb > policy_independent_mean_r + 1e-12
    ):
        reasons.append("policy_mean_r_lcb_exceeds_independent_mean")
    policy_mean_r = finite_or_none(metrics.get("policy_realized_mean_r"))
    policy_profit_factor = finite_or_none(metrics.get("policy_profit_factor"))
    policy_profit_factor_unbounded = metrics.get("policy_profit_factor_unbounded") is True
    policy_gross_gain_r = finite_or_none(metrics.get("policy_gross_gain_r"))
    policy_gross_loss_r = finite_or_none(metrics.get("policy_gross_loss_r"))
    valid_unbounded_profit_factor = (
        policy_profit_factor is None
        and policy_profit_factor_unbounded
        and policy_gross_gain_r is not None
        and policy_gross_gain_r > 0.0
        and policy_gross_loss_r == 0.0
    )
    policy_drawdown = finite_or_none(metrics.get("policy_max_drawdown_r"))
    policy_mean_r_check = policy_mean_r if policy_mean_r is not None else -math.inf
    policy_profit_factor_check = (
        policy_profit_factor
        if policy_profit_factor is not None
        else math.inf
        if valid_unbounded_profit_factor
        else -math.inf
    )
    policy_drawdown_check = policy_drawdown if policy_drawdown is not None else math.inf
    expected_policy_schema = POLICY_METRIC_SCHEMA
    if metrics.get("policy_metric_schema") != expected_policy_schema:
        reasons.append("invalid_policy_metric_schema")
    policy_horizon = finite_or_none(metrics.get("policy_horizon_hours"))
    policy_sleeves = finite_or_none(metrics.get("policy_capital_sleeves"))
    if policy_horizon is None or not policy_horizon.is_integer() or int(policy_horizon) != candidate.horizon:
        reasons.append("policy_horizon_mismatch")
    if policy_sleeves is None or not policy_sleeves.is_integer() or int(policy_sleeves) != candidate.horizon:
        reasons.append("policy_capital_sleeves_mismatch")
    if policy_horizon_phase_expected != candidate.horizon:
        reasons.append("policy_horizon_phase_expected_mismatch")
    if policy_horizon_phase_count != policy_horizon_phase_expected:
        reasons.append("incomplete_policy_horizon_phase_coverage")

    if rows < settings.auto_train_min_holdout_rows:
        reasons.append("holdout_rows_below_minimum")
    if holdout_span_check < settings.auto_train_min_holdout_span_hours:
        reasons.append("holdout_span_below_minimum")
    if log_loss_check > settings.auto_train_max_log_loss:
        reasons.append("log_loss_above_limit")
    if log_loss_skill_check <= 0.0:
        reasons.append("log_loss_skill_vs_prior_not_positive")
    if (
        log_loss_value is not None
        and class_prior_log_loss_value is not None
        and log_loss_skill_value is not None
        and not math.isclose(
            class_prior_log_loss_value - log_loss_value,
            log_loss_skill_value,
            rel_tol=1e-7,
            abs_tol=1e-9,
        )
    ):
        reasons.append("inconsistent_log_loss_skill_vs_prior")
    if brier_check > settings.auto_train_max_multiclass_brier:
        reasons.append("multiclass_brier_above_limit")
    if max_ece_check > settings.auto_train_max_ece:
        reasons.append("calibration_error_above_limit")
    if min_class_fraction < settings.auto_train_min_class_fraction:
        reasons.append("holdout_class_fraction_below_minimum")
    if policy_trades < settings.auto_train_min_policy_trades:
        reasons.append("policy_trade_count_below_minimum")
    if not valid_policy_trade_rate or policy_trade_rate < settings.auto_train_min_policy_trade_rate:
        reasons.append("policy_trade_rate_below_minimum")
    if policy_independent_cohorts < settings.auto_train_min_policy_cohorts:
        reasons.append("policy_independent_cohort_count_below_minimum")
    if policy_mean_r_check < settings.auto_train_min_policy_realized_mean_r:
        reasons.append("policy_realized_mean_r_below_minimum")
    if policy_mean_r_lcb is None or policy_mean_r_lcb <= settings.auto_train_min_policy_mean_r_lcb:
        reasons.append("policy_mean_r_lcb_not_above_minimum")
    if policy_profit_factor_check < settings.auto_train_min_policy_profit_factor:
        reasons.append("policy_profit_factor_below_minimum")
    if policy_drawdown_check > settings.auto_train_max_policy_drawdown_r:
        reasons.append("policy_drawdown_above_limit")

    relative: dict[str, Any] | None = None
    incumbent = candidate.incumbent_metrics
    if incumbent and "comparison_skipped" in incumbent:
        reasons.append("incumbent_comparison_unavailable")
        relative = {
            "incumbent_version": candidate.incumbent_version,
            **incumbent,
        }
    elif incumbent:
        incumbent_log_loss = finite_or_none(incumbent.get("log_loss"))
        incumbent_brier = finite_or_none(incumbent.get("multiclass_brier"))
        incumbent_policy_trades_value = finite_or_none(incumbent.get("policy_trades"))
        incumbent_policy_cohorts_value = finite_or_none(incumbent.get("policy_cohorts"))
        incumbent_policy_trade_cohorts_value = finite_or_none(
            incumbent.get("policy_trade_cohorts")
        )
        incumbent_policy_no_trade_cohorts_value = finite_or_none(
            incumbent.get("policy_no_trade_cohorts")
        )
        incumbent_policy_independent_cohorts_value = finite_or_none(
            incumbent.get("policy_independent_cohorts")
        )
        incumbent_policy_trades = (
            int(incumbent_policy_trades_value)
            if incumbent_policy_trades_value is not None
            and incumbent_policy_trades_value >= 0
            and incumbent_policy_trades_value.is_integer()
            else None
        )
        incumbent_policy_cohorts = (
            int(incumbent_policy_cohorts_value)
            if incumbent_policy_cohorts_value is not None
            and incumbent_policy_cohorts_value >= 0
            and incumbent_policy_cohorts_value.is_integer()
            else None
        )
        incumbent_policy_trade_cohorts = (
            int(incumbent_policy_trade_cohorts_value)
            if incumbent_policy_trade_cohorts_value is not None
            and incumbent_policy_trade_cohorts_value >= 0
            and incumbent_policy_trade_cohorts_value.is_integer()
            else None
        )
        incumbent_policy_no_trade_cohorts = (
            int(incumbent_policy_no_trade_cohorts_value)
            if incumbent_policy_no_trade_cohorts_value is not None
            and incumbent_policy_no_trade_cohorts_value >= 0
            and incumbent_policy_no_trade_cohorts_value.is_integer()
            else None
        )
        incumbent_policy_independent_cohorts = (
            int(incumbent_policy_independent_cohorts_value)
            if incumbent_policy_independent_cohorts_value is not None
            and incumbent_policy_independent_cohorts_value >= 0
            and incumbent_policy_independent_cohorts_value.is_integer()
            else None
        )
        incumbent_policy_mean_r = finite_or_none(incumbent.get("policy_realized_mean_r"))
        incumbent_policy_mean_r_lcb = finite_or_none(incumbent.get("policy_mean_r_lcb"))
        incumbent_policy_drawdown = finite_or_none(incumbent.get("policy_max_drawdown_r"))
        incumbent_policy_schema = incumbent.get("policy_metric_schema")
        incumbent_policy_horizon = finite_or_none(incumbent.get("policy_horizon_hours"))
        incumbent_policy_sleeves = finite_or_none(incumbent.get("policy_capital_sleeves"))
        invalid_incumbent_fields = [
            name
            for name, value in (
                ("log_loss", incumbent_log_loss),
                ("multiclass_brier", incumbent_brier),
                ("policy_trades", incumbent_policy_trades),
                ("policy_cohorts", incumbent_policy_cohorts),
                ("policy_trade_cohorts", incumbent_policy_trade_cohorts),
                ("policy_no_trade_cohorts", incumbent_policy_no_trade_cohorts),
                ("policy_independent_cohorts", incumbent_policy_independent_cohorts),
            )
            if value is None
        ]
        if incumbent_policy_schema != expected_policy_schema:
            invalid_incumbent_fields.append("policy_metric_schema")
        if incumbent.get("policy_mean_r_uncertainty_schema") != POLICY_UNCERTAINTY_SCHEMA:
            invalid_incumbent_fields.append("policy_mean_r_uncertainty_schema")
        if (
            incumbent_policy_trade_cohorts is not None
            and incumbent_policy_cohorts is not None
            and incumbent_policy_trade_cohorts > incumbent_policy_cohorts
        ):
            invalid_incumbent_fields.append("policy_trade_cohorts")
        if (
            incumbent_policy_trade_cohorts is not None
            and incumbent_policy_trades is not None
            and incumbent_policy_trade_cohorts > incumbent_policy_trades
        ):
            invalid_incumbent_fields.append("policy_trade_cohorts")
        if (
            incumbent_policy_no_trade_cohorts is not None
            and incumbent_policy_cohorts is not None
            and incumbent_policy_trade_cohorts is not None
            and incumbent_policy_no_trade_cohorts
            != incumbent_policy_cohorts - incumbent_policy_trade_cohorts
        ):
            invalid_incumbent_fields.append("policy_no_trade_cohorts")
        if (
            incumbent_policy_horizon is None
            or not incumbent_policy_horizon.is_integer()
            or int(incumbent_policy_horizon) != candidate.horizon
        ):
            invalid_incumbent_fields.append("policy_horizon_hours")
        if (
            incumbent_policy_sleeves is None
            or not incumbent_policy_sleeves.is_integer()
            or int(incumbent_policy_sleeves) != candidate.horizon
        ):
            invalid_incumbent_fields.append("policy_capital_sleeves")
        if incumbent_policy_cohorts is not None and incumbent_policy_cohorts > 0:
            if incumbent_policy_mean_r is None:
                invalid_incumbent_fields.append("policy_realized_mean_r")
            if incumbent_policy_drawdown is None:
                invalid_incumbent_fields.append("policy_max_drawdown_r")
        if (
            incumbent_policy_independent_cohorts is not None
            and incumbent_policy_independent_cohorts > 1
            and incumbent_policy_mean_r_lcb is None
        ):
            invalid_incumbent_fields.append("policy_mean_r_lcb")
        if invalid_incumbent_fields:
            reasons.append("invalid_incumbent_metrics")
            relative = {
                "incumbent_version": candidate.incumbent_version,
                "invalid_fields": invalid_incumbent_fields,
            }
        else:
            assert incumbent_log_loss is not None
            assert incumbent_brier is not None
            incumbent_policy_mean_r_check = (
                incumbent_policy_mean_r if incumbent_policy_mean_r is not None else -math.inf
            )
            incumbent_policy_drawdown_check = (
                incumbent_policy_drawdown if incumbent_policy_drawdown is not None else math.inf
            )
            log_loss_delta_check = log_loss_check - incumbent_log_loss
            brier_delta_check = brier_check - incumbent_brier
            policy_mean_r_delta_check = policy_mean_r_check - incumbent_policy_mean_r_check
            policy_drawdown_delta_check = policy_drawdown_check - incumbent_policy_drawdown_check
            log_loss_delta = finite_or_none(log_loss_delta_check)
            brier_delta = finite_or_none(brier_delta_check)
            policy_mean_r_delta = finite_or_none(policy_mean_r_delta_check)
            policy_drawdown_delta = finite_or_none(policy_drawdown_delta_check)
            ml_improved = (
                log_loss_delta_check <= -settings.auto_train_min_metric_improvement
                or brier_delta_check <= -settings.auto_train_min_metric_improvement
            )
            policy_improved = policy_mean_r_delta_check >= settings.auto_train_min_policy_improvement_r
            improved = ml_improved or policy_improved
            if log_loss_delta_check > settings.auto_train_max_log_loss_regression:
                reasons.append("log_loss_regressed_vs_incumbent")
            if brier_delta_check > settings.auto_train_max_brier_regression:
                reasons.append("multiclass_brier_regressed_vs_incumbent")
            if policy_mean_r_delta_check < -settings.auto_train_max_policy_mean_r_regression:
                reasons.append("policy_mean_r_regressed_vs_incumbent")
            if policy_drawdown_delta_check > settings.auto_train_max_policy_drawdown_regression_r:
                reasons.append("policy_drawdown_regressed_vs_incumbent")
            if settings.auto_train_require_improvement and not improved:
                reasons.append("no_required_improvement_vs_incumbent")
            relative = {
                "incumbent_version": candidate.incumbent_version,
                "candidate_log_loss": log_loss_value,
                "incumbent_log_loss": incumbent_log_loss,
                "log_loss_delta": log_loss_delta,
                "candidate_multiclass_brier": brier_value,
                "incumbent_multiclass_brier": incumbent_brier,
                "multiclass_brier_delta": brier_delta,
                "candidate_policy_realized_mean_r": policy_mean_r,
                "incumbent_policy_realized_mean_r": incumbent_policy_mean_r,
                "candidate_policy_mean_r_lcb": policy_mean_r_lcb,
                "incumbent_policy_mean_r_lcb": incumbent_policy_mean_r_lcb,
                "policy_realized_mean_r_delta": policy_mean_r_delta,
                "candidate_policy_max_drawdown_r": policy_drawdown,
                "incumbent_policy_max_drawdown_r": incumbent_policy_drawdown,
                "policy_max_drawdown_r_delta": policy_drawdown_delta,
                "ml_improved": ml_improved,
                "policy_improved": policy_improved,
                "improved": improved,
            }

    result = {
        "passed": not reasons,
        "reasons": reasons,
        "absolute": {
            "market_context_schema": context_schema,
            "expected_market_context_schema": MARKET_CONTEXT_SCHEMA_VERSION,
            "market_context_availability_schema": context_availability_schema,
            "market_context_ablation_schema": ablation_schema,
            "market_context_log_loss_benefit": ablation_benefit,
            "market_context_walk_forward_noninferior_folds": context_noninferior_folds,
            "entry_execution_model_schema": entry_execution_schema,
            "expected_entry_execution_model_schema": ENTRY_EXECUTION_MODEL_SCHEMA,
            "entry_spread_bps": entry_spread_bps,
            "configured_entry_spread_bps": settings.model_entry_spread_bps,
            "intrahorizon_margin_schema": margin_schema,
            "expected_intrahorizon_margin_schema": INTRAHORIZON_MARGIN_SCHEMA_VERSION,
            "intrahorizon_margin_status": margin_status,
            "research_leverage": margin_leverage,
            "configured_research_leverage": settings.default_leverage,
            "liquidation_equity_reserve_fraction": margin_reserve,
            "configured_liquidation_equity_reserve_fraction": (DEFAULT_EQUITY_RESERVE_FRACTION),
            "policy_liquidation_events": policy_liquidation_events,
            "policy_liquidation_rate": policy_liquidation_rate,
            "walk_forward_schema": walk_forward_schema,
            "expected_walk_forward_schema": WALK_FORWARD_SCHEMA_VERSION,
            "walk_forward_folds_requested": walk_forward_requested,
            "walk_forward_folds_completed": walk_forward_completed,
            "walk_forward_positive_skill_folds": walk_forward_positive_skill_folds,
            "walk_forward_positive_skill_fraction": walk_forward_skill_fraction,
            "walk_forward_positive_policy_folds": walk_forward_positive_policy_folds,
            "walk_forward_positive_policy_fraction": walk_forward_policy_fraction,
            "walk_forward_minimum_positive_fraction": MIN_WALK_FORWARD_POSITIVE_FRACTION,
            "walk_forward_max_log_loss": walk_forward_max_log_loss,
            "walk_forward_max_multiclass_brier": walk_forward_max_brier,
            "holdout_rows": rows,
            "min_holdout_rows": settings.auto_train_min_holdout_rows,
            "holdout_span_hours": holdout_span_value,
            "min_holdout_span_hours": settings.auto_train_min_holdout_span_hours,
            "log_loss": log_loss_value,
            "max_log_loss": settings.auto_train_max_log_loss,
            "class_prior_log_loss": class_prior_log_loss_value,
            "log_loss_skill_vs_prior": log_loss_skill_value,
            "required_log_loss_skill_vs_prior": "> 0",
            "multiclass_brier": brier_value,
            "max_multiclass_brier": settings.auto_train_max_multiclass_brier,
            "max_ece": max_ece,
            "max_ece_limit": settings.auto_train_max_ece,
            "min_class_fraction": min_class_fraction,
            "min_class_fraction_limit": settings.auto_train_min_class_fraction,
            "policy_candidates": policy_candidates,
            "policy_trades": policy_trades,
            "policy_trade_rate": policy_trade_rate,
            "min_policy_trade_rate": settings.auto_train_min_policy_trade_rate,
            "policy_cohorts": policy_cohorts,
            "policy_trade_cohorts": policy_trade_cohorts,
            "policy_no_trade_cohorts": policy_no_trade_cohorts,
            "policy_independent_cohorts": policy_independent_cohorts,
            "policy_horizon_phase_count": policy_horizon_phase_count,
            "policy_horizon_phase_expected": policy_horizon_phase_expected,
            "min_policy_trades": settings.auto_train_min_policy_trades,
            "min_policy_cohorts": settings.auto_train_min_policy_cohorts,
            "policy_realized_mean_r": policy_mean_r,
            "min_policy_realized_mean_r": settings.auto_train_min_policy_realized_mean_r,
            "policy_independent_mean_r": policy_independent_mean_r,
            "policy_mean_r_lcb": policy_mean_r_lcb,
            "min_policy_mean_r_lcb": settings.auto_train_min_policy_mean_r_lcb,
            "policy_mean_r_confidence_level": policy_confidence_level,
            "policy_mean_r_bootstrap_samples": policy_bootstrap_samples,
            "policy_mean_r_bootstrap_block_length": policy_bootstrap_block_length,
            "policy_mean_r_uncertainty_schema": metrics.get("policy_mean_r_uncertainty_schema"),
            "policy_profit_factor": policy_profit_factor,
            "policy_profit_factor_unbounded": valid_unbounded_profit_factor,
            "policy_gross_gain_r": policy_gross_gain_r,
            "policy_gross_loss_r": policy_gross_loss_r,
            "min_policy_profit_factor": settings.auto_train_min_policy_profit_factor,
            "policy_max_drawdown_r": policy_drawdown,
            "max_policy_drawdown_r": settings.auto_train_max_policy_drawdown_r,
        },
        "relative": relative,
    }
    return json_compatible(result)


async def register_model_candidate(
    candidate: ModelCandidate,
    *,
    source: str,
    quality_gate: dict[str, Any] | None,
    activation_requested: bool,
    actor: str,
    incumbent_recovery: dict[str, Any] | None = None,
    experiment_promotion_gate: dict[str, Any] | None = None,
) -> ModelRegistry:
    digest = hashlib.sha256(candidate.path.read_bytes()).hexdigest()
    async with SessionFactory() as session, session.begin():
        registry = await _register_model_candidate_in_session(
            session,
            candidate,
            digest=digest,
            source=source,
            quality_gate=quality_gate,
            activation_requested=activation_requested,
            actor=actor,
            incumbent_recovery=incumbent_recovery,
            experiment_promotion_gate=experiment_promotion_gate,
        )
    return registry


def _candidate_registry_metrics(
    candidate: ModelCandidate,
    *,
    source: str,
    quality_gate: dict[str, Any] | None,
    activation_requested: bool,
    incumbent_recovery: dict[str, Any] | None,
    experiment_promotion_gate: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    safe_quality_gate = json_compatible(quality_gate)
    safe_experiment_promotion_gate = json_compatible(experiment_promotion_gate)
    metrics = json_compatible(
        {
            **candidate.metrics,
            "task": "barrier_outcome_v1",
            "horizon_hours": candidate.horizon,
            "stop_atr_multiplier": DEFAULT_STOP_ATR_MULTIPLIER,
            "tp_atr_multiplier": DEFAULT_TP_ATR_MULTIPLIER,
            "source": source,
            "dataset_rows": candidate.dataset_rows,
            "unique_timestamps": candidate.unique_timestamps,
            "symbol_count": candidate.symbol_count,
            "symbol_sample": list(candidate.symbol_sample),
            "training_data_profile": candidate.training_data_profile.to_dict(),
            "incumbent_version": candidate.incumbent_version,
            "incumbent_metrics_same_holdout": candidate.incumbent_metrics,
            "incumbent_recovery": incumbent_recovery,
            "quality_gate": safe_quality_gate,
            "experiment_promotion_gate": safe_experiment_promotion_gate,
            "activation_requested": activation_requested,
        }
    )
    return metrics, safe_quality_gate


async def _register_model_candidate_in_session(
    session,
    candidate: ModelCandidate,
    *,
    digest: str,
    source: str,
    quality_gate: dict[str, Any] | None,
    activation_requested: bool,
    actor: str,
    incumbent_recovery: dict[str, Any] | None,
    experiment_promotion_gate: dict[str, Any] | None,
) -> ModelRegistry:
    metrics, safe_quality_gate = _candidate_registry_metrics(
        candidate,
        source=source,
        quality_gate=quality_gate,
        activation_requested=activation_requested,
        incumbent_recovery=incumbent_recovery,
        experiment_promotion_gate=experiment_promotion_gate,
    )
    registry = ModelRegistry(
        name=f"Hourly direction-conditional barrier {candidate.model_type} h{candidate.horizon}",
        version=candidate.version,
        model_type=f"barrier_{candidate.model_type}",
        artifact_path=str(candidate.path),
        artifact_sha256=digest,
        feature_schema_version=candidate.feature_schema_version,
        calibration_version=f"sigmoid-ovr-{candidate.version}",
        training_start=candidate.training_start,
        training_end=candidate.training_end,
        metrics=metrics,
        active=False,
    )
    session.add(registry)
    await session.flush()
    event_type = "MODEL_CANDIDATE_TRAINED"
    await append_audit_event(
        session,
        event_type=event_type,
        entity_type="model_registry",
        entity_id=str(registry.id),
        actor=actor,
        payload={
            "version": candidate.version,
            "source": source,
            "quality_gate": safe_quality_gate,
            "experiment_promotion_gate": json_compatible(experiment_promotion_gate),
            "activation_requested": activation_requested,
            "incumbent_recovery": json_compatible(incumbent_recovery),
        },
    )
    await publish_outbox(
        session,
        event_type=event_type,
        aggregate_type="model_registry",
        aggregate_id=str(registry.id),
        payload={"version": candidate.version, "source": source},
    )
    return registry


def _validate_candidate_artifact_for_activation(
    candidate: ModelCandidate,
    *,
    digest: str,
    expected_horizon_hours: int,
) -> dict[str, object]:
    runtime = ModelRuntime(candidate.path, allow_baseline=False)
    runtime.load(
        expected_sha256=digest,
        expected_version=candidate.version,
        source="model_candidate_atomic_activation",
    )
    if runtime.horizon_hours != expected_horizon_hours:
        raise RuntimeError(
            f"Model horizon {runtime.horizon_hours} does not match expected horizon {expected_horizon_hours}"
        )
    return runtime.metadata()


async def register_and_activate_model_candidate(
    candidate: ModelCandidate,
    *,
    source: str,
    quality_gate: dict[str, Any] | None,
    experiment_promotion_gate: dict[str, Any] | None = None,
    actor: str,
    expected_previous_version: str | None,
    expected_horizon_hours: int,
    incumbent_recovery: dict[str, Any] | None = None,
) -> tuple[ModelRegistry, dict[str, object]]:
    """Register and activate a new candidate in one PostgreSQL transaction."""

    quality_activation_gate = require_passed_quality_gate(quality_gate)
    digest = hashlib.sha256(candidate.path.read_bytes()).hexdigest()
    experiment_activation_gate = require_passed_experiment_promotion_gate(
        experiment_promotion_gate,
        expected_model_version=candidate.version,
        expected_model_sha256=digest,
        expected_horizon_hours=expected_horizon_hours,
    )
    policy_activation_binding = require_experiment_policy_binding(
        candidate.metrics.get("promotion_policy_binding")
        if isinstance(candidate.metrics, dict)
        else None
    )
    configured_policy_binding = experiment_policy_binding_from_settings(get_settings())
    if policy_activation_binding != configured_policy_binding:
        raise RuntimeError(
            "Model candidate policy evidence does not match current deployment settings"
        )
    experiment_activation_gate = require_passed_experiment_promotion_gate(
        experiment_activation_gate,
        expected_policy_binding=policy_activation_binding,
    )
    runtime_metadata = _validate_candidate_artifact_for_activation(
        candidate,
        digest=digest,
        expected_horizon_hours=expected_horizon_hours,
    )
    experiment_family = str(experiment_activation_gate["experiment_family"])
    async with SessionFactory() as session, session.begin():
        fresh_experiment_gate = await evaluate_experiment_promotion_gate(
            session,
            experiment_family=experiment_family,
            model_version=candidate.version,
            model_sha256=digest,
            horizon_hours=expected_horizon_hours,
            lock_family=True,
            expected_policy_binding=policy_activation_binding,
        )
        experiment_activation_gate = require_passed_experiment_promotion_gate(
            fresh_experiment_gate,
            expected_model_version=candidate.version,
            expected_model_sha256=digest,
            expected_horizon_hours=expected_horizon_hours,
            expected_policy_binding=policy_activation_binding,
        )
        previous = (
            await session.execute(
                select(ModelRegistry)
                .where(ModelRegistry.active.is_(True))
                .order_by(desc(ModelRegistry.updated_at))
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        previous_version = previous.version if previous else None
        if previous_version != expected_previous_version:
            raise RuntimeError(
                "Active model changed while the candidate was being evaluated: "
                f"expected={expected_previous_version}, actual={previous_version}"
            )

        registry = await _register_model_candidate_in_session(
            session,
            candidate,
            digest=digest,
            source=source,
            quality_gate=quality_gate,
            activation_requested=True,
            actor=actor,
            incumbent_recovery=incumbent_recovery,
            experiment_promotion_gate=experiment_activation_gate,
        )
        await session.execute(
            update(ModelRegistry)
            .where(ModelRegistry.active.is_(True), ModelRegistry.id != registry.id)
            .values(active=False)
        )
        registry.active = True
        await session.flush()
        payload: dict[str, object] = {
            "version": registry.version,
            "model_type": registry.model_type,
            "previous_version": (previous.version if previous and previous.id != registry.id else None),
            "expected_previous_version": expected_previous_version,
            "activation_governance": {
                "schema": "model-activation-governance-v2",
                "quality_gate": quality_activation_gate,
                "experiment_promotion_gate": experiment_activation_gate,
                "emergency_gate_override": False,
                "override_reason": None,
            },
            "runtime": runtime_metadata,
        }
        await append_audit_event(
            session,
            event_type="MODEL_ACTIVATED",
            entity_type="model_registry",
            entity_id=str(registry.id),
            actor=actor,
            payload=payload,
        )
        await publish_outbox(
            session,
            event_type="MODEL_ACTIVATED",
            aggregate_type="model_registry",
            aggregate_id=str(registry.id),
            payload={"version": registry.version},
        )
    return registry, payload

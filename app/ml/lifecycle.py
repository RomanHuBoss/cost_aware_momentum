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

from app.config import Settings
from app.db.engine import SessionFactory
from app.db.models import Candle, ModelRegistry, TickerSnapshot
from app.json_utils import json_compatible
from app.ml.data_profile import (
    TrainingDataProfile,
    profile_from_symbol_rows,
    profile_training_frame,
)
from app.ml.runtime import ModelRuntime
from app.ml.training import (
    DEFAULT_STOP_ATR_MULTIPLIER,
    DEFAULT_TP_ATR_MULTIPLIER,
    MODEL_FEATURE_NAMES,
    MODEL_FEATURE_SCHEMA_VERSION,
    PolicyEvaluationConfig,
    TemporalCalibratedBarrierModel,
    chronological_split,
    evaluate_model,
    evaluate_policy_model,
    make_barrier_dataset,
)
from app.services.audit import append_audit_event, publish_outbox


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


def policy_evaluation_config(settings: Settings) -> PolicyEvaluationConfig:
    return PolicyEvaluationConfig(
        fee_rate_round_trip=settings.fee_rate_taker * 2,
        slippage_rate=settings.base_slippage_bps / 10000,
        stop_gap_reserve_rate=settings.stop_gap_reserve_bps / 10000,
        min_net_rr=settings.min_net_rr,
        min_net_ev_r=settings.min_net_ev_r,
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

    ranked_tickers = (
        select(
            TickerSnapshot.symbol.label("symbol"),
            TickerSnapshot.turnover_24h.label("turnover_24h"),
            func.row_number()
            .over(
                partition_by=TickerSnapshot.symbol,
                order_by=TickerSnapshot.source_time.desc(),
            )
            .label("row_number"),
        )
        .subquery()
    )
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
            latest - timedelta(days=lookback_days)
            if lookback_days and lookback_days > 0
            else None
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
            grouped = [
                grouped_by_symbol.get(symbol, (symbol, 0, None, None))
                for symbol in selected_symbols
            ]
        unique_timestamps = int(
            (
                await session.execute(
                    select(func.count(func.distinct(Candle.open_time))).where(*filters)
                )
            ).scalar_one()
            or 0
        )
    return profile_from_symbol_rows(
        grouped,
        unique_timestamps=unique_timestamps,
        minimum_rows_for_coverage=minimum_rows_for_coverage,
    )


async def load_training_candles(
    symbols: list[str] | tuple[str, ...] | None,
    *,
    lookback_days: int | None = None,
    max_symbols: int = 0,
    interval: str = "60",
) -> pd.DataFrame:
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
        rows = (await session.execute(query.order_by(Candle.open_time, Candle.symbol))).scalars().all()

    return pd.DataFrame(
        [
            {
                "symbol": row.symbol,
                "open_time": row.open_time,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume),
                "turnover": float(row.turnover),
            }
            for row in rows
        ]
    )


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


def build_model_candidate(
    candles: pd.DataFrame,
    *,
    horizon: int,
    model_type: str,
    model_dir: Path,
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

    dataset = make_barrier_dataset(candles, horizon=horizon)
    if dataset.empty:
        raise RuntimeError("No direction-specific barrier labels could be built from PostgreSQL candles")
    split = chronological_split(dataset, purge_rows=horizon)

    model = TemporalCalibratedBarrierModel(model_type).fit(
        split.x_train,
        split.y_train,
        split.x_cal,
        split.y_cal,
    )
    metrics = evaluate_model(model, split)
    label_data_end = _as_datetime(dataset.label_end_time.max())
    metrics["temporal_split_schema"] = "label-end-purged-v2"
    metrics["feature_schema_version"] = MODEL_FEATURE_SCHEMA_VERSION
    metrics["hourly_continuity"] = json_compatible(
        dataset.attrs.get("hourly_continuity") or {}
    )
    metrics["label_data_end"] = label_data_end.isoformat()
    if policy_config is not None:
        metrics.update(evaluate_policy_model(model, split, policy_config))

    incumbent_metrics: dict[str, Any] | None = None
    if incumbent and incumbent.is_artifact_model:
        try:
            runtime = ModelRuntime(Path(incumbent.artifact_path or ""), allow_baseline=False)
            runtime.load(
                expected_sha256=incumbent.artifact_sha256,
                expected_version=incumbent.version,
                source="training_benchmark",
            )
            if runtime.horizon_hours == horizon and runtime.bundle is not None:
                incumbent_metrics = evaluate_model(runtime.bundle["model"], split)
                if policy_config is not None:
                    incumbent_metrics.update(
                        evaluate_policy_model(runtime.bundle["model"], split, policy_config)
                    )
            else:
                incumbent_metrics = {
                    "comparison_skipped": "incumbent_horizon_mismatch",
                    "incumbent_horizon_hours": runtime.horizon_hours,
                }
        except Exception as exc:
            incumbent_metrics = {
                "comparison_skipped": "incumbent_load_or_evaluation_failed",
                "error": str(exc),
            }

    created_at = datetime.now(UTC)
    generated_version = version or (
        f"barrier-{model_type}-h{horizon}-{created_at:%Y%m%dT%H%M%SZ}"
    )
    target = (output or model_dir / f"{generated_version}.joblib").expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    training_start = _as_datetime(dataset.open_time.min())
    training_end = _as_datetime(dataset.open_time.max())
    unique_timestamps = int(dataset["open_time"].nunique())
    symbol_values = tuple(sorted(str(item) for item in dataset["symbol"].unique()))
    training_data_profile = profile_training_frame(
        candles,
        label_cutoff=training_end,
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
        "temporal_split_schema": "label-end-purged-v2",
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

    rows = int(metrics.get("rows", 0) or 0)
    log_loss_value, log_loss_check = required_metric("log_loss")
    brier_value, brier_check = required_metric("multiclass_brier")
    ece_pairs = [
        required_metric("ece_tp"),
        required_metric("ece_sl"),
        required_metric("ece_timeout"),
    ]
    ece_values = [value for value, _ in ece_pairs]
    max_ece = max(value for value in ece_values if value is not None) if all(
        value is not None for value in ece_values
    ) else None
    max_ece_check = max(check for _, check in ece_pairs)

    class_distribution = metrics.get("class_distribution") or {}
    min_class_fraction = min(
        (float(class_distribution.get(label, 0.0)) for label in ("TP", "SL", "TIMEOUT")),
        default=0.0,
    )
    policy_trades = int(metrics.get("policy_trades", 0) or 0)
    policy_mean_r = finite_or_none(metrics.get("policy_realized_mean_r"))
    policy_profit_factor = finite_or_none(metrics.get("policy_profit_factor"))
    policy_drawdown = finite_or_none(metrics.get("policy_max_drawdown_r"))
    policy_mean_r_check = policy_mean_r if policy_mean_r is not None else -math.inf
    policy_profit_factor_check = (
        policy_profit_factor if policy_profit_factor is not None else -math.inf
    )
    policy_drawdown_check = policy_drawdown if policy_drawdown is not None else math.inf

    if rows < settings.auto_train_min_holdout_rows:
        reasons.append("holdout_rows_below_minimum")
    if log_loss_check > settings.auto_train_max_log_loss:
        reasons.append("log_loss_above_limit")
    if brier_check > settings.auto_train_max_multiclass_brier:
        reasons.append("multiclass_brier_above_limit")
    if max_ece_check > settings.auto_train_max_ece:
        reasons.append("calibration_error_above_limit")
    if min_class_fraction < settings.auto_train_min_class_fraction:
        reasons.append("holdout_class_fraction_below_minimum")
    if policy_trades < settings.auto_train_min_policy_trades:
        reasons.append("policy_trade_count_below_minimum")
    if policy_mean_r_check < settings.auto_train_min_policy_realized_mean_r:
        reasons.append("policy_realized_mean_r_below_minimum")
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
        incumbent_log_loss = float(incumbent["log_loss"])
        incumbent_brier = float(incumbent["multiclass_brier"])
        incumbent_policy_mean_r = finite_or_none(incumbent.get("policy_realized_mean_r"))
        incumbent_policy_drawdown = finite_or_none(incumbent.get("policy_max_drawdown_r"))
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
        policy_improved = (
            policy_mean_r_delta_check >= settings.auto_train_min_policy_improvement_r
        )
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
            "holdout_rows": rows,
            "min_holdout_rows": settings.auto_train_min_holdout_rows,
            "log_loss": log_loss_value,
            "max_log_loss": settings.auto_train_max_log_loss,
            "multiclass_brier": brier_value,
            "max_multiclass_brier": settings.auto_train_max_multiclass_brier,
            "max_ece": max_ece,
            "max_ece_limit": settings.auto_train_max_ece,
            "min_class_fraction": min_class_fraction,
            "min_class_fraction_limit": settings.auto_train_min_class_fraction,
            "policy_trades": policy_trades,
            "min_policy_trades": settings.auto_train_min_policy_trades,
            "policy_realized_mean_r": policy_mean_r,
            "min_policy_realized_mean_r": settings.auto_train_min_policy_realized_mean_r,
            "policy_profit_factor": policy_profit_factor,
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
        )
    return registry


def _candidate_registry_metrics(
    candidate: ModelCandidate,
    *,
    source: str,
    quality_gate: dict[str, Any] | None,
    activation_requested: bool,
    incumbent_recovery: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    safe_quality_gate = json_compatible(quality_gate)
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
) -> ModelRegistry:
    metrics, safe_quality_gate = _candidate_registry_metrics(
        candidate,
        source=source,
        quality_gate=quality_gate,
        activation_requested=activation_requested,
        incumbent_recovery=incumbent_recovery,
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
            f"Model horizon {runtime.horizon_hours} does not match "
            f"expected horizon {expected_horizon_hours}"
        )
    return runtime.metadata()


async def register_and_activate_model_candidate(
    candidate: ModelCandidate,
    *,
    source: str,
    quality_gate: dict[str, Any] | None,
    actor: str,
    expected_previous_version: str | None,
    expected_horizon_hours: int,
    incumbent_recovery: dict[str, Any] | None = None,
) -> tuple[ModelRegistry, dict[str, object]]:
    """Register and activate a new candidate in one PostgreSQL transaction."""

    digest = hashlib.sha256(candidate.path.read_bytes()).hexdigest()
    runtime_metadata = _validate_candidate_artifact_for_activation(
        candidate,
        digest=digest,
        expected_horizon_hours=expected_horizon_hours,
    )
    async with SessionFactory() as session, session.begin():
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
            "previous_version": (
                previous.version if previous and previous.id != registry.id else None
            ),
            "expected_previous_version": expected_previous_version,
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

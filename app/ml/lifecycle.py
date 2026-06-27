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
from sqlalchemy import desc, func, select

from app.config import Settings
from app.db.engine import SessionFactory
from app.db.models import Candle, ModelRegistry, TickerSnapshot
from app.ml.runtime import ModelRuntime
from app.ml.training import (
    DEFAULT_STOP_ATR_MULTIPLIER,
    DEFAULT_TP_ATR_MULTIPLIER,
    MODEL_FEATURE_NAMES,
    TemporalCalibratedBarrierModel,
    chronological_split,
    evaluate_model,
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
    metrics: dict[str, Any]
    incumbent_metrics: dict[str, Any] | None
    incumbent_version: str | None


def _as_datetime(value: object) -> datetime:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if not isinstance(value, datetime):
        raise TypeError(f"Expected datetime-like value, got {type(value)!r}")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def load_training_candles(
    symbols: list[str] | tuple[str, ...] | None,
    *,
    lookback_days: int | None = None,
    max_symbols: int = 0,
    interval: str = "60",
) -> pd.DataFrame:
    cutoff = None
    if lookback_days and lookback_days > 0:
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)

    async with SessionFactory() as session:
        selected_symbols = list(symbols) if symbols else []
        if not selected_symbols and max_symbols > 0:
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
            if not selected_symbols:
                selected_symbols = list(
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
    bundle = {
        "task": "barrier_outcome_v1",
        "model": model,
        "model_type": model_type,
        "version": generated_version,
        "calibration_version": f"sigmoid-ovr-{generated_version}",
        "feature_names": MODEL_FEATURE_NAMES,
        "feature_schema_version": "hourly-barrier-v1",
        "horizon_hours": horizon,
        "stop_atr_multiplier": DEFAULT_STOP_ATR_MULTIPLIER,
        "tp_atr_multiplier": DEFAULT_TP_ATR_MULTIPLIER,
        "metrics": metrics,
        "training_start": training_start.isoformat(),
        "training_end": training_end.isoformat(),
        "dataset_rows": int(len(dataset)),
        "unique_timestamps": unique_timestamps,
        "symbol_count": len(symbol_values),
        "symbol_sample": list(symbol_values[:25]),
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
        metrics=metrics,
        incumbent_metrics=incumbent_metrics,
        incumbent_version=incumbent.version if incumbent else None,
    )


def evaluate_quality_gate(candidate: ModelCandidate, settings: Settings) -> dict[str, Any]:
    metrics = candidate.metrics
    reasons: list[str] = []

    def finite_metric(name: str) -> float:
        value = metrics.get(name)
        if value is None or not math.isfinite(float(value)):
            reasons.append(f"missing_or_non_finite_{name}")
            return math.inf
        return float(value)

    rows = int(metrics.get("rows", 0))
    log_loss_value = finite_metric("log_loss")
    brier_value = finite_metric("multiclass_brier")
    ece_values = [
        finite_metric("ece_tp"),
        finite_metric("ece_sl"),
        finite_metric("ece_timeout"),
    ]
    max_ece = max(ece_values)
    class_distribution = metrics.get("class_distribution") or {}
    min_class_fraction = min(
        (float(class_distribution.get(label, 0.0)) for label in ("TP", "SL", "TIMEOUT")),
        default=0.0,
    )

    if rows < settings.auto_train_min_holdout_rows:
        reasons.append("holdout_rows_below_minimum")
    if log_loss_value > settings.auto_train_max_log_loss:
        reasons.append("log_loss_above_limit")
    if brier_value > settings.auto_train_max_multiclass_brier:
        reasons.append("multiclass_brier_above_limit")
    if max_ece > settings.auto_train_max_ece:
        reasons.append("calibration_error_above_limit")
    if min_class_fraction < settings.auto_train_min_class_fraction:
        reasons.append("holdout_class_fraction_below_minimum")

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
        log_loss_delta = log_loss_value - incumbent_log_loss
        brier_delta = brier_value - incumbent_brier
        improved = (
            log_loss_delta <= -settings.auto_train_min_metric_improvement
            or brier_delta <= -settings.auto_train_min_metric_improvement
        )
        if log_loss_delta > settings.auto_train_max_log_loss_regression:
            reasons.append("log_loss_regressed_vs_incumbent")
        if brier_delta > settings.auto_train_max_brier_regression:
            reasons.append("multiclass_brier_regressed_vs_incumbent")
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
            "improved": improved,
        }

    return {
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
        },
        "relative": relative,
    }


async def register_model_candidate(
    candidate: ModelCandidate,
    *,
    source: str,
    quality_gate: dict[str, Any] | None,
    activation_requested: bool,
    actor: str,
) -> ModelRegistry:
    digest = hashlib.sha256(candidate.path.read_bytes()).hexdigest()
    metrics = {
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
        "incumbent_version": candidate.incumbent_version,
        "incumbent_metrics_same_holdout": candidate.incumbent_metrics,
        "quality_gate": quality_gate,
        "activation_requested": activation_requested,
    }
    async with SessionFactory() as session, session.begin():
        registry = ModelRegistry(
            name=f"Hourly direction-conditional barrier {candidate.model_type} h{candidate.horizon}",
            version=candidate.version,
            model_type=f"barrier_{candidate.model_type}",
            artifact_path=str(candidate.path),
            artifact_sha256=digest,
            feature_schema_version="hourly-barrier-v1",
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
                "quality_gate": quality_gate,
                "activation_requested": activation_requested,
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

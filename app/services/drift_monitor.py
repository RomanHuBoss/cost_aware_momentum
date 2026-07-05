from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import JobRun, MarketSignal, ModelRegistry, SignalOutcome
from app.ml.drift import (
    DIRECTIONAL_PREDICTION_SCHEMA,
    PRODUCTION_DRIFT_REPORT_SCHEMA,
    DriftThresholds,
    evaluate_production_drift,
    validate_production_drift_reference,
)


def drift_thresholds(settings: Settings) -> DriftThresholds:
    return DriftThresholds(
        minimum_feature_observations=settings.drift_min_feature_observations,
        minimum_outcome_observations=settings.drift_min_outcome_observations,
        minimum_coverage_rate=settings.drift_min_coverage_rate,
        maximum_missing_rate=settings.drift_max_missing_rate,
        warning_psi=settings.drift_warning_psi,
        critical_psi=settings.drift_critical_psi,
        maximum_log_loss_delta=settings.drift_max_log_loss_delta,
        maximum_brier_delta=settings.drift_max_brier_delta,
        maximum_actionability_rate_delta=settings.drift_max_actionability_rate_delta,
    )


def _blocked_report(*, now: datetime, window_start: datetime, alerts: list[str]) -> dict[str, object]:
    return {
        "schema": PRODUCTION_DRIFT_REPORT_SCHEMA,
        "status": "BLOCKED",
        "generated_at": now.isoformat(),
        "window_start": window_start.isoformat(),
        "window_end": now.isoformat(),
        "model_version": None,
        "alerts": alerts,
        "coverage": {
            "status": "BLOCKED",
            "expected_opportunities": 0,
            "published_opportunities": 0,
            "rate": 0.0,
        },
        "features": {"observations": 0, "max_psi": None, "by_feature": {}},
        "probabilities": {"observations": 0, "max_psi": None, "by_class": {}},
        "calibration": {"status": "INSUFFICIENT_DATA", "observations": 0},
        "actionability": {"status": "INSUFFICIENT_DATA", "observations": 0},
        "automatic_model_action": "none",
    }


def _directional_probability_rows(signal: MarketSignal) -> list[dict[str, float]]:
    snapshot = signal.feature_snapshot if isinstance(signal.feature_snapshot, dict) else {}
    directional = snapshot.get("directional_predictions")
    if not isinstance(directional, dict) or directional.get("schema") != DIRECTIONAL_PREDICTION_SCHEMA:
        return []
    if directional.get("model_version") != signal.model_version:
        return []
    predictions = directional.get("predictions")
    if not isinstance(predictions, dict):
        return []
    rows: list[dict[str, float]] = []
    for direction in ("LONG", "SHORT"):
        probabilities = predictions.get(direction)
        if not isinstance(probabilities, dict):
            return []
        try:
            rows.append(
                {
                    "TP": float(probabilities["TP"]),
                    "SL": float(probabilities["SL"]),
                    "TIMEOUT": float(probabilities["TIMEOUT"]),
                }
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            return []
    return rows


async def build_production_drift_report(
    session: AsyncSession,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    resolved_now = now or datetime.now(UTC)
    if resolved_now.tzinfo is None:
        resolved_now = resolved_now.replace(tzinfo=UTC)
    else:
        resolved_now = resolved_now.astimezone(UTC)
    window_start = resolved_now - timedelta(hours=settings.drift_window_hours)
    if not settings.drift_monitor_enabled:
        return _blocked_report(
            now=resolved_now,
            window_start=window_start,
            alerts=["drift_monitor_disabled"],
        )

    active_model = (
        await session.execute(
            select(ModelRegistry)
            .where(ModelRegistry.active.is_(True))
            .order_by(ModelRegistry.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if active_model is None or active_model.model_type == "deterministic_baseline":
        return _blocked_report(
            now=resolved_now,
            window_start=window_start,
            alerts=["active_artifact_model_required"],
        )
    try:
        reference = validate_production_drift_reference(
            (active_model.metrics or {}).get("production_drift_reference")
        )
    except (TypeError, ValueError):
        report = _blocked_report(
            now=resolved_now,
            window_start=window_start,
            alerts=["invalid_production_drift_reference"],
        )
        report["model_version"] = active_model.version
        return report

    signals = (
        (
            await session.execute(
                select(MarketSignal)
                .where(
                    MarketSignal.model_version == active_model.version,
                    MarketSignal.publish_time >= window_start,
                    MarketSignal.publish_time <= resolved_now,
                )
                .order_by(MarketSignal.publish_time, MarketSignal.symbol)
            )
        )
        .scalars()
        .all()
    )
    inference_jobs = (
        (
            await session.execute(
                select(JobRun)
                .where(
                    JobRun.job_name == "hourly_inference",
                    JobRun.scheduled_for >= window_start,
                    JobRun.scheduled_for <= resolved_now,
                )
                .order_by(JobRun.scheduled_for)
            )
        )
        .scalars()
        .all()
    )
    expected_opportunities = 0
    published_opportunities = 0
    failed_inference_jobs = 0
    invalid_coverage_jobs = 0
    for job in inference_jobs:
        if job.status != "SUCCESS":
            failed_inference_jobs += 1
            continue
        details = job.details if isinstance(job.details, dict) else {}
        try:
            universe_symbols = int(details.get("universe_symbols", 0))
            covered = int(details.get("published", 0)) + int(
                details.get("existing_current_hour", 0)
            )
        except (TypeError, ValueError, OverflowError):
            invalid_coverage_jobs += 1
            continue
        if universe_symbols < 0 or covered < 0 or covered > universe_symbols:
            invalid_coverage_jobs += 1
            continue
        expected_opportunities += universe_symbols
        published_opportunities += covered

    feature_names = list(reference["feature_names"])
    actionability_reference = reference["actionability"]
    min_net_rr = float(actionability_reference["min_net_rr"])
    min_net_ev_r = float(actionability_reference["min_net_ev_r"])
    feature_rows: list[dict[str, object]] = []
    probability_rows: list[dict[str, float]] = []
    actionable_flags: list[bool] = []
    signal_by_id: dict[object, MarketSignal] = {}
    for signal in signals:
        snapshot = signal.feature_snapshot if isinstance(signal.feature_snapshot, dict) else {}
        feature_rows.append({name: snapshot.get(name) for name in feature_names})
        probability_rows.extend(_directional_probability_rows(signal))
        actionable_flags.append(signal.net_rr >= min_net_rr and signal.net_ev_r >= min_net_ev_r)
        signal_by_id[signal.id] = signal

    outcome_rows: list[dict[str, Any]] = []
    if signal_by_id:
        outcomes = (
            (
                await session.execute(
                    select(SignalOutcome).where(SignalOutcome.signal_id.in_(list(signal_by_id)))
                )
            )
            .scalars()
            .all()
        )
        for outcome in outcomes:
            signal = signal_by_id.get(outcome.signal_id)
            if signal is None:
                continue
            outcome_rows.append(
                {
                    "outcome": outcome.outcome,
                    "probabilities": {
                        "TP": signal.p_tp,
                        "SL": signal.p_sl,
                        "TIMEOUT": signal.p_timeout,
                    },
                }
            )

    report = evaluate_production_drift(
        reference,
        feature_rows=feature_rows,
        probability_rows=probability_rows,
        outcome_rows=outcome_rows,
        actionable_flags=actionable_flags,
        expected_opportunities=expected_opportunities,
        published_opportunities=published_opportunities,
        thresholds=drift_thresholds(settings),
    )
    report_alerts = report.get("alerts")
    if not isinstance(report_alerts, list):
        report_alerts = []
        report["alerts"] = report_alerts
    if failed_inference_jobs:
        report["status"] = "BLOCKED"
        report_alerts.append("failed_inference_jobs_in_window")
    if invalid_coverage_jobs:
        report["status"] = "BLOCKED"
        report_alerts.append("invalid_inference_coverage_accounting")
    report.update(
        {
            "generated_at": resolved_now.isoformat(),
            "window_start": window_start.isoformat(),
            "window_end": resolved_now.isoformat(),
            "window_hours": settings.drift_window_hours,
            "model_version": active_model.version,
            "feature_schema_version": active_model.feature_schema_version,
            "signal_observations": len(signals),
            "inference_jobs": len(inference_jobs),
            "failed_inference_jobs": failed_inference_jobs,
            "invalid_coverage_jobs": invalid_coverage_jobs,
            "outcome_observations": len(outcome_rows),
            "automatic_model_action": "none",
        }
    )
    return report

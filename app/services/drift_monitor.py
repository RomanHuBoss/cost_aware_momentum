from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import (
    JobRun,
    MarketSignal,
    ModelInferenceObservation,
    ModelRegistry,
    SignalOutcome,
)
from app.ml.drift import (
    DIRECTIONAL_PREDICTION_SCHEMA,
    PRODUCTION_DRIFT_OUTCOME_COHORT_SCHEMA,
    PRODUCTION_DRIFT_REPORT_SCHEMA,
    DriftThresholds,
    evaluate_production_drift,
    resolve_production_drift_status,
    validate_production_drift_reference,
)

PRODUCTION_DRIFT_PUBLICATION_GUARD_SCHEMA = "production-drift-critical-quarantine-v1"


def _publication_guard_result(
    *,
    blocked: bool,
    model_version: str,
    reason_code: str | None = None,
    active_model_version: str | None = None,
    critical_report_generated_at: str | None = None,
    critical_alerts: list[str] | None = None,
    release_condition: str | None = None,
) -> dict[str, object]:
    return {
        "schema": PRODUCTION_DRIFT_PUBLICATION_GUARD_SCHEMA,
        "blocked": blocked,
        "model_version": model_version,
        "active_model_version": active_model_version,
        "reason_code": reason_code,
        "critical_report_generated_at": critical_report_generated_at,
        "critical_alerts": critical_alerts or [],
        "release_condition": release_condition if blocked else None,
    }


async def production_drift_publication_guard(
    session: AsyncSession,
    *,
    model_version: str,
    monitor_enabled: bool,
    runtime_is_baseline: bool,
) -> dict[str, object]:
    """Latch a CRITICAL production-drift report to the active artifact version.

    Insufficient warm-up evidence is deliberately not used as a publication
    blocker: the current monitor learns from prospectively published prediction
    snapshots, so blocking on minimum-observation alerts would create a permanent
    bootstrap deadlock. A genuine CRITICAL report, however, quarantines the exact
    active artifact until another model version is activated. The latch is rebuilt
    from persisted JobRun evidence after worker restarts.
    """

    version = str(model_version).strip()
    if not version:
        raise ValueError("model_version is required for the production drift guard")
    if runtime_is_baseline:
        return _publication_guard_result(blocked=False, model_version=version)

    # The setting controls new monitor jobs, not enforcement of already persisted
    # CRITICAL evidence. Disabling collection must not silently clear quarantine.
    _ = monitor_enabled

    active_model = (
        await session.execute(
            select(ModelRegistry).where(ModelRegistry.active.is_(True)).limit(1)
        )
    ).scalar_one_or_none()
    if active_model is None:
        return _publication_guard_result(
            blocked=True,
            model_version=version,
            reason_code="active_model_unavailable",
            release_condition="activate_reviewed_model_version",
        )
    active_version = str(active_model.version).strip()
    if active_version != version or active_model.model_type == "deterministic_baseline":
        return _publication_guard_result(
            blocked=True,
            model_version=version,
            active_model_version=active_version,
            reason_code="active_model_version_mismatch",
            release_condition="refresh_runtime_to_active_model_version",
        )

    reports = (
        (
            await session.execute(
                select(JobRun)
                .where(
                    JobRun.job_name == "production_drift_monitor",
                    JobRun.status == "SUCCESS",
                    JobRun.details["model_version"].astext == version,
                    JobRun.details["status"].astext == "CRITICAL",
                )
                .order_by(JobRun.started_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .all()
    )
    for job in reports:
        details = job.details if isinstance(job.details, dict) else {}
        if details.get("model_version") != version or details.get("status") != "CRITICAL":
            continue
        alerts = details.get("alerts")
        critical_alerts = [str(item) for item in alerts] if isinstance(alerts, list) else []
        generated_at = details.get("generated_at")
        return _publication_guard_result(
            blocked=True,
            model_version=version,
            active_model_version=active_version,
            reason_code="critical_production_drift",
            critical_report_generated_at=(str(generated_at) if generated_at is not None else None),
            critical_alerts=critical_alerts,
            release_condition="activate_different_model_version",
        )
    return _publication_guard_result(
        blocked=False,
        model_version=version,
        active_model_version=active_version,
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
        "critical_evidence": [],
        "blocking_evidence": list(alerts),
        "warning_evidence": [],
        "generated_at": now.isoformat(),
        "window_start": window_start.isoformat(),
        "window_end": now.isoformat(),
        "model_version": None,
        "alerts": alerts,
        "coverage": {
            "status": "BLOCKED",
            "expected_opportunities": 0,
            "processed_opportunities": 0,
            "rate": 0.0,
        },
        "features": {"observations": 0, "max_psi": None, "by_feature": {}},
        "probabilities": {"observations": 0, "max_psi": None, "by_class": {}},
        "calibration": {"status": "INSUFFICIENT_DATA", "observations": 0},
        "outcome_coverage": {
            "schema": PRODUCTION_DRIFT_OUTCOME_COHORT_SCHEMA,
            "mature_signals": 0,
            "resolved_mature_signals": 0,
            "unresolved_mature_signals": 0,
            "early_resolved_immature_signals_excluded": 0,
            "invalid_maturity_signals": 0,
            "rate": None,
            "status": "INSUFFICIENT_DATA",
        },
        "actionability": {
            "status": "INSUFFICIENT_DATA",
            "observations": 0,
            "opportunities": 0,
            "actionable_opportunities": 0,
            "rate": 0.0,
        },
        "automatic_model_action": "none",
    }


def _probability_rows_from_snapshot(
    directional: object,
    *,
    model_version: str,
) -> list[dict[str, float]]:
    if not isinstance(directional, dict) or directional.get("schema") != DIRECTIONAL_PREDICTION_SCHEMA:
        return []
    if directional.get("model_version") != model_version:
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


def _directional_probability_rows(signal: MarketSignal) -> list[dict[str, float]]:
    snapshot = signal.feature_snapshot if isinstance(signal.feature_snapshot, dict) else {}
    return _probability_rows_from_snapshot(
        snapshot.get("directional_predictions"),
        model_version=signal.model_version,
    )


def _mature_signal_ids(
    signals: list[MarketSignal],
    *,
    now: datetime,
) -> tuple[set[object], set[object], int]:
    """Partition signals by full-horizon maturity for unbiased outcome calibration."""

    mature: set[object] = set()
    immature: set[object] = set()
    invalid = 0
    for signal in signals:
        event_time = getattr(signal, "event_time", None)
        horizon_hours = getattr(signal, "horizon_hours", None)
        if (
            not isinstance(event_time, datetime)
            or event_time.tzinfo is None
            or isinstance(horizon_hours, bool)
            or not isinstance(horizon_hours, int)
            or horizon_hours <= 0
        ):
            invalid += 1
            continue
        horizon_end = event_time.astimezone(UTC) + timedelta(hours=horizon_hours)
        target = mature if horizon_end <= now else immature
        target.add(signal.id)
    return mature, immature, invalid


def _maturity_aware_outcome_rows(
    signals: list[MarketSignal],
    outcomes: list[SignalOutcome],
    *,
    now: datetime,
) -> tuple[list[dict[str, Any]], dict[str, object], list[str]]:
    """Use only full-horizon mature labels and diagnose censoring/incompleteness."""

    mature_ids, immature_ids, invalid_maturity = _mature_signal_ids(signals, now=now)
    signal_by_id = {signal.id: signal for signal in signals}
    seen_outcome_ids: set[object] = set()
    resolved_mature_ids: set[object] = set()
    early_resolved_immature = 0
    duplicate_outcomes = 0
    rows: list[dict[str, Any]] = []
    for outcome in outcomes:
        signal_id = outcome.signal_id
        if signal_id in seen_outcome_ids:
            duplicate_outcomes += 1
            continue
        seen_outcome_ids.add(signal_id)
        signal = signal_by_id.get(signal_id)
        if signal is None:
            continue
        if signal_id in immature_ids:
            early_resolved_immature += 1
            continue
        if signal_id not in mature_ids:
            continue
        resolved_mature_ids.add(signal_id)
        rows.append(
            {
                "outcome": outcome.outcome,
                "probabilities": {
                    "TP": signal.p_tp,
                    "SL": signal.p_sl,
                    "TIMEOUT": signal.p_timeout,
                },
            }
        )

    mature_count = len(mature_ids)
    resolved_count = len(resolved_mature_ids)
    unresolved_count = mature_count - resolved_count
    alerts: list[str] = []
    if invalid_maturity:
        alerts.append("invalid_signal_maturity_metadata")
    if duplicate_outcomes:
        alerts.append("duplicate_signal_outcomes")
    if unresolved_count:
        alerts.append("incomplete_mature_outcome_coverage")
    if alerts:
        status = "BLOCKED"
    elif mature_count == 0:
        status = "INSUFFICIENT_DATA"
    else:
        status = "OK"
    coverage = {
        "schema": PRODUCTION_DRIFT_OUTCOME_COHORT_SCHEMA,
        "mature_signals": mature_count,
        "resolved_mature_signals": resolved_count,
        "unresolved_mature_signals": unresolved_count,
        "early_resolved_immature_signals_excluded": early_resolved_immature,
        "invalid_maturity_signals": invalid_maturity,
        "rate": (float(resolved_count / mature_count) if mature_count else None),
        "status": status,
    }
    if duplicate_outcomes:
        coverage["duplicate_outcomes"] = duplicate_outcomes
    return rows, coverage, alerts


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

    observations = (
        (
            await session.execute(
                select(ModelInferenceObservation)
                .where(
                    ModelInferenceObservation.model_version == active_model.version,
                    ModelInferenceObservation.observed_at >= window_start,
                    ModelInferenceObservation.observed_at <= resolved_now,
                )
                .order_by(
                    ModelInferenceObservation.observed_at,
                    ModelInferenceObservation.symbol,
                )
            )
        )
        .scalars()
        .all()
    )
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
    processed_opportunities = 0
    actionable_opportunities = 0
    failed_inference_jobs = 0
    invalid_coverage_jobs = 0
    for job in inference_jobs:
        if job.status != "SUCCESS":
            failed_inference_jobs += 1
            continue
        details = job.details if isinstance(job.details, dict) else {}
        try:
            universe_symbols = int(
                details.get("symbols_total", details.get("universe_symbols", 0))
            )
            processed = int(details["symbol_outcome_count"])
            actionable = int(details.get("published", 0)) + int(
                details.get("existing_current_hour", 0)
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid_coverage_jobs += 1
            continue
        if (
            universe_symbols < 0
            or processed < 0
            or processed > universe_symbols
            or actionable < 0
            or actionable > processed
        ):
            invalid_coverage_jobs += 1
            continue
        expected_opportunities += universe_symbols
        processed_opportunities += processed
        actionable_opportunities += actionable

    feature_names = list(reference["feature_names"])
    feature_rows: list[dict[str, object]] = []
    probability_rows: list[dict[str, float]] = []
    invalid_observation_rows = 0
    for observation in observations:
        snapshot = (
            observation.feature_snapshot
            if isinstance(observation.feature_snapshot, dict)
            else {}
        )
        probabilities = _probability_rows_from_snapshot(
            observation.directional_predictions,
            model_version=observation.model_version,
        )
        if (
            observation.feature_schema_version != active_model.feature_schema_version
            or not snapshot
            or len(probabilities) != 2
        ):
            invalid_observation_rows += 1
            continue
        feature_rows.append({name: snapshot.get(name) for name in feature_names})
        probability_rows.extend(probabilities)

    signal_by_id: dict[object, MarketSignal] = {}
    for signal in signals:
        signal_by_id[signal.id] = signal

    outcomes: list[SignalOutcome] = []
    if signal_by_id:
        outcomes = list(
            (
                await session.execute(
                    select(SignalOutcome).where(SignalOutcome.signal_id.in_(list(signal_by_id)))
                )
            )
            .scalars()
            .all()
        )
    outcome_rows, outcome_coverage, outcome_alerts = _maturity_aware_outcome_rows(
        list(signals),
        outcomes,
        now=resolved_now,
    )

    report = evaluate_production_drift(
        reference,
        feature_rows=feature_rows,
        probability_rows=probability_rows,
        outcome_rows=outcome_rows,
        actionable_flags=None,
        expected_opportunities=expected_opportunities,
        processed_opportunities=processed_opportunities,
        actionable_opportunities=actionable_opportunities,
        thresholds=drift_thresholds(settings),
    )
    report_alerts = report.get("alerts")
    if not isinstance(report_alerts, list):
        report_alerts = []
        report["alerts"] = report_alerts
    critical_evidence = report.get("critical_evidence")
    blocking_evidence = report.get("blocking_evidence")
    warning_evidence = report.get("warning_evidence")
    if not isinstance(critical_evidence, list):
        critical_evidence = []
        report["critical_evidence"] = critical_evidence
    if not isinstance(blocking_evidence, list):
        blocking_evidence = []
        report["blocking_evidence"] = blocking_evidence
    if not isinstance(warning_evidence, list):
        warning_evidence = []
        report["warning_evidence"] = warning_evidence

    def add_blocker(reason: str) -> None:
        if reason not in report_alerts:
            report_alerts.append(reason)
        if reason not in blocking_evidence:
            blocking_evidence.append(reason)

    if failed_inference_jobs:
        add_blocker("failed_inference_jobs_in_window")
    if invalid_coverage_jobs:
        add_blocker("invalid_inference_coverage_accounting")
    if invalid_observation_rows:
        add_blocker("invalid_model_inference_observations")
    if outcome_alerts:
        for alert in outcome_alerts:
            add_blocker(alert)
        calibration = report.get("calibration")
        if isinstance(calibration, dict):
            calibration["status"] = "BLOCKED"
            calibration["maturity_evidence_complete"] = False
        # Incomplete/invalid maturity evidence invalidates calibration-only drift,
        # but must not suppress independently confirmed feature/probability/actionability drift.
        critical_evidence[:] = [
            reason for reason in critical_evidence if reason != "calibration_drift"
        ]
        warning_evidence[:] = [
            reason for reason in warning_evidence if reason != "calibration_warning"
        ]
        report_alerts[:] = [
            reason
            for reason in report_alerts
            if reason not in {"calibration_drift", "calibration_warning"}
        ]
    elif isinstance(report.get("calibration"), dict):
        report["calibration"]["maturity_evidence_complete"] = (
            outcome_coverage["status"] == "OK"
        )
    report["status"] = resolve_production_drift_status(
        critical_evidence=critical_evidence,
        blocking_evidence=blocking_evidence,
        warning_evidence=warning_evidence,
    )
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
            "outcome_coverage": outcome_coverage,
            "automatic_model_action": (
                "quarantine_new_signals_and_plans"
                if report.get("status") == "CRITICAL"
                else "none"
            ),
        }
    )
    return report

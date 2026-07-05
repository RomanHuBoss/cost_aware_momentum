from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import JobRun
from app.services.model_promotion import EXPERIMENT_PROMOTION_GATE_SCHEMA

INFERENCE_ATTRITION_SCHEMA = "hourly-inference-terminal-outcomes-v1"
EXECUTION_PLAN_ATTRITION_SCHEMA = "execution-plan-attrition-v1"
ATTRITION_REPORT_SCHEMA = "candidate-live-attrition-report-v2"
INFERENCE_JOB_NAMES = ("hourly_inference", "universe_catchup_inference")


def _unique_strings(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _execution_terminal_stage(status: str) -> str:
    if status in {"ACTIONABLE", "LIMITED"}:
        return "ACTIONABLE"
    if status == "NO_TRADE":
        return "POLICY_ECONOMICS"
    if status in {"BLOCKED_DATA", "BLOCKED_STALE_DATA", "BLOCKED_INVALID_INPUT"}:
        return "DATA_INTEGRITY"
    if status == "BLOCKED_LIQUIDITY":
        return "LIQUIDITY"
    if status in {
        "BLOCKED_MARGIN",
        "BLOCKED_PORTFOLIO",
        "BLOCKED_MIN_SIZE",
        "BLOCKED_LIQUIDATION",
    }:
        return "RISK_EXECUTION"
    if status in {"EXPIRED", "SUPERSEDED", "REJECTED", "ACCEPTED", "ENTERED", "PARTIAL", "CLOSED"}:
        return "LIFECYCLE"
    return "UNKNOWN"


def execution_plan_attrition_evidence(
    *,
    status: str,
    reason_codes: Iterable[object],
    limiting_cap: str | None,
) -> dict[str, object]:
    normalized_status = str(status).strip().upper()
    if not normalized_status:
        raise ValueError("Execution-plan attrition status is required")
    normalized_reasons = _unique_strings(reason_codes)
    if not normalized_reasons:
        normalized_reasons = [f"status.{normalized_status.lower()}"]
    normalized_cap = str(limiting_cap).strip().upper() if limiting_cap else None
    return {
        "schema": EXECUTION_PLAN_ATTRITION_SCHEMA,
        "terminal_stage": _execution_terminal_stage(normalized_status),
        "primary_reason_code": normalized_reasons[0],
        "reason_codes": normalized_reasons,
        "limiting_cap": normalized_cap,
    }


def quality_gate_reason_stage(reason: object) -> str:
    code = str(reason).strip().lower()
    if not code:
        return "UNKNOWN"
    if (
        "incumbent" in code
        or code.endswith("_vs_incumbent")
        or code == "no_required_improvement_vs_incumbent"
    ):
        return "INCUMBENT_RELATIVE"
    if code.startswith("walk_forward_"):
        return "TEMPORAL_VALIDATION"
    if code.startswith("policy_"):
        return "POLICY_ECONOMICS"
    if code.startswith(("log_loss_", "multiclass_brier_", "calibration_")) or code in {
        "invalid_holdout_class_distribution",
        "holdout_class_fraction_below_minimum",
    }:
        return "MODEL_QUALITY"
    if code.startswith(("holdout_", "missing_", "invalid_", "incomplete_")) or any(
        token in code
        for token in (
            "funding",
            "market_context",
            "intrahorizon",
            "schema",
            "evidence",
            "class_distribution",
        )
    ):
        return "EVIDENCE_INTEGRITY"
    return "OTHER"


def _datetime_value(record: Mapping[str, object], *names: str) -> datetime:
    for name in names:
        value = record.get(name)
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return datetime.min.replace(tzinfo=UTC)


def _mapping_job(job: object) -> dict[str, object]:
    if isinstance(job, Mapping):
        return dict(job)
    return {
        "job_name": getattr(job, "job_name", None),
        "status": getattr(job, "status", None),
        "scheduled_for": getattr(job, "scheduled_for", None),
        "started_at": getattr(job, "started_at", None),
        "finished_at": getattr(job, "finished_at", None),
        "details": getattr(job, "details", None),
    }


def _counted(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items()))


def build_attrition_report_from_records(
    *,
    inference_jobs: Iterable[object],
    training_jobs: Iterable[object],
    since: datetime,
    until: datetime,
) -> dict[str, object]:
    if since.tzinfo is None or until.tzinfo is None:
        raise ValueError("Attrition report bounds must be timezone-aware")
    if until <= since:
        raise ValueError("Attrition report until must be after since")

    integrity_errors: list[str] = []
    alerts: list[str] = []
    inference_records = sorted(
        (_mapping_job(job) for job in inference_jobs),
        key=lambda item: _datetime_value(item, "finished_at", "scheduled_for", "started_at"),
    )
    training_records = sorted(
        (_mapping_job(job) for job in training_jobs),
        key=lambda item: _datetime_value(item, "finished_at", "started_at", "scheduled_for"),
    )

    successful_inference_jobs = 0
    instrumented_jobs = 0
    legacy_jobs = 0
    failed_inference_jobs = 0
    symbol_history: dict[tuple[str, str], list[dict[str, object]]] = {}
    plan_rows: dict[str, dict[str, object]] = {}

    for job in inference_records:
        status = str(job.get("status") or "")
        if status != "SUCCESS":
            failed_inference_jobs += 1
            continue
        successful_inference_jobs += 1
        details = job.get("details")
        if not isinstance(details, Mapping):
            integrity_errors.append("inference_job_details_invalid")
            continue
        if details.get("attrition_schema") != INFERENCE_ATTRITION_SCHEMA:
            legacy_jobs += 1
            continue
        instrumented_jobs += 1
        try:
            symbols_total = int(details.get("symbols_total", -1))
        except (TypeError, ValueError):
            symbols_total = -1
        outcomes = details.get("symbol_outcomes")
        if symbols_total < 0 or not isinstance(outcomes, list):
            integrity_errors.append("inference_job_symbol_outcomes_invalid")
            continue
        if len(outcomes) != symbols_total:
            integrity_errors.append("inference_job_symbol_outcome_count_mismatch")
        job_keys: set[tuple[str, str]] = set()
        for raw in outcomes:
            if not isinstance(raw, Mapping):
                integrity_errors.append("inference_symbol_outcome_invalid")
                continue
            symbol = str(raw.get("symbol") or "").strip()
            event_time = str(raw.get("event_time") or "").strip()
            terminal_state = str(raw.get("terminal_state") or "").strip().upper()
            reason_code = str(raw.get("reason_code") or "").strip()
            if not symbol or not event_time or terminal_state not in {
                "SKIPPED",
                "PUBLISHED",
                "EXISTING_CURRENT_HOUR",
            } or not reason_code:
                integrity_errors.append("inference_symbol_outcome_invalid")
                continue
            key = (event_time, symbol)
            if key in job_keys:
                integrity_errors.append("inference_job_duplicate_symbol_outcome")
                continue
            job_keys.add(key)
            symbol_history.setdefault(key, []).append(dict(raw))

        raw_plans = details.get("plan_outcomes", [])
        if not isinstance(raw_plans, list):
            integrity_errors.append("inference_job_plan_outcomes_invalid")
            continue
        try:
            published_count = int(details.get("published", -1))
            profiles_total = int(details.get("profiles_total", -1))
        except (TypeError, ValueError):
            published_count = -1
            profiles_total = -1
        if published_count < 0 or profiles_total < 0:
            integrity_errors.append("inference_job_plan_denominator_invalid")
        elif len(raw_plans) != published_count * profiles_total:
            integrity_errors.append("inference_job_plan_outcome_count_mismatch")
        for raw in raw_plans:
            if not isinstance(raw, Mapping):
                integrity_errors.append("inference_plan_outcome_invalid")
                continue
            plan_id = str(raw.get("plan_id") or "").strip()
            primary_reason = str(raw.get("primary_reason_code") or "").strip()
            stage = str(raw.get("terminal_stage") or "").strip()
            plan_status = str(raw.get("status") or "").strip().upper()
            reason_codes = raw.get("reason_codes")
            if (
                not plan_id
                or raw.get("schema") != EXECUTION_PLAN_ATTRITION_SCHEMA
                or not primary_reason
                or not stage
                or not plan_status
                or not isinstance(reason_codes, list)
            ):
                integrity_errors.append("inference_plan_outcome_invalid")
                continue
            existing = plan_rows.get(plan_id)
            normalized = dict(raw)
            if existing is not None and existing != normalized:
                integrity_errors.append("inference_plan_outcome_conflict")
                continue
            plan_rows[plan_id] = normalized

    signal_reason_counts: Counter[str] = Counter()
    signal_state_counts: Counter[str] = Counter()
    signal_available = 0
    retry_recovered = 0
    for history in symbol_history.values():
        states = [str(item.get("terminal_state") or "").upper() for item in history]
        available = any(state in {"PUBLISHED", "EXISTING_CURRENT_HOUR"} for state in states)
        if available:
            signal_available += 1
            signal_state_counts["SIGNAL_AVAILABLE"] += 1
            first_available = next(
                index
                for index, state in enumerate(states)
                if state in {"PUBLISHED", "EXISTING_CURRENT_HOUR"}
            )
            if any(state == "SKIPPED" for state in states[:first_available]):
                retry_recovered += 1
        else:
            final = history[-1]
            reason = str(final.get("reason_code") or "unknown")
            signal_state_counts["SKIPPED"] += 1
            signal_reason_counts[reason] += 1

    plan_status_counts: Counter[str] = Counter()
    plan_stage_counts: Counter[str] = Counter()
    plan_reason_counts: Counter[str] = Counter()
    contributing_plan_reason_counts: Counter[str] = Counter()
    for row in plan_rows.values():
        status = str(row.get("status") or "UNKNOWN").upper()
        stage = str(row.get("terminal_stage") or "UNKNOWN")
        primary = str(row.get("primary_reason_code") or "unknown")
        plan_status_counts[status] += 1
        plan_stage_counts[stage] += 1
        plan_reason_counts[primary] += 1
        for code in _unique_strings(row.get("reason_codes", [])):
            contributing_plan_reason_counts[code] += 1

    training_terminal_counts: Counter[str] = Counter()
    gate_reason_counts: Counter[str] = Counter()
    gate_stage_counts: Counter[str] = Counter()
    experiment_promotion_reason_counts: Counter[str] = Counter()
    activation_skip_counts: Counter[str] = Counter()
    for job in training_records:
        status = str(job.get("status") or "")
        details = job.get("details")
        if status != "SUCCESS":
            training_terminal_counts["TRAINING_FAILED"] += 1
            continue
        if not isinstance(details, Mapping):
            integrity_errors.append("training_job_details_invalid")
            training_terminal_counts["INCOMPLETE_EVIDENCE"] += 1
            continue
        gate = details.get("quality_gate")
        if not isinstance(gate, Mapping) or not isinstance(gate.get("passed"), bool):
            integrity_errors.append("training_quality_gate_invalid")
            training_terminal_counts["INCOMPLETE_EVIDENCE"] += 1
            continue
        experiment_gate = details.get("experiment_promotion_gate")
        if (
            not isinstance(experiment_gate, Mapping)
            or experiment_gate.get("schema") != EXPERIMENT_PROMOTION_GATE_SCHEMA
            or not isinstance(experiment_gate.get("passed"), bool)
        ):
            integrity_errors.append("training_experiment_promotion_gate_invalid")
            training_terminal_counts["INCOMPLETE_EVIDENCE"] += 1
            continue
        candidate_version = str(details.get("candidate_version") or "").strip()
        if not candidate_version:
            integrity_errors.append("training_candidate_version_missing")
        reasons = gate.get("reasons", [])
        if not isinstance(reasons, list):
            integrity_errors.append("training_quality_gate_reasons_invalid")
            reasons = []
        normalized_gate_reasons = _unique_strings(reasons)
        if gate["passed"] is False and not normalized_gate_reasons:
            integrity_errors.append("training_quality_gate_failed_without_reasons")
        if gate["passed"] is True and normalized_gate_reasons:
            integrity_errors.append("training_quality_gate_passed_with_reasons")
        experiment_reasons = experiment_gate.get("reasons", [])
        if not isinstance(experiment_reasons, list):
            integrity_errors.append("training_experiment_promotion_reasons_invalid")
            experiment_reasons = []
        normalized_experiment_reasons = _unique_strings(experiment_reasons)
        if experiment_gate["passed"] is False and not normalized_experiment_reasons:
            integrity_errors.append("training_experiment_promotion_failed_without_reasons")
        if experiment_gate["passed"] is True and normalized_experiment_reasons:
            integrity_errors.append("training_experiment_promotion_passed_with_reasons")
        if gate["passed"] is False and details.get("activated") is True:
            integrity_errors.append("training_failed_gate_but_activated")
        if experiment_gate["passed"] is False and details.get("activated") is True:
            integrity_errors.append("training_failed_experiment_promotion_but_activated")
        for reason in normalized_gate_reasons:
            gate_reason_counts[reason] += 1
            gate_stage_counts[quality_gate_reason_stage(reason)] += 1
        if gate["passed"] is False:
            training_terminal_counts["QUALITY_GATE_FAILED"] += 1
        elif experiment_gate["passed"] is False:
            training_terminal_counts["EXPERIMENT_PROMOTION_GATE_FAILED"] += 1
            for reason in normalized_experiment_reasons:
                experiment_promotion_reason_counts[reason] += 1
        elif details.get("activated") is True:
            training_terminal_counts["ACTIVATED"] += 1
        else:
            training_terminal_counts["ACTIVATION_SKIPPED"] += 1
            activation_skip_counts[str(details.get("activation_skipped") or "unspecified")] += 1

    if successful_inference_jobs == 0:
        alerts.append("no_successful_inference_jobs_in_window")
    elif instrumented_jobs == 0:
        alerts.append("no_instrumented_inference_jobs_in_window")
    if failed_inference_jobs:
        alerts.append("failed_inference_jobs_present")
    if legacy_jobs:
        alerts.append("legacy_inference_jobs_excluded")
    if not training_records:
        alerts.append("no_training_attempts_in_window")

    report_status = (
        "BLOCKED"
        if integrity_errors or instrumented_jobs == 0 or legacy_jobs > 0 or failed_inference_jobs > 0
        else "OK"
    )
    return {
        "schema": ATTRITION_REPORT_SCHEMA,
        "status": report_status,
        "generated_at": datetime.now(UTC).isoformat(),
        "since": since.isoformat(),
        "until": until.isoformat(),
        "integrity_errors": sorted(set(integrity_errors)),
        "alerts": sorted(set(alerts)),
        "live": {
            "instrumentation": {
                "schema": INFERENCE_ATTRITION_SCHEMA,
                "successful_jobs": successful_inference_jobs,
                "instrumented_jobs": instrumented_jobs,
                "legacy_jobs_excluded": legacy_jobs,
                "failed_jobs": failed_inference_jobs,
                "coverage_rate": (
                    instrumented_jobs / successful_inference_jobs if successful_inference_jobs else 0.0
                ),
            },
            "signal_opportunities": {
                "unique_total": len(symbol_history),
                "signal_available": signal_available,
                "skipped_terminal": len(symbol_history) - signal_available,
                "retry_recovered": retry_recovered,
                "terminal_state_counts": _counted(signal_state_counts),
                "terminal_skip_reason_counts": _counted(signal_reason_counts),
            },
            "plan_opportunities": {
                "total": len(plan_rows),
                "actionable_or_limited": sum(
                    plan_status_counts.get(status, 0) for status in ("ACTIONABLE", "LIMITED")
                ),
                "no_trade": plan_status_counts.get("NO_TRADE", 0),
                "blocked": sum(
                    count for status, count in plan_status_counts.items() if status.startswith("BLOCKED_")
                ),
                "status_counts": _counted(plan_status_counts),
                "terminal_stage_counts": _counted(plan_stage_counts),
                "reason_counts": _counted(plan_reason_counts),
                "contributing_reason_counts": _counted(contributing_plan_reason_counts),
            },
        },
        "training": {
            "attempts": len(training_records),
            "terminal_outcome_counts": _counted(training_terminal_counts),
            "quality_gate_reason_counts": _counted(gate_reason_counts),
            "quality_gate_stage_counts": _counted(gate_stage_counts),
            "experiment_promotion_reason_counts": _counted(
                experiment_promotion_reason_counts
            ),
            "activation_skip_counts": _counted(activation_skip_counts),
        },
    }


async def build_candidate_live_attrition_report(
    session: AsyncSession,
    *,
    since: datetime,
    until: datetime | None = None,
) -> dict[str, object]:
    until = until or datetime.now(UTC)
    inference_jobs = (
        (
            await session.execute(
                select(JobRun)
                .where(
                    JobRun.job_name.in_(INFERENCE_JOB_NAMES),
                    JobRun.scheduled_for >= since,
                    JobRun.scheduled_for <= until,
                )
                .order_by(JobRun.scheduled_for, JobRun.started_at)
            )
        )
        .scalars()
        .all()
    )
    training_jobs = (
        (
            await session.execute(
                select(JobRun)
                .where(
                    JobRun.job_name == "model_retraining",
                    JobRun.started_at >= since,
                    JobRun.started_at <= until,
                )
                .order_by(JobRun.started_at)
            )
        )
        .scalars()
        .all()
    )
    return build_attrition_report_from_records(
        inference_jobs=inference_jobs,
        training_jobs=training_jobs,
        since=since,
        until=until,
    )


def default_attrition_since(*, now: datetime | None = None, hours: int = 168) -> datetime:
    if hours <= 0:
        raise ValueError("Attrition report hours must be positive")
    reference = now or datetime.now(UTC)
    return reference - timedelta(hours=hours)

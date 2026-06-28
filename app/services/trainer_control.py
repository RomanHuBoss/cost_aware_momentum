from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.locks import lock_key
from app.db.models import JobRun, ModelRegistry, ServiceHeartbeat
from app.json_utils import json_compatible
from app.ml.runtime_selection import recoverable_registry_artifact_notice
from app.services.audit import append_audit_event, publish_outbox

TrainerControlAction = Literal["CHECK_NOW", "RECOVER_NOW"]
TRAINER_CONTROL_JOB_NAME = "trainer_control_request"
TRAINER_CONTROL_ACTIONS = frozenset({"CHECK_NOW", "RECOVER_NOW"})
TRAINER_CONTROL_LOCK = lock_key("trainer_control_request", "singleton")
TRAINER_CONTROL_STALE_MIN_SECONDS = 300


def trainer_heartbeat_is_fresh(
    heartbeat: ServiceHeartbeat | None,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> bool:
    if heartbeat is None or heartbeat.status not in {"RUNNING", "DEGRADED"}:
        return False
    current = now or datetime.now(UTC)
    max_age_seconds = max(settings.heartbeat_seconds * 4, 90)
    return (current - heartbeat.last_seen_at).total_seconds() <= max_age_seconds


def trainer_control_stale_after_seconds(settings: Settings) -> int:
    """Return the minimum age before a dead-owner request can be recovered.

    The request must also belong to a trainer whose heartbeat is absent or stale.
    The fixed five-minute floor prevents a startup/reconnect race when PostgreSQL or
    heartbeat writes are briefly delayed.
    """

    return max(TRAINER_CONTROL_STALE_MIN_SECONDS, settings.heartbeat_seconds * 4)


async def acquire_trainer_control_lock(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": TRAINER_CONTROL_LOCK},
    )


def _control_request_accepted_at(job: JobRun) -> datetime:
    details = job.details if isinstance(job.details, dict) else {}
    raw = details.get("accepted_at")
    if isinstance(raw, str):
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.astimezone(UTC)
        except ValueError:
            pass
    value = job.started_at
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def trainer_control_request_is_stale(
    job: JobRun,
    owner_heartbeat: ServiceHeartbeat | None,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> bool:
    if job.status != "RUNNING":
        return False
    current = now or datetime.now(UTC)
    accepted_at = _control_request_accepted_at(job)
    age_seconds = (current - accepted_at).total_seconds()
    if age_seconds < trainer_control_stale_after_seconds(settings):
        return False
    return not trainer_heartbeat_is_fresh(owner_heartbeat, settings, now=current)


async def recover_stale_trainer_control(
    session: AsyncSession,
    settings: Settings,
    *,
    recovered_by: str,
    create_replacement: bool = True,
) -> JobRun | None:
    """Fail a control request abandoned by a dead trainer and optionally retry it.

    The caller must hold ``TRAINER_CONTROL_LOCK`` in the current transaction.  The
    abandoned row remains as terminal evidence; a retry is a new job linked through
    ``retry_of`` instead of mutating historical ownership back to ``PENDING``.
    """

    running = (
        await session.execute(
            select(JobRun)
            .where(
                JobRun.job_name == TRAINER_CONTROL_JOB_NAME,
                JobRun.status == "RUNNING",
            )
            .order_by(JobRun.started_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if running is None:
        return None

    details = dict(running.details or {})
    accepted_by = str(details.get("accepted_by") or running.worker_id or "")
    heartbeat = None
    if accepted_by:
        heartbeat = (
            await session.execute(
                select(ServiceHeartbeat)
                .where(
                    ServiceHeartbeat.service_name == "trainer",
                    ServiceHeartbeat.instance_id == accepted_by,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
    now = datetime.now(UTC)
    if not trainer_control_request_is_stale(
        running,
        heartbeat,
        settings,
        now=now,
    ):
        return None

    accepted_at = _control_request_accepted_at(running)
    recovery_count = int(details.get("recovery_count") or 0) + 1
    stale_result = {
        "action": details.get("action"),
        "training_started": False,
        "error": "stale_trainer_control_owner",
        "accepted_by": accepted_by or None,
        "accepted_at": accepted_at.isoformat(),
        "recovered_at": now.isoformat(),
        "recovered_by": recovered_by,
        "stale_after_seconds": trainer_control_stale_after_seconds(settings),
    }
    details["result"] = stale_result
    details["recovery_count"] = recovery_count
    details["recovered_at"] = now.isoformat()
    details["recovered_by"] = recovered_by
    running.status = "FAILED"
    running.finished_at = now
    running.details = json_compatible(details)

    replacement: JobRun | None = None
    if create_replacement:
        replacement_details = {
            "action": details.get("action"),
            "requested_by": details.get("requested_by"),
            "requested_at": details.get("requested_at") or running.started_at.isoformat(),
            "retry_of": str(running.id),
            "recovery_count": recovery_count,
            "requeued_at": now.isoformat(),
            "requeued_by": recovered_by,
        }
        replacement = JobRun(
            job_name=TRAINER_CONTROL_JOB_NAME,
            scheduled_for=now,
            started_at=now,
            status="PENDING",
            worker_id=f"requeue:{recovered_by}"[:100],
            details=json_compatible(replacement_details),
        )
        session.add(replacement)
        await session.flush()

    await append_audit_event(
        session,
        event_type="TRAINER_CONTROL_STALE_RECOVERED",
        entity_type="trainer_control",
        entity_id=str(running.id),
        actor=recovered_by,
        payload={
            "action": details.get("action"),
            "accepted_by": accepted_by or None,
            "accepted_at": accepted_at.isoformat(),
            "replacement_id": str(replacement.id) if replacement else None,
            "recovery_count": recovery_count,
        },
    )
    await publish_outbox(
        session,
        event_type="TRAINER_CONTROL_STALE_RECOVERED",
        aggregate_type="trainer_control",
        aggregate_id=str(running.id),
        payload={
            "action": details.get("action"),
            "status": "FAILED",
            "replacement_id": str(replacement.id) if replacement else None,
        },
    )
    if replacement is not None:
        await append_audit_event(
            session,
            event_type="TRAINER_CONTROL_REQUEUED",
            entity_type="trainer_control",
            entity_id=str(replacement.id),
            actor=recovered_by,
            payload={
                "action": replacement_details["action"],
                "retry_of": str(running.id),
                "recovery_count": recovery_count,
            },
        )
        await publish_outbox(
            session,
            event_type="TRAINER_CONTROL_REQUEUED",
            aggregate_type="trainer_control",
            aggregate_id=str(replacement.id),
            payload={
                "action": replacement_details["action"],
                "status": "PENDING",
                "retry_of": str(running.id),
            },
        )
    return replacement


def recovery_availability(
    active_model: ModelRegistry | None,
    settings: Settings,
) -> tuple[bool, str]:
    if not settings.auto_train_enabled:
        return False, "auto_training_disabled"
    if settings.active_model_path is not None:
        return False, "active_model_path_override"
    if active_model is None:
        return True, "no_active_model"
    if active_model.model_type == "deterministic_baseline":
        return True, "registry_baseline_active"
    artifact_path = Path(active_model.artifact_path).expanduser() if active_model.artifact_path else None
    if artifact_path is None or not artifact_path.is_file():
        notice = recoverable_registry_artifact_notice(
            active_model,
            allow_baseline_model=settings.allow_baseline_model,
            app_mode=settings.app_mode,
        )
        if notice is not None:
            return True, "active_model_artifact_missing"
        return False, "active_model_artifact_missing_fail_closed"
    return False, "active_model_artifact_available"


def control_job_payload(job: JobRun | None) -> dict[str, object] | None:
    if job is None:
        return None
    details = job.details if isinstance(job.details, dict) else {}
    return {
        "id": str(job.id),
        "action": details.get("action"),
        "requested_by": details.get("requested_by"),
        "requested_at": details.get("requested_at"),
        "status": job.status,
        "started_at": job.started_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "result": details.get("result"),
        "retry_of": details.get("retry_of"),
        "recovery_count": details.get("recovery_count", 0),
    }


async def enqueue_trainer_control(
    session: AsyncSession,
    *,
    action: TrainerControlAction,
    operator: str,
    settings: Settings,
) -> tuple[JobRun, bool]:
    if action not in TRAINER_CONTROL_ACTIONS:
        raise ValueError(f"Unsupported trainer control action: {action}")

    await acquire_trainer_control_lock(session)
    await recover_stale_trainer_control(
        session,
        settings,
        recovered_by=f"operator:{operator}"[:100],
        create_replacement=False,
    )
    existing = (
        await session.execute(
            select(JobRun)
            .where(
                JobRun.job_name == TRAINER_CONTROL_JOB_NAME,
                JobRun.status.in_(["PENDING", "RUNNING"]),
            )
            .order_by(desc(JobRun.started_at))
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    now = datetime.now(UTC)
    job = JobRun(
        job_name=TRAINER_CONTROL_JOB_NAME,
        scheduled_for=now,
        started_at=now,
        status="PENDING",
        worker_id=f"operator:{operator}"[:100],
        details=json_compatible(
            {
                "action": action,
                "requested_by": operator,
                "requested_at": now.isoformat(),
            }
        ),
    )
    session.add(job)
    await session.flush()
    return job, True

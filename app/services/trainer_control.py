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

TrainerControlAction = Literal["CHECK_NOW", "RECOVER_NOW"]
TRAINER_CONTROL_JOB_NAME = "trainer_control_request"
TRAINER_CONTROL_ACTIONS = frozenset({"CHECK_NOW", "RECOVER_NOW"})
_TRAINER_CONTROL_LOCK = lock_key("trainer_control_request", "singleton")


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
    }


async def enqueue_trainer_control(
    session: AsyncSession,
    *,
    action: TrainerControlAction,
    operator: str,
) -> tuple[JobRun, bool]:
    if action not in TRAINER_CONTROL_ACTIONS:
        raise ValueError(f"Unsupported trainer control action: {action}")

    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": _TRAINER_CONTROL_LOCK},
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

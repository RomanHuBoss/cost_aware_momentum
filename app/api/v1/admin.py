from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import desc, select

from app.api.deps import MutatingOperatorDep, SessionDep, SettingsDep
from app.api.schemas import DemoSeedRequest, TrainerControlRequest
from app.db.models import ModelRegistry, ServiceHeartbeat
from app.services.audit import append_audit_event, publish_outbox
from app.services.demo import seed_demo_market
from app.services.trainer_control import (
    automatic_experiment_cancel_availability,
    automatic_experiment_cancel_target_matches,
    control_job_payload,
    enqueue_trainer_control,
    recovery_availability,
    trainer_heartbeat_is_fresh,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.post("/demo-seed")
async def demo_seed(
    payload: DemoSeedRequest,
    session: SessionDep,
    settings: SettingsDep,
    operator: MutatingOperatorDep,
) -> dict:
    if not settings.allow_demo_seed:
        raise HTTPException(status_code=403, detail="Demo seed is disabled")
    result = await seed_demo_market(session, settings, [symbol.upper() for symbol in payload.symbols])
    await session.commit()
    return {"ok": True, **result}


@router.post("/trainer-control", status_code=202)
async def trainer_control(
    payload: TrainerControlRequest,
    session: SessionDep,
    settings: SettingsDep,
    operator: MutatingOperatorDep,
) -> dict:
    if not settings.auto_train_enabled:
        raise HTTPException(status_code=409, detail="Automatic model training is disabled")

    heartbeat = (
        await session.execute(
            select(ServiceHeartbeat)
            .where(ServiceHeartbeat.service_name == "trainer")
            .order_by(desc(ServiceHeartbeat.last_seen_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if not trainer_heartbeat_is_fresh(heartbeat, settings, now=datetime.now(UTC)):
        raise HTTPException(
            status_code=409,
            detail="Background trainer is not running or its heartbeat is stale",
        )

    active_model = None
    recovery_available = False
    recovery_reason = "not_applicable"
    if payload.action == "CANCEL_EXPERIMENT":
        cancellation_available, cancellation_reason, running_experiment = (
            automatic_experiment_cancel_availability(
                heartbeat,
                settings,
                now=datetime.now(UTC),
            )
        )
        if not cancellation_available or running_experiment is None:
            raise HTTPException(
                status_code=409,
                detail=f"Automatic experiment cancellation is not available: {cancellation_reason}",
            )
        if not automatic_experiment_cancel_target_matches(
            running_experiment,
            experiment_family=str(payload.experiment_family),
            candidate_version=str(payload.candidate_version),
        ):
            raise HTTPException(
                status_code=409,
                detail="Automatic experiment target changed; refresh status before cancelling",
            )
    else:
        active_model = (
            await session.execute(
                select(ModelRegistry)
                .where(ModelRegistry.active.is_(True))
                .order_by(desc(ModelRegistry.updated_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        recovery_available, recovery_reason = recovery_availability(active_model, settings)
        if payload.action == "RECOVER_NOW" and not recovery_available:
            raise HTTPException(
                status_code=409,
                detail=f"Recovery training is not available: {recovery_reason}",
            )

    job, created = await enqueue_trainer_control(
        session,
        action=payload.action,
        operator=operator,
        settings=settings,
        experiment_family=payload.experiment_family,
        candidate_version=payload.candidate_version,
    )
    if not created:
        existing_details = job.details if isinstance(job.details, dict) else {}
        exact_same_request = existing_details.get("action") == payload.action
        if payload.action == "CANCEL_EXPERIMENT":
            exact_same_request = exact_same_request and automatic_experiment_cancel_target_matches(
                existing_details,
                experiment_family=str(payload.experiment_family),
                candidate_version=str(payload.candidate_version),
            )
        if not exact_same_request:
            raise HTTPException(
                status_code=409,
                detail="A different trainer control request is already pending or running",
            )
    if created:
        await append_audit_event(
            session,
            event_type="TRAINER_CONTROL_REQUESTED",
            entity_type="trainer_control",
            entity_id=str(job.id),
            actor=operator,
            payload={
                "action": payload.action,
                "recovery_available": recovery_available,
                "recovery_reason": recovery_reason,
                "experiment_family": payload.experiment_family,
                "candidate_version": payload.candidate_version,
            },
        )
        await publish_outbox(
            session,
            event_type="TRAINER_CONTROL_REQUESTED",
            aggregate_type="trainer_control",
            aggregate_id=str(job.id),
            payload={
                "action": payload.action,
                "status": job.status,
                "experiment_family": payload.experiment_family,
                "candidate_version": payload.candidate_version,
            },
        )
    await session.commit()
    return {
        "ok": True,
        "created": created,
        "request": control_job_payload(job),
        "message": "Trainer request queued" if created else "A trainer request is already pending",
    }

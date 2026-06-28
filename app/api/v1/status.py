from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, HTTPException
from sqlalchemy import desc, func, select

from app.api.deps import SessionDep, SettingsDep
from app.db.health import current_revision, database_health
from app.db.models import DataQualityIssue, JobRun, ModelRegistry, ServiceHeartbeat
from app.ml.runtime_selection import CONTROLLED_BASELINE_NOTICE_CODES
from app.services.trainer_control import (
    TRAINER_CONTROL_JOB_NAME,
    control_job_payload,
    recovery_availability,
    trainer_heartbeat_is_fresh,
)

router = APIRouter(tags=["status"])


def candidate_diagnostics(model: object | None) -> dict[str, object] | None:
    if model is None:
        return None
    metrics = getattr(model, "metrics", None)
    metrics = metrics if isinstance(metrics, dict) else {}
    quality_gate = metrics.get("quality_gate")
    quality_gate = quality_gate if isinstance(quality_gate, dict) else {}
    reasons = quality_gate.get("reasons")
    if not isinstance(reasons, list):
        reasons = []
    artifact_text = getattr(model, "artifact_path", None)
    artifact_path = Path(artifact_text).expanduser() if artifact_text else None
    return {
        "version": getattr(model, "version", None),
        "artifact_path": str(artifact_path) if artifact_path else None,
        "artifact_exists": bool(artifact_path and artifact_path.is_file()),
        "activation_requested": metrics.get("activation_requested") is True,
        "quality_gate_passed": quality_gate.get("passed")
        if isinstance(quality_gate.get("passed"), bool)
        else None,
        "quality_gate_reasons": [str(item) for item in reasons[:10]],
        "updated_at": getattr(model, "updated_at", None).isoformat()
        if getattr(model, "updated_at", None) is not None
        else None,
    }


def orphan_model_artifacts(model_dir: Path, registry_models: list[object]) -> list[str]:
    resolved_registered: set[Path] = set()
    for model in registry_models:
        artifact_text = model if isinstance(model, (str, Path)) else getattr(model, "artifact_path", None)
        if not artifact_text:
            continue
        try:
            resolved_registered.add(Path(artifact_text).expanduser().resolve())
        except OSError:
            continue
    directory = model_dir.expanduser()
    if not directory.is_dir():
        return []
    candidates: list[tuple[float, str]] = []
    for path in directory.glob("*.joblib"):
        try:
            resolved = path.resolve()
            modified = path.stat().st_mtime
        except OSError:
            continue
        if resolved not in resolved_registered:
            candidates.append((modified, path.name))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [name for _, name in candidates[:10]]


def assess_model_runtime(
    *,
    registry_version: str | None,
    registry_type: str | None,
    artifact_ok: bool,
    worker_model: dict[str, object] | None,
    worker_notice: dict[str, object] | None,
    allow_baseline_model: bool,
) -> dict[str, object]:
    worker_model = worker_model or {}
    worker_notice = worker_notice or {}
    worker_version = worker_model.get("version")
    runtime_is_baseline = worker_model.get("baseline") is True
    runtime_matches_registry = bool(registry_version and worker_version == registry_version)
    notice_code = worker_notice.get("code")

    registered_baseline_ok = bool(
        registry_version
        and registry_type == "deterministic_baseline"
        and allow_baseline_model
        and artifact_ok
        and runtime_matches_registry
        and runtime_is_baseline
    )
    trained_model_ok = bool(
        registry_version
        and registry_type != "deterministic_baseline"
        and artifact_ok
        and runtime_matches_registry
        and not runtime_is_baseline
    )
    bootstrap_fallback_ok = bool(
        registry_version is None
        and allow_baseline_model
        and runtime_is_baseline
        and notice_code == "NO_ACTIVE_MODEL_REGISTERED"
    )
    missing_artifact_fallback_ok = bool(
        registry_version
        and registry_type != "deterministic_baseline"
        and not artifact_ok
        and allow_baseline_model
        and runtime_is_baseline
        and notice_code == "ACTIVE_MODEL_ARTIFACT_MISSING"
        and worker_notice.get("registry_version") == registry_version
    )
    fallback_active = bootstrap_fallback_ok or missing_artifact_fallback_ok
    ok = trained_model_ok or registered_baseline_ok or fallback_active
    return {
        "ok": ok,
        "runtime_matches_registry": runtime_matches_registry,
        "fallback_active": fallback_active,
        "degraded": bool(ok and runtime_is_baseline),
        "notice": worker_notice or None,
    }


def latest_service_heartbeat(
    heartbeats: list[ServiceHeartbeat],
    service_name: str,
) -> ServiceHeartbeat | None:
    return max(
        (heartbeat for heartbeat in heartbeats if heartbeat.service_name == service_name),
        key=lambda heartbeat: heartbeat.last_seen_at,
        default=None,
    )


def job_run_payload(job: JobRun | None) -> dict[str, object] | None:
    if job is None:
        return None
    return {
        "job": job.job_name,
        "scheduled_for": job.scheduled_for.isoformat(),
        "started_at": job.started_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "status": job.status,
        "details": job.details,
    }


def expected_revision() -> str:
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    return ScriptDirectory.from_config(cfg).get_current_head() or "unknown"


@router.get("/health/live")
async def live() -> dict:
    return {"ok": True, "service": "api", "time": datetime.now(UTC).isoformat()}


@router.get("/health/ready")
async def ready(session: SessionDep, settings: SettingsDep) -> dict:
    checks: dict = {}
    try:
        checks["database"] = await database_health(session)
        current = await current_revision(session)
        expected = expected_revision()
        checks["migration"] = {"current": current, "expected": expected, "ok": current == expected}
        active_model = (
            await session.execute(
                select(ModelRegistry)
                .where(ModelRegistry.active.is_(True))
                .order_by(ModelRegistry.updated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        worker = (
            await session.execute(
                select(ServiceHeartbeat)
                .where(ServiceHeartbeat.service_name == "worker")
                .order_by(desc(ServiceHeartbeat.last_seen_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        trainer = (
            await session.execute(
                select(ServiceHeartbeat)
                .where(ServiceHeartbeat.service_name == "trainer")
                .order_by(desc(ServiceHeartbeat.last_seen_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        max_age = max(settings.heartbeat_seconds * 4, 90)
        worker_fresh = bool(
            worker and (datetime.now(UTC) - worker.last_seen_at).total_seconds() <= max_age
        )
        worker_details = (worker.details or {}) if worker else {}
        worker_model = worker_details.get("model", {})
        market_sync_text = worker_details.get("last_market_sync")
        market_sync_time: datetime | None = None
        if isinstance(market_sync_text, str):
            try:
                market_sync_time = datetime.fromisoformat(market_sync_text)
            except ValueError:
                market_sync_time = None
        market_max_age = max(settings.market_poll_seconds * 3, 300)
        market_fresh = bool(
            market_sync_time
            and (datetime.now(UTC) - market_sync_time).total_seconds() <= market_max_age
        )
        worker_notice = worker_details.get("model_notice")
        controlled_model_degradation = bool(
            worker
            and worker.status == "DEGRADED"
            and isinstance(worker_notice, dict)
            and worker_notice.get("active") is True
            and worker_notice.get("code") in CONTROLLED_BASELINE_NOTICE_CODES
            and not worker_details.get("error")
        )
        worker_operational = bool(
            worker and (worker.status == "RUNNING" or controlled_model_degradation)
        )
        checks["worker"] = {
            "ok": worker_fresh and market_fresh and worker_operational,
            "last_seen_at": worker.last_seen_at.isoformat() if worker else None,
            "instance_id": worker.instance_id if worker else None,
            "status": worker.status if worker else None,
            "degraded": controlled_model_degradation,
            "model_notice": worker_notice if isinstance(worker_notice, dict) else None,
            "last_market_sync": market_sync_time.isoformat() if market_sync_time else None,
            "market_data_fresh": market_fresh,
        }
        trainer_fresh = bool(
            trainer and (datetime.now(UTC) - trainer.last_seen_at).total_seconds() <= max_age
        )
        trainer_details = (trainer.details or {}) if trainer else {}
        checks["trainer"] = {
            "ok": (not settings.auto_train_enabled)
            or (trainer_fresh and trainer.status == "RUNNING" and trainer_details.get("healthy", True)),
            "enabled": settings.auto_train_enabled,
            "last_seen_at": trainer.last_seen_at.isoformat() if trainer else None,
            "instance_id": trainer.instance_id if trainer else None,
            "status": trainer.status if trainer else None,
            "phase": trainer_details.get("phase"),
            "details": trainer_details or None,
        }

        artifact_ok = True
        artifact_detail: dict[str, object] = {}
        if active_model and active_model.model_type != "deterministic_baseline":
            artifact_path = Path(active_model.artifact_path) if active_model.artifact_path else None
            artifact_ok = bool(artifact_path and artifact_path.is_file())
            artifact_detail["path"] = str(artifact_path) if artifact_path else None
            if artifact_ok and active_model.artifact_sha256:
                actual_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
                artifact_detail["sha256"] = actual_hash
                artifact_ok = actual_hash.lower() == active_model.artifact_sha256.lower()
        model_state = assess_model_runtime(
            registry_version=active_model.version if active_model else None,
            registry_type=active_model.model_type if active_model else None,
            artifact_ok=artifact_ok,
            worker_model=worker_model if isinstance(worker_model, dict) else None,
            worker_notice=worker_notice if isinstance(worker_notice, dict) else None,
            allow_baseline_model=settings.allow_baseline_model,
        )
        checks["model"] = {
            **model_state,
            "ok": bool(model_state["ok"] and worker_fresh),
            "registry_version": active_model.version if active_model else None,
            "registry_type": active_model.model_type if active_model else None,
            "worker_runtime": worker_model or None,
            "artifact": artifact_detail or None,
        }
        blocking_issues = (
            await session.execute(
                select(func.count(DataQualityIssue.id)).where(
                    DataQualityIssue.resolved_at.is_(None),
                    DataQualityIssue.severity.in_(["CRITICAL", "HIGH"]),
                )
            )
        ).scalar_one()
        checks["data_quality"] = {"ok": blocking_issues == 0, "blocking_issues": blocking_issues}
        ok = all(item.get("ok", False) for item in checks.values())
    except Exception as exc:
        checks["exception"] = {"ok": False, "message": str(exc)}
        ok = False
    if not ok:
        raise HTTPException(status_code=503, detail={"ok": False, "checks": checks})
    return {"ok": True, "checks": checks}


@router.get("/api/v1/status")
async def status(session: SessionDep, settings: SettingsDep) -> dict:
    heartbeats = (await session.execute(select(ServiceHeartbeat))).scalars().all()
    jobs = (await session.execute(select(JobRun).order_by(desc(JobRun.started_at)).limit(20))).scalars().all()
    latest_control_job = (
        await session.execute(
            select(JobRun)
            .where(JobRun.job_name == TRAINER_CONTROL_JOB_NAME)
            .order_by(desc(JobRun.started_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    latest_training_job = (
        await session.execute(
            select(JobRun)
            .where(JobRun.job_name == "model_retraining")
            .order_by(desc(JobRun.started_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    model = (
        await session.execute(
            select(ModelRegistry)
            .where(ModelRegistry.active.is_(True))
            .order_by(ModelRegistry.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    latest_candidate = (
        await session.execute(
            select(ModelRegistry)
            .where(
                ModelRegistry.active.is_(False),
                ModelRegistry.model_type != "deterministic_baseline",
            )
            .order_by(ModelRegistry.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    registered_artifact_paths = (
        await session.execute(
            select(ModelRegistry.artifact_path).where(ModelRegistry.artifact_path.is_not(None))
        )
    ).scalars().all()
    issues = (
        (
            await session.execute(
                select(DataQualityIssue)
                .where(DataQualityIssue.resolved_at.is_(None))
                .order_by(desc(DataQualityIssue.detected_at))
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    trainer_heartbeat = latest_service_heartbeat(heartbeats, "trainer")
    worker_heartbeat = latest_service_heartbeat(heartbeats, "worker")
    worker_details = worker_heartbeat.details if worker_heartbeat else {}
    recovery_available, recovery_reason = recovery_availability(model, settings)
    artifact_path = Path(model.artifact_path).expanduser() if model and model.artifact_path else None
    artifact_exists = bool(
        model
        and (
            model.model_type == "deterministic_baseline"
            or (artifact_path is not None and artifact_path.is_file())
        )
    )

    return {
        "app_mode": settings.app_mode,
        "universe_config": {
            "mode": settings.universe_mode,
            "static_symbols": settings.symbols if settings.universe_mode == "static" else [],
            "min_age_days": settings.universe_min_age_days,
            "min_turnover_24h": settings.universe_min_turnover_24h,
            "max_spread_bps": settings.universe_max_spread_bps,
            "max_symbols": settings.universe_max_symbols,
            "refresh_seconds": settings.universe_refresh_seconds,
            "min_history_bars": settings.universe_min_history_bars,
        },
        "auto_training": {
            "enabled": settings.auto_train_enabled,
            "auto_activate": settings.auto_train_auto_activate,
            "model_type": settings.auto_train_model_type,
            "interval_hours": settings.auto_train_interval_hours,
            "minimum_new_timestamps": settings.auto_train_min_new_timestamps,
            "data_change_cooldown_hours": settings.auto_train_data_change_cooldown_hours,
            "minimum_new_rows": settings.auto_train_min_new_rows,
            "minimum_dataset_growth_ratio": settings.auto_train_min_dataset_growth_ratio,
            "minimum_new_symbols": settings.auto_train_min_new_symbols,
            "minimum_universe_change_ratio": settings.auto_train_min_universe_change_ratio,
            "minimum_bars_per_symbol": settings.auto_train_min_bars_per_symbol,
            "minimum_symbol_coverage_ratio": settings.auto_train_min_symbol_coverage_ratio,
            "lookback_days": settings.auto_train_lookback_days,
            "max_symbols": settings.auto_train_max_symbols,
            "require_improvement": settings.auto_train_require_improvement,
        },
        "history_backfill": {
            "enabled": settings.history_backfill_enabled,
            "target_days": settings.history_backfill_target_days,
            "interval_seconds": settings.history_backfill_interval_seconds,
            "symbols_per_cycle": settings.history_backfill_symbols_per_cycle,
            "pages_per_symbol": settings.history_backfill_pages_per_symbol,
            "page_size": settings.history_backfill_page_size,
        },
        "database_revision": await current_revision(session),
        "expected_revision": expected_revision(),
        "active_model": {
            "version": model.version if model else None,
            "type": model.model_type if model else None,
            "feature_schema": model.feature_schema_version if model else None,
            "artifact_path": model.artifact_path if model else None,
            "artifact_sha256": model.artifact_sha256 if model else None,
            "artifact_exists": artifact_exists,
            "metrics": model.metrics if model else None,
            "training_data_profile": (model.metrics or {}).get("training_data_profile")
            if model
            else None,
            "worker_runtime": worker_details.get("model"),
            "worker_notice": worker_details.get("model_notice"),
            "latest_candidate": candidate_diagnostics(latest_candidate),
            "orphan_artifacts": orphan_model_artifacts(settings.model_dir, registered_artifact_paths),
        },
        "trainer_control": {
            "trainer_online": trainer_heartbeat_is_fresh(trainer_heartbeat, settings),
            "recovery_available": recovery_available,
            "recovery_reason": recovery_reason,
            "latest_request": control_job_payload(latest_control_job),
            "latest_training_job": job_run_payload(latest_training_job),
        },
        "heartbeats": [
            {
                "service": h.service_name,
                "instance": h.instance_id,
                "last_seen_at": h.last_seen_at.isoformat(),
                "status": h.status,
                "details": h.details,
            }
            for h in heartbeats
        ],
        "recent_jobs": [job_run_payload(job) for job in jobs],
        "data_quality_issues": [
            {
                "id": str(i.id),
                "severity": i.severity,
                "code": i.code,
                "symbol": i.symbol,
                "detected_at": i.detected_at.isoformat(),
                "details": i.details,
            }
            for i in issues
        ],
    }

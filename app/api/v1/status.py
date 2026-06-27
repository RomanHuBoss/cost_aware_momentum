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

router = APIRouter(tags=["status"])


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
        checks["worker"] = {
            "ok": worker_fresh and market_fresh and worker.status == "RUNNING",
            "last_seen_at": worker.last_seen_at.isoformat() if worker else None,
            "instance_id": worker.instance_id if worker else None,
            "status": worker.status if worker else None,
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

        expected_version = active_model.version if active_model else "baseline-momentum-v1"
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
        baseline_allowed = not (
            active_model
            and active_model.model_type == "deterministic_baseline"
            and not settings.allow_baseline_model
        )
        runtime_matches = bool(worker_model and worker_model.get("version") == expected_version)
        checks["model"] = {
            "ok": bool(active_model)
            and artifact_ok
            and baseline_allowed
            and worker_fresh
            and runtime_matches,
            "registry_version": active_model.version if active_model else None,
            "registry_type": active_model.model_type if active_model else None,
            "worker_runtime": worker_model or None,
            "runtime_matches_registry": runtime_matches,
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
    model = (
        await session.execute(
            select(ModelRegistry)
            .where(ModelRegistry.active.is_(True))
            .order_by(ModelRegistry.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
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
            "lookback_days": settings.auto_train_lookback_days,
            "max_symbols": settings.auto_train_max_symbols,
            "require_improvement": settings.auto_train_require_improvement,
        },
        "database_revision": await current_revision(session),
        "expected_revision": expected_revision(),
        "active_model": {
            "version": model.version if model else None,
            "type": model.model_type if model else None,
            "feature_schema": model.feature_schema_version if model else None,
            "artifact_path": model.artifact_path if model else None,
            "artifact_sha256": model.artifact_sha256 if model else None,
            "metrics": model.metrics if model else None,
            "worker_runtime": next(
                (
                    heartbeat.details.get("model")
                    for heartbeat in heartbeats
                    if heartbeat.service_name == "worker" and heartbeat.details.get("model")
                ),
                None,
            ),
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
        "recent_jobs": [
            {
                "job": j.job_name,
                "scheduled_for": j.scheduled_for.isoformat(),
                "started_at": j.started_at.isoformat(),
                "finished_at": j.finished_at.isoformat() if j.finished_at else None,
                "status": j.status,
                "details": j.details,
            }
            for j in jobs
        ],
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

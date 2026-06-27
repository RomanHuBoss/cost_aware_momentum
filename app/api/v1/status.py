from __future__ import annotations

from datetime import UTC, datetime

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
            await session.execute(select(ModelRegistry).where(ModelRegistry.active.is_(True)).limit(1))
        ).scalar_one_or_none()
        checks["model"] = {
            "ok": bool(active_model) or settings.allow_baseline_model,
            "version": active_model.version if active_model else "baseline-momentum-v1",
        }
        worker = (
            await session.execute(
                select(ServiceHeartbeat)
                .where(ServiceHeartbeat.service_name == "worker")
                .order_by(desc(ServiceHeartbeat.last_seen_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        max_age = max(settings.heartbeat_seconds * 4, 90)
        checks["worker"] = {
            "ok": bool(worker and (datetime.now(UTC) - worker.last_seen_at).total_seconds() <= max_age),
            "last_seen_at": worker.last_seen_at.isoformat() if worker else None,
            "instance_id": worker.instance_id if worker else None,
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
        await session.execute(select(ModelRegistry).where(ModelRegistry.active.is_(True)).limit(1))
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
        "database_revision": await current_revision(session),
        "expected_revision": expected_revision(),
        "active_model": {
            "version": model.version if model else "baseline-momentum-v1",
            "type": model.model_type if model else "deterministic_baseline",
            "feature_schema": model.feature_schema_version if model else "hourly-core-v1",
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

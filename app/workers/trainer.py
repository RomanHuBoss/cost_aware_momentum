from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, func, select, text
from sqlalchemy.dialects.postgresql import insert

from app.asyncio_compat import run_with_compatible_event_loop
from app.config import get_settings
from app.db.engine import SessionFactory, dispose_engine, engine
from app.db.locks import lock_key
from app.db.models import Candle, JobRun, ModelRegistry, ServiceHeartbeat
from app.logging import configure_logging
from app.ml.lifecycle import (
    build_model_candidate,
    evaluate_quality_gate,
    incumbent_from_registry,
    load_training_candles,
    register_model_candidate,
)
from scripts.model_registry import activate_registered_model

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


class BackgroundTrainer:
    def __init__(self) -> None:
        self.stop_event = asyncio.Event()
        self.state: dict[str, object] = {
            "phase": "STARTING",
            "healthy": True,
            "enabled": settings.auto_train_enabled,
            "last_result": None,
            "next_check_at": None,
        }

    def request_stop(self) -> None:
        self.stop_event.set()

    async def heartbeat(self) -> None:
        phase = self.state.get("phase")
        if phase in {"STOPPED", "DISABLED"}:
            status = str(phase)
        else:
            status = "RUNNING" if self.state.get("healthy", True) else "DEGRADED"
        async with SessionFactory() as session:
            now = datetime.now(UTC)
            statement = (
                insert(ServiceHeartbeat)
                .values(
                    service_name="trainer",
                    instance_id=settings.trainer_id,
                    last_seen_at=now,
                    status=status,
                    details=dict(self.state),
                )
                .on_conflict_do_update(
                    index_elements=[ServiceHeartbeat.service_name, ServiceHeartbeat.instance_id],
                    set_={"last_seen_at": now, "status": status, "details": dict(self.state)},
                )
            )
            await session.execute(statement)
            await session.commit()

    async def heartbeat_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                await self.heartbeat()
            except Exception:
                logger.exception("Trainer heartbeat failed")
            with suppress(TimeoutError):
                await asyncio.wait_for(self.stop_event.wait(), timeout=settings.heartbeat_seconds)

    async def active_model(self) -> ModelRegistry | None:
        async with SessionFactory() as session:
            return (
                await session.execute(
                    select(ModelRegistry)
                    .where(ModelRegistry.active.is_(True))
                    .order_by(desc(ModelRegistry.updated_at))
                    .limit(1)
                )
            ).scalar_one_or_none()

    async def latest_attempt(self) -> JobRun | None:
        async with SessionFactory() as session:
            return (
                await session.execute(
                    select(JobRun)
                    .where(JobRun.job_name == "model_retraining")
                    .order_by(desc(JobRun.started_at))
                    .limit(1)
                )
            ).scalar_one_or_none()

    async def latest_candle_time(self) -> datetime | None:
        async with SessionFactory() as session:
            return (
                await session.execute(
                    select(func.max(Candle.open_time)).where(
                        Candle.interval == "60",
                        Candle.price_type == "last",
                        Candle.confirmed.is_(True),
                    )
                )
            ).scalar_one_or_none()

    async def timestamp_count(
        self,
        after: datetime | None = None,
        before_or_at: datetime | None = None,
    ) -> int:
        async with SessionFactory() as session:
            query = select(func.count(func.distinct(Candle.open_time))).where(
                Candle.interval == "60",
                Candle.price_type == "last",
                Candle.confirmed.is_(True),
            )
            if after is not None:
                query = query.where(Candle.open_time > after)
            if before_or_at is not None:
                query = query.where(Candle.open_time <= before_or_at)
            return int((await session.execute(query)).scalar_one() or 0)

    async def due_reason(self) -> tuple[bool, dict[str, object]]:
        now = datetime.now(UTC)
        active = await self.active_model()
        latest = await self.latest_attempt()

        if latest is not None:
            age = now - latest.started_at
            wait = timedelta(
                hours=(
                    settings.auto_train_interval_hours
                    if latest.status == "SUCCESS"
                    else settings.auto_train_retry_hours
                )
            )
            if age < wait:
                return False, {
                    "reason": "training_interval_not_elapsed",
                    "last_status": latest.status,
                    "last_started_at": latest.started_at.isoformat(),
                    "next_due_at": (latest.started_at + wait).isoformat(),
                }

        latest_candle_time = await self.latest_candle_time()
        label_cutoff = (
            latest_candle_time - timedelta(hours=settings.default_horizon_hours)
            if latest_candle_time
            else None
        )

        if active and active.model_type != "deterministic_baseline" and active.training_end:
            new_timestamps = await self.timestamp_count(active.training_end, label_cutoff)
            if new_timestamps < settings.auto_train_min_new_timestamps:
                return False, {
                    "reason": "not_enough_new_labeled_time",
                    "active_version": active.version,
                    "active_training_end": active.training_end.isoformat(),
                    "new_timestamps": new_timestamps,
                    "required_new_timestamps": settings.auto_train_min_new_timestamps,
                    "label_cutoff": label_cutoff.isoformat() if label_cutoff else None,
                }
            return True, {
                "reason": "scheduled_retraining",
                "active_version": active.version,
                "new_timestamps": new_timestamps,
                "label_cutoff": label_cutoff.isoformat() if label_cutoff else None,
            }

        total_timestamps = await self.timestamp_count(before_or_at=label_cutoff)
        minimum_bootstrap = 300 + settings.default_horizon_hours + 72
        if total_timestamps < minimum_bootstrap:
            return False, {
                "reason": "not_enough_history_for_bootstrap",
                "timestamps": total_timestamps,
                "required_timestamps": minimum_bootstrap,
            }
        return True, {
            "reason": "bootstrap_training",
            "active_version": active.version if active else None,
            "timestamps": total_timestamps,
        }

    async def create_job(self, scheduled_for: datetime, details: dict[str, object]) -> JobRun:
        async with SessionFactory() as session, session.begin():
            job = JobRun(
                job_name="model_retraining",
                scheduled_for=scheduled_for,
                started_at=datetime.now(UTC),
                status="RUNNING",
                worker_id=settings.trainer_id,
                details=details,
            )
            session.add(job)
            await session.flush()
            return job

    async def finish_job(
        self,
        job_id,
        *,
        status: str,
        details: dict[str, object],
    ) -> None:
        async with SessionFactory() as session, session.begin():
            job = (
                await session.execute(select(JobRun).where(JobRun.id == job_id).with_for_update())
            ).scalar_one()
            job.status = status
            job.finished_at = datetime.now(UTC)
            job.details = details

    async def run_training_once(self, trigger: dict[str, object]) -> dict[str, object]:
        scheduled_for = datetime.now(UTC).replace(microsecond=0)
        lock = lock_key("background_model_training", str(settings.default_horizon_hours))

        async with engine.connect() as connection:
            acquired = bool(
                (await connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": lock})).scalar()
            )
            await connection.commit()
            if not acquired:
                return {"skipped": "another_trainer_holds_lock"}
            try:
                job = await self.create_job(scheduled_for, {"trigger": trigger})
                try:
                    active = await self.active_model()
                    incumbent = incumbent_from_registry(active)
                    symbols = settings.symbols if settings.universe_mode == "static" else None
                    self.state.update(
                        {
                            "phase": "LOADING_DATA",
                            "healthy": True,
                            "active_version_before_training": active.version if active else None,
                        }
                    )
                    candles = await load_training_candles(
                        symbols,
                        lookback_days=settings.auto_train_lookback_days,
                        max_symbols=settings.auto_train_max_symbols,
                    )
                    self.state["phase"] = "FITTING"
                    candidate = await asyncio.to_thread(
                        build_model_candidate,
                        candles,
                        horizon=settings.default_horizon_hours,
                        model_type=settings.auto_train_model_type,
                        model_dir=settings.model_dir,
                        incumbent=incumbent,
                        source="background_trainer",
                    )
                    gate = evaluate_quality_gate(candidate, settings)
                    can_activate = bool(
                        settings.auto_train_auto_activate
                        and gate["passed"]
                        and settings.active_model_path is None
                    )
                    self.state["phase"] = "REGISTERING"
                    registry = await register_model_candidate(
                        candidate,
                        source="background_trainer",
                        quality_gate=gate,
                        activation_requested=can_activate,
                        actor=settings.trainer_id,
                    )

                    activation: dict[str, object] | None = None
                    activation_skipped: str | None = None
                    if can_activate:
                        self.state["phase"] = "ACTIVATING"
                        activation = await activate_registered_model(
                            candidate.version,
                            actor=settings.trainer_id,
                            expected_previous_version=active.version if active else None,
                        )
                    elif settings.active_model_path is not None:
                        activation_skipped = "ACTIVE_MODEL_PATH override is configured"
                    elif not settings.auto_train_auto_activate:
                        activation_skipped = "AUTO_TRAIN_AUTO_ACTIVATE=false"
                    elif not gate["passed"]:
                        activation_skipped = "quality_gate_failed"

                    result = {
                        "trigger": trigger,
                        "candidate_registry_id": str(registry.id),
                        "candidate_version": candidate.version,
                        "artifact_path": str(candidate.path),
                        "training_start": candidate.training_start.isoformat(),
                        "training_end": candidate.training_end.isoformat(),
                        "dataset_rows": candidate.dataset_rows,
                        "unique_timestamps": candidate.unique_timestamps,
                        "symbol_count": candidate.symbol_count,
                        "symbol_sample": list(candidate.symbol_sample),
                        "metrics": candidate.metrics,
                        "incumbent_version": candidate.incumbent_version,
                        "incumbent_metrics_same_holdout": candidate.incumbent_metrics,
                        "quality_gate": gate,
                        "activated": activation is not None,
                        "activation": activation,
                        "activation_skipped": activation_skipped,
                    }
                    await self.finish_job(job.id, status="SUCCESS", details=result)
                    self.state.update(
                        {
                            "phase": "WAITING",
                            "healthy": True,
                            "last_result": result,
                            "active_version_before_training": None,
                        }
                    )
                    logger.info(
                        "Background model training completed",
                        extra={
                            "version": candidate.version,
                            "gate_passed": gate["passed"],
                            "activated": activation is not None,
                        },
                    )
                    return result
                except Exception as exc:
                    details = {"trigger": trigger, "error": str(exc)}
                    await self.finish_job(job.id, status="FAILED", details=details)
                    self.state.update(
                        {
                            "phase": "ERROR",
                            "healthy": False,
                            "last_result": details,
                            "active_version_before_training": None,
                        }
                    )
                    logger.exception("Background model training failed")
                    return details
            finally:
                await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock})
                await connection.commit()

    async def training_loop(self) -> None:
        if settings.auto_train_initial_delay_seconds:
            self.state["phase"] = "INITIAL_DELAY"
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    self.stop_event.wait(), timeout=settings.auto_train_initial_delay_seconds
                )
        while not self.stop_event.is_set():
            try:
                due, trigger = await self.due_reason()
                if due:
                    await self.run_training_once(trigger)
                else:
                    self.state.update(
                        {
                            "phase": "WAITING",
                            "healthy": True,
                            "wait_reason": trigger,
                        }
                    )
            except Exception as exc:
                self.state.update(
                    {
                        "phase": "ERROR",
                        "healthy": False,
                        "last_result": {"error": str(exc)},
                    }
                )
                logger.exception("Trainer scheduling iteration failed")

            next_check = datetime.now(UTC) + timedelta(seconds=settings.auto_train_check_seconds)
            self.state["next_check_at"] = next_check.isoformat()
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    self.stop_event.wait(), timeout=settings.auto_train_check_seconds
                )

    async def run(self) -> None:
        if not settings.auto_train_enabled:
            self.state.update({"phase": "DISABLED", "healthy": True})
            await self.heartbeat()
            return
        heartbeat_task = asyncio.create_task(self.heartbeat_loop())
        try:
            await self.training_loop()
        finally:
            self.state.update({"phase": "STOPPED", "healthy": True})
            await self.heartbeat()
            self.stop_event.set()
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
            await dispose_engine()


async def async_main() -> None:
    trainer = BackgroundTrainer()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, trainer.request_stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_args: loop.call_soon_threadsafe(trainer.request_stop))
    await trainer.run()


def run() -> None:
    run_with_compatible_event_loop(async_main())


if __name__ == "__main__":
    run()

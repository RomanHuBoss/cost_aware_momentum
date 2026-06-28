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
from app.json_utils import json_compatible
from app.logging import configure_logging
from app.ml.data_profile import TrainingDataProfile, compare_training_profiles
from app.ml.lifecycle import (
    build_model_candidate,
    evaluate_quality_gate,
    incumbent_from_registry,
    load_training_candles,
    load_training_data_profile,
    policy_evaluation_config,
    register_and_activate_model_candidate,
    register_model_candidate,
)
from app.ml.runtime_selection import recoverable_registry_artifact_notice

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

BOOTSTRAP_TRIGGER_REASONS = frozenset({"bootstrap_training", "bootstrap_recovery"})


def _job_trigger(details: object) -> dict[str, object] | None:
    if not isinstance(details, dict):
        return None
    trigger = details.get("trigger")
    return trigger if isinstance(trigger, dict) else None


def _same_bootstrap_episode(latest: JobRun, trigger: dict[str, object]) -> bool:
    """Return whether a prior job belongs to the current no-model recovery episode.

    A stale scheduled/data-change failure must not delay recovery after the active
    artifact disappears.  Conversely, repeated failures for the same missing or
    baseline incumbent need a bounded backoff to avoid a tight training loop.
    """

    current_reason = str(trigger.get("reason") or "")
    if current_reason not in BOOTSTRAP_TRIGGER_REASONS:
        return False
    previous = _job_trigger(latest.details)
    if previous is None or str(previous.get("reason") or "") not in BOOTSTRAP_TRIGGER_REASONS:
        return False
    return previous.get("active_version") == trigger.get("active_version")


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
                    details=json_compatible(self.state),
                )
                .on_conflict_do_update(
                    index_elements=[ServiceHeartbeat.service_name, ServiceHeartbeat.instance_id],
                    set_={"last_seen_at": now, "status": status, "details": json_compatible(self.state)},
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

    async def current_training_profile(self) -> TrainingDataProfile:
        symbols = settings.symbols if settings.universe_mode == "static" else None
        return await load_training_data_profile(
            symbols,
            lookback_days=settings.auto_train_lookback_days,
            max_symbols=settings.auto_train_max_symbols,
            horizon=settings.default_horizon_hours,
            minimum_rows_for_coverage=settings.auto_train_min_bars_per_symbol,
        )

    async def due_reason(self) -> tuple[bool, dict[str, object]]:
        now = datetime.now(UTC)
        active = await self.active_model()
        latest = await self.latest_attempt()
        profile = await self.current_training_profile()
        minimum_bootstrap = 300 + settings.default_horizon_hours + 72
        if profile.unique_timestamps < minimum_bootstrap:
            return False, {
                "reason": "not_enough_history_for_bootstrap",
                "timestamps": profile.unique_timestamps,
                "required_timestamps": minimum_bootstrap,
                "training_data_profile": profile.to_dict(),
            }
        if profile.coverage_ratio < settings.auto_train_min_symbol_coverage_ratio:
            return False, {
                "reason": "insufficient_symbol_history_coverage",
                "coverage_ratio": profile.coverage_ratio,
                "required_coverage_ratio": settings.auto_train_min_symbol_coverage_ratio,
                "covered_symbols": profile.covered_symbols,
                "symbol_count": profile.symbol_count,
                "minimum_rows_per_symbol": settings.auto_train_min_bars_per_symbol,
                "training_data_profile": profile.to_dict(),
            }

        recovery_notice = (
            None
            if settings.active_model_path is not None
            else recoverable_registry_artifact_notice(
                active,
                allow_baseline_model=settings.allow_baseline_model,
                app_mode=settings.app_mode,
            )
        )
        active_profile = TrainingDataProfile.from_mapping(
            (active.metrics or {}).get("training_data_profile") if active else None
        )
        comparison = compare_training_profiles(
            profile,
            active_profile,
            minimum_new_rows=settings.auto_train_min_new_rows,
            minimum_growth_ratio=settings.auto_train_min_dataset_growth_ratio,
            minimum_new_symbols=settings.auto_train_min_new_symbols,
            minimum_universe_change_ratio=settings.auto_train_min_universe_change_ratio,
        )
        label_cutoff = profile.end_time
        new_timestamps = 0
        if active and active.training_end and label_cutoff:
            new_timestamps = await self.timestamp_count(active.training_end, label_cutoff)

        if recovery_notice is not None:
            trigger = {
                "reason": "bootstrap_recovery",
                "active_version": active.version if active else None,
                "recovery_notice": recovery_notice,
                "training_data_profile": profile.to_dict(),
            }
            trigger_kind = "bootstrap"
        elif active is None or active.model_type == "deterministic_baseline":
            trigger = {
                "reason": "bootstrap_training",
                "active_version": active.version if active else None,
                "training_data_profile": profile.to_dict(),
            }
            trigger_kind = "bootstrap"
        elif comparison["material_change"]:
            trigger = {
                "reason": "material_training_dataset_change",
                "active_version": active.version,
                "new_timestamps": new_timestamps,
                "dataset_change": comparison,
                "training_data_profile": profile.to_dict(),
            }
            trigger_kind = "data_change"
        elif new_timestamps >= settings.auto_train_min_new_timestamps:
            trigger = {
                "reason": "scheduled_retraining",
                "active_version": active.version,
                "active_training_end": active.training_end.isoformat()
                if active.training_end
                else None,
                "new_timestamps": new_timestamps,
                "required_new_timestamps": settings.auto_train_min_new_timestamps,
                "label_cutoff": label_cutoff.isoformat() if label_cutoff else None,
                "dataset_change": comparison,
                "training_data_profile": profile.to_dict(),
            }
            trigger_kind = "scheduled"
        else:
            return False, {
                "reason": "not_enough_new_or_changed_training_data",
                "active_version": active.version,
                "active_training_end": active.training_end.isoformat()
                if active.training_end
                else None,
                "new_timestamps": new_timestamps,
                "required_new_timestamps": settings.auto_train_min_new_timestamps,
                "label_cutoff": label_cutoff.isoformat() if label_cutoff else None,
                "dataset_change": comparison,
                "training_data_profile": profile.to_dict(),
            }

        if latest is not None:
            age = now - latest.started_at
            if trigger_kind == "bootstrap" and not _same_bootstrap_episode(latest, trigger):
                return True, trigger

            if trigger_kind == "bootstrap" and latest.status != "SUCCESS":
                wait = timedelta(minutes=settings.auto_train_recovery_retry_minutes)
                if age < wait:
                    return False, {
                        "reason": "training_recovery_backoff_not_elapsed",
                        "pending_trigger": trigger,
                        "last_status": latest.status,
                        "last_started_at": latest.started_at.isoformat(),
                        "cooldown_minutes": settings.auto_train_recovery_retry_minutes,
                        "next_due_at": (latest.started_at + wait).isoformat(),
                    }
                return True, trigger

            if latest.status != "SUCCESS":
                wait_hours = settings.auto_train_retry_hours
            elif trigger_kind == "data_change" or (
                trigger_kind == "bootstrap"
                and isinstance(latest.details, dict)
                and latest.details.get("activation_skipped") == "quality_gate_failed"
            ):
                wait_hours = settings.auto_train_data_change_cooldown_hours
            else:
                wait_hours = settings.auto_train_interval_hours
            wait = timedelta(hours=wait_hours)
            if age < wait:
                return False, {
                    "reason": "training_cooldown_not_elapsed",
                    "pending_trigger": trigger,
                    "last_status": latest.status,
                    "last_started_at": latest.started_at.isoformat(),
                    "cooldown_hours": wait_hours,
                    "next_due_at": (latest.started_at + wait).isoformat(),
                }
        return True, trigger

    async def create_job(self, scheduled_for: datetime, details: dict[str, object]) -> JobRun:
        async with SessionFactory() as session, session.begin():
            job = JobRun(
                job_name="model_retraining",
                scheduled_for=scheduled_for,
                started_at=datetime.now(UTC),
                status="RUNNING",
                worker_id=settings.trainer_id,
                details=json_compatible(details),
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
            job.details = json_compatible(details)

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
                    incumbent_recovery = recoverable_registry_artifact_notice(
                        active,
                        allow_baseline_model=settings.allow_baseline_model,
                        app_mode=settings.app_mode,
                    )
                    incumbent = None if incumbent_recovery else incumbent_from_registry(active)
                    if incumbent_recovery:
                        logger.warning(
                            "Missing active artifact is treated as bootstrap baseline for training",
                            extra={"incumbent_recovery": incumbent_recovery},
                        )
                    symbols = settings.symbols if settings.universe_mode == "static" else None
                    self.state.update(
                        {
                            "phase": "LOADING_DATA",
                            "healthy": True,
                            "active_version_before_training": active.version if active else None,
                            "incumbent_recovery": incumbent_recovery,
                        }
                    )
                    candles = await load_training_candles(
                        symbols,
                        lookback_days=settings.auto_train_lookback_days,
                        max_symbols=settings.auto_train_max_symbols,
                    )
                    trigger_profile = trigger.get("training_data_profile")
                    expected_symbols = (
                        [str(item) for item in trigger_profile.get("symbols", []) if item]
                        if isinstance(trigger_profile, dict)
                        else None
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
                        minimum_rows_for_coverage=settings.auto_train_min_bars_per_symbol,
                        policy_config=policy_evaluation_config(settings),
                        expected_symbols=expected_symbols,
                    )
                    gate = evaluate_quality_gate(candidate, settings)
                    can_activate = bool(
                        settings.auto_train_auto_activate
                        and gate["passed"]
                        and settings.active_model_path is None
                    )
                    recovery_activation_skipped: str | None = None
                    if can_activate and incumbent_recovery:
                        current_active = await self.active_model()
                        current_recovery = recoverable_registry_artifact_notice(
                            current_active,
                            allow_baseline_model=settings.allow_baseline_model,
                            app_mode=settings.app_mode,
                        )
                        if (
                            current_active is None
                            or active is None
                            or current_active.version != active.version
                            or current_recovery is None
                        ):
                            can_activate = False
                            recovery_activation_skipped = (
                                "incumbent_recovery_condition_changed_during_training"
                            )
                    self.state["phase"] = "REGISTERING"
                    activation: dict[str, object] | None = None
                    activation_skipped: str | None = None
                    if can_activate:
                        self.state["phase"] = "ACTIVATING"
                        registry, activation = await register_and_activate_model_candidate(
                            candidate,
                            source="background_trainer",
                            quality_gate=gate,
                            actor=settings.trainer_id,
                            expected_previous_version=active.version if active else None,
                            expected_horizon_hours=settings.default_horizon_hours,
                            incumbent_recovery=incumbent_recovery,
                        )
                    else:
                        registry = await register_model_candidate(
                            candidate,
                            source="background_trainer",
                            quality_gate=gate,
                            activation_requested=False,
                            actor=settings.trainer_id,
                            incumbent_recovery=incumbent_recovery,
                        )
                        if recovery_activation_skipped is not None:
                            activation_skipped = recovery_activation_skipped
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
                        "incumbent_recovery": incumbent_recovery,
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
                self.state["phase"] = "CHECKING_DATA"
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

from __future__ import annotations

import asyncio
import hashlib
import logging
import signal
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import desc, func, select, text
from sqlalchemy.dialects.postgresql import insert

from app.asyncio_compat import run_with_compatible_event_loop
from app.config import get_settings
from app.db.engine import SessionFactory, dispose_engine, engine
from app.db.locks import lock_key
from app.db.models import Candle, JobRun, ModelRegistry, ServiceHeartbeat
from app.json_utils import json_compatible
from app.logging import configure_logging
from app.ml.artifact_store import ensure_registry_artifact_durable
from app.ml.data_profile import TrainingDataProfile, compare_training_profiles
from app.ml.lifecycle import (
    build_model_candidate,
    evaluate_quality_gate,
    incumbent_from_registry,
    load_training_data_profile,
    load_training_market_data,
    policy_evaluation_config,
    register_and_activate_model_candidate,
    register_model_candidate,
    require_passed_quality_gate,
)
from app.ml.runtime_selection import registry_artifact_recovery_notice
from app.ml.training import minimum_hourly_history_timestamps_for_quality_gate
from app.services.audit import publish_outbox
from app.services.automatic_experiment import (
    CandidateArtifactContractError,
    candidate_artifact_contract,
    close_candidate_activation_request,
    experiment_gate_is_terminal,
    orchestrate_automatic_experiment,
)
from app.services.model_activation import activate_registered_model
from app.services.model_promotion import (
    blocked_experiment_promotion_gate,
    evaluate_experiment_promotion_gate,
    experiment_policy_binding_from_settings,
    require_experiment_policy_binding,
)
from app.services.trainer_control import (
    TRAINER_CONTROL_ACTIONS,
    TRAINER_CONTROL_JOB_NAME,
    acquire_trainer_control_lock,
    recover_stale_trainer_control,
)

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

BOOTSTRAP_TRIGGER_REASONS = frozenset({"bootstrap_training", "bootstrap_recovery", "operator_recovery"})
TRAINER_CONTROL_POLL_SECONDS = 2.0


def _job_trigger(details: object) -> dict[str, object] | None:
    if not isinstance(details, dict):
        return None
    trigger = details.get("trigger")
    return trigger if isinstance(trigger, dict) else None


def require_training_trigger_profile(
    trigger: dict[str, object],
    *,
    horizon_hours: int,
) -> tuple[TrainingDataProfile, list[str], datetime]:
    """Resolve the exact immutable cohort and data cutoff approved by preflight.

    Background training must consume the same symbols that caused ``due_reason``
    to authorize the run.  The profile end is the latest label-eligible decision
    timestamp, so the raw candle upper bound includes exactly one future label
    horizon and excludes any universe/data expansion that arrives after preflight.
    """

    profile = TrainingDataProfile.from_mapping(
        trigger.get("training_data_profile")
        if isinstance(trigger.get("training_data_profile"), dict)
        else None
    )
    if profile is None:
        raise RuntimeError("Background training requires a valid preflight training_data_profile")
    if not profile.symbols:
        raise RuntimeError("Background training preflight profile contains no symbols")
    if profile.end_time is None:
        raise RuntimeError("Background training preflight profile has no label cutoff")
    if isinstance(horizon_hours, bool) or not isinstance(horizon_hours, int) or horizon_hours <= 0:
        raise ValueError("horizon_hours must be a positive integer")
    symbols = list(profile.symbols)
    maximum_open_time = profile.end_time + timedelta(hours=horizon_hours)
    return profile, symbols, maximum_open_time


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
            "control_request": None,
            "last_control_result": None,
            "automatic_experiment": None,
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

    async def heartbeat_best_effort(self) -> None:
        try:
            await self.heartbeat()
        except Exception:
            logger.exception("Immediate trainer heartbeat failed")

    async def heartbeat_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                await self.heartbeat()
            except Exception:
                logger.exception("Trainer heartbeat failed")
            with suppress(TimeoutError):
                await asyncio.wait_for(self.stop_event.wait(), timeout=settings.heartbeat_seconds)

    async def active_model(self) -> ModelRegistry | None:
        async with SessionFactory() as session, session.begin():
            registry = (
                await session.execute(
                    select(ModelRegistry)
                    .where(ModelRegistry.active.is_(True))
                    .order_by(desc(ModelRegistry.updated_at))
                    .limit(1)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if registry is not None and settings.active_model_path is None:
                await ensure_registry_artifact_durable(
                    session,
                    registry,
                    model_dir=settings.model_dir,
                    actor=settings.trainer_id,
                )
            return registry

    async def _pending_auto_activation_candidate(self) -> ModelRegistry | None:
        """Return the newest safe background candidate awaiting governed activation."""

        async with SessionFactory() as session, session.begin():
            candidates = (
                await session.execute(
                    select(ModelRegistry)
                    .where(
                        ModelRegistry.active.is_(False),
                        ModelRegistry.model_type != "deterministic_baseline",
                    )
                    .order_by(desc(ModelRegistry.created_at))
                    .limit(50)
                    .with_for_update()
                )
            ).scalars().all()
            for candidate in candidates:
                metrics = candidate.metrics if isinstance(candidate.metrics, dict) else {}
                if metrics.get("source") != "background_trainer":
                    continue
                if metrics.get("activation_requested") is not True:
                    continue
                quality_gate = metrics.get("quality_gate")
                try:
                    require_passed_quality_gate(
                        quality_gate if isinstance(quality_gate, dict) else None
                    )
                except RuntimeError:
                    continue
                await ensure_registry_artifact_durable(
                    session,
                    candidate,
                    model_dir=settings.model_dir,
                    actor=settings.trainer_id,
                )
                return candidate
        return None

    @staticmethod
    def _candidate_artifact_rejection(
        candidate: ModelRegistry,
    ) -> tuple[str | None, dict[str, object]]:
        try:
            candidate_artifact_contract(candidate, settings)
        except CandidateArtifactContractError as exc:
            return exc.code, {"error": str(exc)}
        return None, {}

    async def _close_unusable_candidate(
        self,
        candidate: ModelRegistry,
        *,
        reason: str,
        details: dict[str, object] | None = None,
    ) -> dict[str, object]:
        failure_gate = {
            "schema": "automatic-experiment-failure-gate-v1",
            "passed": False,
            "report_status": reason.upper(),
            "reasons": [reason],
            "experiment_family": None,
            **(details or {}),
        }
        closure = await close_candidate_activation_request(
            candidate_version=candidate.version,
            experiment_family=None,
            experiment_gate=failure_gate,
            actor=settings.trainer_id,
        )
        return {
            "status": "REJECTED",
            "reason": reason,
            "candidate_version": candidate.version,
            "experiment_promotion_gate": failure_gate,
            "closure": closure,
            "continue_scheduling": True,
        }

    async def reconcile_pending_activation(self) -> dict[str, object] | None:
        """Recheck staged experiment evidence for an already registered candidate."""

        if not settings.auto_train_auto_activate or settings.active_model_path is not None:
            return None
        candidate = await self._pending_auto_activation_candidate()
        if candidate is None:
            return None

        metrics = candidate.metrics if isinstance(candidate.metrics, dict) else {}
        horizon = metrics.get("horizon_hours")
        if isinstance(horizon, bool):
            horizon = None
        try:
            horizon_hours = int(horizon)
        except (TypeError, ValueError):
            horizon_hours = 0
        if horizon_hours != settings.default_horizon_hours:
            return await self._close_unusable_candidate(
                candidate,
                reason="candidate_horizon_mismatch",
                details={
                    "candidate_horizon_hours": horizon_hours,
                    "expected_horizon_hours": settings.default_horizon_hours,
                },
            )
        artifact_reason, artifact_details = self._candidate_artifact_rejection(candidate)
        if artifact_reason is not None:
            return await self._close_unusable_candidate(
                candidate,
                reason=artifact_reason,
                details=artifact_details,
            )
        artifact_sha256 = str(candidate.artifact_sha256).strip().lower()
        try:
            policy_binding = require_experiment_policy_binding(
                metrics.get("promotion_policy_binding")
            )
        except RuntimeError as exc:
            return await self._close_unusable_candidate(
                candidate,
                reason="candidate_policy_binding_missing_or_invalid",
                details={"error": str(exc)},
            )
        configured_policy_binding = experiment_policy_binding_from_settings(settings)
        if policy_binding != configured_policy_binding:
            failure_gate = {
                "schema": "automatic-experiment-failure-gate-v1",
                "passed": False,
                "report_status": "CANDIDATE_POLICY_BINDING_STALE",
                "reasons": ["candidate_policy_binding_mismatch_current_settings"],
                "experiment_family": None,
                "expected_policy_binding": policy_binding,
                "configured_policy_binding": configured_policy_binding,
            }
            closure = await close_candidate_activation_request(
                candidate_version=candidate.version,
                experiment_family=None,
                experiment_gate=failure_gate,
                actor=settings.trainer_id,
            )
            return {
                "status": "REJECTED",
                "reason": "candidate_policy_binding_mismatch_current_settings",
                "candidate_version": candidate.version,
                "experiment_promotion_gate": failure_gate,
                "closure": closure,
                "continue_scheduling": True,
            }

        persisted_gate = metrics.get("experiment_promotion_gate")
        stored_family = (
            persisted_gate.get("experiment_family")
            if isinstance(persisted_gate, dict)
            else None
        )
        configured_family = (settings.auto_train_experiment_family or "").strip() or None
        # The configured family is an explicit operator selection for this staged
        # candidate. Exact version/SHA/horizon binding below prevents a stale or
        # unrelated family from authorizing activation.
        experiment_family = configured_family or stored_family
        automatic_experiment: dict[str, object] | None = None
        if experiment_family is None and settings.auto_train_auto_experiment:
            self.state["phase"] = "RUNNING_EXPERIMENT"

            async def update_automatic_experiment_status(
                payload: dict[str, object],
            ) -> None:
                self.state["automatic_experiment"] = payload
                if payload.get("subprocess_active") is True:
                    self.state["phase"] = "RUNNING_EXPERIMENT"
                await self.heartbeat_best_effort()

            automatic_experiment = await orchestrate_automatic_experiment(
                candidate,
                settings=settings,
                actor=settings.trainer_id,
                status_callback=update_automatic_experiment_status,
            )
            resolved_family = automatic_experiment.get("experiment_family")
            experiment_family = (
                str(resolved_family).strip()
                if isinstance(resolved_family, str) and resolved_family.strip()
                else None
            )
            automatic_status = str(automatic_experiment.get("status") or "WAITING")
            automatic_reason = str(
                automatic_experiment.get("reason") or "automatic_experiment_incomplete"
            )
            if automatic_status == "CANCELLED":
                failure_gate = {
                    "schema": "automatic-experiment-failure-gate-v1",
                    "passed": False,
                    "report_status": "AUTOMATIC_EXPERIMENT_OPERATOR_CANCELLED",
                    "reasons": [automatic_reason],
                    "experiment_family": experiment_family,
                    "cancel_request_id": automatic_experiment.get("cancel_request_id"),
                    "requested_by": automatic_experiment.get("requested_by"),
                    "closed_trial_ids": automatic_experiment.get("closed_trial_ids"),
                }
                closure = automatic_experiment.get("closure")
                if not isinstance(closure, dict):
                    closure = await close_candidate_activation_request(
                        candidate_version=candidate.version,
                        experiment_family=experiment_family,
                        experiment_gate=failure_gate,
                        actor=settings.trainer_id,
                    )
                return {
                    "status": "REJECTED",
                    "reason": automatic_reason,
                    "candidate_version": candidate.version,
                    "experiment_family": experiment_family,
                    "automatic_experiment": automatic_experiment,
                    "closure": closure,
                }
            if automatic_status == "REJECTED":
                if experiment_family is None:
                    return {
                        "status": "BLOCKED",
                        "reason": "automatic_experiment_rejected_without_family",
                        "candidate_version": candidate.version,
                        "automatic_experiment": automatic_experiment,
                    }
                failure_gate = {
                    "schema": "automatic-experiment-failure-gate-v1",
                    "passed": False,
                    "report_status": "AUTOMATIC_EXPERIMENT_FAILED",
                    "reasons": [automatic_reason],
                    "experiment_family": experiment_family,
                    "configuration_hash": automatic_experiment.get("configuration_hash"),
                    "attempts": automatic_experiment.get("attempts"),
                }
                closure = await close_candidate_activation_request(
                    candidate_version=candidate.version,
                    experiment_family=experiment_family,
                    experiment_gate=failure_gate,
                    actor=settings.trainer_id,
                )
                return {
                    "status": "REJECTED",
                    "reason": automatic_reason,
                    "candidate_version": candidate.version,
                    "experiment_family": experiment_family,
                    "automatic_experiment": automatic_experiment,
                    "closure": closure,
                }
            if automatic_status != "COMPLETE":
                return {
                    "status": automatic_status,
                    "reason": automatic_reason,
                    "candidate_version": candidate.version,
                    "experiment_family": experiment_family,
                    "automatic_experiment": automatic_experiment,
                }
        if experiment_family is None:
            return {
                "status": "WAITING",
                "reason": "missing_auto_train_experiment_family",
                "candidate_version": candidate.version,
            }

        async with SessionFactory() as promotion_session:
            experiment_gate = await evaluate_experiment_promotion_gate(
                promotion_session,
                experiment_family=experiment_family,
                model_version=candidate.version,
                model_sha256=artifact_sha256,
                horizon_hours=horizon_hours,
                expected_policy_binding=policy_binding,
            )
        if experiment_gate.get("passed") is not True:
            if experiment_gate_is_terminal(experiment_gate):
                closure = await close_candidate_activation_request(
                    candidate_version=candidate.version,
                    experiment_family=experiment_family,
                    experiment_gate=experiment_gate,
                    actor=settings.trainer_id,
                )
                return {
                    "status": "REJECTED",
                    "reason": "experiment_promotion_terminal_rejection",
                    "candidate_version": candidate.version,
                    "experiment_family": experiment_family,
                    "experiment_promotion_gate": experiment_gate,
                    "automatic_experiment": automatic_experiment,
                    "closure": closure,
                }
            return {
                "status": "WAITING",
                "reason": "experiment_promotion_gate_failed",
                "candidate_version": candidate.version,
                "experiment_family": experiment_family,
                "experiment_promotion_gate": experiment_gate,
                "automatic_experiment": automatic_experiment,
            }

        active = await self.active_model()
        activation = await activate_registered_model(
            candidate.version,
            actor=settings.trainer_id,
            expected_previous_version=active.version if active else None,
            enforce_expected_previous_version=True,
            experiment_family=experiment_family,
        )
        return {
            "status": "ACTIVATED",
            "candidate_version": candidate.version,
            "experiment_family": experiment_family,
            "experiment_promotion_gate": experiment_gate,
            "automatic_experiment": automatic_experiment,
            "activation": activation,
        }

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
            require_universe_replay=settings.universe_mode == "dynamic",
            universe_replay_max_age_seconds=getattr(
                settings, "universe_refresh_seconds", 300
            )
            * 2,
            maximum_executable_spread_bps=settings.max_spread_bps,
        )

    async def due_reason(
        self,
        *,
        force_recovery: bool = False,
    ) -> tuple[bool, dict[str, object]]:
        now = datetime.now(UTC)
        active = await self.active_model()
        latest = await self.latest_attempt()
        profile = await self.current_training_profile()
        minimum_bootstrap = minimum_hourly_history_timestamps_for_quality_gate(
            horizon_hours=settings.default_horizon_hours,
            minimum_holdout_rows=settings.auto_train_min_holdout_rows,
            minimum_holdout_span_hours=settings.auto_train_min_holdout_span_hours,
        )
        if profile.unique_timestamps < minimum_bootstrap:
            return False, {
                "reason": "not_enough_history_for_bootstrap",
                "timestamps": profile.unique_timestamps,
                "required_timestamps": minimum_bootstrap,
                "required_holdout_rows": settings.auto_train_min_holdout_rows,
                "required_holdout_span_hours": (settings.auto_train_min_holdout_span_hours),
                "horizon_hours": settings.default_horizon_hours,
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
            else registry_artifact_recovery_notice(
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

        if force_recovery:
            if settings.active_model_path is not None:
                return False, {
                    "reason": "operator_recovery_blocked_by_active_model_path",
                    "active_model_path": str(settings.active_model_path),
                    "training_data_profile": profile.to_dict(),
                }
            if recovery_notice is not None:
                recovery_reason = "bootstrap_recovery"
            elif active is None or active.model_type == "deterministic_baseline":
                recovery_reason = "bootstrap_training"
            else:
                return False, {
                    "reason": "operator_recovery_not_required",
                    "active_version": active.version,
                    "training_data_profile": profile.to_dict(),
                }
            trigger = {
                "reason": "operator_recovery",
                "recovery_reason": recovery_reason,
                "active_version": active.version if active else None,
                "recovery_notice": recovery_notice,
                "requested_at": now.isoformat(),
                "training_data_profile": profile.to_dict(),
            }
            trigger_kind = "bootstrap"
        elif recovery_notice is not None:
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
                "active_training_end": active.training_end.isoformat() if active.training_end else None,
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
                "active_training_end": active.training_end.isoformat() if active.training_end else None,
                "new_timestamps": new_timestamps,
                "required_new_timestamps": settings.auto_train_min_new_timestamps,
                "label_cutoff": label_cutoff.isoformat() if label_cutoff else None,
                "dataset_change": comparison,
                "training_data_profile": profile.to_dict(),
            }

        if force_recovery:
            return True, trigger

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

            if (
                trigger_kind == "bootstrap"
                and latest.status == "SUCCESS"
                and isinstance(latest.details, dict)
                and latest.details.get("activation_skipped") == "quality_gate_failed"
                and _same_bootstrap_episode(latest, trigger)
            ):
                previous_trigger = _job_trigger(latest.details)
                previous_profile = TrainingDataProfile.from_mapping(
                    previous_trigger.get("training_data_profile") if previous_trigger is not None else None
                )
                if previous_profile is not None:
                    retry_comparison = compare_training_profiles(
                        profile,
                        previous_profile,
                        minimum_new_rows=settings.auto_train_min_new_rows,
                        minimum_growth_ratio=settings.auto_train_min_dataset_growth_ratio,
                        minimum_new_symbols=settings.auto_train_min_new_symbols,
                        minimum_universe_change_ratio=(settings.auto_train_min_universe_change_ratio),
                    )
                    retry_new_timestamps = 0
                    if previous_profile.end_time and label_cutoff:
                        retry_new_timestamps = await self.timestamp_count(
                            previous_profile.end_time, label_cutoff
                        )
                    if (
                        not retry_comparison["material_change"]
                        and retry_new_timestamps < settings.auto_train_min_new_timestamps
                    ):
                        return False, {
                            "reason": "quality_gate_failed_waiting_for_new_data",
                            "pending_trigger": trigger,
                            "last_started_at": latest.started_at.isoformat(),
                            "new_timestamps": retry_new_timestamps,
                            "required_new_timestamps": (settings.auto_train_min_new_timestamps),
                            "dataset_change": retry_comparison,
                            "previous_training_data_profile": previous_profile.to_dict(),
                            "training_data_profile": profile.to_dict(),
                        }
        return True, trigger

    async def claim_control_request(self) -> JobRun | None:
        async with SessionFactory() as session, session.begin():
            await acquire_trainer_control_lock(session)
            await recover_stale_trainer_control(
                session,
                settings,
                recovered_by=settings.trainer_id,
            )
            job = (
                await session.execute(
                    select(JobRun)
                    .where(
                        JobRun.job_name == TRAINER_CONTROL_JOB_NAME,
                        JobRun.status == "PENDING",
                    )
                    .order_by(JobRun.started_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if job is None:
                return None
            details = dict(job.details or {})
            details["accepted_at"] = datetime.now(UTC).isoformat()
            details["accepted_by"] = settings.trainer_id
            details["claim_token"] = uuid4().hex
            job.status = "RUNNING"
            job.worker_id = settings.trainer_id
            job.details = json_compatible(details)
            await session.flush()
            return job

    async def finish_control_request(
        self,
        job_id,
        *,
        status: str,
        result: dict[str, object],
        claim_token: str,
    ) -> bool:
        async with SessionFactory() as session, session.begin():
            job = (
                await session.execute(select(JobRun).where(JobRun.id == job_id).with_for_update())
            ).scalar_one()
            details = dict(job.details or {})
            if job.status != "RUNNING" or details.get("claim_token") != claim_token:
                logger.warning(
                    "Ignoring completion from a stale trainer control claim",
                    extra={"job_id": str(job.id), "status": job.status},
                )
                return False
            details["result"] = json_compatible(result)
            job.status = status
            job.finished_at = datetime.now(UTC)
            job.details = json_compatible(details)
            await publish_outbox(
                session,
                event_type="TRAINER_CONTROL_COMPLETED",
                aggregate_type="trainer_control",
                aggregate_id=str(job.id),
                payload={
                    "action": details.get("action"),
                    "status": status,
                    "training_started": result.get("training_started"),
                },
            )
            await session.flush()
            return True

    async def process_control_request(self, job: JobRun) -> None:
        details = job.details if isinstance(job.details, dict) else {}
        action = str(details.get("action") or "")
        claim_token = str(details.get("claim_token") or "")
        self.state.pop("wait_reason", None)
        self.state.update(
            {
                "phase": "CHECKING_DATA",
                "healthy": True,
                "control_request": {
                    "id": str(job.id),
                    "action": action,
                    "requested_at": details.get("requested_at"),
                    "accepted_at": details.get("accepted_at"),
                },
            }
        )
        await self.heartbeat_best_effort()

        if action not in TRAINER_CONTROL_ACTIONS:
            result = {
                "action": action,
                "training_started": False,
                "error": "unsupported_trainer_control_action",
            }
            self.state.update(
                {
                    "phase": "ERROR",
                    "healthy": False,
                    "last_control_result": result,
                    "control_request": None,
                }
            )
            await self.finish_control_request(
                job.id,
                status="FAILED",
                result=result,
                claim_token=claim_token,
            )
            await self.heartbeat_best_effort()
            return

        if action == "CANCEL_EXPERIMENT":
            result = {
                "action": action,
                "training_started": False,
                "cancelled": False,
                "error": "automatic_experiment_subprocess_not_running",
                "experiment_family": details.get("experiment_family"),
                "candidate_version": details.get("candidate_version"),
            }
            self.state.update(
                {
                    "phase": "WAITING",
                    "healthy": True,
                    "last_control_result": result,
                    "control_request": None,
                }
            )
            await self.finish_control_request(
                job.id,
                status="FAILED",
                result=result,
                claim_token=claim_token,
            )
            await self.heartbeat_best_effort()
            return

        try:
            due, trigger = await self.due_reason(force_recovery=action == "RECOVER_NOW")
            if due:
                training_result = await self.run_training_once(trigger)
                result = {
                    "action": action,
                    "training_started": "skipped" not in training_result,
                    "trigger": trigger,
                    "training_result": training_result,
                }
                control_status = "FAILED" if training_result.get("error") else "SUCCESS"
            else:
                result = {
                    "action": action,
                    "training_started": False,
                    "wait_reason": trigger,
                }
                control_status = "SUCCESS"
                self.state.update(
                    {
                        "phase": "WAITING",
                        "healthy": True,
                        "wait_reason": trigger,
                    }
                )
            self.state.update(
                {
                    "last_control_result": result,
                    "control_request": None,
                }
            )
            await self.finish_control_request(
                job.id,
                status=control_status,
                result=result,
                claim_token=claim_token,
            )
        except Exception as exc:
            result = {
                "action": action,
                "training_started": False,
                "error": str(exc),
            }
            self.state.update(
                {
                    "phase": "ERROR",
                    "healthy": False,
                    "last_control_result": result,
                    "control_request": None,
                }
            )
            await self.finish_control_request(
                job.id,
                status="FAILED",
                result=result,
                claim_token=claim_token,
            )
            logger.exception("Trainer control request failed")
        await self.heartbeat_best_effort()

    async def run_scheduling_iteration(self) -> None:
        self.state["phase"] = "CHECKING_PROMOTION"
        self.state.pop("wait_reason", None)
        promotion = await self.reconcile_pending_activation()
        if promotion is not None:
            self.state["last_promotion"] = promotion
            if promotion.get("status") == "ACTIVATED":
                self.state.update(
                    {
                        "phase": "WAITING",
                        "healthy": True,
                        "wait_reason": {
                            "reason": "registered_candidate_activated",
                            "candidate_version": promotion.get("candidate_version"),
                        },
                    }
                )
                return
            if promotion.get("status") in {"WAITING", "BLOCKED"}:
                self.state.update(
                    {
                        "phase": "WAITING",
                        "healthy": promotion.get("status") == "WAITING",
                        "wait_reason": {
                            key: value
                            for key, value in {
                                "reason": promotion.get("reason"),
                                "candidate_version": promotion.get("candidate_version"),
                                "experiment_family": promotion.get("experiment_family"),
                            }.items()
                            if value is not None
                        },
                    }
                )
                return
            if promotion.get("status") == "REJECTED":
                self.state.update(
                    {
                        "phase": "WAITING",
                        "healthy": True,
                        "wait_reason": {
                            key: value
                            for key, value in {
                                "reason": promotion.get("reason"),
                                "candidate_version": promotion.get("candidate_version"),
                                "experiment_family": promotion.get("experiment_family"),
                            }.items()
                            if value is not None
                        },
                    }
                )
                if promotion.get("continue_scheduling") is not True:
                    return
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
                    incumbent_recovery = registry_artifact_recovery_notice(
                        active,
                        allow_baseline_model=settings.allow_baseline_model,
                        app_mode=settings.app_mode,
                    )
                    incumbent = None if incumbent_recovery else incumbent_from_registry(active)
                    if incumbent_recovery:
                        logger.warning(
                            "Unusable active artifact is treated as bootstrap recovery input",
                            extra={"incumbent_recovery": incumbent_recovery},
                        )
                    (
                        preflight_profile,
                        expected_symbols,
                        maximum_open_time,
                    ) = require_training_trigger_profile(
                        trigger,
                        horizon_hours=settings.default_horizon_hours,
                    )
                    load_symbols = expected_symbols
                    load_max_symbols = 0
                    self.state.update(
                        {
                            "phase": "LOADING_DATA",
                            "healthy": True,
                            "active_version_before_training": active.version if active else None,
                            "incumbent_recovery": incumbent_recovery,
                        }
                    )
                    market_data = await load_training_market_data(
                        load_symbols,
                        lookback_days=settings.auto_train_lookback_days,
                        max_symbols=load_max_symbols,
                        horizon=settings.default_horizon_hours,
                        minimum_rows_for_coverage=settings.auto_train_min_bars_per_symbol,
                        require_universe_replay=settings.universe_mode == "dynamic",
                        universe_replay_max_age_seconds=getattr(settings, "universe_refresh_seconds", 300) * 2,
                        maximum_executable_spread_bps=settings.max_spread_bps,
                        maximum_open_time=maximum_open_time,
                    )
                    self.state["phase"] = "FITTING"
                    candidate = await asyncio.to_thread(
                        build_model_candidate,
                        market_data.candles,
                        mark_candles=market_data.mark_candles,
                        index_candles=market_data.index_candles,
                        open_interest=market_data.open_interest,
                        horizon=settings.default_horizon_hours,
                        model_type=settings.auto_train_model_type,
                        model_dir=settings.model_dir,
                        entry_spread_bps=settings.model_entry_spread_bps,
                        entry_zone_atr_fraction=getattr(settings, "entry_zone_atr_fraction", 0.12),
                        maximum_signal_publication_delay_seconds=(
                            getattr(settings, "max_signal_publication_delay_seconds", 600)
                        ),
                        funding_history=market_data.funding,
                        funding_interval_minutes=market_data.funding_interval_minutes,
                        funding_interval_history=market_data.funding_interval_history,
                        incumbent=incumbent,
                        source="background_trainer",
                        minimum_rows_for_coverage=settings.auto_train_min_bars_per_symbol,
                        policy_config=policy_evaluation_config(settings),
                        expected_symbols=expected_symbols,
                        universe_eligibility=getattr(market_data, "universe_eligibility", None),
                        require_universe_replay=settings.universe_mode == "dynamic",
                        universe_replay_max_age_seconds=getattr(settings, "universe_refresh_seconds", 300) * 2,
                        maximum_executable_spread_bps=settings.max_spread_bps,
                    )
                    gate = evaluate_quality_gate(
                        candidate,
                        settings,
                        expected_training_profile=preflight_profile,
                    )
                    candidate_digest = hashlib.sha256(candidate.path.read_bytes()).hexdigest()
                    experiment_family = (settings.auto_train_experiment_family or "").strip() or None
                    if not settings.auto_train_auto_activate:
                        experiment_promotion_gate = blocked_experiment_promotion_gate(
                            reason="automatic_activation_not_requested",
                            experiment_family=experiment_family,
                            model_version=candidate.version,
                            model_sha256=candidate_digest,
                            horizon_hours=candidate.horizon,
                        )
                    elif not gate["passed"]:
                        experiment_promotion_gate = blocked_experiment_promotion_gate(
                            reason="quality_gate_failed_before_experiment_promotion",
                            experiment_family=experiment_family,
                            model_version=candidate.version,
                            model_sha256=candidate_digest,
                            horizon_hours=candidate.horizon,
                        )
                    elif settings.active_model_path is not None:
                        experiment_promotion_gate = blocked_experiment_promotion_gate(
                            reason="active_model_path_override_configured",
                            experiment_family=experiment_family,
                            model_version=candidate.version,
                            model_sha256=candidate_digest,
                            horizon_hours=candidate.horizon,
                        )
                    elif experiment_family is None:
                        experiment_promotion_gate = blocked_experiment_promotion_gate(
                            reason="missing_auto_train_experiment_family",
                            experiment_family=None,
                            model_version=candidate.version,
                            model_sha256=candidate_digest,
                            horizon_hours=candidate.horizon,
                        )
                    else:
                        policy_binding = require_experiment_policy_binding(
                            candidate.metrics.get("promotion_policy_binding")
                        )
                        async with SessionFactory() as promotion_session:
                            experiment_promotion_gate = await evaluate_experiment_promotion_gate(
                                promotion_session,
                                experiment_family=experiment_family,
                                model_version=candidate.version,
                                model_sha256=candidate_digest,
                                horizon_hours=candidate.horizon,
                                expected_policy_binding=policy_binding,
                            )
                    can_activate = bool(
                        settings.auto_train_auto_activate
                        and gate["passed"]
                        and experiment_promotion_gate["passed"]
                        and settings.active_model_path is None
                    )
                    recovery_activation_skipped: str | None = None
                    if can_activate and incumbent_recovery:
                        current_active = await self.active_model()
                        current_recovery = registry_artifact_recovery_notice(
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
                            experiment_promotion_gate=experiment_promotion_gate,
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
                            activation_requested=bool(settings.auto_train_auto_activate),
                            actor=settings.trainer_id,
                            experiment_promotion_gate=experiment_promotion_gate,
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
                        elif not experiment_promotion_gate["passed"]:
                            activation_skipped = "experiment_promotion_gate_failed"

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
                        "experiment_promotion_gate": experiment_promotion_gate,
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
        loop = asyncio.get_running_loop()
        initial_delay = max(0, settings.auto_train_initial_delay_seconds)
        next_regular_at = loop.time() + initial_delay
        if initial_delay:
            self.state.update(
                {
                    "phase": "INITIAL_DELAY",
                    "healthy": True,
                    "next_check_at": (datetime.now(UTC) + timedelta(seconds=initial_delay)).isoformat(),
                }
            )

        while not self.stop_event.is_set():
            try:
                control_request = await self.claim_control_request()
                if control_request is not None:
                    await self.process_control_request(control_request)
                    next_regular_at = loop.time() + settings.auto_train_check_seconds
                    self.state["next_check_at"] = (
                        datetime.now(UTC) + timedelta(seconds=settings.auto_train_check_seconds)
                    ).isoformat()
                    continue

                remaining = next_regular_at - loop.time()
                if remaining > 0:
                    with suppress(TimeoutError):
                        await asyncio.wait_for(
                            self.stop_event.wait(),
                            timeout=min(TRAINER_CONTROL_POLL_SECONDS, remaining),
                        )
                    continue

                await self.run_scheduling_iteration()
                next_regular_at = loop.time() + settings.auto_train_check_seconds
                self.state["next_check_at"] = (
                    datetime.now(UTC) + timedelta(seconds=settings.auto_train_check_seconds)
                ).isoformat()
            except Exception as exc:
                self.state.update(
                    {
                        "phase": "ERROR",
                        "healthy": False,
                        "last_result": {"error": str(exc)},
                    }
                )
                logger.exception("Trainer scheduling iteration failed")
                next_regular_at = loop.time() + settings.auto_train_check_seconds
                self.state["next_check_at"] = (
                    datetime.now(UTC) + timedelta(seconds=settings.auto_train_check_seconds)
                ).isoformat()
                with suppress(TimeoutError):
                    await asyncio.wait_for(self.stop_event.wait(), timeout=TRAINER_CONTROL_POLL_SECONDS)

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

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ml.data_profile import profile_from_symbol_rows
from app.workers import trainer as trainer_module


def training_profile(now: datetime, *, unique_timestamps: int = 1500):
    return profile_from_symbol_rows(
        [
            ("BTCUSDT", unique_timestamps, now - timedelta(hours=unique_timestamps), now),
            ("ETHUSDT", unique_timestamps, now - timedelta(hours=unique_timestamps), now),
        ],
        unique_timestamps=unique_timestamps,
        minimum_rows_for_coverage=300,
    )


def active_model(path: Path, profile, *, model_type: str = "barrier_logistic") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        version="trained-v1" if model_type != "deterministic_baseline" else "baseline-momentum-v1",
        model_type=model_type,
        artifact_path=str(path) if model_type != "deterministic_baseline" else None,
        artifact_sha256="0" * 64 if model_type != "deterministic_baseline" else None,
        calibration_version="cal-v1",
        metrics={"training_data_profile": profile.to_dict()},
        training_end=profile.end_time,
    )


def attempt(
    *,
    status: str,
    started_at: datetime,
    trigger_reason: str,
    active_version: str | None,
    activation_skipped: str | None = None,
    profile=None,
    metrics_profile=None,
) -> SimpleNamespace:
    trigger: dict[str, object] = {
        "reason": trigger_reason,
        "active_version": active_version,
    }
    if profile is not None:
        trigger["training_data_profile"] = profile.to_dict()
    details: dict[str, object] = {"trigger": trigger}
    if activation_skipped is not None:
        details["activation_skipped"] = activation_skipped
    if metrics_profile is not None:
        details["metrics"] = {"training_data_profile": metrics_profile.to_dict()}
    return SimpleNamespace(status=status, started_at=started_at, details=details)


async def configure_trainer(
    monkeypatch: pytest.MonkeyPatch,
    *,
    active: SimpleNamespace | None,
    latest: SimpleNamespace | None,
    profile,
    active_model_path: Path | None = None,
    new_timestamps: int = 0,
) -> trainer_module.BackgroundTrainer:
    trainer = trainer_module.BackgroundTrainer()

    async def get_active():
        return active

    async def get_latest():
        return latest

    async def get_profile():
        return profile

    async def count_timestamps(*_args, **_kwargs):
        return new_timestamps

    monkeypatch.setattr(trainer, "active_model", get_active)
    monkeypatch.setattr(trainer, "latest_attempt", get_latest)
    monkeypatch.setattr(trainer, "current_training_profile", get_profile)
    monkeypatch.setattr(trainer, "timestamp_count", count_timestamps)
    monkeypatch.setattr(
        trainer_module,
        "settings",
        trainer_module.settings.model_copy(
            update={
                "app_mode": "paper",
                "allow_baseline_model": True,
                "active_model_path": active_model_path,
                "auto_train_retry_hours": 6,
                "auto_train_data_change_cooldown_hours": 6,
                "auto_train_recovery_retry_minutes": 15,
            }
        ),
    )
    return trainer


@pytest.mark.asyncio
async def test_missing_artifact_triggers_immediate_bootstrap_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    profile = training_profile(now)
    active = active_model(tmp_path / "deleted.joblib", profile)
    latest = attempt(
        status="FAILED",
        started_at=now - timedelta(minutes=5),
        trigger_reason="material_training_dataset_change",
        active_version=active.version,
    )
    trainer = await configure_trainer(
        monkeypatch,
        active=active,
        latest=latest,
        profile=profile,
    )

    due, reason = await trainer.due_reason()

    assert due is True
    assert reason["reason"] == "bootstrap_recovery"
    assert reason["active_version"] == active.version
    assert reason["recovery_notice"]["code"] == "ACTIVE_MODEL_ARTIFACT_MISSING"


@pytest.mark.asyncio
async def test_failed_recovery_attempt_uses_short_retry_backoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    profile = training_profile(now)
    active = active_model(tmp_path / "deleted.joblib", profile)
    latest = attempt(
        status="FAILED",
        started_at=now - timedelta(minutes=5),
        trigger_reason="bootstrap_recovery",
        active_version=active.version,
    )
    trainer = await configure_trainer(
        monkeypatch,
        active=active,
        latest=latest,
        profile=profile,
    )

    due, reason = await trainer.due_reason()

    assert due is False
    assert reason["reason"] == "training_recovery_backoff_not_elapsed"
    assert reason["cooldown_minutes"] == 15
    assert reason["pending_trigger"]["reason"] == "bootstrap_recovery"


@pytest.mark.asyncio
async def test_failed_recovery_attempt_retries_after_short_backoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    profile = training_profile(now)
    active = active_model(tmp_path / "deleted.joblib", profile)
    latest = attempt(
        status="FAILED",
        started_at=now - timedelta(minutes=16),
        trigger_reason="bootstrap_recovery",
        active_version=active.version,
    )
    trainer = await configure_trainer(
        monkeypatch,
        active=active,
        latest=latest,
        profile=profile,
    )

    due, reason = await trainer.due_reason()

    assert due is True
    assert reason["reason"] == "bootstrap_recovery"


@pytest.mark.asyncio
async def test_unrelated_failed_attempt_does_not_delay_baseline_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    profile = training_profile(now)
    active = active_model(Path("unused"), profile, model_type="deterministic_baseline")
    latest = attempt(
        status="FAILED",
        started_at=now - timedelta(minutes=5),
        trigger_reason="scheduled_retraining",
        active_version="old-trained-v1",
    )
    trainer = await configure_trainer(
        monkeypatch,
        active=active,
        latest=latest,
        profile=profile,
    )

    due, reason = await trainer.due_reason()

    assert due is True
    assert reason["reason"] == "bootstrap_training"


@pytest.mark.asyncio
async def test_rejected_recovery_candidate_uses_controlled_success_cooldown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    profile = training_profile(now)
    active = active_model(tmp_path / "deleted.joblib", profile)
    latest = attempt(
        status="SUCCESS",
        started_at=now - timedelta(hours=1),
        trigger_reason="bootstrap_recovery",
        active_version=active.version,
        activation_skipped="quality_gate_failed",
    )
    trainer = await configure_trainer(
        monkeypatch,
        active=active,
        latest=latest,
        profile=profile,
    )

    due, reason = await trainer.due_reason()

    assert due is False
    assert reason["reason"] == "training_cooldown_not_elapsed"
    assert reason["cooldown_hours"] == 6
    assert reason["pending_trigger"]["reason"] == "bootstrap_recovery"




@pytest.mark.asyncio
async def test_rejected_bootstrap_recovers_profile_from_candidate_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    profile = training_profile(now)
    latest = attempt(
        status="SUCCESS",
        started_at=now - timedelta(hours=1),
        trigger_reason="bootstrap_training",
        active_version=None,
        activation_skipped="quality_gate_failed",
        metrics_profile=profile,
    )
    trainer = await configure_trainer(
        monkeypatch,
        active=None,
        latest=latest,
        profile=profile,
    )

    due, reason = await trainer.due_reason()

    assert due is False
    assert reason["reason"] == "quality_gate_failed_waiting_for_new_data"
    assert reason["previous_profile_source"] == "metrics.training_data_profile"
    assert reason["new_timestamps"] == 0


async def test_rejected_bootstrap_reports_new_data_wait_even_during_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    profile = training_profile(now)
    latest = attempt(
        status="SUCCESS",
        started_at=now - timedelta(hours=1),
        trigger_reason="bootstrap_training",
        active_version=None,
        activation_skipped="quality_gate_failed",
        profile=profile,
    )
    trainer = await configure_trainer(
        monkeypatch,
        active=None,
        latest=latest,
        profile=profile,
    )

    due, reason = await trainer.due_reason()

    assert due is False
    assert reason["reason"] == "quality_gate_failed_waiting_for_new_data"
    assert reason["previous_activation_skipped"] == "quality_gate_failed"
    assert reason["new_timestamps"] == 0
    assert reason["required_new_timestamps"] == trainer_module.settings.auto_train_min_new_timestamps
    assert reason["cooldown_hours"] == 6
    assert reason["next_due_at"] is not None

@pytest.mark.asyncio
async def test_rejected_bootstrap_waits_for_new_training_data_after_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    profile = training_profile(now)
    latest = attempt(
        status="SUCCESS",
        started_at=now - timedelta(hours=7),
        trigger_reason="bootstrap_training",
        active_version=None,
        activation_skipped="quality_gate_failed",
        profile=profile,
    )
    trainer = await configure_trainer(
        monkeypatch,
        active=None,
        latest=latest,
        profile=profile,
    )

    due, reason = await trainer.due_reason()

    assert due is False
    assert reason["reason"] == "quality_gate_failed_waiting_for_new_data"
    assert reason["new_timestamps"] == 0
    assert reason["required_new_timestamps"] == trainer_module.settings.auto_train_min_new_timestamps


@pytest.mark.asyncio
async def test_deferred_bootstrap_waits_for_new_training_data_after_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    profile = training_profile(now)
    latest = attempt(
        status="SUCCESS",
        started_at=now - timedelta(hours=7),
        trigger_reason="bootstrap_training",
        active_version=None,
        activation_skipped="insufficient_walk_forward_history_after_filtering",
        profile=profile,
    )
    trainer = await configure_trainer(
        monkeypatch,
        active=None,
        latest=latest,
        profile=profile,
    )

    due, reason = await trainer.due_reason()

    assert due is False
    assert reason["reason"] == "training_deferred_waiting_for_new_data"
    assert reason["previous_activation_skipped"] == (
        "insufficient_walk_forward_history_after_filtering"
    )
    assert reason["new_timestamps"] == 0
    assert reason["required_new_timestamps"] == trainer_module.settings.auto_train_min_new_timestamps


@pytest.mark.asyncio
async def test_rejected_bootstrap_retries_after_required_new_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    previous_profile = training_profile(now - timedelta(days=8))
    current_profile = training_profile(now)
    latest = attempt(
        status="SUCCESS",
        started_at=now - timedelta(hours=7),
        trigger_reason="bootstrap_training",
        active_version=None,
        activation_skipped="quality_gate_failed",
        profile=previous_profile,
    )
    trainer = await configure_trainer(
        monkeypatch,
        active=None,
        latest=latest,
        profile=current_profile,
        new_timestamps=168,
    )

    due, reason = await trainer.due_reason()

    assert due is True
    assert reason["reason"] == "bootstrap_training"


@pytest.mark.asyncio
async def test_no_active_model_retries_failed_bootstrap_after_short_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    profile = training_profile(now)
    latest = attempt(
        status="FAILED",
        started_at=now - timedelta(minutes=16),
        trigger_reason="bootstrap_training",
        active_version=None,
    )
    trainer = await configure_trainer(
        monkeypatch,
        active=None,
        latest=latest,
        profile=profile,
    )

    due, reason = await trainer.due_reason()

    assert due is True
    assert reason["reason"] == "bootstrap_training"


@pytest.mark.asyncio
async def test_registry_artifact_recovery_is_not_scheduled_when_override_is_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    profile = training_profile(now)
    active = active_model(tmp_path / "deleted.joblib", profile)
    trainer = await configure_trainer(
        monkeypatch,
        active=active,
        latest=None,
        profile=profile,
        active_model_path=tmp_path / "override.joblib",
    )

    due, reason = await trainer.due_reason()

    assert due is False
    assert reason["reason"] == "not_enough_new_or_changed_training_data"


@pytest.mark.asyncio
async def test_operator_recovery_bypasses_recovery_backoff_without_bypassing_gates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    profile = training_profile(now)
    active = active_model(tmp_path / "deleted.joblib", profile)
    latest = attempt(
        status="FAILED",
        started_at=now - timedelta(minutes=5),
        trigger_reason="bootstrap_recovery",
        active_version=active.version,
    )
    trainer = await configure_trainer(
        monkeypatch,
        active=active,
        latest=latest,
        profile=profile,
    )

    due, reason = await trainer.due_reason(force_recovery=True)

    assert due is True
    assert reason["reason"] == "operator_recovery"
    assert reason["recovery_reason"] == "bootstrap_recovery"
    assert reason["active_version"] == active.version


@pytest.mark.asyncio
async def test_operator_recovery_does_not_bypass_minimum_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    profile = profile_from_symbol_rows(
        [("BTCUSDT", 120, now - timedelta(days=5), now)],
        unique_timestamps=120,
        minimum_rows_for_coverage=300,
    )
    active = active_model(tmp_path / "deleted.joblib", profile)
    trainer = await configure_trainer(
        monkeypatch,
        active=active,
        latest=None,
        profile=profile,
    )

    due, reason = await trainer.due_reason(force_recovery=True)

    assert due is False
    assert reason["reason"] == "not_enough_history_for_bootstrap"

@pytest.mark.asyncio
async def test_bootstrap_waits_until_configured_holdout_span_is_mathematically_possible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    insufficient_profile = training_profile(now, unique_timestamps=900)
    trainer = await configure_trainer(
        monkeypatch,
        active=None,
        latest=None,
        profile=insufficient_profile,
    )

    due, reason = await trainer.due_reason()

    assert due is False
    assert reason["reason"] == "not_enough_history_for_bootstrap"
    assert reason["timestamps"] == 900
    assert reason["required_timestamps"] == 1206
    assert reason["required_holdout_span_hours"] == 168

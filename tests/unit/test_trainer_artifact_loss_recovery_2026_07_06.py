from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ml.data_profile import profile_from_symbol_rows
from app.services.model_promotion import experiment_policy_binding_from_settings
from app.services.trainer_control import recovery_availability
from app.workers import trainer as trainer_module


def _profile(now: datetime):
    return profile_from_symbol_rows(
        [
            ("BTCUSDT", 1500, now - timedelta(hours=1500), now),
            ("ETHUSDT", 1500, now - timedelta(hours=1500), now),
        ],
        unique_timestamps=1500,
        minimum_rows_for_coverage=300,
    )


def _active_model(path: Path, profile) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        version="active-trained-v1",
        model_type="barrier_hist_gradient_boosting",
        artifact_path=str(path),
        artifact_sha256="a" * 64,
        calibration_version="cal-v1",
        metrics={"training_data_profile": profile.to_dict()},
        training_end=profile.end_time,
    )


@pytest.mark.asyncio
async def test_missing_active_artifact_triggers_production_recovery_without_baseline_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    profile = _profile(now)
    active = _active_model(tmp_path / "deleted.joblib", profile)
    trainer = trainer_module.BackgroundTrainer()

    async def active_model():
        return active

    async def latest_attempt():
        return None

    async def current_training_profile():
        return profile

    async def timestamp_count(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(trainer, "active_model", active_model)
    monkeypatch.setattr(trainer, "latest_attempt", latest_attempt)
    monkeypatch.setattr(trainer, "current_training_profile", current_training_profile)
    monkeypatch.setattr(trainer, "timestamp_count", timestamp_count)
    monkeypatch.setattr(
        trainer_module,
        "settings",
        trainer_module.settings.model_copy(
            update={
                "app_mode": "production",
                "allow_baseline_model": False,
                "active_model_path": None,
            }
        ),
    )

    due, reason = await trainer.due_reason()

    assert due is True
    assert reason["reason"] == "bootstrap_recovery"
    assert reason["recovery_notice"]["code"] == "ACTIVE_MODEL_ARTIFACT_MISSING"
    assert reason["recovery_notice"]["runtime_fallback_allowed"] is False


def test_operator_recovery_is_available_for_missing_artifact_in_fail_closed_production(
    tmp_path: Path,
) -> None:
    settings = trainer_module.settings.model_copy(
        update={
            "app_mode": "production",
            "allow_baseline_model": False,
            "auto_train_enabled": True,
            "active_model_path": None,
        }
    )
    active = _active_model(tmp_path / "deleted.joblib", _profile(datetime.now(UTC)))

    available, reason = recovery_availability(active, settings)

    assert available is True
    assert reason == "active_model_artifact_missing"


def test_operator_recovery_detects_active_artifact_hash_mismatch(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "corrupt.joblib"
    artifact.write_bytes(b"unexpected-bytes")
    settings = trainer_module.settings.model_copy(
        update={
            "app_mode": "production",
            "allow_baseline_model": False,
            "auto_train_enabled": True,
            "active_model_path": None,
        }
    )
    active = _active_model(artifact, _profile(datetime.now(UTC)))

    available, reason = recovery_availability(active, settings)

    assert available is True
    assert reason == "active_model_artifact_hash_mismatch"


@pytest.mark.asyncio
@pytest.mark.parametrize("artifact_state", ["missing", "hash_mismatch"])
async def test_invalid_pending_candidate_artifact_is_closed_before_experiment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_state: str,
) -> None:
    artifact = tmp_path / "candidate.joblib"
    if artifact_state == "hash_mismatch":
        artifact.write_bytes(b"candidate-bytes")
    candidate = SimpleNamespace(
        id=uuid4(),
        version=f"candidate-{artifact_state}",
        model_type="barrier_hist_gradient_boosting",
        artifact_path=str(artifact),
        artifact_sha256="b" * 64,
        active=False,
        metrics={
            "source": "background_trainer",
            "activation_requested": True,
            "horizon_hours": trainer_module.settings.default_horizon_hours,
            "quality_gate": {"passed": True, "reasons": []},
            "experiment_promotion_gate": {"experiment_family": None},
            "promotion_policy_binding": experiment_policy_binding_from_settings(
                trainer_module.settings
            ),
        },
    )
    trainer = trainer_module.BackgroundTrainer()
    closed: dict[str, object] = {}

    async def pending_candidate():
        return candidate

    async def close_candidate(**kwargs):
        closed.update(kwargs)
        return {"status": "CLOSED", "candidate_version": candidate.version}

    async def unexpected_experiment(*_args, **_kwargs):
        raise AssertionError("invalid artifact must be rejected before experiment orchestration")

    monkeypatch.setattr(trainer, "_pending_auto_activation_candidate", pending_candidate)
    monkeypatch.setattr(trainer_module, "close_candidate_activation_request", close_candidate)
    monkeypatch.setattr(trainer_module, "orchestrate_automatic_experiment", unexpected_experiment)

    result = await trainer.reconcile_pending_activation()

    expected_reason = (
        "candidate_artifact_missing"
        if artifact_state == "missing"
        else "candidate_artifact_sha256_mismatch"
    )
    assert result["status"] == "REJECTED"
    assert result["reason"] == expected_reason
    assert result["continue_scheduling"] is True
    assert closed["candidate_version"] == candidate.version
    gate = closed["experiment_gate"]
    assert gate["passed"] is False
    assert gate["reasons"] == [expected_reason]


@pytest.mark.asyncio
async def test_scheduler_continues_to_bootstrap_recovery_after_stale_candidate_closure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trainer = trainer_module.BackgroundTrainer()
    calls: dict[str, object] = {}

    async def rejected_candidate():
        return {
            "status": "REJECTED",
            "reason": "candidate_artifact_missing",
            "candidate_version": "candidate-v1",
            "continue_scheduling": True,
        }

    async def due_reason():
        return True, {"reason": "bootstrap_recovery"}

    async def run_training_once(trigger):
        calls["trigger"] = trigger
        return {"activated": False}

    monkeypatch.setattr(trainer, "reconcile_pending_activation", rejected_candidate)
    monkeypatch.setattr(trainer, "due_reason", due_reason)
    monkeypatch.setattr(trainer, "run_training_once", run_training_once)

    await trainer.run_scheduling_iteration()

    assert calls["trigger"] == {"reason": "bootstrap_recovery"}
    assert trainer.state["last_promotion"]["reason"] == "candidate_artifact_missing"

@pytest.mark.asyncio
async def test_legacy_pending_candidate_without_policy_binding_is_closed_and_does_not_block_scheduler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "candidate.joblib"
    artifact.write_bytes(b"candidate-bytes")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    candidate = SimpleNamespace(
        id=uuid4(),
        version="candidate-without-policy-binding",
        model_type="barrier_hist_gradient_boosting",
        artifact_path=str(artifact),
        artifact_sha256=digest,
        active=False,
        metrics={
            "source": "background_trainer",
            "activation_requested": True,
            "horizon_hours": trainer_module.settings.default_horizon_hours,
            "quality_gate": {"passed": True, "reasons": []},
            "experiment_promotion_gate": {"experiment_family": None},
        },
    )
    trainer = trainer_module.BackgroundTrainer()
    closed: dict[str, object] = {}

    async def pending_candidate():
        return candidate

    async def close_candidate(**kwargs):
        closed.update(kwargs)
        return {"status": "CLOSED", "candidate_version": candidate.version}

    monkeypatch.setattr(trainer, "_pending_auto_activation_candidate", pending_candidate)
    monkeypatch.setattr(trainer_module, "close_candidate_activation_request", close_candidate)

    result = await trainer.reconcile_pending_activation()

    assert result["status"] == "REJECTED"
    assert result["reason"] == "candidate_policy_binding_missing_or_invalid"
    assert result["continue_scheduling"] is True
    assert closed["candidate_version"] == candidate.version
    gate = closed["experiment_gate"]
    assert gate["passed"] is False
    assert gate["reasons"] == ["candidate_policy_binding_missing_or_invalid"]

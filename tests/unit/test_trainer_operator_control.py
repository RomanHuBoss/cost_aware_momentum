from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.v1 import admin
from app.api.v1.status import latest_service_heartbeat
from app.config import get_settings
from app.services.trainer_control import recovery_availability, trainer_heartbeat_is_fresh
from app.workers import trainer as trainer_module


def model(
    path: Path | None,
    *,
    model_type: str = "barrier_logistic",
    artifact_sha256: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        version="trained-v1",
        model_type=model_type,
        artifact_path=str(path) if path is not None else None,
        artifact_sha256=artifact_sha256,
        calibration_version=None,
    )


def test_admin_router_exposes_authenticated_trainer_control_endpoint() -> None:
    route = next(route for route in admin.router.routes if route.path == "/api/v1/admin/trainer-control")
    assert route.methods == {"POST"}
    dependency_names = {dependency.call.__name__ for dependency in route.dependant.dependencies}
    assert "require_csrf" in dependency_names


def test_recovery_availability_tracks_artifact_and_override(tmp_path: Path) -> None:
    settings = get_settings().model_copy(
        update={"auto_train_enabled": True, "active_model_path": None}
    )
    missing = model(tmp_path / "missing.joblib")

    available, reason = recovery_availability(missing, settings)

    assert available is True
    assert reason == "active_model_artifact_missing"

    artifact = tmp_path / "active.joblib"
    artifact.write_bytes(b"artifact")
    available, reason = recovery_availability(
        model(artifact, artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest()),
        settings,
    )

    assert available is False
    assert reason == "active_model_artifact_available"

    override_settings = settings.model_copy(update={"active_model_path": tmp_path / "override.joblib"})
    available, reason = recovery_availability(missing, override_settings)

    assert available is False
    assert reason == "active_model_path_override"


def test_trainer_heartbeat_freshness_is_fail_closed() -> None:
    settings = get_settings().model_copy(update={"heartbeat_seconds": 15})
    now = datetime.now(UTC)
    fresh = SimpleNamespace(status="RUNNING", last_seen_at=now - timedelta(seconds=30))
    stale = SimpleNamespace(status="RUNNING", last_seen_at=now - timedelta(minutes=3))
    degraded = SimpleNamespace(status="DEGRADED", last_seen_at=now)
    stopped = SimpleNamespace(status="STOPPED", last_seen_at=now)

    assert trainer_heartbeat_is_fresh(fresh, settings, now=now) is True
    assert trainer_heartbeat_is_fresh(degraded, settings, now=now) is True
    assert trainer_heartbeat_is_fresh(stale, settings, now=now) is False
    assert trainer_heartbeat_is_fresh(stopped, settings, now=now) is False
    assert trainer_heartbeat_is_fresh(None, settings, now=now) is False


@pytest.mark.asyncio
async def test_check_now_control_updates_wait_reason_without_forcing_training(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trainer = trainer_module.BackgroundTrainer()
    calls: dict[str, object] = {}

    async def due_reason(*, force_recovery: bool = False):
        calls["force_recovery"] = force_recovery
        return False, {"reason": "not_enough_new_or_changed_training_data", "new_timestamps": 2}

    async def heartbeat():
        calls["heartbeats"] = int(calls.get("heartbeats", 0)) + 1

    async def finish(
        job_id,
        *,
        status: str,
        result: dict[str, object],
        claim_token: str,
    ):
        calls["finished"] = (job_id, status, result, claim_token)

    monkeypatch.setattr(trainer, "due_reason", due_reason)
    monkeypatch.setattr(trainer, "heartbeat", heartbeat)
    monkeypatch.setattr(trainer, "finish_control_request", finish)
    job = SimpleNamespace(
        id=uuid4(),
        details={
            "action": "CHECK_NOW",
            "requested_at": datetime.now(UTC).isoformat(),
            "claim_token": "check-token",
        },
    )

    await trainer.process_control_request(job)

    assert calls["force_recovery"] is False
    assert trainer.state["phase"] == "WAITING"
    assert trainer.state["wait_reason"]["reason"] == "not_enough_new_or_changed_training_data"
    _, status, result, claim_token = calls["finished"]
    assert status == "SUCCESS"
    assert result["training_started"] is False
    assert claim_token == "check-token"


@pytest.mark.asyncio
async def test_recover_now_control_requests_forced_recovery_but_keeps_training_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trainer = trainer_module.BackgroundTrainer()
    calls: dict[str, object] = {}
    trigger = {"reason": "operator_recovery", "recovery_reason": "bootstrap_recovery"}

    async def due_reason(*, force_recovery: bool = False):
        calls["force_recovery"] = force_recovery
        return True, trigger

    async def run_training_once(received_trigger: dict[str, object]):
        calls["trigger"] = received_trigger
        return {"candidate_version": "candidate-v2", "activated": False}

    async def heartbeat():
        calls["heartbeats"] = int(calls.get("heartbeats", 0)) + 1

    async def finish(
        job_id,
        *,
        status: str,
        result: dict[str, object],
        claim_token: str,
    ):
        calls["finished"] = (job_id, status, result, claim_token)

    monkeypatch.setattr(trainer, "due_reason", due_reason)
    monkeypatch.setattr(trainer, "run_training_once", run_training_once)
    monkeypatch.setattr(trainer, "heartbeat", heartbeat)
    monkeypatch.setattr(trainer, "finish_control_request", finish)
    job = SimpleNamespace(
        id=uuid4(),
        details={
            "action": "RECOVER_NOW",
            "requested_at": datetime.now(UTC).isoformat(),
            "claim_token": "recover-token",
        },
    )

    await trainer.process_control_request(job)

    assert calls["force_recovery"] is True
    assert calls["trigger"] == trigger
    _, status, result, claim_token = calls["finished"]
    assert status == "SUCCESS"
    assert result["training_started"] is True
    assert result["training_result"]["candidate_version"] == "candidate-v2"
    assert claim_token == "recover-token"


def test_latest_service_heartbeat_uses_freshest_instance() -> None:
    now = datetime.now(UTC)
    stale = SimpleNamespace(
        service_name="worker", last_seen_at=now - timedelta(minutes=5), details={"model": "stale"}
    )
    fresh = SimpleNamespace(
        service_name="worker", last_seen_at=now, details={"model": "fresh"}
    )
    trainer = SimpleNamespace(service_name="trainer", last_seen_at=now, details={})

    assert latest_service_heartbeat([stale, trainer, fresh], "worker") is fresh
    assert latest_service_heartbeat([stale, trainer, fresh], "missing") is None

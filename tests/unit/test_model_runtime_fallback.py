from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.v1.status import assess_model_runtime
from app.ml.runtime_selection import (
    recoverable_registry_artifact_notice,
    select_model_runtime,
)


def registry_model(path: Path | None, *, model_type: str = "barrier_logistic") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        version="missing-model-v1",
        model_type=model_type,
        artifact_path=str(path) if path is not None else None,
        artifact_sha256="0" * 64,
        calibration_version="cal-v1",
    )


def test_missing_active_artifact_falls_back_to_baseline_when_allowed(tmp_path: Path) -> None:
    registry = registry_model(tmp_path / "deleted.joblib")

    selection = select_model_runtime(
        registry=registry,
        active_model_path=None,
        allow_baseline_model=True,
        app_mode="paper",
        default_horizon_hours=8,
    )

    assert selection.runtime.is_baseline is True
    assert selection.runtime.source == "registry_artifact_missing_fallback"
    assert selection.registry_id == str(registry.id)
    assert selection.notice == {
        "active": True,
        "code": "ACTIVE_MODEL_ARTIFACT_MISSING",
        "message": "Active model artifact is missing; deterministic baseline is in use",
        "registry_id": str(registry.id),
        "registry_version": registry.version,
        "artifact_path": registry.artifact_path,
    }


def test_missing_active_artifact_remains_fail_closed_when_baseline_is_disabled(
    tmp_path: Path,
) -> None:
    registry = registry_model(tmp_path / "deleted.joblib")

    with pytest.raises(RuntimeError, match="Active model artifact does not exist"):
        select_model_runtime(
            registry=registry,
            active_model_path=None,
            allow_baseline_model=False,
            app_mode="shadow",
            default_horizon_hours=8,
        )


def test_production_never_falls_back_even_when_flag_is_true(tmp_path: Path) -> None:
    registry = registry_model(tmp_path / "deleted.joblib")

    with pytest.raises(RuntimeError, match="Active model artifact does not exist"):
        select_model_runtime(
            registry=registry,
            active_model_path=None,
            allow_baseline_model=True,
            app_mode="production",
            default_horizon_hours=8,
        )


def test_invalid_existing_artifact_does_not_fall_back(tmp_path: Path) -> None:
    artifact = tmp_path / "corrupt.joblib"
    artifact.write_bytes(b"not-a-joblib-artifact")
    registry = registry_model(artifact)

    with pytest.raises(RuntimeError, match="SHA256 mismatch"):
        select_model_runtime(
            registry=registry,
            active_model_path=None,
            allow_baseline_model=True,
            app_mode="paper",
            default_horizon_hours=8,
        )


def test_missing_environment_override_does_not_fall_back(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Active model artifact does not exist"):
        select_model_runtime(
            registry=None,
            active_model_path=tmp_path / "deleted-override.joblib",
            allow_baseline_model=True,
            app_mode="paper",
            default_horizon_hours=8,
        )


def test_no_registry_starts_bootstrap_baseline() -> None:
    selection = select_model_runtime(
        registry=None,
        active_model_path=None,
        allow_baseline_model=True,
        app_mode="paper",
        default_horizon_hours=8,
    )

    assert selection.runtime.is_baseline is True
    assert selection.runtime.source == "bootstrap_baseline"
    assert selection.registry_id is None
    assert selection.notice and selection.notice["code"] == "NO_ACTIVE_MODEL_REGISTERED"


def test_trainer_can_treat_only_missing_artifact_as_recoverable_bootstrap(tmp_path: Path) -> None:
    registry = registry_model(tmp_path / "deleted.joblib")

    notice = recoverable_registry_artifact_notice(
        registry,
        allow_baseline_model=True,
        app_mode="paper",
    )

    assert notice and notice["code"] == "ACTIVE_MODEL_ARTIFACT_MISSING"
    assert (
        recoverable_registry_artifact_notice(
            registry,
            allow_baseline_model=False,
            app_mode="paper",
        )
        is None
    )


def test_readiness_accepts_explicit_missing_artifact_fallback() -> None:
    result = assess_model_runtime(
        registry_version="trained-v1",
        registry_type="barrier_logistic",
        artifact_ok=False,
        worker_model={"version": "baseline-momentum-v1", "baseline": True},
        worker_notice={
            "active": True,
            "code": "ACTIVE_MODEL_ARTIFACT_MISSING",
            "registry_version": "trained-v1",
        },
        allow_baseline_model=True,
    )

    assert result["ok"] is True
    assert result["fallback_active"] is True
    assert result["degraded"] is True
    assert result["runtime_matches_registry"] is False


def test_readiness_rejects_artifact_failure_without_controlled_fallback() -> None:
    result = assess_model_runtime(
        registry_version="trained-v1",
        registry_type="barrier_logistic",
        artifact_ok=False,
        worker_model={"version": "trained-v1", "baseline": False},
        worker_notice=None,
        allow_baseline_model=True,
    )

    assert result["ok"] is False
    assert result["fallback_active"] is False


def test_readiness_accepts_bootstrap_baseline_without_registry() -> None:
    result = assess_model_runtime(
        registry_version=None,
        registry_type=None,
        artifact_ok=True,
        worker_model={"version": "baseline-momentum-v1", "baseline": True},
        worker_notice={"active": True, "code": "NO_ACTIVE_MODEL_REGISTERED"},
        allow_baseline_model=True,
    )

    assert result["ok"] is True
    assert result["fallback_active"] is True

@pytest.mark.asyncio
async def test_worker_refresh_survives_deleted_active_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers import runner as runner_module

    registry = registry_model(tmp_path / "deleted.joblib")

    class FakeResult:
        def scalar_one_or_none(self) -> SimpleNamespace:
            return registry

    class FakeSession:
        async def __aenter__(self) -> FakeSession:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def begin(self) -> FakeSession:
            return self

        async def execute(self, _statement: object, *_args: object) -> FakeResult:
            return FakeResult()

    monkeypatch.setattr(runner_module, "SessionFactory", FakeSession)
    monkeypatch.setattr(
        runner_module,
        "settings",
        runner_module.settings.model_copy(
            update={
                "active_model_path": None,
                "allow_baseline_model": True,
                "app_mode": "paper",
                "default_horizon_hours": 8,
            }
        ),
    )

    worker = runner_module.Worker()
    try:
        changed = await worker.refresh_model_runtime(force=True)
    finally:
        await worker.client.close()

    assert changed is True
    assert worker.runtime.is_baseline is True
    assert worker.model_notice and worker.model_notice["code"] == "ACTIVE_MODEL_ARTIFACT_MISSING"
    assert worker.model_heartbeat_status() == "DEGRADED"


def test_candidate_diagnostics_distinguish_gate_failure_and_orphan_files(tmp_path: Path) -> None:
    from app.api.v1.status import candidate_diagnostics, orphan_model_artifacts

    registered_path = tmp_path / "registered.joblib"
    registered_path.write_bytes(b"registered")
    orphan_path = tmp_path / "barrier-logistic-h8-20260628T072708Z.joblib"
    orphan_path.write_bytes(b"orphan")
    candidate = SimpleNamespace(
        version="registered",
        artifact_path=str(registered_path),
        metrics={
            "activation_requested": False,
            "quality_gate": {
                "passed": False,
                "reasons": ["policy_profit_factor_below_minimum"],
            },
        },
        updated_at=None,
    )

    details = candidate_diagnostics(candidate)
    orphans = orphan_model_artifacts(tmp_path, [candidate])

    assert details["artifact_exists"] is True
    assert details["quality_gate_passed"] is False
    assert details["quality_gate_reasons"] == ["policy_profit_factor_below_minimum"]
    assert orphans == [orphan_path.name]

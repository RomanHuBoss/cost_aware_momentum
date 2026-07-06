from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.model_promotion import (
    EXPERIMENT_PROMOTION_GATE_SCHEMA,
    experiment_policy_binding_from_settings,
)
from app.workers import trainer as trainer_module


class _Session:
    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        return None


@pytest.mark.asyncio
async def test_trainer_promotes_registered_candidate_after_evidence_becomes_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trainer = trainer_module.BackgroundTrainer()
    monkeypatch.setattr(trainer, "_candidate_artifact_rejection", lambda _candidate: (None, {}))
    policy_binding = experiment_policy_binding_from_settings(trainer_module.settings)
    candidate = SimpleNamespace(
        version="candidate-v2",
        artifact_sha256="a" * 64,
        active=False,
        metrics={
            "source": "background_trainer",
            "activation_requested": True,
            "horizon_hours": 8,
            "quality_gate": {"passed": True, "reasons": []},
            "experiment_promotion_gate": {"experiment_family": "family-v2"},
            "promotion_policy_binding": policy_binding,
        },
    )
    incumbent = SimpleNamespace(version="incumbent-v1", active=True)
    calls: dict[str, object] = {}

    async def pending_candidate() -> object:
        return candidate

    async def active_model() -> object:
        return incumbent

    async def ready_gate(_session: object, **kwargs: object) -> dict[str, object]:
        calls["gate_kwargs"] = kwargs
        return {
            "schema": EXPERIMENT_PROMOTION_GATE_SCHEMA,
            "passed": True,
            "reasons": [],
            "experiment_family": "family-v2",
            "binding": {
                "model_version": "candidate-v2",
                "model_sha256": "a" * 64,
                "horizon_hours": 8,
            },
        }

    async def activate(version: str, **kwargs: object) -> dict[str, object]:
        calls["activation"] = {"version": version, **kwargs}
        return {"version": version, "previous_version": "incumbent-v1"}

    monkeypatch.setattr(trainer_module, "settings", trainer_module.settings.model_copy(update={
        "auto_train_auto_activate": True,
        "auto_train_experiment_family": "family-v2",
        "active_model_path": None,
        "default_horizon_hours": 8,
    }))
    monkeypatch.setattr(trainer, "_pending_auto_activation_candidate", pending_candidate)
    monkeypatch.setattr(trainer, "active_model", active_model)
    monkeypatch.setattr(trainer_module, "SessionFactory", lambda: _Session())
    monkeypatch.setattr(trainer_module, "evaluate_experiment_promotion_gate", ready_gate)
    monkeypatch.setattr(trainer_module, "activate_registered_model", activate)

    result = await trainer.reconcile_pending_activation()

    assert result["status"] == "ACTIVATED"
    assert result["candidate_version"] == "candidate-v2"
    assert calls["gate_kwargs"] == {
        "experiment_family": "family-v2",
        "model_version": "candidate-v2",
        "model_sha256": "a" * 64,
        "horizon_hours": 8,
        "expected_policy_binding": policy_binding,
    }
    assert calls["activation"] == {
        "version": "candidate-v2",
        "actor": trainer_module.settings.trainer_id,
        "expected_previous_version": "incumbent-v1",
        "enforce_expected_previous_version": True,
        "experiment_family": "family-v2",
    }


@pytest.mark.asyncio
async def test_scheduling_iteration_does_not_retrain_after_deferred_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trainer = trainer_module.BackgroundTrainer()

    async def promoted() -> dict[str, object]:
        return {
            "status": "ACTIVATED",
            "candidate_version": "candidate-v2",
            "activation": {"version": "candidate-v2"},
        }

    async def unexpected(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("training eligibility must not be evaluated after activation")

    monkeypatch.setattr(trainer, "reconcile_pending_activation", promoted)
    monkeypatch.setattr(trainer, "due_reason", unexpected)
    monkeypatch.setattr(trainer, "run_training_once", unexpected)

    await trainer.run_scheduling_iteration()

    assert trainer.state["phase"] == "WAITING"
    assert trainer.state["healthy"] is True
    assert trainer.state["last_promotion"]["status"] == "ACTIVATED"
    assert trainer.state["wait_reason"] == {
        "reason": "registered_candidate_activated",
        "candidate_version": "candidate-v2",
    }

@pytest.mark.asyncio
async def test_deferred_promotion_remains_fail_closed_until_experiment_is_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trainer = trainer_module.BackgroundTrainer()
    monkeypatch.setattr(trainer, "_candidate_artifact_rejection", lambda _candidate: (None, {}))
    policy_binding = experiment_policy_binding_from_settings(trainer_module.settings)
    candidate = SimpleNamespace(
        version="candidate-waiting",
        artifact_sha256="b" * 64,
        active=False,
        metrics={
            "source": "background_trainer",
            "activation_requested": True,
            "horizon_hours": 8,
            "quality_gate": {"passed": True, "reasons": []},
            "experiment_promotion_gate": {"experiment_family": "family-waiting"},
            "promotion_policy_binding": policy_binding,
        },
    )

    async def pending_candidate() -> object:
        return candidate

    async def blocked_gate(_session: object, **_kwargs: object) -> dict[str, object]:
        return {
            "schema": EXPERIMENT_PROMOTION_GATE_SCHEMA,
            "passed": False,
            "reasons": ["experiment_governance_in_progress"],
            "experiment_family": "family-waiting",
            "binding": {
                "model_version": "candidate-waiting",
                "model_sha256": "b" * 64,
                "horizon_hours": 8,
            },
        }

    async def unexpected_activation(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("a blocked candidate must never be activated")

    monkeypatch.setattr(trainer_module, "settings", trainer_module.settings.model_copy(update={
        "auto_train_auto_activate": True,
        "auto_train_experiment_family": "family-waiting",
        "active_model_path": None,
        "default_horizon_hours": 8,
    }))
    monkeypatch.setattr(trainer, "_pending_auto_activation_candidate", pending_candidate)
    monkeypatch.setattr(trainer_module, "SessionFactory", lambda: _Session())
    monkeypatch.setattr(trainer_module, "evaluate_experiment_promotion_gate", blocked_gate)
    monkeypatch.setattr(trainer_module, "activate_registered_model", unexpected_activation)

    result = await trainer.reconcile_pending_activation()

    assert result["status"] == "WAITING"
    assert result["reason"] == "experiment_promotion_gate_failed"
    assert result["experiment_promotion_gate"]["reasons"] == [
        "experiment_governance_in_progress"
    ]

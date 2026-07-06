from __future__ import annotations

from collections import Counter
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.research.preregistration import normalize_preregistration_spec
from app.services.automatic_experiment import (
    AUTOMATIC_EXPERIMENT_SCHEMA,
    automatic_experiment_plan,
    finalize_automatic_preregistration,
)
from app.services.model_promotion import (
    EXPERIMENT_PROMOTION_GATE_SCHEMA,
    experiment_policy_binding_from_settings,
)
from app.workers import trainer as trainer_module


class _Session:
    def begin(self) -> _Session:
        return self

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        return None


def _template(family: str) -> dict[str, object]:
    return {
        "schema": "formal-experiment-family-preregistration-v1",
        "experiment_family": family,
        "hypothesis": "REPLACE_WITH_A_SUBSTANTIVE_DIRECTIONAL_HYPOTHESIS_BEFORE_ANY_TRIAL",
        "primary_metric": {"name": "nonannualized_sharpe", "direction": "maximize"},
        "configuration_contract": {
            "fixed_parameters": {
                "schema": "barrier-policy-experiment-configuration-v1",
                "dataset_fingerprint": "f" * 64,
                "model_version": "candidate-v3",
                "model_sha256": "a" * 64,
                "horizon": 8,
                "policy_source": "cost_aware_ev_r_v1",
                "portfolio_accounting": "risk_budgeted_hourly_mark_to_market_single_active_symbol_v4",
            },
            "search_space": {
                "minimum_net_rr": {"values": [1.2]},
                "minimum_net_ev_r": {"values": [0.05]},
            },
        },
        "governance": {
            "pbo_segments": 6,
            "minimum_trials": 4,
            "minimum_periods": 60,
            "maximum_pbo": 0.2,
            "minimum_dsr_probability": 0.95,
            "dependence_block_periods": 8,
            "minimum_independent_blocks": 6,
            "bootstrap_replicates": 1000,
            "confidence_level": 0.95,
        },
        "stopping_rule": {"max_unique_configurations": 4, "stop_after_utc": None},
        "exclusion_criteria": [
            {
                "code": "REPLACE_EXCLUSION_CODE",
                "description": "REPLACE_WITH_AN_OBJECTIVE_PRE_RESULT_EXCLUSION_CRITERION",
            }
        ],
        "template_created_at": "2026-07-06T00:00:00+00:00",
    }


def test_automatic_experiment_plan_is_bounded_deterministic_and_contains_deployment_policy() -> None:
    settings = Settings(
        auto_train_experiment_rr_multipliers=(1.0, 1.25),
        auto_train_experiment_ev_additions=(0.0, 0.05),
        min_net_rr=1.2,
        min_net_ev_r=0.05,
        experiment_min_trials=4,
    )

    plan = automatic_experiment_plan(
        settings,
        model_version="candidate-v3",
        model_sha256="a" * 64,
    )
    repeated = automatic_experiment_plan(
        settings,
        model_version="candidate-v3",
        model_sha256="a" * 64,
    )

    assert plan == repeated
    assert plan["schema"] == AUTOMATIC_EXPERIMENT_SCHEMA
    assert plan["search_parameters"] == ["minimum_net_rr", "minimum_net_ev_r"]
    assert plan["configurations"] == [
        {"minimum_net_rr": 1.2, "minimum_net_ev_r": 0.05},
        {"minimum_net_rr": 1.2, "minimum_net_ev_r": 0.1},
        {"minimum_net_rr": 1.5, "minimum_net_ev_r": 0.05},
        {"minimum_net_rr": 1.5, "minimum_net_ev_r": 0.1},
    ]
    assert plan["deployment_configuration"] == {
        "minimum_net_rr": 1.2,
        "minimum_net_ev_r": 0.05,
    }
    assert len(plan["configurations"]) == settings.experiment_min_trials
    assert str(plan["experiment_family"]).startswith("auto-candidate-v3-")


def test_automatic_preregistration_is_complete_before_any_trial() -> None:
    settings = Settings(
        auto_train_experiment_rr_multipliers=(1.0, 1.25),
        auto_train_experiment_ev_additions=(0.0, 0.05),
        min_net_rr=1.2,
        min_net_ev_r=0.05,
        experiment_min_trials=4,
    )
    plan = automatic_experiment_plan(
        settings,
        model_version="candidate-v3",
        model_sha256="a" * 64,
    )
    template = _template(str(plan["experiment_family"]))
    untouched = deepcopy(template)

    specification = finalize_automatic_preregistration(
        template,
        plan=plan,
        model_version="candidate-v3",
        model_sha256="a" * 64,
    )
    normalized = normalize_preregistration_spec(
        specification,
        expected_family=str(plan["experiment_family"]),
    )

    assert template == untouched
    assert "REPLACE_" not in str(normalized)
    assert normalized["stopping_rule"]["max_unique_configurations"] == 4
    assert normalized["configuration_contract"]["search_space"] == {
        "minimum_net_ev_r": {"values": [0.05, 0.1]},
        "minimum_net_rr": {"values": [1.2, 1.5]},
    }
    assert normalized["configuration_contract"]["fixed_parameters"]["model_version"] == "candidate-v3"
    assert normalized["configuration_contract"]["fixed_parameters"]["model_sha256"] == "a" * 64


@pytest.mark.asyncio
async def test_trainer_automatically_orchestrates_missing_family_before_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trainer = trainer_module.BackgroundTrainer()
    monkeypatch.setattr(trainer, "_candidate_artifact_rejection", lambda _candidate: (None, {}))
    policy_binding = experiment_policy_binding_from_settings(trainer_module.settings)
    candidate = SimpleNamespace(
        version="candidate-v3",
        artifact_sha256="a" * 64,
        artifact_path="models/candidate-v3.joblib",
        active=False,
        metrics={
            "source": "background_trainer",
            "activation_requested": True,
            "horizon_hours": 8,
            "quality_gate": {"passed": True, "reasons": []},
            "experiment_promotion_gate": {"experiment_family": None},
            "promotion_policy_binding": policy_binding,
        },
    )
    incumbent = SimpleNamespace(version="incumbent-v2", active=True)
    calls: dict[str, object] = {}

    async def pending_candidate() -> object:
        return candidate

    async def active_model() -> object:
        return incumbent

    async def orchestrate(candidate_arg: object, **kwargs: object) -> dict[str, object]:
        calls["orchestration"] = {"candidate": candidate_arg, **kwargs}
        return {
            "status": "COMPLETE",
            "experiment_family": "auto-candidate-v3-family",
            "report_status": "READY",
        }

    async def ready_gate(_session: object, **kwargs: object) -> dict[str, object]:
        calls["gate"] = kwargs
        return {
            "schema": EXPERIMENT_PROMOTION_GATE_SCHEMA,
            "passed": True,
            "reasons": [],
            "experiment_family": "auto-candidate-v3-family",
            "binding": {
                "model_version": "candidate-v3",
                "model_sha256": "a" * 64,
                "horizon_hours": 8,
            },
        }

    async def activate(version: str, **kwargs: object) -> dict[str, object]:
        calls["activation"] = {"version": version, **kwargs}
        return {"version": version, "previous_version": "incumbent-v2"}

    monkeypatch.setattr(trainer_module, "settings", trainer_module.settings.model_copy(update={
        "auto_train_auto_activate": True,
        "auto_train_auto_experiment": True,
        "auto_train_experiment_family": None,
        "active_model_path": None,
        "default_horizon_hours": 8,
    }))
    monkeypatch.setattr(trainer, "_pending_auto_activation_candidate", pending_candidate)
    monkeypatch.setattr(trainer, "active_model", active_model)
    monkeypatch.setattr(trainer_module, "SessionFactory", lambda: _Session())
    monkeypatch.setattr(trainer_module, "orchestrate_automatic_experiment", orchestrate)
    monkeypatch.setattr(trainer_module, "evaluate_experiment_promotion_gate", ready_gate)
    monkeypatch.setattr(trainer_module, "activate_registered_model", activate)

    result = await trainer.reconcile_pending_activation()

    assert result["status"] == "ACTIVATED"
    assert result["experiment_family"] == "auto-candidate-v3-family"
    assert calls["orchestration"]["candidate"] is candidate
    assert calls["gate"]["experiment_family"] == "auto-candidate-v3-family"
    assert calls["activation"]["experiment_family"] == "auto-candidate-v3-family"


@pytest.mark.asyncio
async def test_scheduler_does_not_retrain_while_automatic_experiment_is_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trainer = trainer_module.BackgroundTrainer()

    async def waiting() -> dict[str, object]:
        return {
            "status": "WAITING",
            "reason": "automatic_experiment_open_trial",
            "candidate_version": "candidate-v3",
            "experiment_family": "auto-candidate-v3-family",
        }

    async def unexpected(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("trainer must not create another candidate while governance is pending")

    monkeypatch.setattr(trainer, "reconcile_pending_activation", waiting)
    monkeypatch.setattr(trainer, "due_reason", unexpected)
    monkeypatch.setattr(trainer, "run_training_once", unexpected)

    await trainer.run_scheduling_iteration()

    assert trainer.state["phase"] == "WAITING"
    assert trainer.state["healthy"] is True
    assert trainer.state["wait_reason"] == {
        "reason": "automatic_experiment_open_trial",
        "candidate_version": "candidate-v3",
        "experiment_family": "auto-candidate-v3-family",
    }


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar(self) -> object:
        return self._value


class _Connection:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        return None

    async def execute(self, statement: object, _parameters: object = None) -> _ScalarResult:
        sql = str(statement)
        if "pg_try_advisory_lock" in sql:
            self.events.append("lock")
            return _ScalarResult(True)
        if "pg_advisory_unlock" in sql:
            self.events.append("unlock")
            return _ScalarResult(True)
        raise AssertionError(f"unexpected SQL: {sql}")

    async def commit(self) -> None:
        return None


class _Engine:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def connect(self) -> _Connection:
        return _Connection(self.events)


@pytest.mark.asyncio
async def test_orchestrator_registers_complete_preregistration_before_first_trial(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from app.services import automatic_experiment as automatic_module

    events: list[str] = []
    artifact = tmp_path / "candidate.joblib"
    artifact.write_bytes(b"immutable-candidate")
    digest = __import__("hashlib").sha256(artifact.read_bytes()).hexdigest()
    candidate = SimpleNamespace(
        version="candidate-v4",
        artifact_sha256=digest,
        artifact_path=str(artifact),
        metrics={"horizon_hours": 8},
    )
    settings = Settings(
        default_horizon_hours=8,
        auto_train_experiment_rr_multipliers=(1.0, 1.25),
        auto_train_experiment_ev_additions=(0.0, 0.05),
        experiment_min_trials=4,
    )
    registration_holder: dict[str, object] = {}
    successful_hashes: set[str] = set()

    async def load_registration(_session: object, **_kwargs: object) -> object | None:
        return registration_holder.get("row")

    async def register_family(_session: object, **kwargs: object) -> object:
        events.append("register")
        specification = kwargs["specification"]
        assert "REPLACE_" not in str(specification)
        row = SimpleNamespace(specification=specification, record_hash="b" * 64)
        registration_holder["row"] = row
        return row

    async def progress(
        _family: str,
        specification: object,
        _record_hash: str,
    ) -> dict[str, object]:
        attempted = Counter(successful_hashes)
        return {
            "attempted": attempted,
            "successful": set(successful_hashes),
            "failed": Counter(),
            "open_trials": [],
            "event_count": len(successful_hashes) * 2,
            "specification": specification,
        }

    async def report(_session: object, **_kwargs: object) -> dict[str, object]:
        return {"status": "READY", "selected_configuration_hash": next(iter(successful_hashes))}

    async def runner(command: object, _cwd: object, _timeout: int) -> dict[str, object]:
        command = list(command)
        if "--prepare-preregistration" in command:
            events.append("prepare")
            output = command[command.index("--prepare-preregistration") + 1]
            family = command[command.index("--experiment-family") + 1]
            model_sha = command[command.index("--model-sha256") + 1]
            template = _template(family)
            template["configuration_contract"]["fixed_parameters"]["model_version"] = "candidate-v4"
            template["configuration_contract"]["fixed_parameters"]["model_sha256"] = model_sha
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_text(__import__("json").dumps(template), encoding="utf-8")
        else:
            assert "register" in events
            events.append("trial")
            rr = float(command[command.index("--minimum-net-rr") + 1])
            ev = float(command[command.index("--minimum-net-ev-r") + 1])
            specification = registration_holder["row"].specification
            configuration = {
                **specification["configuration_contract"]["fixed_parameters"],
                "minimum_net_rr": rr,
                "minimum_net_ev_r": ev,
            }
            from app.services.experiment_ledger import experiment_configuration_hash

            successful_hashes.add(experiment_configuration_hash(configuration))
        return {"returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(automatic_module, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(automatic_module, "engine", _Engine(events))
    monkeypatch.setattr(automatic_module, "SessionFactory", lambda: _Session())
    monkeypatch.setattr(automatic_module, "load_experiment_preregistration", load_registration)
    monkeypatch.setattr(automatic_module, "register_experiment_family", register_family)
    monkeypatch.setattr(automatic_module, "_load_progress", progress)
    monkeypatch.setattr(automatic_module, "experiment_governance_report", report)

    result = await automatic_module.orchestrate_automatic_experiment(
        candidate,
        settings=settings,
        actor="trainer-test",
        command_runner=runner,
    )

    assert result["status"] == "COMPLETE"
    assert result["configuration_count"] == 4
    assert result["executed_configuration_count"] == 4
    assert events[0:3] == ["lock", "prepare", "register"]
    assert events.count("trial") == 4
    assert events[-1] == "unlock"


def test_policy_mismatch_ready_report_is_terminal_for_exact_candidate() -> None:
    from app.services.automatic_experiment import experiment_gate_is_terminal

    assert experiment_gate_is_terminal(
        {
            "report_status": "READY",
            "reasons": ["selected_trial_policy_mismatch:minimum_net_ev_r"],
        }
    )
    assert not experiment_gate_is_terminal(
        {
            "report_status": "BLOCKED_INCOMPLETE_LEDGER",
            "reasons": ["experiment_governance_blocked_incomplete_ledger"],
        }
    )

@pytest.mark.asyncio
async def test_trainer_closes_candidate_when_automatic_experiment_retries_are_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trainer = trainer_module.BackgroundTrainer()
    monkeypatch.setattr(trainer, "_candidate_artifact_rejection", lambda _candidate: (None, {}))
    candidate = SimpleNamespace(
        version="candidate-v5",
        artifact_sha256="c" * 64,
        artifact_path="models/candidate-v5.joblib",
        active=False,
        metrics={
            "source": "background_trainer",
            "activation_requested": True,
            "horizon_hours": 8,
            "quality_gate": {"passed": True, "reasons": []},
            "experiment_promotion_gate": {"experiment_family": None},
            "promotion_policy_binding": experiment_policy_binding_from_settings(
                trainer_module.settings
            ),
        },
    )
    calls: dict[str, object] = {}

    async def pending_candidate() -> object:
        return candidate

    async def orchestrate(_candidate: object, **_kwargs: object) -> dict[str, object]:
        return {
            "status": "REJECTED",
            "reason": "automatic_experiment_retry_exhausted",
            "experiment_family": "auto-candidate-v5-family",
            "configuration_hash": "d" * 64,
            "attempts": 2,
        }

    async def close_request(**kwargs: object) -> dict[str, object]:
        calls["closure"] = kwargs
        return {"status": "CLOSED", "candidate_version": "candidate-v5"}

    async def unexpected(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("terminal automatic experiment failure must not reach promotion evaluation")

    monkeypatch.setattr(trainer_module, "settings", trainer_module.settings.model_copy(update={
        "auto_train_auto_activate": True,
        "auto_train_auto_experiment": True,
        "auto_train_experiment_family": None,
        "active_model_path": None,
        "default_horizon_hours": 8,
    }))
    monkeypatch.setattr(trainer, "_pending_auto_activation_candidate", pending_candidate)
    monkeypatch.setattr(trainer_module, "orchestrate_automatic_experiment", orchestrate)
    monkeypatch.setattr(trainer_module, "close_candidate_activation_request", close_request)
    monkeypatch.setattr(trainer_module, "evaluate_experiment_promotion_gate", unexpected)
    monkeypatch.setattr(trainer_module, "activate_registered_model", unexpected)

    result = await trainer.reconcile_pending_activation()

    assert result["status"] == "REJECTED"
    assert result["reason"] == "automatic_experiment_retry_exhausted"
    assert calls["closure"]["candidate_version"] == "candidate-v5"
    assert calls["closure"]["experiment_family"] == "auto-candidate-v5-family"
    assert calls["closure"]["experiment_gate"]["report_status"] == "AUTOMATIC_EXPERIMENT_FAILED"


@pytest.mark.asyncio
async def test_orchestrator_marks_any_open_attempt_failed_when_trial_process_aborts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from app.services import automatic_experiment as automatic_module

    events: list[str] = []
    artifact = tmp_path / "candidate.joblib"
    artifact.write_bytes(b"candidate-with-aborted-trial")
    digest = __import__("hashlib").sha256(artifact.read_bytes()).hexdigest()
    candidate = SimpleNamespace(
        version="candidate-v6",
        artifact_sha256=digest,
        artifact_path=str(artifact),
        metrics={"horizon_hours": 8},
    )
    settings = Settings(default_horizon_hours=8, experiment_min_trials=4)
    plan = automatic_experiment_plan(
        settings,
        model_version=candidate.version,
        model_sha256=digest,
    )
    raw_template = _template(str(plan["experiment_family"]))
    raw_template["configuration_contract"]["fixed_parameters"]["model_version"] = candidate.version
    raw_template["configuration_contract"]["fixed_parameters"]["model_sha256"] = digest
    specification = finalize_automatic_preregistration(
        raw_template,
        plan=plan,
        model_version=candidate.version,
        model_sha256=digest,
    )
    registration = SimpleNamespace(specification=specification, record_hash="e" * 64)
    failed: list[dict[str, object]] = []

    async def load_registration(_session: object, **_kwargs: object) -> object:
        return registration

    async def progress(
        _family: str,
        specification_arg: object,
        _record_hash: str,
    ) -> dict[str, object]:
        return {
            "attempted": Counter(),
            "successful": set(),
            "failed": Counter(),
            "open_trials": [],
            "event_count": 0,
            "specification": specification_arg,
        }

    async def runner(_command: object, _cwd: object, _timeout: int) -> dict[str, object]:
        raise RuntimeError("simulated child crash after STARTED")

    async def fail_open(**kwargs: object) -> list[str]:
        failed.append(kwargs)
        return ["00000000-0000-0000-0000-000000000001"]

    monkeypatch.setattr(automatic_module, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(automatic_module, "engine", _Engine(events))
    monkeypatch.setattr(automatic_module, "SessionFactory", lambda: _Session())
    monkeypatch.setattr(automatic_module, "load_experiment_preregistration", load_registration)
    monkeypatch.setattr(automatic_module, "_load_progress", progress)
    monkeypatch.setattr(automatic_module, "fail_open_automatic_experiment_attempts", fail_open)

    with pytest.raises(RuntimeError, match="simulated child crash"):
        await automatic_module.orchestrate_automatic_experiment(
            candidate,
            settings=settings,
            actor="trainer-test",
            command_runner=runner,
        )

    assert len(failed) == 1
    assert failed[0]["experiment_family"] == plan["experiment_family"]
    assert failed[0]["configuration_hash"]
    assert failed[0]["error_type"] == "RuntimeError"
    assert events[-1] == "unlock"

def test_automatic_experiment_grid_parses_environment_list_syntax() -> None:
    settings = Settings(
        auto_train_experiment_rr_multipliers="1.0,1.5",
        auto_train_experiment_ev_additions="0,0.1",
        experiment_min_trials=4,
    )

    assert settings.auto_train_experiment_rr_multipliers == [1.0, 1.5]
    assert settings.auto_train_experiment_ev_additions == [0.0, 0.1]


def test_automatic_experiment_grid_requires_exact_deployment_configuration() -> None:
    with pytest.raises(ValueError, match="exact deployment policy"):
        Settings(
            auto_train_experiment_rr_multipliers=[1.25, 1.5],
            auto_train_experiment_ev_additions=[0.0, 0.05],
            experiment_min_trials=4,
        )


def test_automatic_experiment_grid_is_bounded_to_sixteen_configurations() -> None:
    with pytest.raises(ValueError, match="limited to 16 configurations"):
        Settings(
            auto_train_experiment_rr_multipliers=[1.0, 1.25, 1.5, 1.75, 2.0],
            auto_train_experiment_ev_additions=[0.0, 0.01, 0.02, 0.03],
            experiment_min_trials=4,
        )

@pytest.mark.asyncio
async def test_orchestrator_recovers_timed_out_open_trial_before_evaluating_family(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from app.services import automatic_experiment as automatic_module
    from app.services.experiment_ledger import experiment_configuration_hash

    events: list[str] = []
    artifact = tmp_path / "candidate.joblib"
    artifact.write_bytes(b"candidate-with-stale-open-trial")
    digest = __import__("hashlib").sha256(artifact.read_bytes()).hexdigest()
    candidate = SimpleNamespace(
        version="candidate-v7",
        artifact_sha256=digest,
        artifact_path=str(artifact),
        metrics={"horizon_hours": 8},
    )
    settings = Settings(default_horizon_hours=8, experiment_min_trials=4)
    plan = automatic_experiment_plan(
        settings,
        model_version=candidate.version,
        model_sha256=digest,
    )
    raw_template = _template(str(plan["experiment_family"]))
    raw_template["configuration_contract"]["fixed_parameters"]["model_version"] = candidate.version
    raw_template["configuration_contract"]["fixed_parameters"]["model_sha256"] = digest
    specification = finalize_automatic_preregistration(
        raw_template,
        plan=plan,
        model_version=candidate.version,
        model_sha256=digest,
    )
    registration = SimpleNamespace(specification=specification, record_hash="f" * 64)
    successful = {
        experiment_configuration_hash(
            {
                **specification["configuration_contract"]["fixed_parameters"],
                **selected,
            }
        )
        for selected in plan["configurations"]
    }
    progress_calls = 0
    recovery_calls: list[dict[str, object]] = []

    async def load_registration(_session: object, **_kwargs: object) -> object:
        return registration

    async def progress(
        _family: str,
        specification_arg: object,
        _record_hash: str,
    ) -> dict[str, object]:
        nonlocal progress_calls
        progress_calls += 1
        return {
            "attempted": Counter(successful),
            "successful": successful,
            "failed": Counter(),
            "open_trials": ["00000000-0000-0000-0000-000000000007"] if progress_calls == 1 else [],
            "event_count": len(successful) * 2,
            "specification": specification_arg,
        }

    async def recover(**kwargs: object) -> list[str]:
        recovery_calls.append(kwargs)
        return ["00000000-0000-0000-0000-000000000007"]

    async def report(_session: object, **_kwargs: object) -> dict[str, object]:
        return {"status": "READY"}

    async def unexpected_runner(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("all preregistered configurations are already successful")

    monkeypatch.setattr(automatic_module, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(automatic_module, "engine", _Engine(events))
    monkeypatch.setattr(automatic_module, "SessionFactory", lambda: _Session())
    monkeypatch.setattr(automatic_module, "load_experiment_preregistration", load_registration)
    monkeypatch.setattr(automatic_module, "_load_progress", progress)
    monkeypatch.setattr(automatic_module, "recover_stale_automatic_experiment_attempts", recover)
    monkeypatch.setattr(automatic_module, "experiment_governance_report", report)

    result = await automatic_module.orchestrate_automatic_experiment(
        candidate,
        settings=settings,
        actor="trainer-test",
        command_runner=unexpected_runner,
    )

    assert result["status"] == "COMPLETE"
    assert result["executed_configuration_count"] == 0
    assert result["already_successful_configuration_count"] == 4
    assert result["recovered_stale_trial_ids"] == [
        "00000000-0000-0000-0000-000000000007"
    ]
    assert recovery_calls == [{
        "experiment_family": plan["experiment_family"],
        "timeout_seconds": settings.auto_train_experiment_timeout_seconds,
    }]

@pytest.mark.asyncio
async def test_trainer_rejects_stale_policy_binding_before_automatic_backtests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trainer = trainer_module.BackgroundTrainer()
    monkeypatch.setattr(trainer, "_candidate_artifact_rejection", lambda _candidate: (None, {}))
    persisted_binding = experiment_policy_binding_from_settings(trainer_module.settings)
    candidate = SimpleNamespace(
        version="candidate-v8",
        artifact_sha256="8" * 64,
        artifact_path="models/candidate-v8.joblib",
        active=False,
        metrics={
            "source": "background_trainer",
            "activation_requested": True,
            "horizon_hours": trainer_module.settings.default_horizon_hours,
            "quality_gate": {"passed": True, "reasons": []},
            "promotion_policy_binding": persisted_binding,
            "experiment_promotion_gate": {"experiment_family": None},
        },
    )
    calls: dict[str, object] = {}

    async def pending_candidate() -> object:
        return candidate

    async def close_request(**kwargs: object) -> dict[str, object]:
        calls["closure"] = kwargs
        return {"status": "CLOSED", "candidate_version": candidate.version}

    async def unexpected(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("stale candidate policy must be rejected before experiment execution")

    monkeypatch.setattr(
        trainer_module,
        "settings",
        trainer_module.settings.model_copy(
            update={
                "min_net_rr": trainer_module.settings.min_net_rr + 0.1,
                "auto_train_auto_activate": True,
                "auto_train_auto_experiment": True,
                "active_model_path": None,
            }
        ),
    )
    monkeypatch.setattr(trainer, "_pending_auto_activation_candidate", pending_candidate)
    monkeypatch.setattr(trainer_module, "close_candidate_activation_request", close_request)
    monkeypatch.setattr(trainer_module, "orchestrate_automatic_experiment", unexpected)
    monkeypatch.setattr(trainer_module, "evaluate_experiment_promotion_gate", unexpected)

    result = await trainer.reconcile_pending_activation()

    assert result["status"] == "REJECTED"
    assert result["reason"] == "candidate_policy_binding_mismatch_current_settings"
    assert calls["closure"]["experiment_gate"]["report_status"] == (
        "CANDIDATE_POLICY_BINDING_STALE"
    )

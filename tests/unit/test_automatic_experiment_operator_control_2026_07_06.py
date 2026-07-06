from __future__ import annotations

import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.schemas import TrainerControlRequest
from app.config import Settings
from app.services.automatic_experiment import AutomaticExperimentCancelled, _run_subprocess
from app.services.trainer_control import (
    ExperimentCancelClaim,
    automatic_experiment_cancel_availability,
    automatic_experiment_cancel_target_matches,
    control_job_payload,
    pending_automatic_experiment_cancel_statement,
    trainer_control_can_be_superseded_by_cancel,
)


def test_cancel_request_requires_exact_candidate_and_family() -> None:
    with pytest.raises(ValidationError):
        TrainerControlRequest(action="CANCEL_EXPERIMENT")

    request = TrainerControlRequest(
        action="CANCEL_EXPERIMENT",
        experiment_family="auto-candidate-v3-family",
        candidate_version="candidate-v3",
    )
    assert request.experiment_family == "auto-candidate-v3-family"
    assert request.candidate_version == "candidate-v3"

    with pytest.raises(ValidationError):
        TrainerControlRequest(
            action="CHECK_NOW",
            experiment_family="auto-candidate-v3-family",
            candidate_version="candidate-v3",
        )


def test_cancel_availability_is_fail_closed_and_exact_targeted() -> None:
    now = datetime.now(UTC)
    settings = Settings(heartbeat_seconds=15)
    heartbeat = SimpleNamespace(
        status="RUNNING",
        last_seen_at=now,
        details={
            "automatic_experiment": {
                "status": "RUNNING",
                "subprocess_active": True,
                "experiment_family": "auto-candidate-v3-family",
                "candidate_version": "candidate-v3",
                "stage": "formal_backtest",
            }
        },
    )

    available, reason, payload = automatic_experiment_cancel_availability(
        heartbeat,
        settings,
        now=now,
    )

    assert available is True
    assert reason == "automatic_experiment_subprocess_running"
    assert payload["experiment_family"] == "auto-candidate-v3-family"
    assert automatic_experiment_cancel_target_matches(
        {
            "experiment_family": "auto-candidate-v3-family",
            "candidate_version": "candidate-v3",
        },
        experiment_family="auto-candidate-v3-family",
        candidate_version="candidate-v3",
    )
    assert not automatic_experiment_cancel_target_matches(
        {
            "experiment_family": "auto-candidate-v3-family",
            "candidate_version": "candidate-v2",
        },
        experiment_family="auto-candidate-v3-family",
        candidate_version="candidate-v3",
    )

    heartbeat.details["automatic_experiment"]["subprocess_active"] = False
    available, reason, _payload = automatic_experiment_cancel_availability(
        heartbeat,
        settings,
        now=now,
    )
    assert available is False
    assert reason == "automatic_experiment_subprocess_not_running"


@pytest.mark.asyncio
async def test_cancellable_subprocess_terminates_child_and_returns_claim(tmp_path: Path) -> None:
    claim = ExperimentCancelClaim(
        request_id=uuid4(),
        claim_token="claim-token",
        requested_by="operator",
        requested_at=datetime.now(UTC).isoformat(),
        experiment_family="auto-candidate-v3-family",
        candidate_version="candidate-v3",
    )
    probe_calls = 0

    async def probe() -> ExperimentCancelClaim | None:
        nonlocal probe_calls
        probe_calls += 1
        return claim

    started = time.monotonic()
    with pytest.raises(AutomaticExperimentCancelled) as captured:
        await _run_subprocess(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            tmp_path,
            10,
            cancellation_probe=probe,
            cancellation_poll_seconds=0.01,
            cancellation_grace_seconds=0.25,
        )

    assert time.monotonic() - started < 3
    assert probe_calls >= 1
    assert captured.value.claim == claim
    assert captured.value.process_result["cancelled"] is True
    assert captured.value.process_result["returncode"] is not None




def test_cancel_claim_query_ignores_non_cancel_controls_and_pending_checks_are_supersedable() -> None:
    from sqlalchemy.dialects import postgresql

    statement = pending_automatic_experiment_cancel_statement()
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "CANCEL_EXPERIMENT" in sql
    assert "details" in sql and "action" in sql

    pending_check = SimpleNamespace(
        status="PENDING",
        details={"action": "CHECK_NOW"},
    )
    running_check = SimpleNamespace(
        status="RUNNING",
        details={"action": "CHECK_NOW"},
    )
    pending_cancel = SimpleNamespace(
        status="PENDING",
        details={"action": "CANCEL_EXPERIMENT"},
    )
    assert trainer_control_can_be_superseded_by_cancel(pending_check) is True
    assert trainer_control_can_be_superseded_by_cancel(running_check) is False
    assert trainer_control_can_be_superseded_by_cancel(pending_cancel) is False


def test_control_payload_exposes_cancel_target() -> None:
    now = datetime.now(UTC)
    job = SimpleNamespace(
        id=uuid4(),
        status="PENDING",
        started_at=now,
        finished_at=None,
        details={
            "action": "CANCEL_EXPERIMENT",
            "requested_by": "operator",
            "requested_at": now.isoformat(),
            "experiment_family": "auto-candidate-v3-family",
            "candidate_version": "candidate-v3",
        },
    )

    payload = control_job_payload(job)

    assert payload["experiment_family"] == "auto-candidate-v3-family"
    assert payload["candidate_version"] == "candidate-v3"


def test_operator_ui_exposes_exact_experiment_status_and_cancel_control() -> None:
    root = Path(__file__).resolve().parents[2]
    html = (root / "web" / "index.html").read_text(encoding="utf-8")
    javascript = (root / "web" / "js" / "app.js").read_text(encoding="utf-8")

    assert 'id="trainer-cancel-experiment-button"' in html
    assert "automatic_experiment" in javascript
    assert "CANCEL_EXPERIMENT" in javascript
    assert "experiment_family" in javascript
    assert "candidate_version" in javascript


class _Scalar:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar(self) -> object:
        return self.value


class _Connection:
    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, statement: object, _params: object = None) -> _Scalar:
        sql = str(statement)
        if "pg_try_advisory_lock" in sql or "pg_advisory_unlock" in sql:
            return _Scalar(True)
        raise AssertionError(sql)

    async def commit(self) -> None:
        return None


class _Engine:
    def connect(self) -> _Connection:
        return _Connection()


class _Session:
    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


@pytest.mark.asyncio
async def test_orchestrator_cancellation_closes_candidate_and_publishes_terminal_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import automatic_experiment as automatic_module

    artifact = tmp_path / "candidate.joblib"
    artifact.write_bytes(b"candidate")
    digest = __import__("hashlib").sha256(artifact.read_bytes()).hexdigest()
    candidate = SimpleNamespace(
        version="candidate-v3",
        artifact_path=str(artifact),
        artifact_sha256=digest,
        metrics={"horizon_hours": 8},
    )
    settings = Settings(
        default_horizon_hours=8,
        auto_train_experiment_rr_multipliers=(1.0, 1.25),
        auto_train_experiment_ev_additions=(0.0, 0.05),
        experiment_min_trials=4,
    )
    claim = ExperimentCancelClaim(
        request_id=uuid4(),
        claim_token="claim-token",
        requested_by="operator",
        requested_at=datetime.now(UTC).isoformat(),
        experiment_family="placeholder",
        candidate_version="candidate-v3",
    )
    statuses: list[dict[str, object]] = []
    calls: dict[str, object] = {}

    async def load_registration(_session: object, **_kwargs: object) -> None:
        return None

    async def runner(_command: object, _cwd: object, _timeout: int) -> dict[str, object]:
        raise AutomaticExperimentCancelled(
            claim,
            {
                "cancelled": True,
                "returncode": -15,
                "termination": "process_group_sigterm",
                "process_tree": {
                    "schema": "subprocess-tree-termination-v1",
                    "scope": "process_group",
                    "tree_termination_verified": True,
                },
                "stdout": "",
                "stderr": "",
            },
        )

    async def close_candidate(**kwargs: object) -> dict[str, object]:
        calls["closure"] = kwargs
        return {"status": "CLOSED", "candidate_version": "candidate-v3"}

    async def finish_cancel(
        received_claim: ExperimentCancelClaim,
        **kwargs: object,
    ) -> bool:
        calls["finish"] = {"claim": received_claim, **kwargs}
        return True

    async def status_callback(payload: dict[str, object]) -> None:
        statuses.append(payload)

    monkeypatch.setattr(automatic_module, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(automatic_module, "engine", _Engine())
    monkeypatch.setattr(automatic_module, "SessionFactory", lambda: _Session())
    monkeypatch.setattr(automatic_module, "load_experiment_preregistration", load_registration)
    monkeypatch.setattr(automatic_module, "close_candidate_activation_request", close_candidate)
    monkeypatch.setattr(automatic_module, "finish_automatic_experiment_cancel", finish_cancel)

    result = await automatic_module.orchestrate_automatic_experiment(
        candidate,
        settings=settings,
        actor="trainer-test",
        command_runner=runner,
        status_callback=status_callback,
    )

    assert result["status"] == "CANCELLED"
    assert result["reason"] == "automatic_experiment_cancelled_by_operator"
    assert result["closure"]["status"] == "CLOSED"
    assert calls["closure"]["experiment_gate"]["report_status"] == (
        "AUTOMATIC_EXPERIMENT_OPERATOR_CANCELLED"
    )
    assert calls["finish"]["status"] == "SUCCESS"
    assert calls["finish"]["result"]["process_tree"]["tree_termination_verified"] is True
    assert calls["closure"]["experiment_gate"]["process_tree"][
        "tree_termination_verified"
    ] is True
    assert result["process_tree"]["tree_termination_verified"] is True
    assert any(item["subprocess_active"] is True for item in statuses)
    assert statuses[-1]["status"] == "CANCELLED"
    assert statuses[-1]["subprocess_active"] is False


@pytest.mark.asyncio
async def test_stale_cancel_claim_reaching_normal_loop_never_starts_training(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers import trainer as trainer_module

    trainer = trainer_module.BackgroundTrainer()
    calls: dict[str, object] = {}

    async def unexpected(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("stale cancellation must not run due_reason or training")

    async def finish(
        job_id: object,
        *,
        status: str,
        result: dict[str, object],
        claim_token: str,
    ) -> bool:
        calls["finish"] = (job_id, status, result, claim_token)
        return True

    async def heartbeat() -> None:
        calls["heartbeat"] = True

    monkeypatch.setattr(trainer, "due_reason", unexpected)
    monkeypatch.setattr(trainer, "run_training_once", unexpected)
    monkeypatch.setattr(trainer, "finish_control_request", finish)
    monkeypatch.setattr(trainer, "heartbeat_best_effort", heartbeat)
    job = SimpleNamespace(
        id=uuid4(),
        details={
            "action": "CANCEL_EXPERIMENT",
            "claim_token": "claim-token",
            "experiment_family": "auto-old-family",
            "candidate_version": "candidate-old",
        },
    )

    await trainer.process_control_request(job)

    _job_id, status, result, claim_token = calls["finish"]
    assert status == "FAILED"
    assert result["error"] == "automatic_experiment_subprocess_not_running"
    assert claim_token == "claim-token"
    assert trainer.state["phase"] == "WAITING"
    assert trainer.state["healthy"] is True

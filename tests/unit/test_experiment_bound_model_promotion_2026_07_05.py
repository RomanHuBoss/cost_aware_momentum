from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.ml.data_profile import profile_from_symbol_rows
from app.ml.lifecycle import ModelCandidate, register_and_activate_model_candidate
from app.services.experiment_ledger import experiment_configuration_hash
from app.services.model_promotion import (
    EXPERIMENT_PROMOTION_GATE_SCHEMA,
    evaluate_experiment_promotion_gate,
)

NOW = datetime(2026, 7, 5, 18, tzinfo=UTC)
TRIAL_ID = UUID("11111111-1111-1111-1111-111111111111")


def _passed_cost_stress() -> dict[str, object]:
    return {
        "schema": "hourly-mark-to-market-cost-stress-v1",
        "minimum_terminal_return": 0.0,
        "scenarios": {
            "x1_5": {
                "period_count": 60,
                "terminal_return": 0.08,
                "max_drawdown": -0.04,
            },
            "x2": {
                "period_count": 60,
                "terminal_return": 0.03,
                "max_drawdown": -0.07,
            },
        },
        "passed": True,
    }


class _ScalarResult:
    def __init__(self, value: object = None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value


class _Session:
    def __init__(self, value: object = None) -> None:
        self.value = value
        self.execute_calls = 0

    async def execute(self, _statement: object) -> _ScalarResult:
        self.execute_calls += 1
        return _ScalarResult(self.value)


def _configuration(*, model_sha256: str = "b" * 64) -> dict[str, object]:
    return {
        "model_version": "candidate-v1",
        "model_sha256": model_sha256,
        "horizon": 8,
    }


def _ready_report(*, model_sha256: str = "b" * 64) -> dict[str, object]:
    selected_hash = experiment_configuration_hash(_configuration(model_sha256=model_sha256))
    return {
        "schema": "experiment-selection-preregistered-governance-v4",
        "experiment_family": "family-v1",
        "status": "READY",
        "selected_trial_id": str(TRIAL_ID),
        "selected_configuration_hash": selected_hash,
        "pbo": {"pbo": 0.10},
        "deflated_sharpe": {"probability": 0.98},
        "dependence_aware_inference": {"dependence_supported": True},
        "cost_stress": _passed_cost_stress(),
        "preregistration": {"record_hash": "d" * 64},
        "ledger": {"schema": "append-only-research-experiment-events-v1"},
    }


def _started_event(*, model_sha256: str = "b" * 64) -> SimpleNamespace:
    return SimpleNamespace(
        trial_id=TRIAL_ID,
        experiment_family="family-v1",
        event_sequence=0,
        event_type="STARTED",
        observed_at=NOW,
        configuration_hash=experiment_configuration_hash(
            _configuration(model_sha256=model_sha256)
        ),
        configuration=_configuration(model_sha256=model_sha256),
        evidence={"preregistration_record_hash": "d" * 64},
        previous_event_hash=None,
        record_hash="e" * 64,
    )


@pytest.mark.asyncio
async def test_ready_experiment_gate_binds_selected_trial_to_exact_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import model_promotion

    async def report(*_args: object, **_kwargs: object) -> dict[str, object]:
        return _ready_report()

    monkeypatch.setattr(model_promotion, "experiment_governance_report", report)
    monkeypatch.setattr(model_promotion, "verify_experiment_event_integrity", lambda _row: True)

    gate = await evaluate_experiment_promotion_gate(
        _Session(_started_event()),
        experiment_family="family-v1",
        model_version="candidate-v1",
        model_sha256="b" * 64,
        horizon_hours=8,
    )

    assert gate["schema"] == EXPERIMENT_PROMOTION_GATE_SCHEMA
    assert gate["passed"] is True
    assert gate["reasons"] == []
    assert gate["selected_configuration_hash"] == experiment_configuration_hash(_configuration())
    assert gate["binding"]["model_sha256"] == "b" * 64


@pytest.mark.asyncio
async def test_experiment_gate_rejects_selected_trial_for_different_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import model_promotion

    async def report(*_args: object, **_kwargs: object) -> dict[str, object]:
        return _ready_report(model_sha256="a" * 64)

    monkeypatch.setattr(model_promotion, "experiment_governance_report", report)
    monkeypatch.setattr(model_promotion, "verify_experiment_event_integrity", lambda _row: True)

    gate = await evaluate_experiment_promotion_gate(
        _Session(_started_event(model_sha256="a" * 64)),
        experiment_family="family-v1",
        model_version="candidate-v1",
        model_sha256="b" * 64,
        horizon_hours=8,
    )

    assert gate["passed"] is False
    assert "selected_trial_model_sha256_mismatch" in gate["reasons"]


@pytest.mark.asyncio
async def test_non_ready_family_fails_closed_without_selected_trial_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import model_promotion

    async def report(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "schema": "experiment-selection-preregistered-governance-v4",
            "experiment_family": "family-v1",
            "status": "REJECTED",
        }

    monkeypatch.setattr(model_promotion, "experiment_governance_report", report)
    session = _Session(_started_event())
    gate = await evaluate_experiment_promotion_gate(
        session,
        experiment_family="family-v1",
        model_version="candidate-v1",
        model_sha256="b" * 64,
        horizon_hours=8,
    )

    assert gate["passed"] is False
    assert gate["reasons"] == ["experiment_governance_rejected"]
    assert session.execute_calls == 0


def _candidate(tmp_path: Path) -> ModelCandidate:
    artifact = tmp_path / "candidate.joblib"
    artifact.write_bytes(b"candidate")
    profile = profile_from_symbol_rows(
        [("BTCUSDT", 500, NOW, NOW)],
        unique_timestamps=500,
        minimum_rows_for_coverage=300,
    )
    return ModelCandidate(
        path=artifact,
        version="candidate-v1",
        model_type="logistic",
        horizon=8,
        training_start=NOW,
        training_end=NOW,
        dataset_rows=500,
        unique_timestamps=500,
        symbol_count=1,
        symbol_sample=("BTCUSDT",),
        training_data_profile=profile,
        metrics={"rows": 100},
        incumbent_metrics=None,
        incumbent_version="incumbent-v1",
    )


@pytest.mark.asyncio
async def test_ready_report_without_cost_stress_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import model_promotion

    async def report(*_args: object, **_kwargs: object) -> dict[str, object]:
        value = _ready_report()
        value.pop("cost_stress")
        return value

    monkeypatch.setattr(model_promotion, "experiment_governance_report", report)
    gate = await evaluate_experiment_promotion_gate(
        _Session(_started_event()),
        experiment_family="family-v1",
        model_version="candidate-v1",
        model_sha256="b" * 64,
        horizon_hours=8,
    )

    assert gate["passed"] is False
    assert "invalid_experiment_cost_stress_evidence" in gate["reasons"]


def test_legacy_promotion_gate_schema_cannot_authorize_activation() -> None:
    gate = {
        "schema": "model-promotion-experiment-governance-v2",
        "passed": True,
        "reasons": [],
    }

    from app.services.model_promotion import require_passed_experiment_promotion_gate

    with pytest.raises(RuntimeError, match="invalid schema"):
        require_passed_experiment_promotion_gate(gate)


@pytest.mark.asyncio
async def test_atomic_activation_rejects_missing_experiment_gate_before_artifact_or_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ml import lifecycle

    session_calls = 0

    def session_factory() -> object:
        nonlocal session_calls
        session_calls += 1
        raise AssertionError("database must not be touched")

    monkeypatch.setattr(lifecycle, "SessionFactory", session_factory)
    monkeypatch.setattr(
        lifecycle,
        "_validate_candidate_artifact_for_activation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("artifact must not be read")),
    )

    with pytest.raises(RuntimeError, match="experiment promotion gate"):
        await register_and_activate_model_candidate(
            _candidate(tmp_path),
            source="background_trainer",
            quality_gate={"passed": True, "reasons": []},
            experiment_promotion_gate=None,
            actor="trainer-1",
            expected_previous_version="incumbent-v1",
            expected_horizon_hours=8,
        )

    assert session_calls == 0


@pytest.mark.asyncio
async def test_atomic_activation_rejects_gate_bound_to_different_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ml import lifecycle

    session_calls = 0

    def session_factory() -> object:
        nonlocal session_calls
        session_calls += 1
        raise AssertionError("database must not be touched")

    monkeypatch.setattr(lifecycle, "SessionFactory", session_factory)
    monkeypatch.setattr(
        lifecycle,
        "_validate_candidate_artifact_for_activation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("artifact runtime must not load")),
    )
    mismatched_gate = {
        "schema": EXPERIMENT_PROMOTION_GATE_SCHEMA,
        "passed": True,
        "reasons": [],
        "experiment_family": "family-v1",
        "selected_configuration_hash": "c" * 64,
        "preregistration_record_hash": "d" * 64,
        "binding": {
            "model_version": "candidate-v1",
            "model_sha256": "0" * 64,
            "horizon_hours": 8,
        },
        "cost_stress": _passed_cost_stress(),
    }

    with pytest.raises(RuntimeError, match="artifact SHA-256 mismatch"):
        await register_and_activate_model_candidate(
            _candidate(tmp_path),
            source="background_trainer",
            quality_gate={"passed": True, "reasons": []},
            experiment_promotion_gate=mismatched_gate,
            actor="trainer-1",
            expected_previous_version="incumbent-v1",
            expected_horizon_hours=8,
        )

    assert session_calls == 0


@pytest.mark.asyncio
async def test_registered_activation_requires_matching_ready_experiment_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import model_activation

    target = SimpleNamespace(
        id=uuid4(),
        version="candidate-v1",
        model_type="barrier_logistic",
        artifact_sha256="b" * 64,
        metrics={"quality_gate": {"passed": True, "reasons": []}},
        active=False,
    )
    previous = SimpleNamespace(id=uuid4(), version="incumbent-v1", active=True)

    class _Tx:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_args: object) -> None:
            return None

    class _RegistrySession:
        def __init__(self) -> None:
            self.values = [target, previous, None]

        async def __aenter__(self) -> _RegistrySession:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def begin(self) -> _Tx:
            return _Tx()

        async def execute(self, _statement: object) -> _ScalarResult:
            return _ScalarResult(self.values.pop(0) if self.values else None)

        async def flush(self) -> None:
            return None

    monkeypatch.setattr(model_activation, "SessionFactory", _RegistrySession)
    monkeypatch.setattr(
        model_activation,
        "validate_registry_artifact",
        lambda _target: {"version": "candidate-v1", "horizon_hours": 8},
    )

    with pytest.raises(RuntimeError, match="experiment family"):
        await model_activation.activate_registered_model("candidate-v1")


def test_attrition_report_separates_experiment_promotion_rejection() -> None:
    from app.services.attrition import build_attrition_report_from_records

    report = build_attrition_report_from_records(
        inference_jobs=[],
        training_jobs=[
            {
                "status": "SUCCESS",
                "started_at": NOW,
                "details": {
                    "candidate_version": "candidate-v1",
                    "quality_gate": {"passed": True, "reasons": []},
                    "experiment_promotion_gate": {
                        "schema": EXPERIMENT_PROMOTION_GATE_SCHEMA,
                        "passed": False,
                        "reasons": ["experiment_governance_rejected"],
                        "experiment_family": "family-v1",
                    },
                    "activated": False,
                    "activation_skipped": "experiment_promotion_gate_failed",
                },
            }
        ],
        since=NOW.replace(hour=17),
        until=NOW.replace(hour=19),
    )

    assert report["training"]["terminal_outcome_counts"] == {
        "EXPERIMENT_PROMOTION_GATE_FAILED": 1
    }
    assert report["training"]["experiment_promotion_reason_counts"] == {
        "experiment_governance_rejected": 1
    }

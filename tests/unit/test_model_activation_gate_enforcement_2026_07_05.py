from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ml.data_profile import profile_from_symbol_rows
from app.ml.lifecycle import ModelCandidate, register_and_activate_model_candidate


class _ScalarResult:
    def __init__(self, value: object = None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value


class _Transaction:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> _Transaction:
        self.session.in_transaction = True
        return self

    async def __aexit__(self, exc_type, _exc, _tb) -> None:
        self.session.in_transaction = False
        self.session.committed = exc_type is None
        self.session.rolled_back = exc_type is not None


class _FakeSession:
    def __init__(self, results: list[object | None]) -> None:
        self.results = list(results)
        self.in_transaction = False
        self.committed = False
        self.rolled_back = False
        self.execute_calls = 0
        self.added: list[object] = []

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        return None

    def begin(self) -> _Transaction:
        return _Transaction(self)

    def add(self, value: object) -> None:
        if getattr(value, "id", None) is None:
            value.id = uuid4()
        self.added.append(value)

    async def flush(self) -> None:
        return None

    async def execute(self, _statement: object) -> _ScalarResult:
        self.execute_calls += 1
        value = self.results.pop(0) if self.results else None
        return _ScalarResult(value)


def _candidate(tmp_path: Path) -> ModelCandidate:
    now = datetime.now(UTC)
    artifact = tmp_path / "candidate.joblib"
    artifact.write_bytes(b"candidate")
    profile = profile_from_symbol_rows(
        [("BTCUSDT", 500, now, now)],
        unique_timestamps=500,
        minimum_rows_for_coverage=300,
    )
    return ModelCandidate(
        path=artifact,
        version="candidate-v1",
        model_type="logistic",
        horizon=8,
        training_start=now,
        training_end=now,
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
@pytest.mark.parametrize(
    "quality_gate",
    [
        None,
        {"passed": False, "reasons": ["policy_mean_r_lcb_not_above_minimum"]},
        {"passed": True, "reasons": ["contradictory_reason"]},
    ],
)
async def test_atomic_candidate_activation_rejects_missing_failed_or_inconsistent_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    quality_gate: dict[str, object] | None,
) -> None:
    from app.ml import lifecycle

    session = _FakeSession([SimpleNamespace(id=uuid4(), version="incumbent-v1", active=True)])
    monkeypatch.setattr(lifecycle, "SessionFactory", lambda: session)
    monkeypatch.setattr(
        lifecycle,
        "_validate_candidate_artifact_for_activation",
        lambda *_args, **_kwargs: {"version": "candidate-v1", "horizon_hours": 8},
    )

    async def no_op(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(lifecycle, "append_audit_event", no_op)
    monkeypatch.setattr(lifecycle, "publish_outbox", no_op)

    with pytest.raises(RuntimeError, match="quality gate"):
        await register_and_activate_model_candidate(
            _candidate(tmp_path),
            source="manual_cli",
            quality_gate=quality_gate,
            actor="training-cli",
            expected_previous_version="incumbent-v1",
            expected_horizon_hours=8,
        )

    assert session.execute_calls == 0
    assert session.added == []


@pytest.mark.asyncio
async def test_registered_activation_requires_explicit_reasoned_emergency_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import model_activation

    target = SimpleNamespace(
        id=uuid4(),
        version="failed-v1",
        model_type="barrier_logistic",
        metrics={
            "quality_gate": {
                "passed": False,
                "reasons": ["policy_mean_r_lcb_not_above_minimum"],
            }
        },
        active=False,
    )
    previous = SimpleNamespace(id=uuid4(), version="incumbent-v1", active=True)
    session = _FakeSession([target, previous, None])
    monkeypatch.setattr(model_activation, "SessionFactory", lambda: session)
    monkeypatch.setattr(
        model_activation,
        "validate_registry_artifact",
        lambda _model: {"version": "failed-v1", "horizon_hours": 8},
    )

    async def no_op(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(model_activation, "append_audit_event", no_op)
    monkeypatch.setattr(model_activation, "publish_outbox", no_op)

    with pytest.raises(RuntimeError, match="quality gate"):
        await model_activation.activate_registered_model("failed-v1")

    second_session = _FakeSession([target, previous, None])
    monkeypatch.setattr(model_activation, "SessionFactory", lambda: second_session)
    with pytest.raises(ValueError, match="override reason"):
        await model_activation.activate_registered_model(
            "failed-v1",
            emergency_gate_override=True,
            override_reason="",
        )


@pytest.mark.asyncio
async def test_reasoned_emergency_override_is_explicitly_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import model_activation

    target = SimpleNamespace(
        id=uuid4(),
        version="rollback-v1",
        model_type="barrier_logistic",
        metrics={"quality_gate": None},
        active=False,
    )
    previous = SimpleNamespace(id=uuid4(), version="incumbent-v2", active=True)
    session = _FakeSession([target, previous, None])
    monkeypatch.setattr(model_activation, "SessionFactory", lambda: session)
    monkeypatch.setattr(
        model_activation,
        "validate_registry_artifact",
        lambda _model: {"version": "rollback-v1", "horizon_hours": 8},
    )
    audit_payloads: list[dict[str, object]] = []

    async def audit(*_args: object, payload: dict[str, object], **_kwargs: object) -> None:
        audit_payloads.append(payload)

    async def no_op(*_args: object, **_kwargs: object) -> None:
        return None

    async def durable(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"available": True, "action": "available"}

    monkeypatch.setattr(model_activation, "append_audit_event", audit)
    monkeypatch.setattr(model_activation, "publish_outbox", no_op)
    monkeypatch.setattr(model_activation, "ensure_registry_artifact_durable", durable)

    result = await model_activation.activate_registered_model(
        "rollback-v1",
        emergency_gate_override=True,
        override_reason="Rollback after incumbent artifact integrity incident",
    )

    assert result["activation_governance"]["emergency_gate_override"] is True
    assert result["activation_governance"]["override_reason"] == (
        "Rollback after incumbent artifact integrity incident"
    )
    assert audit_payloads[0]["activation_governance"] == result["activation_governance"]


@pytest.mark.asyncio
async def test_manual_train_activate_registers_failed_candidate_inactive(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from scripts import train

    candidate = _candidate(tmp_path)
    settings = SimpleNamespace(
        horizons_hours=(8,),
        symbols=("BTCUSDT",),
        universe_mode="static",
        auto_train_max_symbols=3,
        model_dir=tmp_path,
        model_entry_spread_bps=18.0,
        max_spread_bps=18.0,
        auto_train_min_bars_per_symbol=300,
        default_horizon_hours=8,
    )
    market_data = SimpleNamespace(
        candles=object(),
        mark_candles=object(),
        index_candles=object(),
        open_interest=object(),
        funding=object(),
        funding_interval_minutes={},
        funding_interval_history=object(),
    )
    failed_gate = {
        "passed": False,
        "reasons": ["policy_mean_r_lcb_not_above_minimum"],
    }
    captured: dict[str, object] = {}

    monkeypatch.setattr(train, "get_settings", lambda: settings)
    monkeypatch.setattr(train, "active_model", lambda: _async_value(None))
    monkeypatch.setattr(train, "load_training_market_data", lambda *_a, **_k: _async_value(market_data))
    monkeypatch.setattr(train, "build_model_candidate", lambda *_a, **_k: candidate)
    monkeypatch.setattr(train, "incumbent_from_registry", lambda _model: None)
    monkeypatch.setattr(train, "policy_evaluation_config", lambda _settings: object())
    monkeypatch.setattr(train, "evaluate_quality_gate", lambda *_a, **_k: failed_gate, raising=False)

    async def unexpected_activation(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("failed candidate must not be activated")

    async def register_inactive(*_args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(id=uuid4())

    async def dispose() -> None:
        return None

    monkeypatch.setattr(train, "register_and_activate_model_candidate", unexpected_activation)
    monkeypatch.setattr(train, "register_model_candidate", register_inactive)
    monkeypatch.setattr(train, "dispose_engine", dispose)

    args = SimpleNamespace(
        horizon=8,
        lookback_days=None,
        model_type="logistic",
        version=None,
        output=None,
        activate=True,
    )
    await train.run(args)

    assert captured["quality_gate"] == failed_gate
    assert captured["activation_requested"] is True


async def _async_value(value: object) -> object:
    return value

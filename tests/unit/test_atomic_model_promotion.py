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
        self.session.transaction_entries += 1
        self.session.in_transaction = True
        return self

    async def __aexit__(self, exc_type, _exc, _tb) -> None:
        self.session.in_transaction = False
        if exc_type is None:
            self.session.committed = True
        else:
            self.session.rolled_back = True


class _FakeSession:
    def __init__(self, previous: object | None) -> None:
        self.previous = previous
        self.in_transaction = False
        self.transaction_entries = 0
        self.committed = False
        self.rolled_back = False
        self.added: list[object] = []
        self.execute_calls = 0

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
        if self.execute_calls == 1:
            return _ScalarResult(self.previous)
        return _ScalarResult()


def _candidate(tmp_path: Path) -> ModelCandidate:
    now = datetime.now(UTC)
    artifact = tmp_path / "candidate-v2.joblib"
    artifact.write_bytes(b"immutable-candidate")
    profile = profile_from_symbol_rows(
        [("BTCUSDT", 500, now, now)],
        unique_timestamps=500,
        minimum_rows_for_coverage=300,
    )
    return ModelCandidate(
        path=artifact,
        version="candidate-v2",
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
async def test_register_and_activate_uses_one_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ml import lifecycle

    previous = SimpleNamespace(id=uuid4(), version="incumbent-v1", active=True)
    session = _FakeSession(previous)
    event_transactions: list[tuple[str, bool]] = []

    monkeypatch.setattr(lifecycle, "SessionFactory", lambda: session)
    monkeypatch.setattr(
        lifecycle,
        "_validate_candidate_artifact_for_activation",
        lambda *_args, **_kwargs: {"version": "candidate-v2", "horizon_hours": 8},
    )

    async def audit(active_session: _FakeSession, *, event_type: str, **_kwargs: object) -> None:
        event_transactions.append((event_type, active_session.in_transaction))

    async def outbox(active_session: _FakeSession, *, event_type: str, **_kwargs: object) -> None:
        event_transactions.append((event_type, active_session.in_transaction))

    monkeypatch.setattr(lifecycle, "append_audit_event", audit)
    monkeypatch.setattr(lifecycle, "publish_outbox", outbox)

    registry, activation = await register_and_activate_model_candidate(
        _candidate(tmp_path),
        source="background_trainer",
        quality_gate={"passed": True, "reasons": []},
        actor="trainer-1",
        expected_previous_version="incumbent-v1",
        expected_horizon_hours=8,
    )

    assert session.transaction_entries == 1
    assert session.committed is True
    assert session.rolled_back is False
    assert registry.active is True
    assert activation["previous_version"] == "incumbent-v1"
    assert event_transactions == [
        ("MODEL_CANDIDATE_TRAINED", True),
        ("MODEL_CANDIDATE_TRAINED", True),
        ("MODEL_ACTIVATED", True),
        ("MODEL_ACTIVATED", True),
    ]


@pytest.mark.asyncio
async def test_activation_audit_failure_rolls_back_candidate_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ml import lifecycle

    previous = SimpleNamespace(id=uuid4(), version="incumbent-v1", active=True)
    session = _FakeSession(previous)

    monkeypatch.setattr(lifecycle, "SessionFactory", lambda: session)
    monkeypatch.setattr(
        lifecycle,
        "_validate_candidate_artifact_for_activation",
        lambda *_args, **_kwargs: {"version": "candidate-v2", "horizon_hours": 8},
    )

    async def audit(_session: _FakeSession, *, event_type: str, **_kwargs: object) -> None:
        if event_type == "MODEL_ACTIVATED":
            raise RuntimeError("simulated activation audit failure")

    async def outbox(_session: _FakeSession, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(lifecycle, "append_audit_event", audit)
    monkeypatch.setattr(lifecycle, "publish_outbox", outbox)

    with pytest.raises(RuntimeError, match="simulated activation audit failure"):
        await register_and_activate_model_candidate(
            _candidate(tmp_path),
            source="background_trainer",
            quality_gate={"passed": True, "reasons": []},
            actor="trainer-1",
            expected_previous_version="incumbent-v1",
            expected_horizon_hours=8,
        )

    assert session.transaction_entries == 1
    assert session.committed is False
    assert session.rolled_back is True


@pytest.mark.asyncio
async def test_atomic_promotion_rejects_changed_active_version_before_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ml import lifecycle

    previous = SimpleNamespace(id=uuid4(), version="concurrent-v3", active=True)
    session = _FakeSession(previous)

    monkeypatch.setattr(lifecycle, "SessionFactory", lambda: session)
    monkeypatch.setattr(
        lifecycle,
        "_validate_candidate_artifact_for_activation",
        lambda *_args, **_kwargs: {"version": "candidate-v2", "horizon_hours": 8},
    )

    with pytest.raises(RuntimeError, match="expected=incumbent-v1, actual=concurrent-v3"):
        await register_and_activate_model_candidate(
            _candidate(tmp_path),
            source="background_trainer",
            quality_gate={"passed": True, "reasons": []},
            actor="trainer-1",
            expected_previous_version="incumbent-v1",
            expected_horizon_hours=8,
        )

    assert session.transaction_entries == 1
    assert session.committed is False
    assert session.rolled_back is True
    assert session.added == []

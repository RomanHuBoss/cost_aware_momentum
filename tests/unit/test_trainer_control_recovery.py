from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.config import Settings
from app.services import trainer_control
from app.workers import trainer as trainer_module


class _ScalarResult:
    def __init__(self, value: object = None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value

    def scalar_one(self) -> object:
        return self.value


class _Transaction:
    async def __aenter__(self) -> _Transaction:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class _FakeSession:
    def __init__(self, results: list[object]) -> None:
        self.results = iter(results)
        self.flush_count = 0
        self.added: list[object] = []

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def begin(self) -> _Transaction:
        return _Transaction()

    async def execute(self, _statement: object, _params: object = None) -> _ScalarResult:
        return _ScalarResult(next(self.results))

    async def flush(self) -> None:
        self.flush_count += 1

    def add(self, value: object) -> None:
        if getattr(value, "id", None) is None:
            value.id = uuid4()
        self.added.append(value)


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        heartbeat_seconds=15,
    )


def _running_request(now: datetime, *, accepted_by: str = "trainer-dead") -> SimpleNamespace:
    accepted_at = now - timedelta(minutes=6)
    return SimpleNamespace(
        id=uuid4(),
        job_name=trainer_control.TRAINER_CONTROL_JOB_NAME,
        status="RUNNING",
        started_at=accepted_at,
        finished_at=None,
        worker_id=accepted_by,
        details={
            "action": "CHECK_NOW",
            "requested_by": "operator",
            "requested_at": (accepted_at - timedelta(seconds=5)).isoformat(),
            "accepted_at": accepted_at.isoformat(),
            "accepted_by": accepted_by,
        },
    )


def test_running_request_is_stale_only_when_owner_heartbeat_is_not_fresh() -> None:
    now = datetime.now(UTC)
    job = _running_request(now)
    fresh_heartbeat = SimpleNamespace(
        status="RUNNING",
        last_seen_at=now - timedelta(seconds=10),
    )
    stale_heartbeat = SimpleNamespace(
        status="RUNNING",
        last_seen_at=now - timedelta(minutes=10),
    )

    assert (
        trainer_control.trainer_control_request_is_stale(
            job,
            stale_heartbeat,
            _settings(),
            now=now,
        )
        is True
    )
    assert (
        trainer_control.trainer_control_request_is_stale(
            job,
            fresh_heartbeat,
            _settings(),
            now=now,
        )
        is False
    )
    job.status = "PENDING"
    assert (
        trainer_control.trainer_control_request_is_stale(
            job,
            stale_heartbeat,
            _settings(),
            now=now,
        )
        is False
    )


@pytest.mark.asyncio
async def test_recovery_fails_abandoned_attempt_and_creates_audited_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    job = _running_request(now)
    stale_heartbeat = SimpleNamespace(
        status="RUNNING",
        last_seen_at=now - timedelta(minutes=10),
    )
    session = _FakeSession([job, stale_heartbeat])
    audit_events: list[tuple[str, str]] = []
    outbox_events: list[tuple[str, str]] = []

    async def audit(
        _session: object,
        *,
        event_type: str,
        entity_id: str,
        **_kwargs: object,
    ) -> None:
        audit_events.append((event_type, entity_id))

    async def outbox(
        _session: object,
        *,
        event_type: str,
        aggregate_id: str,
        **_kwargs: object,
    ) -> None:
        outbox_events.append((event_type, aggregate_id))

    monkeypatch.setattr(trainer_control, "append_audit_event", audit)
    monkeypatch.setattr(trainer_control, "publish_outbox", outbox)
    monkeypatch.setattr(trainer_control, "datetime", SimpleNamespace(now=lambda _tz: now, fromisoformat=datetime.fromisoformat))

    replacement = await trainer_control.recover_stale_trainer_control(
        session,
        _settings(),
        recovered_by="trainer-live",
    )

    assert job.status == "FAILED"
    assert job.finished_at == now
    assert job.details["result"]["error"] == "stale_trainer_control_owner"
    assert replacement is session.added[0]
    assert replacement.status == "PENDING"
    assert replacement.details["retry_of"] == str(job.id)
    assert replacement.details["recovery_count"] == 1
    assert audit_events == [
        ("TRAINER_CONTROL_STALE_RECOVERED", str(job.id)),
        ("TRAINER_CONTROL_REQUEUED", str(replacement.id)),
    ]
    assert outbox_events == audit_events


@pytest.mark.asyncio
async def test_claim_recovers_stale_request_before_claiming_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trainer = trainer_module.BackgroundTrainer()
    pending = SimpleNamespace(
        id=uuid4(),
        status="PENDING",
        worker_id="operator:operator",
        details={"action": "CHECK_NOW"},
    )
    session = _FakeSession([None, pending])
    calls: list[str] = []

    async def recover(_session: object, _settings: Settings, *, recovered_by: str) -> object:
        calls.append(recovered_by)
        return None

    monkeypatch.setattr(trainer_module, "SessionFactory", lambda: session)
    monkeypatch.setattr(
        trainer_module,
        "settings",
        _settings().model_copy(update={"trainer_id": "trainer-live"}),
    )
    monkeypatch.setattr(
        trainer_module,
        "recover_stale_trainer_control",
        recover,
        raising=False,
    )

    claimed = await trainer.claim_control_request()

    assert calls == ["trainer-live"]
    assert claimed is pending
    assert pending.status == "RUNNING"
    assert pending.details["accepted_by"] == "trainer-live"
    assert pending.details["claim_token"]


@pytest.mark.asyncio
async def test_finish_does_not_overwrite_request_already_failed_by_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trainer = trainer_module.BackgroundTrainer()
    job = _running_request(datetime.now(UTC))
    job.status = "FAILED"
    job.finished_at = datetime.now(UTC)
    job.details["claim_token"] = "replacement-token"
    original_details = dict(job.details)
    session = _FakeSession([job])

    monkeypatch.setattr(trainer_module, "SessionFactory", lambda: session)

    finished = await trainer.finish_control_request(
        job.id,
        status="SUCCESS",
        result={"training_started": True},
        claim_token="stale-token",
    )

    assert finished is False
    assert job.status == "FAILED"
    assert job.details == original_details
    assert session.flush_count == 0

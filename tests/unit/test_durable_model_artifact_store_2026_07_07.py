from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest


def test_model_artifact_blob_migration_matches_orm_contract() -> None:
    from app.db.models import ModelArtifactBlob

    table = ModelArtifactBlob.__table__
    assert table.schema == "model"
    assert table.name == "model_artifact_blobs"
    assert table.c.model_registry_id.primary_key is True
    assert table.c.payload.nullable is False
    assert table.c.artifact_sha256.nullable is False
    assert table.c.size_bytes.nullable is False

    project_root = Path(__file__).resolve().parents[2]
    migration = (
        project_root / "migrations/versions/0017_model_artifact_blobs.py"
    ).read_text(encoding="utf-8")
    assert 'revision = "0017_model_artifact_blobs"' in migration
    assert 'down_revision = "0016_universe_replay_asof"' in migration
    assert "CREATE TABLE model.model_artifact_blobs" in migration
    assert "CHECK (size_bytes <= 268435456)" in migration
    assert "CHECK (octet_length(payload) = size_bytes)" in migration
    assert "BEFORE UPDATE OR DELETE" in migration


def test_verified_restore_writes_canonical_copy_without_overwriting_corrupt_file(
    tmp_path: Path,
) -> None:
    from app.ml.artifact_store import restore_artifact_bytes

    corrupt = tmp_path / "legacy" / "active.joblib"
    corrupt.parent.mkdir()
    corrupt.write_bytes(b"corrupt")
    payload = b"immutable-model-artifact"
    digest = hashlib.sha256(payload).hexdigest()

    restored = restore_artifact_bytes(
        payload,
        expected_sha256=digest,
        model_dir=tmp_path / "new-release" / "models",
        version="barrier-logistic-h8-v1",
    )

    assert restored.is_file()
    assert restored.read_bytes() == payload
    assert restored.parent == (tmp_path / "new-release" / "models").resolve()
    assert digest[:12] in restored.name
    assert corrupt.read_bytes() == b"corrupt"
    assert not list(restored.parent.glob("*.tmp"))


def test_verified_restore_rejects_corrupt_database_payload_before_writing(
    tmp_path: Path,
) -> None:
    from app.ml.artifact_store import restore_artifact_bytes

    model_dir = tmp_path / "models"
    with pytest.raises(RuntimeError, match="SHA-256"):
        restore_artifact_bytes(
            b"tampered",
            expected_sha256=hashlib.sha256(b"expected").hexdigest(),
            model_dir=model_dir,
            version="candidate-v1",
        )

    assert not model_dir.exists()


class _ScalarResult:
    def __init__(self, value: object | None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object | None:
        return self.value


class _ArchiveSession:
    def __init__(self, existing: object | None = None) -> None:
        self.existing = existing
        self.added: list[object] = []
        self.execute_calls = 0

    async def execute(self, _statement: object) -> _ScalarResult:
        self.execute_calls += 1
        return _ScalarResult(self.existing)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_candidate_registration_archives_exact_bytes_idempotently() -> None:
    from app.db.models import ModelArtifactBlob
    from app.ml.artifact_store import archive_model_artifact_bytes

    payload = b"candidate-joblib-bytes"
    digest = hashlib.sha256(payload).hexdigest()
    registry = SimpleNamespace(
        id=uuid4(),
        version="candidate-v1",
        artifact_sha256=digest,
    )
    session = _ArchiveSession()

    result = await archive_model_artifact_bytes(
        session,  # type: ignore[arg-type]
        registry,
        payload,
    )

    assert result["created"] is True
    assert result["sha256"] == digest
    assert result["size_bytes"] == len(payload)
    assert len(session.added) == 1
    stored = session.added[0]
    assert isinstance(stored, ModelArtifactBlob)
    assert stored.model_registry_id == registry.id
    assert stored.version == registry.version
    assert stored.artifact_sha256 == digest
    assert stored.size_bytes == len(payload)
    assert stored.payload == payload

    existing = SimpleNamespace(
        model_registry_id=registry.id,
        version=registry.version,
        artifact_sha256=digest,
        size_bytes=len(payload),
        payload=payload,
    )
    second_session = _ArchiveSession(existing)
    second = await archive_model_artifact_bytes(
        second_session,  # type: ignore[arg-type]
        registry,
        payload,
    )
    assert second["created"] is False
    assert second_session.added == []


@pytest.mark.asyncio
async def test_existing_blob_with_different_bytes_fails_closed() -> None:
    from app.ml.artifact_store import archive_model_artifact_bytes

    payload = b"candidate-joblib-bytes"
    digest = hashlib.sha256(payload).hexdigest()
    registry = SimpleNamespace(
        id=uuid4(),
        version="candidate-v1",
        artifact_sha256=digest,
    )
    existing = SimpleNamespace(
        model_registry_id=registry.id,
        version=registry.version,
        artifact_sha256=digest,
        size_bytes=len(payload),
        payload=b"different-joblib-bytes",
    )
    session = _ArchiveSession(existing)

    with pytest.raises(RuntimeError, match="stored model artifact bytes"):
        await archive_model_artifact_bytes(
            session,  # type: ignore[arg-type]
            registry,
            payload,
        )


@pytest.mark.asyncio
async def test_missing_registry_file_is_restored_from_exact_database_blob(
    tmp_path: Path,
) -> None:
    from app.ml.artifact_store import ensure_registry_artifact_durable

    payload = b"active-model-artifact"
    digest = hashlib.sha256(payload).hexdigest()
    registry = SimpleNamespace(
        id=uuid4(),
        version="active-v1",
        model_type="barrier_logistic",
        artifact_path=str(tmp_path / "deleted-release" / "models" / "active-v1.joblib"),
        artifact_sha256=digest,
    )
    blob = SimpleNamespace(
        model_registry_id=registry.id,
        version=registry.version,
        artifact_sha256=digest,
        size_bytes=len(payload),
        payload=payload,
    )
    session = _ArchiveSession(blob)

    result = await ensure_registry_artifact_durable(
        session,  # type: ignore[arg-type]
        registry,
        model_dir=tmp_path / "current-release" / "models",
    )

    restored = Path(registry.artifact_path)
    assert result["action"] == "restored"
    assert result["available"] is True
    assert restored.is_file()
    assert restored.read_bytes() == payload
    assert restored.parent == (tmp_path / "current-release" / "models").resolve()
    assert result["previous_path"].endswith("active-v1.joblib")

class _TransactionSession:
    def __init__(self, result: object | None = None) -> None:
        self.result = result

    async def __aenter__(self) -> _TransactionSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def begin(self) -> _TransactionSession:
        return self

    async def execute(self, _statement: object, *_args: object) -> _ScalarResult:
        return _ScalarResult(self.result)


@pytest.mark.asyncio
async def test_registration_passes_exact_file_bytes_into_registry_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ml import lifecycle

    payload = b"exact-joblib-registration-payload"
    artifact = tmp_path / "candidate.joblib"
    artifact.write_bytes(payload)
    candidate = SimpleNamespace(path=artifact)
    session = _TransactionSession()
    registry = SimpleNamespace(version="candidate-v1")
    captured: dict[str, object] = {}

    async def register_in_session(
        actual_session: object,
        actual_candidate: object,
        **kwargs: object,
    ) -> object:
        captured["session"] = actual_session
        captured["candidate"] = actual_candidate
        captured.update(kwargs)
        return registry

    monkeypatch.setattr(lifecycle, "SessionFactory", lambda: session)
    monkeypatch.setattr(
        lifecycle,
        "_register_model_candidate_in_session",
        register_in_session,
    )

    result = await lifecycle.register_model_candidate(
        candidate,  # type: ignore[arg-type]
        source="background_trainer",
        quality_gate={"passed": False},
        activation_requested=False,
        actor="trainer-test",
    )

    assert result is registry
    assert captured["session"] is session
    assert captured["candidate"] is candidate
    assert captured["artifact_bytes"] == payload
    assert captured["digest"] == hashlib.sha256(payload).hexdigest()


@pytest.mark.asyncio
async def test_worker_repairs_registry_artifact_before_runtime_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers import runner as runner_module

    registry = SimpleNamespace(
        id=uuid4(),
        version="active-v1",
        model_type="barrier_logistic",
        artifact_path="missing.joblib",
        artifact_sha256="a" * 64,
    )
    session = _TransactionSession(registry)
    events: list[str] = []

    async def ensure_durable(
        _session: object,
        actual_registry: object,
        **_kwargs: object,
    ) -> dict[str, object]:
        events.append("durability")
        actual_registry.artifact_path = "restored.joblib"
        return {"available": True, "action": "restored"}

    runtime = SimpleNamespace(metadata=lambda: {"version": "active-v1"})

    def select_runtime(**kwargs: object) -> object:
        events.append("selection")
        assert kwargs["registry"].artifact_path == "restored.joblib"
        return SimpleNamespace(
            runtime=runtime,
            registry_id=str(registry.id),
            notice=None,
        )

    monkeypatch.setattr(runner_module, "SessionFactory", lambda: session)
    monkeypatch.setattr(runner_module, "ensure_registry_artifact_durable", ensure_durable)
    monkeypatch.setattr(runner_module, "select_model_runtime", select_runtime)
    monkeypatch.setattr(
        runner_module,
        "settings",
        runner_module.settings.model_copy(
            update={"active_model_path": None, "allow_baseline_model": True}
        ),
    )

    worker = runner_module.Worker()
    try:
        await worker.refresh_model_runtime(force=True)
    finally:
        await worker.client.close()

    assert events == ["durability", "selection"]
    assert worker.model_artifact_durability == {
        "available": True,
        "action": "restored",
    }

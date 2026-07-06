from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ModelArtifactBlob
from app.services.audit import append_audit_event, publish_outbox

MODEL_ARTIFACT_ARCHIVE_SCHEMA = "postgresql-immutable-model-artifact-v1"
MAX_MODEL_ARTIFACT_BYTES = 256 * 1024 * 1024
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SAFE_VERSION_RE = re.compile(r"[^A-Za-z0-9._-]+")


class RegistryArtifact(Protocol):
    id: UUID | object
    version: str
    model_type: str
    artifact_path: str | None
    artifact_sha256: str | None


def _expected_sha256(value: object) -> str:
    digest = str(value or "").strip().lower()
    if _SHA256_RE.fullmatch(digest) is None:
        raise RuntimeError("Model artifact registry SHA-256 is missing or invalid")
    return digest


def _validated_payload(payload: bytes | bytearray | memoryview, expected_sha256: str) -> bytes:
    data = bytes(payload)
    if not data:
        raise RuntimeError("Model artifact payload is empty")
    if len(data) > MAX_MODEL_ARTIFACT_BYTES:
        raise RuntimeError(
            f"Model artifact exceeds the {MAX_MODEL_ARTIFACT_BYTES}-byte archive limit"
        )
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha256:
        raise RuntimeError(
            "Model artifact payload SHA-256 does not match the immutable registry metadata"
        )
    return data


def _safe_version(value: str, expected_sha256: str) -> str:
    normalized = _SAFE_VERSION_RE.sub("_", str(value).strip()).strip("._-")
    return normalized[:96] or f"model-{expected_sha256[:12]}"


def _file_digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def restore_artifact_bytes(
    payload: bytes | bytearray | memoryview,
    *,
    expected_sha256: str,
    model_dir: Path,
    version: str,
) -> Path:
    """Atomically materialize verified bytes without overwriting forensic evidence."""

    expected = _expected_sha256(expected_sha256)
    data = _validated_payload(payload, expected)
    root = model_dir.expanduser().resolve()
    safe_version = _safe_version(version, expected)
    target = root / f"{safe_version}-{expected[:12]}.joblib"

    if target.is_file():
        if _file_digest(target) == expected:
            return target
        target = root / f"{safe_version}-{expected[:12]}-{uuid4().hex[:8]}.joblib"

    root.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=root,
            prefix=f".{safe_version}-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name != "nt":
            temporary.chmod(0o600)
        if _file_digest(temporary) != expected:
            raise RuntimeError("Restored model artifact failed the post-write SHA-256 check")
        os.replace(temporary, target)
        temporary = None
        if _file_digest(target) != expected:
            raise RuntimeError("Restored model artifact failed the final SHA-256 check")
        return target
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _validate_existing_blob(
    blob: ModelArtifactBlob | object,
    *,
    registry: RegistryArtifact,
    expected_sha256: str,
) -> bytes:
    if str(getattr(blob, "model_registry_id", "")) != str(registry.id):
        raise RuntimeError("Stored model artifact is bound to a different registry row")
    if str(getattr(blob, "version", "")) != registry.version:
        raise RuntimeError("Stored model artifact version does not match the registry")
    if str(getattr(blob, "artifact_sha256", "")).strip().lower() != expected_sha256:
        raise RuntimeError("Stored model artifact SHA-256 does not match the registry")
    payload = _validated_payload(getattr(blob, "payload", b""), expected_sha256)
    if int(getattr(blob, "size_bytes", -1)) != len(payload):
        raise RuntimeError("Stored model artifact size metadata is invalid")
    return payload


async def archive_model_artifact_bytes(
    session: AsyncSession,
    registry: RegistryArtifact,
    payload: bytes | bytearray | memoryview,
    *,
    assume_new: bool = False,
) -> dict[str, object]:
    """Insert exact immutable bytes for a registry row, idempotently and fail-closed."""

    expected = _expected_sha256(registry.artifact_sha256)
    data = _validated_payload(payload, expected)
    existing = None
    if not assume_new:
        existing = (
            await session.execute(
                select(ModelArtifactBlob).where(
                    ModelArtifactBlob.model_registry_id == registry.id
                )
            )
        ).scalar_one_or_none()
    if existing is not None:
        try:
            stored = _validate_existing_blob(
                existing,
                registry=registry,
                expected_sha256=expected,
            )
        except RuntimeError as exc:
            raise RuntimeError("Existing stored model artifact bytes are invalid") from exc
        if stored != data:
            raise RuntimeError("Existing stored model artifact bytes differ from candidate bytes")
        return {
            "schema": MODEL_ARTIFACT_ARCHIVE_SCHEMA,
            "created": False,
            "sha256": expected,
            "size_bytes": len(data),
        }

    session.add(
        ModelArtifactBlob(
            model_registry_id=registry.id,
            version=registry.version,
            artifact_sha256=expected,
            size_bytes=len(data),
            payload=data,
        )
    )
    await session.flush()
    return {
        "schema": MODEL_ARTIFACT_ARCHIVE_SCHEMA,
        "created": True,
        "sha256": expected,
        "size_bytes": len(data),
    }


async def ensure_registry_artifact_durable(
    session: AsyncSession,
    registry: RegistryArtifact,
    *,
    model_dir: Path,
    actor: str | None = None,
) -> dict[str, object]:
    """Archive a valid file or restore an unavailable one from PostgreSQL bytes."""

    if actor:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"model-artifact:{registry.id}"},
        )

    if registry.model_type == "deterministic_baseline":
        return {
            "schema": MODEL_ARTIFACT_ARCHIVE_SCHEMA,
            "available": True,
            "action": "baseline",
        }

    expected = _expected_sha256(registry.artifact_sha256)
    previous_path = registry.artifact_path
    path = Path(previous_path).expanduser() if previous_path else None
    if path is not None and path.is_file() and _file_digest(path) == expected:
        payload = path.read_bytes()
        archive = await archive_model_artifact_bytes(session, registry, payload)
        action = "archived" if archive["created"] is True else "available"
        if archive["created"] is True and actor:
            await append_audit_event(
                session,
                event_type="MODEL_ARTIFACT_ARCHIVED",
                entity_type="model_registry",
                entity_id=str(registry.id),
                actor=actor,
                payload={
                    "version": registry.version,
                    "artifact_path": str(path),
                    "artifact_archive": archive,
                },
            )
            await publish_outbox(
                session,
                event_type="MODEL_ARTIFACT_ARCHIVED",
                aggregate_type="model_registry",
                aggregate_id=str(registry.id),
                payload={"version": registry.version, "sha256": expected},
            )
        return {
            **archive,
            "available": True,
            "action": action,
            "path": str(path),
            "previous_path": previous_path,
        }

    blob = (
        await session.execute(
            select(ModelArtifactBlob).where(
                ModelArtifactBlob.model_registry_id == registry.id
            )
        )
    ).scalar_one_or_none()
    if blob is None:
        return {
            "schema": MODEL_ARTIFACT_ARCHIVE_SCHEMA,
            "available": False,
            "action": "unavailable",
            "reason": "artifact_blob_missing",
            "previous_path": previous_path,
        }

    payload = _validate_existing_blob(
        blob,
        registry=registry,
        expected_sha256=expected,
    )
    restored = restore_artifact_bytes(
        payload,
        expected_sha256=expected,
        model_dir=model_dir,
        version=registry.version,
    )
    registry.artifact_path = str(restored)
    await session.flush()
    result = {
        "schema": MODEL_ARTIFACT_ARCHIVE_SCHEMA,
        "available": True,
        "action": "restored",
        "path": str(restored),
        "previous_path": previous_path,
        "sha256": expected,
        "size_bytes": len(payload),
    }
    if actor:
        await append_audit_event(
            session,
            event_type="MODEL_ARTIFACT_RESTORED",
            entity_type="model_registry",
            entity_id=str(registry.id),
            actor=actor,
            payload={"version": registry.version, **result},
        )
        await publish_outbox(
            session,
            event_type="MODEL_ARTIFACT_RESTORED",
            aggregate_type="model_registry",
            aggregate_id=str(registry.id),
            payload={
                "version": registry.version,
                "artifact_path": str(restored),
                "sha256": expected,
            },
        )
    return result

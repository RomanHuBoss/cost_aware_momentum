from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.ml.runtime import ModelRuntime

CONTROLLED_BASELINE_NOTICE_CODES = frozenset(
    {
        "NO_ACTIVE_MODEL_REGISTERED",
        "REGISTRY_BASELINE_ACTIVE",
        "ACTIVE_MODEL_ARTIFACT_MISSING",
    }
)


class RegistryModel(Protocol):
    id: object
    version: str
    model_type: str
    artifact_path: str | None
    artifact_sha256: str | None
    calibration_version: str | None


@dataclass(frozen=True)
class RuntimeSelection:
    runtime: ModelRuntime
    registry_id: str | None
    notice: dict[str, object] | None


def baseline_fallback_allowed(*, allow_baseline_model: bool, app_mode: str) -> bool:
    return allow_baseline_model and app_mode != "production"


def _baseline_notice(
    *,
    code: str,
    message: str,
    registry: RegistryModel | None,
    artifact_path: str | None = None,
) -> dict[str, object]:
    return {
        "active": True,
        "code": code,
        "message": message,
        "registry_id": str(registry.id) if registry is not None else None,
        "registry_version": registry.version if registry is not None else None,
        "artifact_path": artifact_path,
    }


def recoverable_registry_artifact_notice(
    registry: RegistryModel | None,
    *,
    allow_baseline_model: bool,
    app_mode: str,
) -> dict[str, object] | None:
    if registry is None or registry.model_type == "deterministic_baseline":
        return None
    if not baseline_fallback_allowed(
        allow_baseline_model=allow_baseline_model,
        app_mode=app_mode,
    ):
        return None
    artifact_path = Path(registry.artifact_path) if registry.artifact_path else None
    if artifact_path is not None and artifact_path.is_file():
        return None
    return _baseline_notice(
        code="ACTIVE_MODEL_ARTIFACT_MISSING",
        message="Active model artifact is missing; deterministic baseline is in use",
        registry=registry,
        artifact_path=registry.artifact_path,
    )


def _load_baseline(*, source: str, allow_baseline_model: bool) -> ModelRuntime:
    runtime = ModelRuntime(None, allow_baseline=allow_baseline_model)
    runtime.load(source=source)
    return runtime


def _validate_horizon(runtime: ModelRuntime, expected_horizon_hours: int, *, label: str) -> None:
    if runtime.horizon_hours != expected_horizon_hours:
        raise RuntimeError(
            f"{label} horizon {runtime.horizon_hours} does not match "
            f"DEFAULT_HORIZON_HOURS={expected_horizon_hours}"
        )


def select_model_runtime(
    *,
    registry: RegistryModel | None,
    active_model_path: Path | None,
    allow_baseline_model: bool,
    app_mode: str,
    default_horizon_hours: int,
) -> RuntimeSelection:
    if active_model_path is not None:
        runtime = ModelRuntime(Path(active_model_path), allow_baseline=False)
        runtime.load(source="environment_override")
        _validate_horizon(runtime, default_horizon_hours, label="Model override")
        return RuntimeSelection(runtime=runtime, registry_id=None, notice=None)

    if registry is None:
        runtime = _load_baseline(
            source="bootstrap_baseline",
            allow_baseline_model=baseline_fallback_allowed(
                allow_baseline_model=allow_baseline_model,
                app_mode=app_mode,
            ),
        )
        notice = _baseline_notice(
            code="NO_ACTIVE_MODEL_REGISTERED",
            message="No active model is registered; deterministic baseline is in use",
            registry=None,
        )
        return RuntimeSelection(runtime=runtime, registry_id=None, notice=notice)

    registry_id = str(registry.id)
    if registry.model_type == "deterministic_baseline":
        runtime = _load_baseline(
            source="registry_baseline",
            allow_baseline_model=baseline_fallback_allowed(
                allow_baseline_model=allow_baseline_model,
                app_mode=app_mode,
            ),
        )
        runtime.version = registry.version
        runtime.calibration_version = registry.calibration_version or "uncalibrated-baseline-v1"
        notice = _baseline_notice(
            code="REGISTRY_BASELINE_ACTIVE",
            message="The active registry model is the deterministic baseline",
            registry=registry,
        )
        return RuntimeSelection(runtime=runtime, registry_id=registry_id, notice=notice)

    fallback_notice = recoverable_registry_artifact_notice(
        registry,
        allow_baseline_model=allow_baseline_model,
        app_mode=app_mode,
    )
    artifact_path = Path(registry.artifact_path) if registry.artifact_path else None
    if fallback_notice is not None:
        runtime = _load_baseline(source="registry_artifact_missing_fallback", allow_baseline_model=True)
        return RuntimeSelection(runtime=runtime, registry_id=registry_id, notice=fallback_notice)

    if artifact_path is None or not artifact_path.is_file():
        path_text = registry.artifact_path or "<not configured>"
        raise RuntimeError(f"Active model artifact does not exist: {path_text}")

    runtime = ModelRuntime(artifact_path, allow_baseline=False)
    runtime.load(
        expected_sha256=registry.artifact_sha256,
        expected_version=registry.version,
        source="model_registry",
    )
    _validate_horizon(runtime, default_horizon_hours, label="Active model")
    return RuntimeSelection(runtime=runtime, registry_id=registry_id, notice=None)

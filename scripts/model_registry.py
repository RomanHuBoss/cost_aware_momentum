from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import desc, select, update

from app.asyncio_compat import run_with_compatible_event_loop
from app.config import get_settings
from app.db.engine import SessionFactory, dispose_engine
from app.db.models import ModelRegistry
from app.ml.artifact_recovery import load_recovery_candidate
from app.ml.lifecycle import (
    evaluate_quality_gate,
    register_and_activate_model_candidate,
    register_model_candidate,
)
from app.ml.runtime import ModelRuntime
from app.ml.runtime_selection import (
    baseline_fallback_allowed,
    recoverable_registry_artifact_notice,
)
from app.services.audit import append_audit_event, publish_outbox


def validate_registry_artifact(model: ModelRegistry) -> dict[str, object]:
    settings = get_settings()
    if model.model_type == "deterministic_baseline":
        if not settings.allow_baseline_model:
            raise RuntimeError("Baseline activation is disabled by ALLOW_BASELINE_MODEL=false")
        runtime = ModelRuntime(None, allow_baseline=True)
        runtime.load(source="model_registry_cli")
        runtime.version = model.version
        runtime.calibration_version = model.calibration_version or "uncalibrated-baseline-v1"
        return runtime.metadata()

    if not model.artifact_path:
        raise RuntimeError(f"Model {model.version} has no artifact_path")
    artifact_path = Path(model.artifact_path).expanduser().resolve()
    runtime = ModelRuntime(artifact_path, allow_baseline=False)
    runtime.load(
        expected_sha256=model.artifact_sha256,
        expected_version=model.version,
        source="model_registry_cli",
    )
    if runtime.horizon_hours != settings.default_horizon_hours:
        raise RuntimeError(
            f"Model horizon {runtime.horizon_hours} does not match "
            f"DEFAULT_HORIZON_HOURS={settings.default_horizon_hours}"
        )
    return runtime.metadata()


async def activate_registered_model(
    version: str,
    *,
    actor: str = "operator-cli",
    expected_previous_version: str | None = None,
) -> dict[str, object]:
    async with SessionFactory() as session, session.begin():
        target = (
            await session.execute(
                select(ModelRegistry).where(ModelRegistry.version == version).with_for_update()
            )
        ).scalar_one_or_none()
        if target is None:
            raise SystemExit(f"Model version not found: {version}")

        runtime_metadata = validate_registry_artifact(target)
        previous = (
            await session.execute(
                select(ModelRegistry)
                .where(ModelRegistry.active.is_(True))
                .order_by(desc(ModelRegistry.updated_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        previous_version = previous.version if previous else None
        if expected_previous_version is not None and previous_version != expected_previous_version:
            raise RuntimeError(
                "Active model changed while the candidate was being evaluated: "
                f"expected={expected_previous_version}, actual={previous_version}"
            )
        await session.execute(
            update(ModelRegistry)
            .where(ModelRegistry.active.is_(True), ModelRegistry.id != target.id)
            .values(active=False)
        )
        target.active = True
        await session.flush()
        payload = {
            "version": target.version,
            "model_type": target.model_type,
            "previous_version": previous.version if previous and previous.id != target.id else None,
            "expected_previous_version": expected_previous_version,
            "runtime": runtime_metadata,
        }
        await append_audit_event(
            session,
            event_type="MODEL_ACTIVATED",
            entity_type="model_registry",
            entity_id=str(target.id),
            actor=actor,
            payload=payload,
        )
        await publish_outbox(
            session,
            event_type="MODEL_ACTIVATED",
            aggregate_type="model_registry",
            aggregate_id=str(target.id),
            payload={"version": target.version},
        )
    return payload


async def recover_artifact(artifact: Path) -> dict[str, object]:
    settings = get_settings()
    if not baseline_fallback_allowed(
        allow_baseline_model=settings.allow_baseline_model,
        app_mode=settings.app_mode,
    ):
        raise RuntimeError(
            "Artifact recovery is available only outside production with "
            "ALLOW_BASELINE_MODEL=true"
        )

    resolved = artifact.expanduser().resolve()
    model_dir = settings.model_dir.expanduser().resolve()
    if not resolved.is_relative_to(model_dir):
        raise RuntimeError(f"Recovery artifact must be inside MODEL_DIR={model_dir}")

    candidate = load_recovery_candidate(
        resolved,
        expected_horizon_hours=settings.default_horizon_hours,
    )
    async with SessionFactory() as session:
        active = (
            await session.execute(
                select(ModelRegistry)
                .where(ModelRegistry.active.is_(True))
                .order_by(desc(ModelRegistry.updated_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        existing = (
            await session.execute(
                select(ModelRegistry).where(ModelRegistry.version == candidate.version)
            )
        ).scalar_one_or_none()

    if active is None:
        recovery_notice: dict[str, object] | None = {
            "active": True,
            "code": "NO_ACTIVE_MODEL_REGISTERED",
            "message": "No active model is registered; artifact recovery was requested",
            "registry_id": None,
            "registry_version": None,
            "artifact_path": None,
        }
    elif active.model_type == "deterministic_baseline":
        recovery_notice = {
            "active": True,
            "code": "REGISTRY_BASELINE_ACTIVE",
            "message": "The active registry model is the deterministic baseline",
            "registry_id": str(active.id),
            "registry_version": active.version,
            "artifact_path": None,
        }
    else:
        recovery_notice = recoverable_registry_artifact_notice(
            active,
            allow_baseline_model=settings.allow_baseline_model,
            app_mode=settings.app_mode,
        )
    if recovery_notice is None:
        raise RuntimeError(
            "A valid trained model is already active; orphan recovery cannot replace it. "
            "Use the normal reviewed model-registry activation workflow instead."
        )

    if existing is not None:
        existing_path = Path(existing.artifact_path).expanduser().resolve() if existing.artifact_path else None
        if existing_path != resolved:
            raise RuntimeError(
                f"Registry version {candidate.version} already points to a different artifact"
            )
        quality_gate = (existing.metrics or {}).get("quality_gate")
        gate_passed = bool(isinstance(quality_gate, dict) and quality_gate.get("passed") is True)
        if not gate_passed:
            return {
                "version": existing.version,
                "registry_id": str(existing.id),
                "artifact": str(resolved),
                "registered": True,
                "activated": False,
                "quality_gate": quality_gate,
                "reason": "registered_candidate_did_not_pass_quality_gate",
            }
        activation = await activate_registered_model(
            existing.version,
            actor="operator-artifact-recovery",
            expected_previous_version=active.version if active else None,
        )
        return {
            "version": existing.version,
            "registry_id": str(existing.id),
            "artifact": str(resolved),
            "registered": True,
            "activated": True,
            "quality_gate": quality_gate,
            "activation": activation,
            "reason": "resumed_registered_recovery_candidate",
        }

    quality_gate = evaluate_quality_gate(candidate, settings)
    activation = None
    if quality_gate["passed"]:
        registry, activation = await register_and_activate_model_candidate(
            candidate,
            source="operator_artifact_recovery",
            quality_gate=quality_gate,
            actor="operator-artifact-recovery",
            expected_previous_version=active.version if active else None,
            expected_horizon_hours=settings.default_horizon_hours,
            incumbent_recovery=recovery_notice,
        )
    else:
        registry = await register_model_candidate(
            candidate,
            source="operator_artifact_recovery",
            quality_gate=quality_gate,
            activation_requested=False,
            actor="operator-artifact-recovery",
            incumbent_recovery=recovery_notice,
        )
    return {
        "version": candidate.version,
        "registry_id": str(registry.id),
        "artifact": str(candidate.path),
        "registered": True,
        "activated": activation is not None,
        "quality_gate": quality_gate,
        "activation": activation,
        "reason": (
            "orphan_recovery_activated"
            if activation is not None
            else "orphan_recovery_quality_gate_failed"
        ),
    }


async def list_models() -> list[dict[str, object]]:
    async with SessionFactory() as session:
        models = (
            await session.execute(select(ModelRegistry).order_by(desc(ModelRegistry.updated_at)))
        ).scalars().all()
    return [
        {
            "version": model.version,
            "name": model.name,
            "type": model.model_type,
            "active": model.active,
            "artifact_path": model.artifact_path,
            "artifact_sha256": model.artifact_sha256,
            "feature_schema": model.feature_schema_version,
            "calibration": model.calibration_version,
            "training_start": model.training_start.isoformat() if model.training_start else None,
            "training_end": model.training_end.isoformat() if model.training_end else None,
            "metrics": model.metrics,
            "updated_at": model.updated_at.isoformat(),
        }
        for model in models
    ]


async def async_main(args: argparse.Namespace) -> None:
    try:
        if args.action == "list":
            result: object = await list_models()
        elif args.action == "activate":
            result = await activate_registered_model(args.version)
        else:
            result = await recover_artifact(args.artifact)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List, activate or roll back immutable model artifacts in PostgreSQL."
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("list", help="List registered models and the active version")
    activate = subparsers.add_parser(
        "activate",
        help="Activate a reviewed model version; activating an older version performs rollback",
    )
    activate.add_argument("--version", required=True)
    recover = subparsers.add_parser(
        "recover-artifact",
        help=(
            "Validate, quality-gate and register an orphan artifact while the active "
            "trained artifact is missing"
        ),
    )
    recover.add_argument("--artifact", required=True, type=Path)
    run_with_compatible_event_loop(async_main(parser.parse_args()))


if __name__ == "__main__":
    main()

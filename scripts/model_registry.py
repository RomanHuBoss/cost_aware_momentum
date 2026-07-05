from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from sqlalchemy import desc, select

from app.asyncio_compat import run_with_compatible_event_loop
from app.config import get_settings
from app.db.engine import SessionFactory, dispose_engine
from app.db.models import ModelRegistry
from app.ml.artifact_recovery import load_recovery_candidate
from app.ml.lifecycle import evaluate_quality_gate, register_model_candidate
from app.ml.runtime_selection import (
    baseline_fallback_allowed,
    recoverable_registry_artifact_notice,
)
from app.services.model_activation import activate_registered_model
from app.services.model_promotion import blocked_experiment_promotion_gate


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
            emergency_gate_override=True,
            override_reason=(
                "Non-production orphan artifact recovery after active registry artifact failure"
            ),
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
    candidate_digest = candidate.path.read_bytes()
    experiment_promotion_gate = blocked_experiment_promotion_gate(
        reason="operator_artifact_recovery_requires_emergency_override",
        experiment_family=None,
        model_version=candidate.version,
        model_sha256=hashlib.sha256(candidate_digest).hexdigest(),
        horizon_hours=candidate.horizon,
    )
    registry = await register_model_candidate(
        candidate,
        source="operator_artifact_recovery",
        quality_gate=quality_gate,
        activation_requested=bool(quality_gate["passed"]),
        actor="operator-artifact-recovery",
        incumbent_recovery=recovery_notice,
        experiment_promotion_gate=experiment_promotion_gate,
    )
    activation = None
    if quality_gate["passed"]:
        activation = await activate_registered_model(
            registry.version,
            actor="operator-artifact-recovery",
            expected_previous_version=active.version if active else None,
            emergency_gate_override=True,
            override_reason=(
                "Non-production orphan artifact recovery after active registry artifact failure"
            ),
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
            result = await activate_registered_model(
                args.version,
                experiment_family=args.experiment_family,
                emergency_gate_override=args.emergency_gate_override,
                override_reason=args.override_reason,
            )
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
    activate.add_argument(
        "--experiment-family",
        help=(
            "Preregistered experiment family whose READY selected trial must bind to this "
            "exact model version, SHA-256 and horizon."
        ),
    )
    activate.add_argument(
        "--emergency-gate-override",
        action="store_true",
        help=(
            "Explicitly activate a model without all normal quality/experiment gates. "
            "Reserved for reviewed emergency rollback and requires --override-reason."
        ),
    )
    activate.add_argument(
        "--override-reason",
        help="Mandatory human-readable incident reason for --emergency-gate-override.",
    )
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

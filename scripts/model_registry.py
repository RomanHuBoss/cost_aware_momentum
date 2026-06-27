from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import desc, select, update

from app.asyncio_compat import run_with_compatible_event_loop
from app.config import get_settings
from app.db.engine import SessionFactory, dispose_engine
from app.db.models import ModelRegistry
from app.ml.runtime import ModelRuntime
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


async def activate_registered_model(version: str, *, actor: str = "operator-cli") -> dict[str, object]:
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
        else:
            result = await activate_registered_model(args.version)
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
    run_with_compatible_event_loop(async_main(parser.parse_args()))


if __name__ == "__main__":
    main()

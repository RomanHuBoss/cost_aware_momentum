from __future__ import annotations

from pathlib import Path

from sqlalchemy import desc, select, update

from app.config import get_settings
from app.db.engine import SessionFactory
from app.db.models import ModelRegistry
from app.ml.artifact_store import ensure_registry_artifact_durable
from app.ml.lifecycle import require_passed_quality_gate
from app.ml.runtime import ModelRuntime
from app.services.audit import append_audit_event, publish_outbox
from app.services.model_promotion import (
    evaluate_experiment_promotion_gate,
    experiment_policy_binding_from_settings,
    require_experiment_policy_binding,
    require_passed_experiment_promotion_gate,
)


def validate_registry_artifact(model: ModelRegistry) -> dict[str, object]:
    settings = get_settings()
    if model.model_type == "deterministic_baseline":
        if not settings.allow_baseline_model:
            raise RuntimeError("Baseline activation is disabled by ALLOW_BASELINE_MODEL=false")
        runtime = ModelRuntime(None, allow_baseline=True)
        runtime.load(source="model_activation_service")
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
        source="model_activation_service",
    )
    if runtime.horizon_hours != settings.default_horizon_hours:
        raise RuntimeError(
            f"Model horizon {runtime.horizon_hours} does not match "
            f"DEFAULT_HORIZON_HOURS={settings.default_horizon_hours}"
        )
    return runtime.metadata()


def registered_activation_governance(
    model: ModelRegistry,
    *,
    experiment_promotion_gate: dict[str, object] | None,
    expected_policy_binding: dict[str, object] | None,
    emergency_gate_override: bool,
    override_reason: str | None,
) -> dict[str, object]:
    metrics = model.metrics if isinstance(model.metrics, dict) else {}
    quality_gate = metrics.get("quality_gate")
    quality_validated: dict[str, object] | None = None
    quality_error: RuntimeError | None = None
    experiment_validated: dict[str, object] | None = None
    experiment_error: RuntimeError | None = None
    try:
        quality_validated = require_passed_quality_gate(
            quality_gate if isinstance(quality_gate, dict) else None
        )
    except RuntimeError as exc:
        quality_error = exc
    try:
        metrics_horizon = metrics.get("horizon_hours")
        try:
            expected_horizon = int(metrics_horizon)
        except (TypeError, ValueError):
            expected_horizon = None
        experiment_validated = require_passed_experiment_promotion_gate(
            experiment_promotion_gate,
            expected_model_version=model.version,
            expected_model_sha256=getattr(model, "artifact_sha256", None),
            expected_horizon_hours=expected_horizon,
            expected_policy_binding=expected_policy_binding,
        )
    except RuntimeError as exc:
        experiment_error = exc

    if emergency_gate_override:
        normalized_reason = (override_reason or "").strip()
        if not normalized_reason:
            raise ValueError("Emergency activation override reason is required")
        if quality_error is None and experiment_error is None:
            raise ValueError("Emergency activation override is not allowed when all gates passed")
        return {
            "schema": "model-activation-governance-v2",
            "quality_gate": quality_validated,
            "experiment_promotion_gate": experiment_promotion_gate,
            "quality_gate_passed": quality_error is None,
            "experiment_promotion_gate_passed": experiment_error is None,
            "emergency_gate_override": True,
            "override_reason": normalized_reason,
        }

    if override_reason is not None and override_reason.strip():
        raise ValueError("Override reason was supplied without --emergency-gate-override")
    if quality_error is not None:
        raise RuntimeError(
            f"Registered model {model.version} cannot be activated because its quality gate "
            "is missing, failed, or inconsistent. Use --emergency-gate-override with "
            "--override-reason only for a reviewed emergency rollback."
        ) from quality_error
    if experiment_error is not None:
        raise RuntimeError(
            f"Registered model {model.version} cannot be activated because its experiment "
            "promotion gate is missing, failed, or inconsistent. Provide a matching READY "
            "preregistered experiment family, or use an explicit emergency rollback override."
        ) from experiment_error
    return {
        "schema": "model-activation-governance-v2",
        "quality_gate": quality_validated,
        "experiment_promotion_gate": experiment_validated,
        "quality_gate_passed": True,
        "experiment_promotion_gate_passed": True,
        "emergency_gate_override": False,
        "override_reason": None,
    }


async def activate_registered_model(
    version: str,
    *,
    actor: str = "operator-cli",
    expected_previous_version: str | None = None,
    enforce_expected_previous_version: bool = False,
    experiment_family: str | None = None,
    emergency_gate_override: bool = False,
    override_reason: str | None = None,
) -> dict[str, object]:
    """Activate an already registered immutable artifact under fail-closed governance."""

    async with SessionFactory() as session, session.begin():
        target = (
            await session.execute(
                select(ModelRegistry).where(ModelRegistry.version == version).with_for_update()
            )
        ).scalar_one_or_none()
        if target is None:
            raise RuntimeError(f"Model version not found: {version}")

        metrics = target.metrics if isinstance(target.metrics, dict) else {}
        if not emergency_gate_override:
            quality_gate = metrics.get("quality_gate")
            require_passed_quality_gate(
                quality_gate if isinstance(quality_gate, dict) else None
            )
        persisted_experiment_gate = metrics.get("experiment_promotion_gate")
        stored_family = (
            persisted_experiment_gate.get("experiment_family")
            if isinstance(persisted_experiment_gate, dict)
            else None
        )
        selected_family = (experiment_family or stored_family or "").strip() or None
        experiment_gate: dict[str, object] | None = None
        expected_policy_binding: dict[str, object] | None = None
        if not emergency_gate_override:
            if selected_family is None:
                raise RuntimeError(
                    "Normal model activation requires an experiment family with matching READY "
                    "PBO/DSR/preregistration evidence"
                )
            horizon = metrics.get("horizon_hours")
            if isinstance(horizon, bool):
                horizon = None
            try:
                horizon_hours = int(horizon)
            except (TypeError, ValueError):
                horizon_hours = 0
            expected_policy_binding = require_experiment_policy_binding(
                metrics.get("promotion_policy_binding")
            )
            configured_policy_binding = experiment_policy_binding_from_settings(get_settings())
            if expected_policy_binding != configured_policy_binding:
                raise RuntimeError(
                    "Registered model policy evidence does not match current deployment settings"
                )
            experiment_gate = await evaluate_experiment_promotion_gate(
                session,
                experiment_family=selected_family,
                model_version=target.version,
                model_sha256=target.artifact_sha256 or "",
                horizon_hours=horizon_hours,
                lock_family=True,
                expected_policy_binding=expected_policy_binding,
            )
        else:
            experiment_gate = (
                persisted_experiment_gate
                if isinstance(persisted_experiment_gate, dict)
                else None
            )

        activation_governance = registered_activation_governance(
            target,
            experiment_promotion_gate=experiment_gate,
            expected_policy_binding=expected_policy_binding,
            emergency_gate_override=emergency_gate_override,
            override_reason=override_reason,
        )
        artifact_durability = await ensure_registry_artifact_durable(
            session,
            target,
            model_dir=get_settings().model_dir,
        )
        runtime_metadata = validate_registry_artifact(target)
        if not emergency_gate_override:
            runtime_horizon = runtime_metadata.get("horizon_hours")
            binding = (
                experiment_gate.get("binding")
                if isinstance(experiment_gate, dict)
                else None
            )
            if not isinstance(binding, dict) or binding.get("horizon_hours") != runtime_horizon:
                raise RuntimeError(
                    "Experiment promotion evidence horizon does not match the validated artifact"
                )
        previous = (
            await session.execute(
                select(ModelRegistry)
                .where(ModelRegistry.active.is_(True))
                .order_by(desc(ModelRegistry.updated_at))
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        previous_version = previous.version if previous else None
        if (
            enforce_expected_previous_version
            and previous_version != expected_previous_version
        ) or (
            not enforce_expected_previous_version
            and expected_previous_version is not None
            and previous_version != expected_previous_version
        ):
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
        target.metrics = {
            **metrics,
            "experiment_promotion_gate": experiment_gate,
        }
        await session.flush()
        payload = {
            "version": target.version,
            "model_type": target.model_type,
            "previous_version": previous.version if previous and previous.id != target.id else None,
            "expected_previous_version": expected_previous_version,
            "activation_governance": activation_governance,
            "artifact_durability": artifact_durability,
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

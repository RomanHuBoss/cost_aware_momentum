from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ResearchExperimentEvent
from app.json_utils import json_compatible
from app.services.experiment_ledger import (
    experiment_configuration_hash,
    experiment_governance_report,
    verify_experiment_event_integrity,
)

EXPERIMENT_PROMOTION_GATE_SCHEMA = "model-promotion-experiment-governance-v1"
EXPERIMENT_GOVERNANCE_REPORT_SCHEMA = "experiment-selection-preregistered-governance-v3"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _normalized_reason(status: object) -> str:
    token = re.sub(r"[^a-z0-9]+", "_", str(status or "unknown").lower()).strip("_")
    return f"experiment_governance_{token or 'unknown'}"


def blocked_experiment_promotion_gate(
    *,
    reason: str,
    experiment_family: str | None,
    model_version: str,
    model_sha256: str | None,
    horizon_hours: int | None,
) -> dict[str, Any]:
    normalized_reason = str(reason).strip()
    if not normalized_reason:
        raise ValueError("Experiment promotion gate reason is required")
    return json_compatible(
        {
            "schema": EXPERIMENT_PROMOTION_GATE_SCHEMA,
            "passed": False,
            "reasons": [normalized_reason],
            "experiment_family": (experiment_family or "").strip() or None,
            "report_schema": None,
            "report_status": None,
            "selected_trial_id": None,
            "selected_configuration_hash": None,
            "preregistration_record_hash": None,
            "binding": {
                "model_version": str(model_version),
                "model_sha256": str(model_sha256).lower() if model_sha256 else None,
                "horizon_hours": int(horizon_hours) if horizon_hours is not None else None,
            },
            "pbo": None,
            "deflated_sharpe_probability": None,
            "dependence_supported": None,
        }
    )


async def evaluate_experiment_promotion_gate(
    session: AsyncSession,
    *,
    experiment_family: str,
    model_version: str,
    model_sha256: str,
    horizon_hours: int,
    lock_family: bool = False,
) -> dict[str, Any]:
    family = str(experiment_family).strip()
    version = str(model_version).strip()
    digest = str(model_sha256).lower().strip()
    reasons: list[str] = []
    if not family:
        return blocked_experiment_promotion_gate(
            reason="missing_experiment_family",
            experiment_family=None,
            model_version=version,
            model_sha256=digest or None,
            horizon_hours=horizon_hours,
        )
    if not version:
        reasons.append("missing_model_version")
    if not _SHA256.fullmatch(digest):
        reasons.append("invalid_model_sha256")
    if isinstance(horizon_hours, bool) or int(horizon_hours) <= 0:
        reasons.append("invalid_horizon_hours")
    if reasons:
        gate = blocked_experiment_promotion_gate(
            reason=reasons[0],
            experiment_family=family,
            model_version=version,
            model_sha256=digest or None,
            horizon_hours=horizon_hours,
        )
        gate["reasons"] = reasons
        return gate

    report = await experiment_governance_report(
        session,
        experiment_family=family,
        lock_family=lock_family,
    )
    report_schema = report.get("schema") if isinstance(report, Mapping) else None
    report_status = report.get("status") if isinstance(report, Mapping) else None
    if report_schema != EXPERIMENT_GOVERNANCE_REPORT_SCHEMA:
        reasons.append("invalid_experiment_governance_report_schema")
    if report_status != "READY":
        reasons.append(_normalized_reason(report_status))

    selected_trial_id = report.get("selected_trial_id") if isinstance(report, Mapping) else None
    selected_hash = (
        report.get("selected_configuration_hash") if isinstance(report, Mapping) else None
    )
    preregistration = report.get("preregistration") if isinstance(report, Mapping) else None
    preregistration_hash = (
        preregistration.get("record_hash") if isinstance(preregistration, Mapping) else None
    )
    if reasons:
        return json_compatible(
            {
                **blocked_experiment_promotion_gate(
                    reason=reasons[0],
                    experiment_family=family,
                    model_version=version,
                    model_sha256=digest,
                    horizon_hours=horizon_hours,
                ),
                "reasons": reasons,
                "report_schema": report_schema,
                "report_status": report_status,
                "selected_trial_id": selected_trial_id,
                "selected_configuration_hash": selected_hash,
                "preregistration_record_hash": preregistration_hash,
                "pbo": report.get("pbo") if isinstance(report, Mapping) else None,
                "deflated_sharpe_probability": (
                    report.get("deflated_sharpe", {}).get("probability")
                    if isinstance(report.get("deflated_sharpe"), Mapping)
                    else None
                ),
                "dependence_supported": (
                    report.get("dependence_aware_inference", {}).get("dependence_supported")
                    if isinstance(report.get("dependence_aware_inference"), Mapping)
                    else None
                ),
            }
        )

    try:
        trial_uuid = UUID(str(selected_trial_id))
    except (TypeError, ValueError):
        reasons.append("invalid_selected_trial_id")
        trial_uuid = None
    if not isinstance(selected_hash, str) or not _SHA256.fullmatch(selected_hash):
        reasons.append("invalid_selected_configuration_hash")
    if not isinstance(preregistration_hash, str) or not _SHA256.fullmatch(preregistration_hash):
        reasons.append("invalid_preregistration_record_hash")

    started = None
    if not reasons and trial_uuid is not None:
        started = (
            await session.execute(
                select(ResearchExperimentEvent).where(
                    ResearchExperimentEvent.trial_id == trial_uuid,
                    ResearchExperimentEvent.event_type == "STARTED",
                )
            )
        ).scalar_one_or_none()
        if started is None:
            reasons.append("selected_trial_started_event_missing")
        elif not verify_experiment_event_integrity(started):
            reasons.append("selected_trial_started_event_integrity_failed")

    configuration: Mapping[str, Any] = {}
    if started is not None and not reasons:
        if started.experiment_family != family:
            reasons.append("selected_trial_family_mismatch")
        if started.configuration_hash != selected_hash:
            reasons.append("selected_trial_configuration_hash_mismatch")
        configuration = started.configuration if isinstance(started.configuration, Mapping) else {}
        if experiment_configuration_hash(configuration) != selected_hash:
            reasons.append("selected_trial_configuration_integrity_failed")
        evidence = started.evidence if isinstance(started.evidence, Mapping) else {}
        if evidence.get("preregistration_record_hash") != preregistration_hash:
            reasons.append("selected_trial_preregistration_hash_mismatch")
        if configuration.get("model_version") != version:
            reasons.append("selected_trial_model_version_mismatch")
        if str(configuration.get("model_sha256", "")).lower() != digest:
            reasons.append("selected_trial_model_sha256_mismatch")
        try:
            configured_horizon = int(configuration.get("horizon"))
        except (TypeError, ValueError):
            configured_horizon = None
        if configured_horizon != int(horizon_hours):
            reasons.append("selected_trial_horizon_mismatch")

    pbo = report.get("pbo") if isinstance(report, Mapping) else None
    dsr = report.get("deflated_sharpe") if isinstance(report, Mapping) else None
    dependence = report.get("dependence_aware_inference") if isinstance(report, Mapping) else None
    return json_compatible(
        {
            "schema": EXPERIMENT_PROMOTION_GATE_SCHEMA,
            "passed": not reasons,
            "reasons": reasons,
            "experiment_family": family,
            "report_schema": report_schema,
            "report_status": report_status,
            "selected_trial_id": str(selected_trial_id),
            "selected_configuration_hash": selected_hash,
            "preregistration_record_hash": preregistration_hash,
            "binding": {
                "model_version": version,
                "model_sha256": digest,
                "horizon_hours": int(horizon_hours),
            },
            "pbo": pbo,
            "deflated_sharpe_probability": (
                dsr.get("probability") if isinstance(dsr, Mapping) else None
            ),
            "dependence_supported": (
                dependence.get("dependence_supported")
                if isinstance(dependence, Mapping)
                else None
            ),
        }
    )


def require_passed_experiment_promotion_gate(
    gate: Mapping[str, Any] | None,
    *,
    expected_model_version: str | None = None,
    expected_model_sha256: str | None = None,
    expected_horizon_hours: int | None = None,
) -> dict[str, Any]:
    if not isinstance(gate, Mapping):
        raise RuntimeError("Model activation requires a persisted passed experiment promotion gate")
    reasons = gate.get("reasons")
    if gate.get("schema") != EXPERIMENT_PROMOTION_GATE_SCHEMA:
        raise RuntimeError("Model activation experiment promotion gate has an invalid schema")
    if not isinstance(reasons, list) or any(
        not isinstance(item, str) or not item for item in reasons
    ):
        raise RuntimeError("Model activation experiment promotion gate has invalid reasons evidence")
    if gate.get("passed") is not True or reasons:
        detail = ", ".join(reasons) if reasons else "gate_not_passed"
        raise RuntimeError(f"Model activation experiment promotion gate did not pass: {detail}")
    family = gate.get("experiment_family")
    selected_hash = gate.get("selected_configuration_hash")
    preregistration_hash = gate.get("preregistration_record_hash")
    if not isinstance(family, str) or not family.strip():
        raise RuntimeError("Model activation experiment promotion gate lacks experiment family")
    if not isinstance(selected_hash, str) or not _SHA256.fullmatch(selected_hash):
        raise RuntimeError("Model activation experiment promotion gate lacks selected configuration hash")
    if not isinstance(preregistration_hash, str) or not _SHA256.fullmatch(preregistration_hash):
        raise RuntimeError("Model activation experiment promotion gate lacks preregistration hash")
    binding = gate.get("binding")
    if not isinstance(binding, Mapping):
        raise RuntimeError("Model activation experiment promotion gate lacks artifact binding")
    if expected_model_version is not None and binding.get("model_version") != expected_model_version:
        raise RuntimeError("Model activation experiment promotion gate model version mismatch")
    if expected_model_sha256 is not None:
        normalized_expected_sha = str(expected_model_sha256).lower()
        if not _SHA256.fullmatch(normalized_expected_sha):
            raise RuntimeError("Expected model SHA-256 is invalid")
        if str(binding.get("model_sha256", "")).lower() != normalized_expected_sha:
            raise RuntimeError("Model activation experiment promotion gate artifact SHA-256 mismatch")
    if expected_horizon_hours is not None:
        try:
            bound_horizon = int(binding.get("horizon_hours"))
        except (TypeError, ValueError):
            bound_horizon = None
        if bound_horizon != int(expected_horizon_hours):
            raise RuntimeError("Model activation experiment promotion gate horizon mismatch")
    return json_compatible(dict(gate))

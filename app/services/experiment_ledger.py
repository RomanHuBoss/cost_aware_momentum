from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ResearchExperimentEvent
from app.json_utils import json_compatible
from app.research.overfitting import (
    ExperimentFamilyEvidence,
    ExperimentTrialEvidence,
    analyze_experiment_family,
)
from app.research.preregistration import (
    normalize_preregistration_spec,
    validate_preregistered_trial,
)
from app.services.experiment_preregistration import (
    load_experiment_preregistration,
    preregistration_report_metadata,
    require_trial_preregistration,
)

EXPERIMENT_EVENT_SCHEMA_VERSION = "append-only-research-experiment-events-v1"
_ALLOWED_EVENT_TYPES = frozenset({"STARTED", "SUCCEEDED", "FAILED"})


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _canonical(value: Any) -> str:
    return json.dumps(
        json_compatible(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def experiment_configuration_hash(configuration: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(dict(configuration)).encode("utf-8")).hexdigest()


def build_experiment_event_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(dict(payload)).encode("utf-8")).hexdigest()


def _event_payload(
    *,
    trial_id: UUID | str,
    experiment_family: str,
    event_sequence: int,
    event_type: str,
    observed_at: datetime | str,
    configuration_hash: str,
    configuration: Mapping[str, Any],
    evidence: Mapping[str, Any],
    previous_event_hash: str | None,
) -> dict[str, Any]:
    timestamp = observed_at.isoformat() if isinstance(observed_at, datetime) else str(observed_at)
    return {
        "schema": EXPERIMENT_EVENT_SCHEMA_VERSION,
        "trial_id": str(trial_id),
        "experiment_family": experiment_family,
        "event_sequence": int(event_sequence),
        "event_type": event_type,
        "observed_at": timestamp,
        "configuration_hash": configuration_hash,
        "configuration": json_compatible(dict(configuration)),
        "evidence": json_compatible(dict(evidence)),
        "previous_event_hash": previous_event_hash,
    }


def verify_experiment_event_integrity(row: ResearchExperimentEvent) -> bool:
    payload = _event_payload(
        trial_id=row.trial_id,
        experiment_family=row.experiment_family,
        event_sequence=row.event_sequence,
        event_type=row.event_type,
        observed_at=row.observed_at,
        configuration_hash=row.configuration_hash,
        configuration=row.configuration,
        evidence=row.evidence,
        previous_event_hash=row.previous_event_hash,
    )
    return build_experiment_event_hash(payload) == row.record_hash


async def append_experiment_event(
    session: AsyncSession,
    *,
    trial_id: UUID,
    experiment_family: str,
    event_type: str,
    observed_at: datetime,
    configuration: Mapping[str, Any],
    evidence: Mapping[str, Any] | None = None,
) -> ResearchExperimentEvent:
    if event_type not in _ALLOWED_EVENT_TYPES:
        raise ValueError(f"Unsupported experiment event_type: {event_type}")
    if not experiment_family or len(experiment_family) > 160:
        raise ValueError("experiment_family must contain 1..160 characters")
    observed = _aware(observed_at, "observed_at")
    normalized_configuration = json_compatible(dict(configuration))
    normalized_evidence = json_compatible(dict(evidence or {}))
    configuration_hash = experiment_configuration_hash(normalized_configuration)
    existing = list(
        (
            await session.execute(
                select(ResearchExperimentEvent)
                .where(ResearchExperimentEvent.trial_id == trial_id)
                .order_by(ResearchExperimentEvent.event_sequence)
                .with_for_update()
            )
        ).scalars()
    )
    if not existing:
        if event_type != "STARTED":
            raise ValueError("The first experiment event must be STARTED")
        registration, selected_search = await require_trial_preregistration(
            session,
            experiment_family=experiment_family,
            configuration=normalized_configuration,
            configuration_hash=configuration_hash,
            observed_at=observed,
        )
        normalized_evidence = {
            **normalized_evidence,
            "preregistration_record_hash": registration.record_hash,
            "preregistered_search_values": selected_search,
        }
        sequence = 0
        previous_hash = None
    else:
        latest = existing[-1]
        if latest.event_type != "STARTED" or len(existing) != 1:
            raise ValueError("Experiment trial already has a terminal event")
        if event_type not in {"SUCCEEDED", "FAILED"}:
            raise ValueError("The terminal experiment event must be SUCCEEDED or FAILED")
        if latest.experiment_family != experiment_family:
            raise ValueError("Experiment family cannot change within a trial")
        if latest.configuration_hash != configuration_hash:
            raise ValueError("Experiment configuration cannot change within a trial")
        if not verify_experiment_event_integrity(latest):
            raise ValueError("Previous experiment event hash is invalid")
        registration = await load_experiment_preregistration(
            session,
            experiment_family=experiment_family,
            for_update=True,
        )
        if registration is None:
            raise ValueError("Experiment preregistration is missing for a terminal event")
        if latest.evidence.get("preregistration_record_hash") != registration.record_hash:
            raise ValueError("Experiment preregistration changed or was not recorded at STARTED")
        sequence = 1
        previous_hash = latest.record_hash

    payload = _event_payload(
        trial_id=trial_id,
        experiment_family=experiment_family,
        event_sequence=sequence,
        event_type=event_type,
        observed_at=observed,
        configuration_hash=configuration_hash,
        configuration=normalized_configuration,
        evidence=normalized_evidence,
        previous_event_hash=previous_hash,
    )
    row = ResearchExperimentEvent(
        trial_id=trial_id,
        experiment_family=experiment_family,
        event_sequence=sequence,
        event_type=event_type,
        observed_at=observed,
        configuration_hash=configuration_hash,
        configuration=normalized_configuration,
        evidence=normalized_evidence,
        previous_event_hash=previous_hash,
        record_hash=build_experiment_event_hash(payload),
    )
    session.add(row)
    await session.flush()
    return row


def _trial_evidence_from_success(row: ResearchExperimentEvent) -> ExperimentTrialEvidence:
    period_returns = row.evidence.get("period_returns")
    if not isinstance(period_returns, list) or not period_returns:
        raise ValueError("Successful experiment event lacks period_returns")
    timestamps: list[datetime] = []
    returns: list[float] = []
    for item in period_returns:
        if not isinstance(item, dict) or set(item) != {"timestamp", "return"}:
            raise ValueError("Experiment period_returns schema is invalid")
        timestamp = datetime.fromisoformat(str(item["timestamp"]))
        timestamps.append(_aware(timestamp, "period return timestamp"))
        returns.append(float(item["return"]))
    return ExperimentTrialEvidence(
        trial_id=str(row.trial_id),
        configuration_hash=row.configuration_hash,
        timestamps=tuple(timestamps),
        returns=tuple(returns),
    )


async def load_experiment_family_evidence(
    session: AsyncSession,
    *,
    experiment_family: str,
    preregistration_spec: Mapping[str, Any] | None = None,
    preregistration_record_hash: str | None = None,
) -> tuple[ExperimentFamilyEvidence, dict[str, int]]:
    rows = list(
        (
            await session.execute(
                select(ResearchExperimentEvent)
                .where(ResearchExperimentEvent.experiment_family == experiment_family)
                .order_by(
                    ResearchExperimentEvent.observed_at,
                    ResearchExperimentEvent.trial_id,
                    ResearchExperimentEvent.event_sequence,
                )
            )
        ).scalars()
    )
    grouped: dict[UUID, list[ResearchExperimentEvent]] = defaultdict(list)
    for row in rows:
        if not verify_experiment_event_integrity(row):
            raise ValueError(f"Experiment ledger hash mismatch for event {row.id}")
        grouped[row.trial_id].append(row)

    attempted: list[str] = []
    successes: list[ExperimentTrialEvidence] = []
    open_trials: list[str] = []
    failed_hashes: list[str] = []
    successful_hashes: set[str] = set()
    declared_horizons: list[int] = []
    failed_attempts = 0
    repeated_attempts = 0
    for trial_id, events in grouped.items():
        events.sort(key=lambda item: item.event_sequence)
        if events[0].event_sequence != 0 or events[0].event_type != "STARTED":
            raise ValueError(f"Experiment trial {trial_id} lacks a valid STARTED event")
        if len(events) > 2 or any(item.event_sequence != index for index, item in enumerate(events)):
            raise ValueError(f"Experiment trial {trial_id} has a broken event sequence")
        start = events[0]
        if preregistration_spec is not None:
            validate_preregistered_trial(preregistration_spec, start.configuration)
            if start.evidence.get("preregistration_record_hash") != preregistration_record_hash:
                raise ValueError(
                    f"Experiment trial {trial_id} does not reference the active preregistration"
                )
        attempted.append(start.configuration_hash)
        raw_horizon = start.configuration.get("horizon")
        if raw_horizon is not None:
            try:
                horizon = int(raw_horizon)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Experiment trial {trial_id} has invalid horizon") from exc
            if horizon <= 0:
                raise ValueError(f"Experiment trial {trial_id} has invalid horizon")
            declared_horizons.append(horizon)
        if len(events) == 1:
            open_trials.append(str(trial_id))
            continue
        terminal = events[1]
        if terminal.previous_event_hash != start.record_hash:
            raise ValueError(f"Experiment trial {trial_id} hash chain is broken")
        if terminal.configuration_hash != start.configuration_hash:
            raise ValueError(f"Experiment trial {trial_id} configuration changed")
        if terminal.event_type == "SUCCEEDED":
            successes.append(_trial_evidence_from_success(terminal))
            successful_hashes.add(terminal.configuration_hash)
        elif terminal.event_type == "FAILED":
            failed_attempts += 1
            failed_hashes.append(terminal.configuration_hash)
        else:
            raise ValueError(f"Experiment trial {trial_id} has an invalid terminal event")

    for configuration_hash in set(attempted):
        count = attempted.count(configuration_hash)
        if count > 1:
            repeated_attempts += count - 1
    unresolved_failed = tuple(sorted(set(failed_hashes).difference(successful_hashes)))
    evidence = ExperimentFamilyEvidence(
        experiment_family=experiment_family,
        attempted_configuration_hashes=tuple(attempted),
        successful_trials=tuple(successes),
        failed_configuration_hashes=unresolved_failed,
        open_trial_ids=tuple(open_trials),
        declared_horizons=tuple(declared_horizons),
    )
    counts = {
        "event_count": len(rows),
        "trial_attempt_count": len(grouped),
        "failed_attempt_count": failed_attempts,
        "repeated_attempt_count": repeated_attempts,
    }
    return evidence, counts


async def experiment_governance_report(
    session: AsyncSession,
    *,
    experiment_family: str,
    requested_governance: Mapping[str, Any] | None = None,
    lock_family: bool = False,
) -> dict[str, Any]:
    registration = await load_experiment_preregistration(
        session,
        experiment_family=experiment_family,
        for_update=lock_family,
    )
    if registration is None:
        evidence, counts = await load_experiment_family_evidence(
            session,
            experiment_family=experiment_family,
        )
        return {
            "schema": "experiment-selection-preregistered-governance-v3",
            "experiment_family": experiment_family,
            "status": "BLOCKED_UNREGISTERED_FAMILY",
            "reason": "A formal immutable preregistration is required before the first trial",
            "attempted_trial_count": len(evidence.attempted_configuration_hashes),
            "ledger": {
                "schema": EXPERIMENT_EVENT_SCHEMA_VERSION,
                **counts,
            },
            "automatic_model_action": "none",
            "profitability_claimed": False,
        }

    specification = normalize_preregistration_spec(
        registration.specification,
        expected_family=experiment_family,
    )
    governance = dict(specification["governance"])
    if requested_governance:
        mismatches = {
            key: {"preregistered": governance.get(key), "requested": value}
            for key, value in requested_governance.items()
            if key not in governance or governance[key] != value
        }
        if mismatches:
            return {
                "schema": "experiment-selection-preregistered-governance-v3",
                "experiment_family": experiment_family,
                "status": "BLOCKED_PREREGISTRATION_POLICY_MISMATCH",
                "mismatches": mismatches,
                "preregistration": preregistration_report_metadata(registration),
                "automatic_model_action": "none",
                "profitability_claimed": False,
            }

    evidence, counts = await load_experiment_family_evidence(
        session,
        experiment_family=experiment_family,
        preregistration_spec=specification,
        preregistration_record_hash=registration.record_hash,
    )
    unique_attempts = len(set(evidence.attempted_configuration_hashes))
    maximum = int(specification["stopping_rule"]["max_unique_configurations"])
    if unique_attempts > maximum:
        return {
            "schema": "experiment-selection-preregistered-governance-v3",
            "experiment_family": experiment_family,
            "status": "BLOCKED_PREREGISTRATION_VIOLATION",
            "reason": "Unique attempted configurations exceed the preregistered stopping budget",
            "unique_attempted_configurations": unique_attempts,
            "maximum_unique_configurations": maximum,
            "preregistration": preregistration_report_metadata(registration),
            "ledger": {"schema": EXPERIMENT_EVENT_SCHEMA_VERSION, **counts},
            "automatic_model_action": "none",
            "profitability_claimed": False,
        }

    report = analyze_experiment_family(
        evidence,
        segments=int(governance["pbo_segments"]),
        minimum_trials=int(governance["minimum_trials"]),
        minimum_periods=int(governance["minimum_periods"]),
        maximum_pbo=float(governance["maximum_pbo"]),
        minimum_dsr_probability=float(governance["minimum_dsr_probability"]),
        dependence_block_periods=int(governance["dependence_block_periods"]),
        minimum_independent_blocks=int(governance["minimum_independent_blocks"]),
        bootstrap_replicates=int(governance["bootstrap_replicates"]),
        confidence_level=float(governance["confidence_level"]),
    )
    report["schema"] = "experiment-selection-preregistered-governance-v3"
    report["preregistration"] = preregistration_report_metadata(registration)
    report["preregistration"]["unique_attempted_configurations"] = unique_attempts
    report["ledger"] = {
        "schema": EXPERIMENT_EVENT_SCHEMA_VERSION,
        **counts,
    }
    return report


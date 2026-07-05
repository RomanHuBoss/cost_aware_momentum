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
    failed_attempts = 0
    repeated_attempts = 0
    for trial_id, events in grouped.items():
        events.sort(key=lambda item: item.event_sequence)
        if events[0].event_sequence != 0 or events[0].event_type != "STARTED":
            raise ValueError(f"Experiment trial {trial_id} lacks a valid STARTED event")
        if len(events) > 2 or any(item.event_sequence != index for index, item in enumerate(events)):
            raise ValueError(f"Experiment trial {trial_id} has a broken event sequence")
        start = events[0]
        attempted.append(start.configuration_hash)
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
    segments: int,
    minimum_trials: int,
    minimum_periods: int,
    maximum_pbo: float,
    minimum_dsr_probability: float,
) -> dict[str, Any]:
    evidence, counts = await load_experiment_family_evidence(
        session,
        experiment_family=experiment_family,
    )
    report = analyze_experiment_family(
        evidence,
        segments=segments,
        minimum_trials=minimum_trials,
        minimum_periods=minimum_periods,
        maximum_pbo=maximum_pbo,
        minimum_dsr_probability=minimum_dsr_probability,
    )
    report["ledger"] = {
        "schema": EXPERIMENT_EVENT_SCHEMA_VERSION,
        **counts,
    }
    return report

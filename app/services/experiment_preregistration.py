from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ResearchExperimentEvent, ResearchExperimentFamilyRegistration
from app.research.preregistration import (
    PREREGISTRATION_RECORD_SCHEMA_VERSION,
    build_preregistration_record_hash,
    normalize_preregistration_spec,
    validate_preregistered_trial,
    validate_stopping_rule,
    verify_preregistration_integrity,
)


async def register_experiment_family(
    session: AsyncSession,
    *,
    experiment_family: str,
    registered_at: datetime,
    specification: Mapping[str, Any],
    release_version: str,
) -> ResearchExperimentFamilyRegistration:
    normalized = normalize_preregistration_spec(
        specification,
        expected_family=experiment_family,
    )
    if registered_at.tzinfo is None or registered_at.utcoffset() is None:
        raise ValueError("registered_at must be timezone-aware")
    stop_after = normalized["stopping_rule"]["stop_after_utc"]
    if stop_after is not None and datetime.fromisoformat(stop_after) <= registered_at.astimezone(UTC):
        raise ValueError("stopping_rule.stop_after_utc must be later than registration time")
    existing = await session.get(
        ResearchExperimentFamilyRegistration,
        experiment_family,
        with_for_update=True,
    )
    if existing is not None:
        if not verify_preregistration_integrity(existing):
            raise ValueError("Existing experiment preregistration failed integrity validation")
        candidate_hash = build_preregistration_record_hash(
            experiment_family=experiment_family,
            registered_at=existing.registered_at,
            specification=normalized,
            release_version=existing.release_version,
        )
        if candidate_hash != existing.record_hash:
            raise ValueError("Experiment family is already registered with a different specification")
        return existing

    prior_event = (
        await session.execute(
            select(ResearchExperimentEvent.id)
            .where(ResearchExperimentEvent.experiment_family == experiment_family)
            .limit(1)
        )
    ).scalar_one_or_none()
    if prior_event is not None:
        raise ValueError("Experiment family cannot be preregistered after its first trial event")

    record_hash = build_preregistration_record_hash(
        experiment_family=experiment_family,
        registered_at=registered_at,
        specification=normalized,
        release_version=release_version,
    )
    row = ResearchExperimentFamilyRegistration(
        experiment_family=experiment_family,
        registered_at=registered_at,
        registration_schema=PREREGISTRATION_RECORD_SCHEMA_VERSION,
        specification=normalized,
        release_version=release_version,
        record_hash=record_hash,
    )
    session.add(row)
    await session.flush()
    return row


async def load_experiment_preregistration(
    session: AsyncSession,
    *,
    experiment_family: str,
    for_update: bool = False,
) -> ResearchExperimentFamilyRegistration | None:
    statement = select(ResearchExperimentFamilyRegistration).where(
        ResearchExperimentFamilyRegistration.experiment_family == experiment_family
    )
    if for_update:
        statement = statement.with_for_update()
    row = (await session.execute(statement)).scalar_one_or_none()
    if row is not None:
        if row.registration_schema != PREREGISTRATION_RECORD_SCHEMA_VERSION:
            raise ValueError("Unsupported experiment preregistration record schema")
        if not verify_preregistration_integrity(row):
            raise ValueError("Experiment preregistration hash mismatch")
        normalize_preregistration_spec(row.specification, expected_family=experiment_family)
    return row


async def require_trial_preregistration(
    session: AsyncSession,
    *,
    experiment_family: str,
    configuration: Mapping[str, Any],
    configuration_hash: str,
    observed_at: datetime,
) -> tuple[ResearchExperimentFamilyRegistration, dict[str, Any]]:
    row = await load_experiment_preregistration(
        session,
        experiment_family=experiment_family,
        for_update=True,
    )
    if row is None:
        raise ValueError(
            "Experiment family is not preregistered; create and register a formal specification before STARTED"
        )
    selected = validate_preregistered_trial(row.specification, configuration)
    attempted = tuple(
        (
            await session.execute(
                select(ResearchExperimentEvent.configuration_hash).where(
                    ResearchExperimentEvent.experiment_family == experiment_family,
                    ResearchExperimentEvent.event_type == "STARTED",
                )
            )
        ).scalars()
    )
    validate_stopping_rule(
        row.specification,
        attempted_configuration_hashes=attempted,
        candidate_configuration_hash=configuration_hash,
        observed_at=observed_at,
    )
    return row, selected


def preregistration_report_metadata(row: ResearchExperimentFamilyRegistration) -> dict[str, Any]:
    normalized = normalize_preregistration_spec(
        row.specification,
        expected_family=row.experiment_family,
    )
    return {
        "schema": row.registration_schema,
        "experiment_family": row.experiment_family,
        "registered_at": row.registered_at.isoformat(),
        "release_version": row.release_version,
        "record_hash": row.record_hash,
        "hypothesis": normalized["hypothesis"],
        "primary_metric": normalized["primary_metric"],
        "governance": normalized["governance"],
        "stopping_rule": normalized["stopping_rule"],
        "exclusion_criteria": normalized["exclusion_criteria"],
    }

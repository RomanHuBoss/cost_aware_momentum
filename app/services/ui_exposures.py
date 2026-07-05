from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from app.db.models import SelectionExperimentLedger, SelectionExposureLedger

UI_EXPOSURE_SCHEMA = "recommendation-ui-visible-dwell-v1"
UI_EXPOSURE_SURFACE = "RECOMMENDATION_TILE"
MIN_VIEWPORT_RATIO = Decimal("0.50")
MIN_DWELL_MS = 1000
MAX_DWELL_MS = 600_000
MAX_CLIENT_EVENT_AGE = timedelta(minutes=15)
MAX_FUTURE_CLOCK_SKEW = timedelta(seconds=5)
MAX_PREPLAN_CLOCK_SKEW = timedelta(seconds=5)


def _aware_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _ratio(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("viewport ratio must be numeric") from exc
    if not result.is_finite():
        raise ValueError("viewport ratio must be finite")
    return result


def validate_ui_exposure_evidence(
    *,
    plan_observed_at: datetime,
    exposed_at: datetime,
    received_at: datetime,
    viewport_ratio: Decimal | float | str,
    dwell_ms: int,
    surface: str,
) -> None:
    plan_time = _aware_utc(plan_observed_at, "plan observed_at")
    exposure_time = _aware_utc(exposed_at, "exposed_at")
    receive_time = _aware_utc(received_at, "received_at")
    ratio = _ratio(viewport_ratio)
    if surface != UI_EXPOSURE_SURFACE:
        raise ValueError("surface must be RECOMMENDATION_TILE")
    if ratio < MIN_VIEWPORT_RATIO or ratio > 1:
        raise ValueError("viewport ratio must be between 0.50 and 1")
    if dwell_ms < MIN_DWELL_MS or dwell_ms > MAX_DWELL_MS:
        raise ValueError("dwell time must be between 1000 and 600000 milliseconds")
    if exposure_time < plan_time - MAX_PREPLAN_CLOCK_SKEW:
        raise ValueError("exposure cannot predate plan observation")
    if exposure_time > receive_time + MAX_FUTURE_CLOCK_SKEW:
        raise ValueError("exposure timestamp is in the future")
    if exposure_time < receive_time - MAX_CLIENT_EVENT_AGE:
        raise ValueError("exposure event is too old")


def _exposure_hash_payload(row: SelectionExposureLedger) -> dict[str, Any]:
    return {
        "exposure_schema": row.exposure_schema,
        "plan_id": str(row.plan_id),
        "signal_id": str(row.signal_id),
        "profile_id": str(row.profile_id),
        "plan_version": int(row.plan_version),
        "exposed_at": row.exposed_at.astimezone(UTC).isoformat(),
        "received_at": row.received_at.astimezone(UTC).isoformat(),
        "operator_id": row.operator_id,
        "surface": row.surface,
        "viewport_ratio": format(Decimal(str(row.viewport_ratio)), "f"),
        "dwell_ms": int(row.dwell_ms),
        "client_event_id": str(row.client_event_id),
        "page_instance_id": str(row.page_instance_id),
        "release_version": row.release_version,
    }


def _hash_exposure_row(row: SelectionExposureLedger) -> str:
    encoded = json.dumps(
        _exposure_hash_payload(row),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_selection_exposure_row(
    *,
    ledger: SelectionExperimentLedger,
    operator_id: str,
    exposed_at: datetime,
    received_at: datetime,
    viewport_ratio: Decimal | float | str,
    dwell_ms: int,
    surface: str,
    client_event_id: UUID,
    page_instance_id: UUID,
    release_version: str,
) -> SelectionExposureLedger:
    if not operator_id or len(operator_id) > 80:
        raise ValueError("operator_id must be between 1 and 80 characters")
    if not release_version or len(release_version) > 40:
        raise ValueError("release_version must be between 1 and 40 characters")
    validate_ui_exposure_evidence(
        plan_observed_at=ledger.observed_at,
        exposed_at=exposed_at,
        received_at=received_at,
        viewport_ratio=viewport_ratio,
        dwell_ms=dwell_ms,
        surface=surface,
    )
    row = SelectionExposureLedger(
        id=uuid4(),
        plan_id=ledger.plan_id,
        signal_id=ledger.signal_id,
        profile_id=ledger.profile_id,
        plan_version=ledger.plan_version,
        exposed_at=_aware_utc(exposed_at, "exposed_at"),
        received_at=_aware_utc(received_at, "received_at"),
        operator_id=operator_id,
        surface=surface,
        viewport_ratio=_ratio(viewport_ratio),
        dwell_ms=int(dwell_ms),
        client_event_id=client_event_id,
        page_instance_id=page_instance_id,
        exposure_schema=UI_EXPOSURE_SCHEMA,
        evidence_hash="",
        release_version=release_version,
    )
    row.evidence_hash = _hash_exposure_row(row)
    return row


def verify_selection_exposure_integrity(row: SelectionExposureLedger) -> bool:
    try:
        validate_ui_exposure_evidence(
            plan_observed_at=row.exposed_at,
            exposed_at=row.exposed_at,
            received_at=row.received_at,
            viewport_ratio=row.viewport_ratio,
            dwell_ms=row.dwell_ms,
            surface=row.surface,
        )
        return (
            row.exposure_schema == UI_EXPOSURE_SCHEMA
            and bool(row.evidence_hash)
            and row.evidence_hash == _hash_exposure_row(row)
        )
    except (ArithmeticError, TypeError, ValueError, OverflowError):
        return False


def exposure_insert_values(row: SelectionExposureLedger) -> dict[str, Any]:
    """Return explicit immutable values for PostgreSQL INSERT ... ON CONFLICT."""

    return {
        "id": row.id,
        "plan_id": row.plan_id,
        "signal_id": row.signal_id,
        "profile_id": row.profile_id,
        "plan_version": row.plan_version,
        "exposed_at": row.exposed_at,
        "received_at": row.received_at,
        "operator_id": row.operator_id,
        "surface": row.surface,
        "viewport_ratio": row.viewport_ratio,
        "dwell_ms": row.dwell_ms,
        "client_event_id": row.client_event_id,
        "page_instance_id": row.page_instance_id,
        "exposure_schema": row.exposure_schema,
        "evidence_hash": row.evidence_hash,
        "release_version": row.release_version,
    }

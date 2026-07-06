from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.services import signals
from app.services.drift_monitor import (
    PRODUCTION_DRIFT_PUBLICATION_GUARD_SCHEMA,
    production_drift_publication_guard,
)
from app.workers import runner as runner_module
from app.workers.runner import Worker


class _Result:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value

    def scalars(self) -> _Result:
        return self

    def all(self) -> object:
        return self.value


class _Session:
    def __init__(self, results: list[object]) -> None:
        self.results = iter(results)

    async def execute(self, _query: object) -> _Result:
        return _Result(next(self.results))


@pytest.mark.asyncio
async def test_current_model_critical_drift_latches_publication_quarantine() -> None:
    activated_at = datetime(2026, 7, 6, 10, tzinfo=UTC)
    active_model = SimpleNamespace(
        version="model-v2",
        model_type="logistic",
        updated_at=activated_at,
    )
    reports = [
        SimpleNamespace(
            scheduled_for=activated_at + timedelta(hours=2),
            details={
                "status": "CRITICAL",
                "model_version": "model-v2",
                "generated_at": "2026-07-06T12:00:00+00:00",
                "alerts": ["calibration_drift"],
            },
        ),
        SimpleNamespace(
            scheduled_for=activated_at + timedelta(hours=3),
            details={
                "status": "BLOCKED",
                "model_version": "model-v2",
                "generated_at": "2026-07-06T13:00:00+00:00",
                "alerts": ["insufficient_inference_coverage"],
            },
        ),
    ]

    guard = await production_drift_publication_guard(
        _Session([active_model, reports]),
        model_version="model-v2",
        monitor_enabled=True,
        runtime_is_baseline=False,
    )

    assert guard["schema"] == PRODUCTION_DRIFT_PUBLICATION_GUARD_SCHEMA
    assert guard["blocked"] is True
    assert guard["reason_code"] == "critical_production_drift"
    assert guard["critical_alerts"] == ["calibration_drift"]
    assert guard["release_condition"] == "activate_different_model_version"


@pytest.mark.asyncio
async def test_reactivating_same_artifact_version_does_not_clear_critical_latch() -> None:
    reactivated_at = datetime(2026, 7, 6, 15, tzinfo=UTC)
    active_model = SimpleNamespace(
        version="model-v2",
        model_type="logistic",
        updated_at=reactivated_at,
    )
    reports = [
        SimpleNamespace(
            scheduled_for=reactivated_at - timedelta(hours=3),
            details={
                "status": "CRITICAL",
                "model_version": "model-v2",
                "generated_at": "2026-07-06T12:00:00+00:00",
                "alerts": ["calibration_drift"],
            },
        )
    ]

    guard = await production_drift_publication_guard(
        _Session([active_model, reports]),
        model_version="model-v2",
        monitor_enabled=True,
        runtime_is_baseline=False,
    )

    assert guard["blocked"] is True
    assert guard["reason_code"] == "critical_production_drift"
    assert guard["release_condition"] == "activate_different_model_version"


@pytest.mark.asyncio
async def test_disabling_monitor_does_not_clear_existing_critical_quarantine() -> None:
    activated_at = datetime(2026, 7, 6, 10, tzinfo=UTC)
    active_model = SimpleNamespace(
        version="model-v2",
        model_type="logistic",
        updated_at=activated_at,
    )
    reports = [
        SimpleNamespace(
            scheduled_for=activated_at + timedelta(hours=2),
            details={
                "status": "CRITICAL",
                "model_version": "model-v2",
                "generated_at": "2026-07-06T12:00:00+00:00",
                "alerts": ["calibration_drift"],
            },
        )
    ]

    guard = await production_drift_publication_guard(
        _Session([active_model, reports]),
        model_version="model-v2",
        monitor_enabled=False,
        runtime_is_baseline=False,
    )

    assert guard["blocked"] is True
    assert guard["reason_code"] == "critical_production_drift"


@pytest.mark.asyncio
async def test_previous_model_critical_drift_does_not_quarantine_new_active_model() -> None:
    activated_at = datetime(2026, 7, 6, 10, tzinfo=UTC)
    active_model = SimpleNamespace(
        version="model-v2",
        model_type="logistic",
        updated_at=activated_at,
    )
    reports = [
        SimpleNamespace(
            scheduled_for=activated_at + timedelta(hours=1),
            details={
                "status": "CRITICAL",
                "model_version": "model-v1",
                "alerts": ["feature_distribution_drift"],
            },
        )
    ]

    guard = await production_drift_publication_guard(
        _Session([active_model, reports]),
        model_version="model-v2",
        monitor_enabled=True,
        runtime_is_baseline=False,
    )

    assert guard["blocked"] is False
    assert guard["reason_code"] is None


@pytest.mark.asyncio
async def test_runtime_model_version_mismatch_fails_closed() -> None:
    active_model = SimpleNamespace(
        version="model-v3",
        model_type="logistic",
        updated_at=datetime(2026, 7, 6, 10, tzinfo=UTC),
    )

    guard = await production_drift_publication_guard(
        _Session([active_model]),
        model_version="model-v2",
        monitor_enabled=True,
        runtime_is_baseline=False,
    )

    assert guard["blocked"] is True
    assert guard["reason_code"] == "active_model_version_mismatch"
    assert guard["active_model_version"] == "model-v3"
    assert guard["release_condition"] == "refresh_runtime_to_active_model_version"


@pytest.mark.asyncio
async def test_signal_publication_short_circuits_under_critical_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = {
        "schema": PRODUCTION_DRIFT_PUBLICATION_GUARD_SCHEMA,
        "blocked": True,
        "model_version": "model-v2",
        "reason_code": "critical_production_drift",
        "critical_alerts": ["calibration_drift"],
        "release_condition": "activate_different_model_version",
    }
    monkeypatch.setattr(
        signals,
        "production_drift_publication_guard",
        AsyncMock(return_value=guard),
    )
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=AssertionError("market queries must not run while quarantined"))
    )
    diagnostics: dict[str, object] = {}

    published = await signals.publish_hourly_signals(
        session,
        settings=Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            symbols=["BTCUSDT", "ETHUSDT"],
        ),
        runtime=SimpleNamespace(version="model-v2", is_baseline=False),
        event_time=datetime(2026, 7, 6, 14, tzinfo=UTC),
        diagnostics=diagnostics,
    )

    assert published == []
    assert diagnostics["drift_interlock"] == guard
    assert diagnostics["skip_counts"] == {"critical_production_drift": 2}
    assert diagnostics["skipped_total"] == 2
    assert diagnostics["symbol_outcome_count"] == 2
    assert all(
        row["reason_code"] == "critical_production_drift"
        for row in diagnostics["symbol_outcomes"]
    )


@pytest.mark.asyncio
async def test_hourly_cycle_evaluates_drift_before_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner_module,
        "settings",
        SimpleNamespace(drift_monitor_enabled=True),
    )
    worker = object.__new__(Worker)
    events: list[str] = []

    async def record(name: str, _event_time: datetime) -> dict[str, object]:
        events.append(name)
        return {}

    worker.hourly_market_close_job = lambda event_time: record("market_close", event_time)
    worker.counterfactual_outcome_job = lambda event_time: record("outcomes", event_time)
    worker.drift_monitor_job = lambda event_time: record("drift", event_time)
    worker.inference_job = lambda event_time: record("inference", event_time)
    worker.retention_job = lambda event_time: record("retention", event_time)

    await worker.hourly_decision_cycle(datetime(2026, 7, 6, 14, tzinfo=UTC))

    assert events == ["market_close", "outcomes", "drift", "inference", "retention"]

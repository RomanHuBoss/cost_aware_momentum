from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.db.models import ModelInferenceObservation
from app.ml.drift import DIRECTIONAL_PREDICTION_SCHEMA
from app.services.drift_monitor import build_production_drift_report
from tests.drift_reference import valid_production_drift_reference


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


def _observation(*, now: datetime, value: float, model_version: str = "model-v1") -> SimpleNamespace:
    reference = valid_production_drift_reference()
    features = {name: value for name in reference["feature_names"]}
    probabilities = {"TP": 0.99, "SL": 0.005, "TIMEOUT": 0.005}
    return SimpleNamespace(
        model_version=model_version,
        feature_schema_version="schema-v1",
        observed_at=now,
        feature_snapshot=features,
        directional_predictions={
            "schema": DIRECTIONAL_PREDICTION_SCHEMA,
            "model_version": model_version,
            "calibration_version": "cal-v1",
            "predictions": {"LONG": probabilities, "SHORT": probabilities},
        },
    )


def test_model_inference_observation_has_immutable_point_in_time_contract() -> None:
    table = ModelInferenceObservation.__table__
    assert table.schema == "model"
    assert {column.name for column in table.columns} >= {
        "id",
        "symbol",
        "event_time",
        "observed_at",
        "model_version",
        "calibration_version",
        "feature_schema_version",
        "feature_snapshot",
        "directional_predictions",
    }
    unique_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("model_version", "symbol", "event_time") in unique_sets

    migration = Path("migrations/versions/0018_inference_observations.py").read_text(encoding="utf-8")
    assert "BEFORE UPDATE OR DELETE ON model.model_inference_observations" in migration
    assert "uq_model_inference_observation" in migration


@pytest.mark.asyncio
async def test_drift_uses_all_model_evaluable_observations_not_only_published_signals() -> None:
    now = datetime(2026, 7, 7, 12, tzinfo=UTC)
    reference = valid_production_drift_reference(directional_rows=12, actionability_rate=0.01)
    active_model = SimpleNamespace(
        active=True,
        model_type="logistic",
        version="model-v1",
        feature_schema_version="schema-v1",
        metrics={"production_drift_reference": reference},
        updated_at=now,
    )
    observations = [_observation(now=now - timedelta(minutes=index), value=1000.0) for index in range(6)]
    stable_feature_snapshot = {
        name: float(reference["features"][name]["mean"]) for name in reference["feature_names"]
    }
    stable_feature_snapshot["directional_predictions"] = observations[0].directional_predictions
    published_signal = SimpleNamespace(
        id="signal-1",
        model_version="model-v1",
        event_time=now - timedelta(hours=10),
        publish_time=now - timedelta(hours=9),
        horizon_hours=8,
        feature_snapshot=stable_feature_snapshot,
        p_tp=0.99,
        p_sl=0.005,
        p_timeout=0.005,
    )
    inference_job = SimpleNamespace(
        status="SUCCESS",
        details={
            "symbols_total": 100,
            "symbol_outcome_count": 100,
            "published": 1,
            "existing_current_hour": 0,
        },
    )
    session = _Session([active_model, observations, [published_signal], [inference_job], []])
    settings = SimpleNamespace(
        drift_window_hours=24,
        drift_monitor_enabled=True,
        drift_min_feature_observations=4,
        drift_min_outcome_observations=1,
        drift_min_coverage_rate=0.8,
        drift_max_missing_rate=0.1,
        drift_warning_psi=0.1,
        drift_critical_psi=0.25,
        drift_max_log_loss_delta=10.0,
        drift_max_brier_delta=10.0,
        drift_max_actionability_rate_delta=0.2,
    )

    report = await build_production_drift_report(session, settings, now=now)

    assert report["features"]["observations"] == 6
    assert report["probabilities"]["observations"] == 12
    assert report["status"] == "CRITICAL"
    assert "feature_distribution_drift" in report["critical_evidence"]
    assert "probability_distribution_drift" in report["critical_evidence"]


class _WriteSession:
    def __init__(self, existing: object | None = None) -> None:
        self.existing = existing
        self.added: list[object] = []
        self.flushes = 0

    async def execute(self, _query: object) -> _Result:
        return _Result(self.existing)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flushes += 1


@pytest.mark.asyncio
async def test_persist_model_inference_observation_is_idempotent_and_artifact_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ml.runtime import Prediction
    from app.services.signals import persist_model_inference_observation

    lock_calls: list[tuple[str, str]] = []

    async def acquire(_session: object, namespace: str, value: str) -> None:
        lock_calls.append((namespace, value))

    monkeypatch.setattr("app.services.signals.acquire_advisory_xact_lock", acquire)
    runtime = SimpleNamespace(
        is_baseline=False,
        version="model-v1",
        bundle={"feature_schema_version": "schema-v1"},
    )
    predictions = (
        Prediction("LONG", 0.6, 0.2, 0.2, 0.1, "model-v1", "cal-v1", ()),
        Prediction("SHORT", 0.2, 0.6, 0.2, -0.1, "model-v1", "cal-v1", ()),
    )
    event_time = datetime(2026, 7, 7, 12, tzinfo=UTC)
    observed_at = event_time + timedelta(seconds=10)
    session = _WriteSession()

    observation, created = await persist_model_inference_observation(
        session,
        runtime=runtime,
        symbol="BTCUSDT",
        event_time=event_time,
        observed_at=observed_at,
        model_features={"ret_1h": 0.01},
        directional_predictions=predictions,
    )

    assert created is True
    assert observation is session.added[0]
    assert session.flushes == 1
    assert observation.model_version == "model-v1"
    assert observation.calibration_version == "cal-v1"
    assert observation.feature_schema_version == "schema-v1"
    assert observation.feature_snapshot == {"ret_1h": 0.01}
    assert lock_calls == [
        (
            "model_inference_observation",
            "model-v1|BTCUSDT|2026-07-07T12:00:00+00:00",
        )
    ]

    existing_session = _WriteSession(existing=observation)
    duplicate, duplicate_created = await persist_model_inference_observation(
        existing_session,
        runtime=runtime,
        symbol="BTCUSDT",
        event_time=event_time,
        observed_at=observed_at + timedelta(seconds=5),
        model_features={"ret_1h": 999.0},
        directional_predictions=predictions,
    )
    assert duplicate is observation
    assert duplicate_created is False
    assert existing_session.added == []
    assert existing_session.flushes == 0

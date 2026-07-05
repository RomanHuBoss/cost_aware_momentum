from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.config import Settings
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

    async def execute(self, _query) -> _Result:
        return _Result(next(self.results))


def _signal(*, signal_id: str, event_time: datetime, horizon_hours: int = 4) -> SimpleNamespace:
    reference = valid_production_drift_reference()
    feature_snapshot = {
        name: float(reference["features"][name]["mean"])
        for name in reference["feature_names"]
    }
    feature_snapshot["directional_predictions"] = {
        "schema": DIRECTIONAL_PREDICTION_SCHEMA,
        "model_version": "model-v1",
        "predictions": {
            "LONG": {"TP": 0.60, "SL": 0.20, "TIMEOUT": 0.20},
            "SHORT": {"TP": 0.20, "SL": 0.60, "TIMEOUT": 0.20},
        },
    }
    return SimpleNamespace(
        id=signal_id,
        model_version="model-v1",
        event_time=event_time,
        horizon_hours=horizon_hours,
        feature_snapshot=feature_snapshot,
        net_rr=1.3,
        net_ev_r=0.06,
        p_tp=0.60,
        p_sl=0.20,
        p_timeout=0.20,
    )


def _active_model() -> SimpleNamespace:
    return SimpleNamespace(
        active=True,
        model_type="logistic",
        version="model-v1",
        feature_schema_version="schema-v1",
        metrics={"production_drift_reference": valid_production_drift_reference()},
    )


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        drift_min_feature_observations=1,
        drift_min_outcome_observations=1,
        drift_max_missing_rate=0.99,
    )


@pytest.mark.asyncio
async def test_drift_calibration_excludes_early_outcome_before_full_horizon_maturity() -> None:
    now = datetime(2026, 7, 5, 12, tzinfo=UTC)
    mature = _signal(signal_id="mature", event_time=now - timedelta(hours=6))
    immature = _signal(signal_id="immature", event_time=now - timedelta(hours=1))
    successful_job = SimpleNamespace(
        status="SUCCESS",
        details={"universe_symbols": 2, "published": 2, "existing_current_hour": 0},
    )
    outcomes = [
        SimpleNamespace(signal_id="mature", outcome="TIMEOUT"),
        SimpleNamespace(signal_id="immature", outcome="TP"),
    ]
    session = _Session([_active_model(), [mature, immature], [successful_job], outcomes])

    report = await build_production_drift_report(session, _settings(), now=now)

    assert report["outcome_observations"] == 1
    assert report["outcome_coverage"] == {
        "schema": "full-horizon-mature-signal-outcomes-v1",
        "mature_signals": 1,
        "resolved_mature_signals": 1,
        "unresolved_mature_signals": 0,
        "early_resolved_immature_signals_excluded": 1,
        "invalid_maturity_signals": 0,
        "rate": pytest.approx(1.0),
        "status": "OK",
    }


@pytest.mark.asyncio
async def test_unresolved_mature_signal_blocks_calibration_evidence() -> None:
    now = datetime(2026, 7, 5, 12, tzinfo=UTC)
    first = _signal(signal_id="first", event_time=now - timedelta(hours=8))
    second = _signal(signal_id="second", event_time=now - timedelta(hours=7))
    successful_job = SimpleNamespace(
        status="SUCCESS",
        details={"universe_symbols": 2, "published": 2, "existing_current_hour": 0},
    )
    outcomes = [SimpleNamespace(signal_id="first", outcome="TP")]
    session = _Session([_active_model(), [first, second], [successful_job], outcomes])

    report = await build_production_drift_report(session, _settings(), now=now)

    assert report["status"] == "BLOCKED"
    assert report["calibration"]["status"] == "BLOCKED"
    assert report["outcome_coverage"]["unresolved_mature_signals"] == 1
    assert report["outcome_coverage"]["rate"] == pytest.approx(0.5)
    assert "incomplete_mature_outcome_coverage" in report["alerts"]

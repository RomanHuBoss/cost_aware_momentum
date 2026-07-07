from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.ml.drift import DIRECTIONAL_PREDICTION_SCHEMA, DriftThresholds, evaluate_production_drift
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


def _thresholds() -> DriftThresholds:
    return DriftThresholds(
        minimum_feature_observations=4,
        minimum_outcome_observations=3,
        minimum_coverage_rate=0.80,
        maximum_missing_rate=0.05,
        warning_psi=0.10,
        critical_psi=0.25,
        maximum_log_loss_delta=0.20,
        maximum_brier_delta=0.10,
        maximum_actionability_rate_delta=0.20,
    )


def _feature_rows(*, shifted: bool) -> list[dict[str, float]]:
    base = [
        {"ret_1h": -0.02, "atr_pct_14": 0.010},
        {"ret_1h": -0.01, "atr_pct_14": 0.012},
        {"ret_1h": 0.00, "atr_pct_14": 0.014},
        {"ret_1h": 0.01, "atr_pct_14": 0.016},
        {"ret_1h": 0.02, "atr_pct_14": 0.018},
        {"ret_1h": 0.03, "atr_pct_14": 0.020},
    ]
    if not shifted:
        return base
    return [
        {"ret_1h": row["ret_1h"] + 3.0, "atr_pct_14": row["atr_pct_14"] + 1.0}
        for row in base
    ]


def _probability_rows() -> list[dict[str, float]]:
    return [
        {"TP": 0.70, "SL": 0.20, "TIMEOUT": 0.10},
        {"TP": 0.20, "SL": 0.70, "TIMEOUT": 0.10},
        {"TP": 0.10, "SL": 0.20, "TIMEOUT": 0.70},
        {"TP": 0.65, "SL": 0.25, "TIMEOUT": 0.10},
        {"TP": 0.25, "SL": 0.65, "TIMEOUT": 0.10},
        {"TP": 0.10, "SL": 0.25, "TIMEOUT": 0.65},
    ]


def _small_reference() -> dict[str, object]:
    from app.ml.drift import (
        PRODUCTION_DRIFT_CALIBRATION_COHORT_SCHEMA,
        build_production_drift_reference,
    )

    features = [[row["ret_1h"], row["atr_pct_14"]] for row in _feature_rows(shifted=False)]
    probabilities = [list(row.values()) for row in _probability_rows()]
    outcomes = ["TP", "SL", "TIMEOUT", "TP", "SL", "TIMEOUT"]
    return build_production_drift_reference(
        features,
        probabilities,
        outcomes,
        feature_names=["ret_1h", "atr_pct_14"],
        classes=["TP", "SL", "TIMEOUT"],
        actionability_rate=0.5,
        min_net_rr=1.2,
        min_net_ev_r=0.05,
        calibration_reference={
            "rows": 6,
            "log_loss": 0.3937289300155933,
            "multiclass_brier": 0.1675,
        },
        calibration_cohort_schema=PRODUCTION_DRIFT_CALIBRATION_COHORT_SCHEMA,
    )


def test_confirmed_critical_feature_drift_dominates_incomplete_coverage() -> None:
    report = evaluate_production_drift(
        _small_reference(),
        feature_rows=_feature_rows(shifted=True),
        probability_rows=_probability_rows(),
        outcome_rows=[],
        actionable_flags=[True, False, True, False, True, False],
        expected_opportunities=10,
        published_opportunities=6,
        thresholds=_thresholds(),
    )

    assert report["features"]["max_psi"] > 0.25
    assert report["coverage"]["status"] == "BLOCKED"
    assert "insufficient_inference_coverage" in report["alerts"]
    assert "feature_distribution_drift" in report["alerts"]
    assert report["status"] == "CRITICAL"


def _signal(
    *,
    signal_id: str,
    event_time: datetime,
    row_index: int,
    shifted: bool,
) -> SimpleNamespace:
    reference = valid_production_drift_reference()
    feature_snapshot = {
        name: float(-0.03 + feature_index * 0.001 + row_index * (0.06 / 11.0))
        + (100.0 if shifted else 0.0)
        for feature_index, name in enumerate(reference["feature_names"])
    }
    probability_cycle = (
        {"TP": 0.70, "SL": 0.20, "TIMEOUT": 0.10},
        {"TP": 0.20, "SL": 0.70, "TIMEOUT": 0.10},
        {"TP": 0.10, "SL": 0.20, "TIMEOUT": 0.70},
    )
    probabilities = probability_cycle[row_index % len(probability_cycle)]
    feature_snapshot["directional_predictions"] = {
        "schema": DIRECTIONAL_PREDICTION_SCHEMA,
        "model_version": "model-v1",
        "predictions": {
            "LONG": dict(probabilities),
            "SHORT": dict(probabilities),
        },
    }
    actionable = row_index == 0
    return SimpleNamespace(
        id=signal_id,
        model_version="model-v1",
        event_time=event_time,
        horizon_hours=4,
        feature_snapshot=feature_snapshot,
        net_rr=1.3 if actionable else 1.0,
        net_ev_r=0.06 if actionable else 0.0,
        p_tp=float(probabilities["TP"]),
        p_sl=float(probabilities["SL"]),
        p_timeout=float(probabilities["TIMEOUT"]),
    )


def _service_evidence(*, now: datetime, shifted: bool) -> tuple[list[SimpleNamespace], list[SimpleNamespace]]:
    signals = [
        _signal(
            signal_id=f"signal-{index}",
            event_time=now - timedelta(hours=8 + index),
            row_index=index,
            shifted=shifted,
        )
        for index in range(12)
    ]
    labels = ("TP", "SL", "TIMEOUT")
    outcomes = [
        SimpleNamespace(signal_id=signals[index].id, outcome=labels[index % 3])
        for index in range(11)
    ]
    return signals, outcomes

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
        drift_min_feature_observations=2,
        drift_min_outcome_observations=1,
        drift_max_missing_rate=0.99,
    )


@pytest.mark.asyncio
async def test_incomplete_outcomes_do_not_suppress_independent_critical_feature_drift() -> None:
    now = datetime(2026, 7, 6, 12, tzinfo=UTC)
    signals, outcomes = _service_evidence(now=now, shifted=True)
    successful_job = SimpleNamespace(
        status="SUCCESS",
        details={"universe_symbols": 12, "published": 12, "existing_current_hour": 0},
    )
    session = _Session([_active_model(), signals, [successful_job], outcomes])

    report = await build_production_drift_report(session, _settings(), now=now)

    assert report["features"]["max_psi"] > _settings().drift_critical_psi
    assert report["outcome_coverage"]["unresolved_mature_signals"] == 1
    assert report["calibration"]["status"] == "BLOCKED"
    assert "feature_distribution_drift" in report["alerts"]
    assert "incomplete_mature_outcome_coverage" in report["alerts"]
    assert report["status"] == "CRITICAL"
    assert report["automatic_model_action"] == "quarantine_new_signals_and_plans"


@pytest.mark.asyncio
async def test_incomplete_outcomes_without_independent_critical_evidence_remain_blocked() -> None:
    now = datetime(2026, 7, 6, 12, tzinfo=UTC)
    signals, outcomes = _service_evidence(now=now, shifted=False)
    successful_job = SimpleNamespace(
        status="SUCCESS",
        details={"universe_symbols": 12, "published": 12, "existing_current_hour": 0},
    )
    session = _Session([_active_model(), signals, [successful_job], outcomes])

    report = await build_production_drift_report(session, _settings(), now=now)

    assert report["status"] == "BLOCKED"
    assert report["automatic_model_action"] == "none"
    assert "incomplete_mature_outcome_coverage" in report["alerts"]

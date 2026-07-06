from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pytest

from app.config import Settings
from app.ml.drift import (
    DIRECTIONAL_PREDICTION_SCHEMA,
    PRODUCTION_DRIFT_CALIBRATION_COHORT_SCHEMA,
    PRODUCTION_DRIFT_REFERENCE_SCHEMA,
    DriftThresholds,
    build_production_drift_reference,
    directional_prediction_snapshot,
    evaluate_production_drift,
)
from app.ml.runtime import Prediction
from app.services.drift_monitor import build_production_drift_report
from app.workers.runner import Worker
from tests.drift_reference import valid_production_drift_reference

FEATURES = ["ret_1h", "atr_pct_14"]
CLASSES = ["TP", "SL", "TIMEOUT"]


def _reference() -> dict[str, object]:
    features = np.array(
        [
            [-0.02, 0.010],
            [-0.01, 0.012],
            [0.00, 0.014],
            [0.01, 0.016],
            [0.02, 0.018],
            [0.03, 0.020],
        ],
        dtype=float,
    )
    probabilities = np.array(
        [
            [0.70, 0.20, 0.10],
            [0.20, 0.70, 0.10],
            [0.10, 0.20, 0.70],
            [0.65, 0.25, 0.10],
            [0.25, 0.65, 0.10],
            [0.10, 0.25, 0.65],
        ],
        dtype=float,
    )
    outcomes = np.array(["TP", "SL", "TIMEOUT", "TP", "SL", "TIMEOUT"])
    return build_production_drift_reference(
        features,
        probabilities,
        outcomes,
        feature_names=FEATURES,
        classes=CLASSES,
        actionability_rate=0.5,
        min_net_rr=1.2,
        min_net_ev_r=0.05,
        calibration_cohort_schema=PRODUCTION_DRIFT_CALIBRATION_COHORT_SCHEMA,
    )


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


def _feature_rows() -> list[dict[str, float]]:
    return [
        {"ret_1h": -0.02, "atr_pct_14": 0.010},
        {"ret_1h": -0.01, "atr_pct_14": 0.012},
        {"ret_1h": 0.00, "atr_pct_14": 0.014},
        {"ret_1h": 0.01, "atr_pct_14": 0.016},
        {"ret_1h": 0.02, "atr_pct_14": 0.018},
        {"ret_1h": 0.03, "atr_pct_14": 0.020},
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


def _outcome_rows() -> list[dict[str, object]]:
    labels = ["TP", "SL", "TIMEOUT", "TP", "SL", "TIMEOUT"]
    return [
        {"outcome": label, "probabilities": probabilities}
        for label, probabilities in zip(labels, _probability_rows(), strict=True)
    ]


def test_same_distribution_produces_ok_drift_report() -> None:
    reference = _reference()
    report = evaluate_production_drift(
        reference,
        feature_rows=_feature_rows(),
        probability_rows=_probability_rows(),
        outcome_rows=_outcome_rows(),
        actionable_flags=[True, False, True, False, True, False],
        expected_opportunities=6,
        published_opportunities=6,
        thresholds=_thresholds(),
    )

    assert reference["schema"] == PRODUCTION_DRIFT_REFERENCE_SCHEMA
    assert report["status"] == "OK"
    assert report["coverage"]["rate"] == pytest.approx(1.0)
    assert report["features"]["max_psi"] == pytest.approx(0.0)
    assert report["probabilities"]["max_psi"] == pytest.approx(0.0)
    assert report["calibration"]["log_loss_delta"] == pytest.approx(0.0)
    assert report["actionability"]["absolute_delta"] == pytest.approx(0.0)
    assert report["alerts"] == []


def test_large_feature_and_probability_shift_is_critical() -> None:
    shifted_features = [
        {"ret_1h": row["ret_1h"] + 3.0, "atr_pct_14": row["atr_pct_14"] + 1.0}
        for row in _feature_rows()
    ]
    shifted_probabilities = [{"TP": 0.98, "SL": 0.01, "TIMEOUT": 0.01}] * 6

    report = evaluate_production_drift(
        _reference(),
        feature_rows=shifted_features,
        probability_rows=shifted_probabilities,
        outcome_rows=[],
        actionable_flags=[True, False, True, False, True, False],
        expected_opportunities=6,
        published_opportunities=6,
        thresholds=_thresholds(),
    )

    assert report["status"] == "CRITICAL"
    assert report["features"]["max_psi"] > 0.25
    assert report["probabilities"]["max_psi"] > 0.25
    assert "feature_distribution_drift" in report["alerts"]
    assert "probability_distribution_drift" in report["alerts"]
    assert report["calibration"]["status"] == "INSUFFICIENT_DATA"


def test_low_coverage_and_missing_features_block_monitor() -> None:
    feature_rows = _feature_rows()[:4]
    feature_rows[0] = {"ret_1h": float("nan"), "atr_pct_14": 0.010}

    report = evaluate_production_drift(
        _reference(),
        feature_rows=feature_rows,
        probability_rows=_probability_rows()[:4],
        outcome_rows=_outcome_rows()[:3],
        actionable_flags=[True, False, True, False],
        expected_opportunities=10,
        published_opportunities=4,
        thresholds=_thresholds(),
    )

    assert report["status"] == "CRITICAL"
    assert "feature_missingness_above_limit" in report["critical_evidence"]
    assert "insufficient_inference_coverage" in report["blocking_evidence"]
    assert report["coverage"]["rate"] == pytest.approx(0.4)
    assert report["features"]["by_feature"]["ret_1h"]["missing_rate"] == pytest.approx(0.25)
    assert "insufficient_inference_coverage" in report["alerts"]
    assert "feature_missingness_above_limit" in report["alerts"]


def test_calibration_degradation_is_critical() -> None:
    wrong = [
        {"outcome": "SL", "probabilities": {"TP": 0.98, "SL": 0.01, "TIMEOUT": 0.01}},
        {"outcome": "TP", "probabilities": {"TP": 0.01, "SL": 0.98, "TIMEOUT": 0.01}},
        {"outcome": "TIMEOUT", "probabilities": {"TP": 0.98, "SL": 0.01, "TIMEOUT": 0.01}},
        {"outcome": "SL", "probabilities": {"TP": 0.98, "SL": 0.01, "TIMEOUT": 0.01}},
    ]
    report = evaluate_production_drift(
        _reference(),
        feature_rows=_feature_rows(),
        probability_rows=_probability_rows(),
        outcome_rows=wrong,
        actionable_flags=[True, False, True, False, True, False],
        expected_opportunities=6,
        published_opportunities=6,
        thresholds=_thresholds(),
    )

    assert report["status"] == "CRITICAL"
    assert report["calibration"]["status"] == "CRITICAL"
    assert report["calibration"]["log_loss_delta"] > 0.20
    assert "calibration_drift" in report["alerts"]


def test_directional_prediction_snapshot_is_complete_and_ordered() -> None:
    predictions = (
        Prediction("LONG", 0.6, 0.2, 0.2, 0.1, "m1", "c1", ()),
        Prediction("SHORT", 0.2, 0.6, 0.2, -0.1, "m1", "c1", ()),
    )
    snapshot = directional_prediction_snapshot(predictions)

    assert snapshot["schema"] == DIRECTIONAL_PREDICTION_SCHEMA
    assert list(snapshot["predictions"]) == ["LONG", "SHORT"]
    assert snapshot["predictions"]["LONG"] == {"TP": 0.6, "SL": 0.2, "TIMEOUT": 0.2}
    assert snapshot["predictions"]["SHORT"] == {"TP": 0.2, "SL": 0.6, "TIMEOUT": 0.2}


def test_invalid_drift_threshold_order_is_rejected_by_settings() -> None:
    with pytest.raises(ValueError, match="DRIFT_WARNING_PSI"):
        Settings(
            drift_warning_psi=0.30,
            drift_critical_psi=0.20,
        )


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


@pytest.mark.asyncio
async def test_failed_inference_job_blocks_report_without_automatic_model_action() -> None:
    active_model = SimpleNamespace(
        active=True,
        model_type="logistic",
        version="model-v1",
        feature_schema_version="schema-v1",
        metrics={"production_drift_reference": valid_production_drift_reference()},
    )
    failed_job = SimpleNamespace(status="FAILED", details={})
    session = _Session([active_model, [], [failed_job]])
    report = await build_production_drift_report(
        session,
        Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            drift_min_feature_observations=1,
            drift_min_outcome_observations=1,
        ),
        now=datetime(2026, 7, 5, 12, tzinfo=UTC),
    )

    assert report["status"] == "BLOCKED"
    assert "failed_inference_jobs_in_window" in report["alerts"]
    assert report["failed_inference_jobs"] == 1
    assert report["automatic_model_action"] == "none"


def test_critical_or_blocked_drift_degrades_worker_heartbeat() -> None:
    worker = object.__new__(Worker)
    worker.model_notice = None
    worker.runtime = SimpleNamespace(metadata=lambda: {"version": "model-v1"})
    worker.active_model_registry_id = "registry-v1"
    worker.universe_summary = {"selected_count": 1}

    for status in ("CRITICAL", "BLOCKED"):
        worker.last_drift_summary = {"status": status, "automatic_model_action": "none"}
        assert worker.model_heartbeat_status() == "DEGRADED"
        assert worker.heartbeat_details()["production_drift"]["automatic_model_action"] == "none"

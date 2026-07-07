from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.ml.drift import (
    DIRECTIONAL_PREDICTION_SCHEMA,
    DriftThresholds,
    evaluate_production_drift,
    validate_production_drift_reference,
)
from app.services.drift_monitor import build_production_drift_report
from app.workers.runner import should_retry_incomplete_inference
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
        minimum_feature_observations=1,
        minimum_outcome_observations=1,
        minimum_coverage_rate=0.80,
        maximum_missing_rate=0.10,
        warning_psi=0.10,
        critical_psi=0.25,
        maximum_log_loss_delta=10.0,
        maximum_brier_delta=10.0,
        maximum_actionability_rate_delta=0.20,
    )


def _single_feature_and_probability(reference: dict[str, object]) -> tuple[list[dict[str, float]], list[dict[str, float]]]:
    feature_row = {
        name: float(reference["features"][name]["mean"])
        for name in reference["feature_names"]
    }
    probability_row = {
        label: float(reference["probabilities"][label]["mean"])
        for label in reference["classes"]
    }
    total = sum(probability_row.values())
    probability_row = {key: value / total for key, value in probability_row.items()}
    return [feature_row], [probability_row]


def test_reference_binds_actionability_to_published_policy_trade_density() -> None:
    reference = valid_production_drift_reference()
    assert (
        reference["actionability"]["cohort_schema"]
        == "published-policy-trades-per-symbol-opportunity-v1"
    )


def test_reference_rejects_unknown_actionability_cohort_semantics() -> None:
    reference = deepcopy(valid_production_drift_reference())
    reference["actionability"]["cohort_schema"] = "pre-overlap-actionable-candidates-v0"
    with pytest.raises(ValueError, match="actionability cohort"):
        validate_production_drift_reference(reference)


def test_completed_sparse_inference_is_not_retried() -> None:
    assert not should_retry_incomplete_inference(
        {
            "symbols_total": 141,
            "published": 1,
            "existing_current_hour": 0,
            "symbol_outcome_count": 141,
            "inference_retry_count": 0,
        },
        max_retries=5,
    )


def test_incomplete_terminal_coverage_remains_retryable() -> None:
    assert should_retry_incomplete_inference(
        {
            "symbols_total": 141,
            "published": 1,
            "existing_current_hour": 0,
            "symbol_outcome_count": 140,
            "inference_retry_count": 0,
        },
        max_retries=5,
    )


def test_drift_coverage_uses_processed_symbols_not_recommendation_count() -> None:
    reference = valid_production_drift_reference()
    reference = deepcopy(reference)
    reference["actionability"]["rate"] = 0.05
    feature_rows, probability_rows = _single_feature_and_probability(reference)

    report = evaluate_production_drift(
        reference,
        feature_rows=feature_rows,
        probability_rows=probability_rows,
        outcome_rows=[],
        actionable_flags=None,
        expected_opportunities=100,
        processed_opportunities=100,
        actionable_opportunities=5,
        thresholds=_thresholds(),
    )

    assert report["coverage"]["status"] == "OK"
    assert report["coverage"]["rate"] == pytest.approx(1.0)
    assert report["actionability"]["rate"] == pytest.approx(0.05)
    assert report["actionability"]["status"] == "OK"
    assert "insufficient_inference_coverage" not in report["alerts"]
    assert "actionability_density_drift" not in report["alerts"]


def test_low_processing_coverage_does_not_rewrite_actionability_density() -> None:
    reference = deepcopy(valid_production_drift_reference())
    reference["actionability"]["rate"] = 0.05
    feature_rows, probability_rows = _single_feature_and_probability(reference)

    report = evaluate_production_drift(
        reference,
        feature_rows=feature_rows,
        probability_rows=probability_rows,
        outcome_rows=[],
        actionable_flags=None,
        expected_opportunities=100,
        processed_opportunities=60,
        actionable_opportunities=5,
        thresholds=_thresholds(),
    )

    assert report["coverage"]["status"] == "BLOCKED"
    assert report["coverage"]["rate"] == pytest.approx(0.60)
    assert report["actionability"]["rate"] == pytest.approx(0.05)
    assert report["actionability"]["status"] == "OK"


def test_true_actionability_density_drift_is_still_critical() -> None:
    reference = deepcopy(valid_production_drift_reference())
    reference["actionability"]["rate"] = 0.05
    feature_rows, probability_rows = _single_feature_and_probability(reference)

    report = evaluate_production_drift(
        reference,
        feature_rows=feature_rows,
        probability_rows=probability_rows,
        outcome_rows=[],
        actionable_flags=None,
        expected_opportunities=100,
        processed_opportunities=100,
        actionable_opportunities=50,
        thresholds=_thresholds(),
    )

    assert report["coverage"]["status"] == "OK"
    assert report["actionability"]["rate"] == pytest.approx(0.50)
    assert report["actionability"]["status"] == "CRITICAL"
    assert "actionability_density_drift" in report["critical_evidence"]


@pytest.mark.asyncio
async def test_service_report_separates_terminal_coverage_from_sparse_signal_density() -> None:
    now = datetime(2026, 7, 7, 12, tzinfo=UTC)
    reference = deepcopy(valid_production_drift_reference())
    reference["actionability"]["rate"] = 0.01
    feature_snapshot = {
        name: float(reference["features"][name]["mean"])
        for name in reference["feature_names"]
    }
    probabilities = {"TP": 0.70, "SL": 0.20, "TIMEOUT": 0.10}
    feature_snapshot["directional_predictions"] = {
        "schema": DIRECTIONAL_PREDICTION_SCHEMA,
        "model_version": "model-v1",
        "predictions": {"LONG": probabilities, "SHORT": probabilities},
    }
    signal = SimpleNamespace(
        id="signal-1",
        model_version="model-v1",
        event_time=now - timedelta(hours=10),
        horizon_hours=8,
        feature_snapshot=feature_snapshot,
        net_rr=1.5,
        net_ev_r=0.10,
        p_tp=0.70,
        p_sl=0.20,
        p_timeout=0.10,
    )
    outcome = SimpleNamespace(signal_id=signal.id, outcome="TP")
    active_model = SimpleNamespace(
        active=True,
        model_type="logistic",
        version="model-v1",
        feature_schema_version="schema-v1",
        metrics={"production_drift_reference": reference},
    )
    successful_job = SimpleNamespace(
        status="SUCCESS",
        details={
            "symbols_total": 100,
            "universe_symbols": 100,
            "published": 1,
            "existing_current_hour": 0,
            "symbol_outcome_count": 100,
        },
    )
    session = _Session([active_model, [signal], [successful_job], [outcome]])
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        drift_min_feature_observations=1,
        drift_min_outcome_observations=1,
        drift_max_missing_rate=0.99,
        drift_max_log_loss_delta=10.0,
        drift_max_brier_delta=10.0,
    )

    report = await build_production_drift_report(session, settings, now=now)

    assert report["coverage"]["status"] == "OK"
    assert report["coverage"]["expected_opportunities"] == 100
    assert report["coverage"]["processed_opportunities"] == 100
    assert report["actionability"]["rate"] == pytest.approx(0.01)
    assert report["actionability"]["opportunities"] == 100
    assert report["actionability"]["actionable_opportunities"] == 1
    assert "insufficient_inference_coverage" not in report["alerts"]
    assert "actionability_density_drift" not in report["alerts"]

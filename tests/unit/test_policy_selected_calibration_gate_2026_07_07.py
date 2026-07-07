from __future__ import annotations

from copy import deepcopy

import numpy as np
import pytest

from app.config import Settings
from app.ml.drift import (
    PRODUCTION_DRIFT_CALIBRATION_COHORT_SCHEMA,
    build_production_drift_reference,
)
from app.ml.lifecycle import evaluate_quality_gate
from app.ml.training import MODEL_BASE_FEATURE_NAMES, OUTCOME_CLASSES
from tests.unit.test_model_lifecycle import _candidate, _metrics


def _settings() -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@localhost/db")


def _selected_reference(*, directional_rows: int = 300, selected_rows: int = 150) -> dict[str, object]:
    features = np.zeros((directional_rows, len(MODEL_BASE_FEATURE_NAMES)), dtype=float)
    probabilities = np.repeat([[0.70, 0.20, 0.10]], directional_rows, axis=0)
    outcomes = np.repeat("TP", directional_rows)
    return build_production_drift_reference(
        features,
        probabilities,
        outcomes,
        feature_names=MODEL_BASE_FEATURE_NAMES,
        classes=[str(item) for item in OUTCOME_CLASSES],
        actionability_rate=80 / 150,
        min_net_rr=1.2,
        min_net_ev_r=0.05,
        calibration_reference={
            "rows": selected_rows,
            "log_loss": 0.50,
            "multiclass_brier": 0.20,
        },
        calibration_cohort_schema=PRODUCTION_DRIFT_CALIBRATION_COHORT_SCHEMA,
    )


def _valid_metrics() -> dict[str, object]:
    metrics = _metrics()
    metrics["policy_candidates"] = 150
    metrics["policy_trade_rate"] = metrics["policy_trades"] / 150
    metrics["production_drift_reference"] = _selected_reference()
    return metrics


def test_selected_calibration_schema_requires_explicit_selected_cohort() -> None:
    rows = 12
    features = np.zeros((rows, len(MODEL_BASE_FEATURE_NAMES)), dtype=float)
    probabilities = np.repeat([[0.4, 0.3, 0.3]], rows, axis=0)
    outcomes = np.asarray(["TP", "SL", "TIMEOUT"] * 4)

    with pytest.raises(ValueError, match="explicit selected-direction calibration"):
        build_production_drift_reference(
            features,
            probabilities,
            outcomes,
            feature_names=MODEL_BASE_FEATURE_NAMES,
            classes=[str(item) for item in OUTCOME_CLASSES],
            actionability_rate=0.08,
            min_net_rr=1.2,
            min_net_ev_r=0.05,
            calibration_cohort_schema=PRODUCTION_DRIFT_CALIBRATION_COHORT_SCHEMA,
        )


def test_quality_gate_rejects_poor_selected_direction_log_loss(tmp_path) -> None:
    metrics = _valid_metrics()
    reference = deepcopy(metrics["production_drift_reference"])
    reference["calibration"]["log_loss"] = 4.0
    metrics["production_drift_reference"] = reference

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is False
    assert "policy_selected_log_loss_above_limit" in result["reasons"]


def test_quality_gate_rejects_poor_selected_direction_brier(tmp_path) -> None:
    metrics = _valid_metrics()
    reference = deepcopy(metrics["production_drift_reference"])
    reference["calibration"]["multiclass_brier"] = 1.4
    metrics["production_drift_reference"] = reference

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is False
    assert "policy_selected_multiclass_brier_above_limit" in result["reasons"]


def test_quality_gate_rejects_directional_row_candidate_count_mismatch(tmp_path) -> None:
    metrics = _valid_metrics()
    metrics["policy_candidates"] = 149
    metrics["policy_trade_rate"] = metrics["policy_trades"] / 149

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is False
    assert "policy_candidate_count_does_not_match_directional_holdout_rows" in result["reasons"]


def test_quality_gate_rejects_selected_calibration_row_count_mismatch(tmp_path) -> None:
    metrics = _valid_metrics()
    reference = deepcopy(metrics["production_drift_reference"])
    reference["calibration"]["rows"] = 149
    metrics["production_drift_reference"] = reference

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is False
    assert "policy_selected_calibration_rows_mismatch" in result["reasons"]


def test_quality_gate_rejects_drift_reference_directional_row_mismatch(tmp_path) -> None:
    metrics = _valid_metrics()
    reference = deepcopy(metrics["production_drift_reference"])
    reference["rows"] = 299
    metrics["production_drift_reference"] = reference

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is False
    assert "production_drift_reference_rows_mismatch" in result["reasons"]

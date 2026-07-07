from __future__ import annotations

from datetime import UTC, datetime, timedelta

import joblib
import numpy as np
import pandas as pd
import pytest

import app.ml.training as training
from app.config import Settings
from app.ml.lifecycle import evaluate_quality_gate
from app.ml.runtime import ModelRuntime
from app.ml.training import MODEL_FEATURE_NAMES, OUTCOME_CLASSES, DatasetSplit, PolicyEvaluationConfig
from tests.unit.test_model_artifact_recovery import _write_artifact
from tests.unit.test_model_lifecycle import _candidate, _metrics

ACTIONABLE_SCHEMA = "actionable-policy-trades-final-holdout-v1"


class RareOverconfidentPolicyModel:
    classes_ = OUTCOME_CLASSES

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        probabilities = np.zeros((len(x), len(OUTCOME_CLASSES)), dtype=float)
        actionable = x[:, 0] > 0.5
        probabilities[actionable] = np.asarray([0.99, 0.005, 0.005], dtype=float)
        probabilities[~actionable] = np.asarray([0.10, 0.80, 0.10], dtype=float)
        return probabilities


def _rare_bad_actionable_split() -> DatasetSplit:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    records: list[dict[str, object]] = []
    markers: list[float] = []
    directions: list[float] = []
    for hour in range(150):
        decision_time = start + timedelta(hours=hour)
        actionable = hour < 20
        for direction, direction_code in (("LONG", 1.0), ("SHORT", -1.0)):
            records.append(
                {
                    "decision_time": decision_time,
                    "label_end_time": decision_time + timedelta(hours=1),
                    "symbol": "BTCUSDT",
                    "direction": direction,
                    "target": "SL",
                    "exit_index": 0,
                    "exit_at_open": False,
                    "realized_gross_return": -0.10,
                    "barrier_upside_rate": 0.10,
                    "barrier_downside_rate": 0.10,
                }
            )
            markers.append(1.0 if actionable else 0.0)
            directions.append(direction_code)
    meta = pd.DataFrame.from_records(records)
    values = np.zeros((len(meta), len(MODEL_FEATURE_NAMES)), dtype=float)
    values[:, 0] = np.asarray(markers, dtype=float)
    values[:, -1] = np.asarray(directions, dtype=float)
    targets = meta["target"].to_numpy()
    return DatasetSplit(values, targets, values, targets, values, targets, meta)


def _settings() -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@localhost/db")


def _metrics_with_actionable_calibration() -> dict[str, object]:
    metrics = _metrics()
    metrics.update(
        {
            "policy_actionable_calibration_schema": ACTIONABLE_SCHEMA,
            "policy_actionable_calibration_rows": metrics["policy_trades"],
            "policy_actionable_log_loss": 0.60,
            "policy_actionable_multiclass_brier": 0.30,
        }
    )
    return metrics


def test_policy_evaluation_exposes_bad_calibration_on_the_rare_traded_subset() -> None:
    metrics = training.evaluate_policy_model(
        RareOverconfidentPolicyModel(),
        _rare_bad_actionable_split(),
        PolicyEvaluationConfig(
            fee_rate_round_trip=0.0,
            slippage_rate=0.0,
            stop_gap_reserve_rate=0.0,
            min_net_rr=0.0,
            min_net_ev_r=0.05,
            horizon_hours=1,
            bootstrap_samples=500,
            confidence_level=0.95,
        ),
    )

    assert metrics["policy_trades"] == 20
    assert metrics["policy_selected_log_loss"] < 1.20
    assert metrics["policy_selected_multiclass_brier"] < 0.75
    assert metrics["policy_actionable_calibration_schema"] == ACTIONABLE_SCHEMA
    assert metrics["policy_actionable_calibration_rows"] == 20
    assert metrics["policy_actionable_log_loss"] > 4.0
    assert metrics["policy_actionable_multiclass_brier"] > 1.5


def test_quality_gate_rejects_missing_actionable_calibration(tmp_path) -> None:
    metrics = _metrics()
    for key in (
        "policy_actionable_calibration_schema",
        "policy_actionable_calibration_rows",
        "policy_actionable_log_loss",
        "policy_actionable_multiclass_brier",
    ):
        metrics.pop(key, None)

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is False
    assert "invalid_policy_actionable_calibration_schema" in result["reasons"]


def test_quality_gate_rejects_bad_actionable_log_loss(tmp_path) -> None:
    metrics = _metrics_with_actionable_calibration()
    metrics["policy_actionable_log_loss"] = 4.0

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is False
    assert "policy_actionable_log_loss_above_limit" in result["reasons"]


def test_quality_gate_rejects_bad_actionable_brier(tmp_path) -> None:
    metrics = _metrics_with_actionable_calibration()
    metrics["policy_actionable_multiclass_brier"] = 1.4

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is False
    assert "policy_actionable_multiclass_brier_above_limit" in result["reasons"]


def test_quality_gate_rejects_actionable_calibration_row_mismatch(tmp_path) -> None:
    metrics = _metrics_with_actionable_calibration()
    metrics["policy_actionable_calibration_rows"] = int(metrics["policy_trades"]) - 1

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is False
    assert "policy_actionable_calibration_rows_mismatch" in result["reasons"]


def test_quality_gate_accepts_consistent_actionable_calibration(tmp_path) -> None:
    result = evaluate_quality_gate(
        _candidate(tmp_path, metrics=_metrics_with_actionable_calibration()),
        _settings(),
    )

    assert result["passed"] is True
    assert result["reasons"] == []


def test_runtime_rejects_legacy_artifact_without_actionable_calibration(tmp_path) -> None:
    artifact = tmp_path / "legacy.joblib"
    _write_artifact(artifact, version="legacy")
    bundle = joblib.load(artifact)
    metrics = dict(bundle["metrics"])
    for key in (
        "policy_actionable_calibration_schema",
        "policy_actionable_calibration_rows",
        "policy_actionable_log_loss",
        "policy_actionable_multiclass_brier",
    ):
        metrics.pop(key, None)
    bundle["metrics"] = metrics
    joblib.dump(bundle, artifact)

    runtime = ModelRuntime(artifact, allow_baseline=False)
    with pytest.raises(ValueError, match="actionable calibration"):
        runtime.load(expected_version="legacy")

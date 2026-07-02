from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from app.config import Settings
from app.ml.data_profile import profile_from_symbol_rows
from app.ml.lifecycle import ModelCandidate, evaluate_quality_gate
from app.ml.training import (
    MODEL_FEATURE_NAMES,
    OUTCOME_CLASSES,
    DatasetSplit,
    PolicyEvaluationConfig,
    evaluate_policy_model,
)


def _candidate(tmp_path: Path, metrics: dict[str, object]) -> ModelCandidate:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return ModelCandidate(
        path=tmp_path / "candidate.joblib",
        version="candidate-v1",
        model_type="logistic",
        horizon=8,
        training_start=now,
        training_end=now,
        dataset_rows=1000,
        unique_timestamps=500,
        symbol_count=1,
        symbol_sample=("BTCUSDT",),
        training_data_profile=profile_from_symbol_rows(
            [("BTCUSDT", 500, now, now)],
            unique_timestamps=500,
            minimum_rows_for_coverage=300,
        ),
        metrics=metrics,
        incumbent_metrics=None,
        incumbent_version=None,
    )


def _passing_metrics() -> dict[str, object]:
    return {
        "rows": 300,
        "holdout_span_hours": 336.0,
        "log_loss": 0.9,
        "class_prior_log_loss": 1.05,
        "log_loss_skill_vs_prior": 0.15,
        "multiclass_brier": 0.55,
        "ece_tp": 0.05,
        "ece_sl": 0.05,
        "ece_timeout": 0.05,
        "class_distribution": {"TP": 0.35, "SL": 0.40, "TIMEOUT": 0.25},
        "policy_metric_schema": "exit-time-open-gap-horizon-independent-cohort-v8",
        "policy_horizon_hours": 8,
        "policy_capital_sleeves": 8,
        "policy_trades": 80,
        "policy_cohorts": 80,
        "policy_independent_cohorts": 40,
        "policy_realized_mean_r": 0.05,
        "policy_profit_factor": 1.2,
        "policy_max_drawdown_r": 5.0,
    }


def test_hourly_overlapping_policy_cohorts_are_not_counted_as_independent() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    probabilities: list[list[float]] = []
    for index in range(20):
        decision_time = start + timedelta(hours=index)
        symbol = f"COHORT{index}USDT"
        rows.extend(
            [
                {
                    "decision_time": decision_time,
                    "label_end_time": decision_time + timedelta(hours=8),
                    "symbol": symbol,
                    "direction": "LONG",
                    "target": "TIMEOUT",
                    "exit_index": 7,
                    "exit_at_open": False,
                    "realized_gross_return": 0.005,
                    "barrier_upside_rate": 0.01,
                    "barrier_downside_rate": 0.01,
                },
                {
                    "decision_time": decision_time,
                    "label_end_time": decision_time + timedelta(hours=8),
                    "symbol": symbol,
                    "direction": "SHORT",
                    "target": "SL",
                    "exit_index": 0,
                    "exit_at_open": False,
                    "realized_gross_return": -0.01,
                    "barrier_upside_rate": 0.01,
                    "barrier_downside_rate": 0.01,
                },
            ]
        )
        probabilities.extend([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0]])

    meta = pd.DataFrame(rows)
    values = np.zeros((len(meta), len(MODEL_FEATURE_NAMES)), dtype=float)
    values[:, -1] = np.where(meta["direction"].eq("LONG"), 1.0, -1.0)

    class RowProbabilityModel:
        classes_ = OUTCOME_CLASSES

        def predict_proba(self, _: np.ndarray) -> np.ndarray:
            return np.asarray(probabilities, dtype=float)

    split = DatasetSplit(
        values,
        meta["target"].to_numpy(),
        values,
        meta["target"].to_numpy(),
        values,
        meta["target"].to_numpy(),
        meta,
    )
    metrics = evaluate_policy_model(
        RowProbabilityModel(),
        split,
        PolicyEvaluationConfig(
            fee_rate_round_trip=0.0,
            slippage_rate=0.0,
            stop_gap_reserve_rate=0.0,
            min_net_rr=0.0,
            min_net_ev_r=-100.0,
            timeout_return_rate=0.005,
            horizon_hours=8,
        ),
    )

    assert metrics["policy_cohorts"] == 20
    assert metrics["policy_independent_cohorts"] == 3


def test_quality_gate_rejects_large_cross_section_from_short_holdout(tmp_path: Path) -> None:
    metrics = _passing_metrics()
    metrics["holdout_span_hours"] = 47.0

    result = evaluate_quality_gate(
        _candidate(tmp_path, metrics),
        Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            auto_train_min_holdout_span_hours=168,
        ),
    )

    assert result["passed"] is False
    assert "holdout_span_below_minimum" in result["reasons"]


def test_quality_gate_rejects_model_without_skill_over_class_prior(tmp_path: Path) -> None:
    metrics = _passing_metrics()
    metrics["class_prior_log_loss"] = 1.05
    metrics["log_loss_skill_vs_prior"] = -0.02

    result = evaluate_quality_gate(
        _candidate(tmp_path, metrics),
        Settings(database_url="postgresql+psycopg://u:p@localhost/db"),
    )

    assert result["passed"] is False
    assert "log_loss_skill_vs_prior_not_positive" in result["reasons"]

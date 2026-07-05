from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.ml.data_profile import profile_from_symbol_rows
from app.ml.lifecycle import ModelCandidate, evaluate_quality_gate


def _candidate(
    tmp_path: Path,
    *,
    metrics: dict,
    incumbent_metrics: dict | None = None,
) -> ModelCandidate:
    now = datetime.now(UTC)
    profile = profile_from_symbol_rows(
        [
            ("BTCUSDT", 500, now, now),
            ("ETHUSDT", 500, now, now),
            ("SOLUSDT", 500, now, now),
        ],
        unique_timestamps=500,
        minimum_rows_for_coverage=300,
    )
    return ModelCandidate(
        path=tmp_path / "candidate.joblib",
        version="candidate-v1",
        model_type="logistic",
        horizon=8,
        training_start=now,
        training_end=now,
        dataset_rows=1000,
        unique_timestamps=500,
        symbol_count=3,
        symbol_sample=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        training_data_profile=profile,
        metrics=metrics,
        incumbent_metrics=incumbent_metrics,
        incumbent_version="incumbent-v1" if incumbent_metrics else None,
    )


def _metrics(*, log_loss: float = 0.90, brier: float = 0.55) -> dict:
    return {
        "rows": 300,
        "holdout_span_hours": 336.0,
        "log_loss": log_loss,
        "class_prior_log_loss": 1.05,
        "log_loss_skill_vs_prior": 1.05 - log_loss,
        "multiclass_brier": brier,
        "ece_tp": 0.05,
        "ece_sl": 0.06,
        "ece_timeout": 0.07,
        "class_distribution": {"TP": 0.35, "SL": 0.40, "TIMEOUT": 0.25},
        "policy_metric_schema": "decision-open-entry-exit-time-cohort-v11",
        "policy_horizon_hours": 8,
        "policy_capital_sleeves": 8,
        "policy_candidates": 1_000,
        "policy_trades": 80,
        "policy_trade_rate": 0.08,
        "policy_cohorts": 80,
        "policy_independent_cohorts": 80,
        "policy_independent_mean_r": 0.04,
        "policy_mean_r_lcb": 0.01,
        "policy_mean_r_confidence_level": 0.95,
        "policy_mean_r_bootstrap_samples": 2_000,
        "policy_mean_r_bootstrap_block_length": 1,
        "policy_mean_r_uncertainty_schema": "horizon-separated-circular-moving-block-v1",
        "policy_realized_mean_r": 0.05,
        "policy_profit_factor": 1.2,
        "policy_max_drawdown_r": 5.0,
    }


def test_quality_gate_accepts_bootstrap_candidate(tmp_path: Path) -> None:
    settings = Settings(database_url="postgresql+psycopg://u:p@localhost/db")
    result = evaluate_quality_gate(_candidate(tmp_path, metrics=_metrics()), settings)

    assert result["passed"] is True
    assert result["reasons"] == []
    assert result["relative"] is None


def test_quality_gate_requires_open_gap_propagation_metric_schema(tmp_path: Path) -> None:
    metrics = _metrics()
    metrics["policy_metric_schema"] = "decision-open-entry-exit-time-cohort-v11"

    result = evaluate_quality_gate(
        _candidate(tmp_path, metrics=metrics),
        Settings(database_url="postgresql+psycopg://u:p@localhost/db"),
    )

    assert result["passed"] is True
    assert "invalid_policy_metric_schema" not in result["reasons"]

    legacy_metrics = _metrics()
    legacy_metrics["policy_metric_schema"] = "exit-time-open-gap-horizon-independent-cohort-v8"
    legacy_result = evaluate_quality_gate(
        _candidate(tmp_path, metrics=legacy_metrics),
        Settings(database_url="postgresql+psycopg://u:p@localhost/db"),
    )
    assert legacy_result["passed"] is False
    assert "invalid_policy_metric_schema" in legacy_result["reasons"]


def test_quality_gate_rejects_candidate_without_required_improvement(tmp_path: Path) -> None:
    settings = Settings(database_url="postgresql+psycopg://u:p@localhost/db")
    candidate = _candidate(
        tmp_path,
        metrics=_metrics(log_loss=0.90, brier=0.55),
        incumbent_metrics=_metrics(log_loss=0.899, brier=0.549),
    )

    result = evaluate_quality_gate(candidate, settings)

    assert result["passed"] is False
    assert "no_required_improvement_vs_incumbent" in result["reasons"]


def test_quality_gate_rejects_material_regression(tmp_path: Path) -> None:
    settings = Settings(database_url="postgresql+psycopg://u:p@localhost/db")
    candidate = _candidate(
        tmp_path,
        metrics=_metrics(log_loss=1.00, brier=0.66),
        incumbent_metrics=_metrics(log_loss=0.90, brier=0.55),
    )

    result = evaluate_quality_gate(candidate, settings)

    assert result["passed"] is False
    assert "log_loss_regressed_vs_incumbent" in result["reasons"]
    assert "multiclass_brier_regressed_vs_incumbent" in result["reasons"]


def test_quality_gate_blocks_auto_activation_without_incumbent_comparison(tmp_path: Path) -> None:
    settings = Settings(database_url="postgresql+psycopg://u:p@localhost/db")
    candidate = _candidate(
        tmp_path,
        metrics=_metrics(),
        incumbent_metrics={
            "comparison_skipped": "incumbent_load_or_evaluation_failed",
            "error": "checksum mismatch",
        },
    )

    result = evaluate_quality_gate(candidate, settings)

    assert result["passed"] is False
    assert "incumbent_comparison_unavailable" in result["reasons"]


def test_quality_gate_remains_strict_json_when_incumbent_has_no_policy_trades(
    tmp_path: Path,
) -> None:
    incumbent_metrics = _metrics(log_loss=0.95, brier=0.56)
    incumbent_metrics.update(
        {
            "policy_trades": 0,
            "policy_trade_rate": 0.0,
            "policy_realized_mean_r": None,
            "policy_profit_factor": None,
            "policy_max_drawdown_r": 0.0,
        }
    )
    candidate = _candidate(
        tmp_path,
        metrics=_metrics(log_loss=0.90, brier=0.55),
        incumbent_metrics=incumbent_metrics,
    )

    result = evaluate_quality_gate(
        candidate,
        Settings(database_url="postgresql+psycopg://u:p@localhost/db"),
    )

    json.dumps(result, allow_nan=False)
    assert result["relative"]["incumbent_policy_realized_mean_r"] is None
    assert result["relative"]["policy_realized_mean_r_delta"] is None
    assert result["relative"]["policy_improved"] is True


def test_quality_gate_serializes_missing_candidate_policy_metrics_as_null(
    tmp_path: Path,
) -> None:
    metrics = _metrics()
    metrics.update(
        {
            "policy_trades": 0,
            "policy_trade_rate": 0.0,
            "policy_realized_mean_r": None,
            "policy_profit_factor": None,
            "policy_max_drawdown_r": None,
        }
    )

    result = evaluate_quality_gate(
        _candidate(tmp_path, metrics=metrics),
        Settings(database_url="postgresql+psycopg://u:p@localhost/db"),
    )

    json.dumps(result, allow_nan=False)
    assert result["absolute"]["policy_realized_mean_r"] is None
    assert result["absolute"]["policy_profit_factor"] is None
    assert result["absolute"]["policy_max_drawdown_r"] is None


def test_quality_gate_rejects_legacy_policy_metric_schema(tmp_path: Path) -> None:
    metrics = _metrics()
    metrics.pop("policy_metric_schema")
    metrics.pop("policy_horizon_hours")
    metrics.pop("policy_capital_sleeves")

    result = evaluate_quality_gate(
        _candidate(tmp_path, metrics=metrics),
        Settings(database_url="postgresql+psycopg://u:p@localhost/db"),
    )

    assert result["passed"] is False
    assert "invalid_policy_metric_schema" in result["reasons"]
    assert "policy_horizon_mismatch" in result["reasons"]
    assert "policy_capital_sleeves_mismatch" in result["reasons"]

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.ml.lifecycle import ModelCandidate, evaluate_quality_gate


def _candidate(
    tmp_path: Path,
    *,
    metrics: dict,
    incumbent_metrics: dict | None = None,
) -> ModelCandidate:
    now = datetime.now(UTC)
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
        metrics=metrics,
        incumbent_metrics=incumbent_metrics,
        incumbent_version="incumbent-v1" if incumbent_metrics else None,
    )


def _metrics(*, log_loss: float = 0.90, brier: float = 0.55) -> dict:
    return {
        "rows": 300,
        "log_loss": log_loss,
        "multiclass_brier": brier,
        "ece_tp": 0.05,
        "ece_sl": 0.06,
        "ece_timeout": 0.07,
        "class_distribution": {"TP": 0.35, "SL": 0.40, "TIMEOUT": 0.25},
    }


def test_quality_gate_accepts_bootstrap_candidate(tmp_path: Path) -> None:
    settings = Settings(database_url="postgresql+psycopg://u:p@localhost/db")
    result = evaluate_quality_gate(_candidate(tmp_path, metrics=_metrics()), settings)

    assert result["passed"] is True
    assert result["reasons"] == []
    assert result["relative"] is None


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

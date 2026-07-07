from __future__ import annotations

from datetime import UTC, datetime, timedelta

import joblib
import pandas as pd
import pytest

from app.config import Settings
from app.ml import training
from app.ml.lifecycle import evaluate_quality_gate
from app.ml.runtime import ModelRuntime
from tests.unit.test_model_artifact_recovery import _write_artifact
from tests.unit.test_model_lifecycle import _candidate, _metrics

CLUSTER_SCHEMA = "absolute-correlation-components-leave-one-cluster-out-opportunity-cohort-v1"


def _settings() -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@localhost/db")


def _robust_cluster_evidence(*, policy_trades: int = 80) -> dict[str, object]:
    first = policy_trades // 2
    second = policy_trades - first
    return {
        "schema": CLUSTER_SCHEMA,
        "correlation_threshold": 0.70,
        "minimum_shared_active_observations": 8,
        "symbol_count": 3,
        "cluster_count": 2,
        "trade_count": policy_trades,
        "max_cluster_trade_fraction": first / policy_trades,
        "leave_one_cluster_out_mean_r_min": 0.01,
        "clusters": [
            {
                "cluster_id": "cluster-001",
                "symbols": ["BTCUSDT", "ETHUSDT"],
                "trades": first,
                "trade_fraction": first / policy_trades,
                "leave_one_cluster_out_policy_mean_r": 0.02,
            },
            {
                "cluster_id": "cluster-002",
                "symbols": ["SOLUSDT"],
                "trades": second,
                "trade_fraction": second / policy_trades,
                "leave_one_cluster_out_policy_mean_r": 0.01,
            },
        ],
    }


def _cluster_masking_trades() -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    times: list[datetime] = []
    winner_path = [1.0, 0.6, 1.2, 0.8, 1.1, 0.7, 1.3, 0.9, 1.05, 0.65]
    for index, winner_return in enumerate(winner_path):
        decision_time = start + timedelta(hours=index)
        times.append(decision_time)
        rows.extend(
            [
                {"symbol": "ALPHAUSDT", "decision_time": decision_time, "realized_r": winner_return},
                {"symbol": "BETAUSDT", "decision_time": decision_time, "realized_r": winner_return * 0.95},
                {"symbol": "LOSSUSDT", "decision_time": decision_time, "realized_r": -0.20},
            ]
        )
    return pd.DataFrame.from_records(rows), pd.DatetimeIndex(times)


def test_cluster_jackknife_exposes_correlated_group_dependency() -> None:
    builder = getattr(training, "_policy_cluster_robustness", None)
    assert callable(builder), "cluster robustness calculation is missing"
    trades, opportunity_times = _cluster_masking_trades()

    symbol_evidence = training._policy_symbol_robustness(trades, opportunity_times)
    evidence = builder(trades, opportunity_times)

    assert symbol_evidence["leave_one_symbol_out_mean_r_min"] > 0.0
    assert evidence["schema"] == CLUSTER_SCHEMA
    assert evidence["symbol_count"] == 3
    assert evidence["cluster_count"] == 2
    assert evidence["clusters"][0]["symbols"] == ["ALPHAUSDT", "BETAUSDT"]
    assert evidence["clusters"][1]["symbols"] == ["LOSSUSDT"]
    assert evidence["leave_one_cluster_out_mean_r_min"] == pytest.approx(-0.20)


def test_quality_gate_rejects_edge_that_depends_on_one_cluster(tmp_path) -> None:
    metrics = _metrics()
    evidence = _robust_cluster_evidence(policy_trades=int(metrics["policy_trades"]))
    evidence["clusters"][0]["leave_one_cluster_out_policy_mean_r"] = -0.01
    evidence["leave_one_cluster_out_mean_r_min"] = -0.01
    metrics["policy_cluster_robustness"] = evidence

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is False
    assert "policy_cluster_leave_one_out_mean_r_not_above_minimum" in result["reasons"]


def test_quality_gate_rejects_missing_cluster_evidence(tmp_path) -> None:
    metrics = _metrics()
    metrics.pop("policy_cluster_robustness", None)

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is False
    assert "invalid_policy_cluster_robustness" in result["reasons"]


def test_quality_gate_rejects_cluster_symbol_overlap(tmp_path) -> None:
    metrics = _metrics()
    evidence = _robust_cluster_evidence(policy_trades=int(metrics["policy_trades"]))
    evidence["clusters"][1]["symbols"] = ["ETHUSDT", "SOLUSDT"]
    metrics["policy_cluster_robustness"] = evidence

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is False
    assert "invalid_policy_cluster_robustness" in result["reasons"]


def test_quality_gate_rejects_cluster_symbol_set_mismatch(tmp_path) -> None:
    metrics = _metrics()
    evidence = _robust_cluster_evidence(policy_trades=int(metrics["policy_trades"]))
    evidence["clusters"][1]["symbols"] = ["XRPUSDT"]
    metrics["policy_cluster_robustness"] = evidence

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is False
    assert "policy_cluster_symbol_set_mismatch" in result["reasons"]


def test_quality_gate_accepts_cluster_robust_candidate(tmp_path) -> None:
    metrics = _metrics()
    metrics["policy_cluster_robustness"] = _robust_cluster_evidence(
        policy_trades=int(metrics["policy_trades"])
    )

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is True
    assert result["reasons"] == []


def test_runtime_rejects_artifact_without_cluster_robustness(tmp_path) -> None:
    artifact = tmp_path / "missing-cluster-robustness.joblib"
    _write_artifact(artifact, version="missing-cluster-robustness")
    bundle = joblib.load(artifact)
    metrics = dict(bundle["metrics"])
    metrics.pop("policy_cluster_robustness", None)
    bundle["metrics"] = metrics
    joblib.dump(bundle, artifact)

    runtime = ModelRuntime(artifact, allow_baseline=False)
    with pytest.raises(ValueError, match="cluster robustness"):
        runtime.load(expected_version="missing-cluster-robustness")


def test_runtime_rejects_malformed_cluster_robustness(tmp_path) -> None:
    artifact = tmp_path / "malformed-cluster-robustness.joblib"
    _write_artifact(artifact, version="malformed-cluster-robustness")
    bundle = joblib.load(artifact)
    metrics = dict(bundle["metrics"])
    evidence = _robust_cluster_evidence(policy_trades=int(metrics["policy_trades"]))
    evidence["clusters"][0]["trade_fraction"] = 0.99
    metrics["policy_cluster_robustness"] = evidence
    bundle["metrics"] = metrics
    joblib.dump(bundle, artifact)

    runtime = ModelRuntime(artifact, allow_baseline=False)
    with pytest.raises(ValueError, match="cluster robustness"):
        runtime.load(expected_version="malformed-cluster-robustness")

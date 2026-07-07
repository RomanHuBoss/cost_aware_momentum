from __future__ import annotations

from datetime import UTC, datetime, timedelta

import joblib
import numpy as np
import pandas as pd
import pytest

from app.config import Settings
from app.ml.lifecycle import evaluate_quality_gate
from app.ml.runtime import ModelRuntime
from app.ml.training import (
    MODEL_FEATURE_NAMES,
    OUTCOME_CLASSES,
    DatasetSplit,
    PolicyEvaluationConfig,
    evaluate_policy_model,
)
from tests.unit.test_model_artifact_recovery import _write_artifact
from tests.unit.test_model_lifecycle import _candidate, _metrics

SYMBOL_ROBUSTNESS_SCHEMA = "leave-one-symbol-out-opportunity-cohort-v1"


def _settings() -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@localhost/db")


def _robust_symbol_evidence(*, policy_trades: int = 80) -> dict[str, object]:
    first = policy_trades // 2
    second = policy_trades - first
    return {
        "schema": SYMBOL_ROBUSTNESS_SCHEMA,
        "symbol_count": 2,
        "trade_count": policy_trades,
        "max_symbol_trade_fraction": max(first, second) / policy_trades,
        "leave_one_symbol_out_mean_r_min": 0.01,
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "trades": first,
                "trade_fraction": first / policy_trades,
                "leave_one_symbol_out_policy_mean_r": 0.02,
            },
            {
                "symbol": "ETHUSDT",
                "trades": second,
                "trade_fraction": second / policy_trades,
                "leave_one_symbol_out_policy_mean_r": 0.01,
            },
        ],
    }


def _concentrated_split() -> tuple[DatasetSplit, np.ndarray]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    probabilities: list[list[float]] = []
    for hour in range(20):
        decision_time = start + timedelta(hours=hour)
        for symbol, gross in (("WINUSDT", 0.01), ("LOSSUSDT", -0.002)):
            target = "TP" if gross > 0 else "TIMEOUT"
            rows.extend(
                [
                    {
                        "decision_time": decision_time,
                        "label_end_time": decision_time + timedelta(hours=1),
                        "symbol": symbol,
                        "direction": "LONG",
                        "target": target,
                        "exit_index": 0,
                        "exit_at_open": False,
                        "realized_gross_return": gross,
                        "barrier_upside_rate": 0.01,
                        "barrier_downside_rate": 0.01,
                    },
                    {
                        "decision_time": decision_time,
                        "label_end_time": decision_time + timedelta(hours=1),
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
            probabilities.extend([[1.0, 0.0, 0.0] if target == "TP" else [0.0, 0.0, 1.0], [0.0, 1.0, 0.0]])

    meta = pd.DataFrame.from_records(rows)
    values = np.zeros((len(meta), len(MODEL_FEATURE_NAMES)), dtype=float)
    values[:, -1] = np.where(meta["direction"].eq("LONG"), 1.0, -1.0)
    targets = meta["target"].to_numpy()
    return DatasetSplit(values, targets, values, targets, values, targets, meta), np.asarray(probabilities)


def test_policy_evaluation_exposes_single_symbol_edge_dependency() -> None:
    split, probabilities = _concentrated_split()

    class RowProbabilityModel:
        classes_ = OUTCOME_CLASSES

        def predict_proba(self, _: np.ndarray) -> np.ndarray:
            return probabilities

    metrics = evaluate_policy_model(
        RowProbabilityModel(),
        split,
        PolicyEvaluationConfig(
            fee_rate_round_trip=0.0,
            slippage_rate=0.0,
            stop_gap_reserve_rate=0.0,
            min_net_rr=0.0,
            min_net_ev_r=-100.0,
            timeout_return_rate=0.0,
            horizon_hours=1,
            bootstrap_samples=500,
            confidence_level=0.95,
        ),
    )

    assert metrics["policy_realized_mean_r"] == pytest.approx(0.4)
    evidence = metrics["policy_symbol_robustness"]
    assert evidence["schema"] == SYMBOL_ROBUSTNESS_SCHEMA
    assert evidence["symbol_count"] == 2
    assert evidence["trade_count"] == 40
    assert evidence["leave_one_symbol_out_mean_r_min"] == pytest.approx(-0.2)
    assert evidence["symbols"] == [
        {
            "symbol": "LOSSUSDT",
            "trades": 20,
            "trade_fraction": 0.5,
            "leave_one_symbol_out_policy_mean_r": pytest.approx(1.0),
        },
        {
            "symbol": "WINUSDT",
            "trades": 20,
            "trade_fraction": 0.5,
            "leave_one_symbol_out_policy_mean_r": pytest.approx(-0.2),
        },
    ]


def test_quality_gate_rejects_edge_that_depends_on_one_symbol(tmp_path) -> None:
    metrics = _metrics()
    evidence = _robust_symbol_evidence(policy_trades=int(metrics["policy_trades"]))
    evidence["symbols"][0]["leave_one_symbol_out_policy_mean_r"] = -0.01
    evidence["leave_one_symbol_out_mean_r_min"] = -0.01
    metrics["policy_symbol_robustness"] = evidence

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is False
    assert "policy_symbol_leave_one_out_mean_r_not_above_minimum" in result["reasons"]


def test_quality_gate_rejects_symbol_trade_count_mismatch(tmp_path) -> None:
    metrics = _metrics()
    evidence = _robust_symbol_evidence(policy_trades=int(metrics["policy_trades"]))
    evidence["trade_count"] = int(metrics["policy_trades"]) - 1
    metrics["policy_symbol_robustness"] = evidence

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is False
    assert "invalid_policy_symbol_robustness" in result["reasons"]


def test_quality_gate_rejects_duplicate_symbol_evidence(tmp_path) -> None:
    metrics = _metrics()
    evidence = _robust_symbol_evidence(policy_trades=int(metrics["policy_trades"]))
    evidence["symbols"][1]["symbol"] = "BTCUSDT"
    metrics["policy_symbol_robustness"] = evidence

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is False
    assert "invalid_policy_symbol_robustness" in result["reasons"]


def test_quality_gate_accepts_symbol_robust_candidate(tmp_path) -> None:
    metrics = _metrics()
    policy_trades = int(metrics["policy_trades"])
    metrics["policy_symbol_robustness"] = _robust_symbol_evidence(
        policy_trades=policy_trades
    )
    first = policy_trades // 2
    second = policy_trades - first
    metrics["policy_cluster_robustness"] = {
        "schema": (
            "absolute-correlation-components-leave-one-cluster-out-"
            "opportunity-cohort-v1"
        ),
        "correlation_threshold": 0.70,
        "minimum_shared_active_observations": 8,
        "symbol_count": 2,
        "cluster_count": 2,
        "trade_count": policy_trades,
        "max_cluster_trade_fraction": max(first, second) / policy_trades,
        "leave_one_cluster_out_mean_r_min": 0.01,
        "clusters": [
            {
                "cluster_id": "cluster-001",
                "symbols": ["BTCUSDT"],
                "trades": first,
                "trade_fraction": first / policy_trades,
                "leave_one_cluster_out_policy_mean_r": 0.02,
            },
            {
                "cluster_id": "cluster-002",
                "symbols": ["ETHUSDT"],
                "trades": second,
                "trade_fraction": second / policy_trades,
                "leave_one_cluster_out_policy_mean_r": 0.01,
            },
        ],
    }
    metrics["policy_interaction_robustness"] = {
        "schema": "symbol-direction-regime-supported-cells-sparse-pool-jackknife-v2",
        "minimum_trades_per_supported_cell": 5,
        "trade_count": policy_trades,
        "observed_cell_count": 2,
        "supported_cell_count": 2,
        "sparse_cell_count": 0,
        "supported_trade_count": policy_trades,
        "sparse_trade_count": 0,
        "tested_bucket_count": 2,
        "worst_tested_bucket_mean_r": 0.02,
        "worst_tested_bucket_log_loss": 0.60,
        "worst_tested_bucket_multiclass_brier": 0.30,
        "cells": [
            {
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "regime": "RANGE",
                "support": "SUPPORTED",
                "trades": first,
                "trade_fraction": first / policy_trades,
                "realized_trade_mean_r": 0.03,
                "calibration_rows": first,
                "log_loss": 0.55,
                "multiclass_brier": 0.28,
            },
            {
                "symbol": "ETHUSDT",
                "direction": "SHORT",
                "regime": "UPTREND",
                "support": "SUPPORTED",
                "trades": second,
                "trade_fraction": second / policy_trades,
                "realized_trade_mean_r": 0.02,
                "calibration_rows": second,
                "log_loss": 0.60,
                "multiclass_brier": 0.30,
            },
        ],
        "sparse_pool": None,
    }

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is True
    assert result["reasons"] == []


def test_runtime_rejects_artifact_without_symbol_robustness(tmp_path) -> None:
    artifact = tmp_path / "missing-symbol-robustness.joblib"
    _write_artifact(artifact, version="missing-symbol-robustness")
    bundle = joblib.load(artifact)
    metrics = dict(bundle["metrics"])
    metrics.pop("policy_symbol_robustness", None)
    bundle["metrics"] = metrics
    joblib.dump(bundle, artifact)

    runtime = ModelRuntime(artifact, allow_baseline=False)
    with pytest.raises(ValueError, match="symbol robustness"):
        runtime.load(expected_version="missing-symbol-robustness")


def test_runtime_rejects_malformed_symbol_robustness(tmp_path) -> None:
    artifact = tmp_path / "malformed-symbol-robustness.joblib"
    _write_artifact(artifact, version="malformed-symbol-robustness")
    bundle = joblib.load(artifact)
    metrics = dict(bundle["metrics"])
    metrics["policy_symbol_robustness"] = _robust_symbol_evidence(
        policy_trades=int(metrics["policy_trades"])
    )
    metrics["policy_symbol_robustness"]["symbols"][0]["trade_fraction"] = 0.99
    bundle["metrics"] = metrics
    joblib.dump(bundle, artifact)

    runtime = ModelRuntime(artifact, allow_baseline=False)
    with pytest.raises(ValueError, match="symbol robustness"):
        runtime.load(expected_version="malformed-symbol-robustness")

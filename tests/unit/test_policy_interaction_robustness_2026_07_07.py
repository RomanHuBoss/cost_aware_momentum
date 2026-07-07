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

INTERACTION_SCHEMA = "symbol-direction-regime-supported-cells-sparse-pool-jackknife-v2"
SPARSE_JACKKNIFE_SCHEMA = "leave-one-sparse-interaction-cell-out-v1"


def _settings() -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@localhost/db")


def _masking_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DatetimeIndex]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    selected_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    times: list[datetime] = []
    definitions = (
        ("BTCUSDT", "LONG", "UPTREND", -0.20),
        ("BTCUSDT", "LONG", "RANGE", 1.00),
        ("ETHUSDT", "SHORT", "UPTREND", 1.00),
        ("ETHUSDT", "SHORT", "RANGE", 1.00),
    )
    index = 0
    for symbol, direction, regime, realized_r in definitions:
        for _ in range(10):
            decision_time = start + timedelta(hours=index)
            index += 1
            times.append(decision_time)
            selected_rows.append(
                {
                    "decision_time": decision_time,
                    "regime_ret_24h": 0.02 if regime == "UPTREND" else 0.0,
                    "regime_atr_pct_14": 0.01,
                }
            )
            target = "TP" if realized_r > 0 else "TIMEOUT"
            trade_rows.append(
                {
                    "symbol": symbol,
                    "direction": direction,
                    "decision_time": decision_time,
                    "realized_r": realized_r,
                    "target": target,
                    "p_tp": 0.80 if target == "TP" else 0.10,
                    "p_sl": 0.10,
                    "p_timeout": 0.10 if target == "TP" else 0.80,
                }
            )
    return (
        pd.DataFrame.from_records(selected_rows),
        pd.DataFrame.from_records(trade_rows),
        pd.DatetimeIndex(times),
    )


def _interaction_evidence(
    *,
    sparse_pool_mean: float | None = None,
    sparse_counts: tuple[int, int] = (3, 2),
) -> dict[str, object]:
    cells = [
        ("BTCUSDT", "LONG", "RANGE", 15, -0.01 if sparse_pool_mean is None else 0.03, "SUPPORTED"),
        ("BTCUSDT", "SHORT", "UPTREND", 12, 0.02, "SUPPORTED"),
        ("ETHUSDT", "LONG", "UPTREND", 13, 0.03, "SUPPORTED"),
        ("ETHUSDT", "SHORT", "RANGE", 13, 0.02, "SUPPORTED"),
        ("SOLUSDT", "LONG", "RANGE", 14, 0.03, "SUPPORTED"),
        ("SOLUSDT", "SHORT", "UPTREND", 13, 0.02, "SUPPORTED"),
    ]
    if sparse_pool_mean is not None:
        first_sparse, second_sparse = sparse_counts
        remaining_supported = 20 - first_sparse - second_sparse
        cells = [
            ("BTCUSDT", "LONG", "RANGE", 20, 0.03, "SUPPORTED"),
            ("ETHUSDT", "SHORT", "UPTREND", 20, 0.03, "SUPPORTED"),
            ("SOLUSDT", "LONG", "UPTREND", 20, 0.03, "SUPPORTED"),
            ("BTCUSDT", "SHORT", "RANGE", first_sparse, sparse_pool_mean, "SPARSE"),
            ("ETHUSDT", "LONG", "RANGE", second_sparse, sparse_pool_mean, "SPARSE"),
            (
                "SOLUSDT",
                "SHORT",
                "UPTREND",
                remaining_supported,
                0.03,
                "SUPPORTED",
            ),
        ]
    total = sum(item[3] for item in cells)
    entries: list[dict[str, object]] = []
    for symbol, direction, regime, trades, mean_r, support in sorted(
        cells,
        key=lambda item: (item[0], ("LONG", "SHORT").index(item[1]), ("DOWNTREND", "RANGE", "UPTREND", "HIGH_VOLATILITY").index(item[2])),
    ):
        entries.append(
            {
                "symbol": symbol,
                "direction": direction,
                "regime": regime,
                "support": support,
                "trades": trades,
                "trade_fraction": trades / total,
                "realized_trade_mean_r": mean_r,
                "calibration_rows": trades,
                "log_loss": 0.60,
                "multiclass_brier": 0.30,
            }
        )
    sparse = [item for item in entries if item["support"] == "SPARSE"]
    supported = [item for item in entries if item["support"] == "SUPPORTED"]
    sparse_trades = sum(int(item["trades"]) for item in sparse)
    sparse_pool = None
    if sparse:
        leave_one_cell_out: list[dict[str, object]] = []
        for omitted in sparse:
            residual = [item for item in sparse if item is not omitted]
            residual_trades = sum(int(item["trades"]) for item in residual)
            residual_mean = (
                sum(
                    float(item["realized_trade_mean_r"]) * int(item["trades"])
                    for item in residual
                )
                / residual_trades
                if residual_trades
                else None
            )
            leave_one_cell_out.append(
                {
                    "omitted_symbol": omitted["symbol"],
                    "omitted_direction": omitted["direction"],
                    "omitted_regime": omitted["regime"],
                    "omitted_trades": omitted["trades"],
                    "residual_trades": residual_trades,
                    "residual_trade_fraction_of_sparse_pool": residual_trades / sparse_trades,
                    "residual_realized_trade_mean_r": residual_mean,
                    "calibration_rows": residual_trades,
                    "log_loss": 0.60 if residual_trades else None,
                    "multiclass_brier": 0.30 if residual_trades else None,
                }
            )
        nonempty = [
            item for item in leave_one_cell_out if int(item["residual_trades"]) > 0
        ]
        sparse_pool = {
            "cell_count": len(sparse),
            "trades": sparse_trades,
            "trade_fraction": sparse_trades / total,
            "realized_trade_mean_r": sum(float(item["realized_trade_mean_r"]) * int(item["trades"]) for item in sparse) / sparse_trades,
            "calibration_rows": sparse_trades,
            "log_loss": 0.60,
            "multiclass_brier": 0.30,
            "jackknife_schema": SPARSE_JACKKNIFE_SCHEMA,
            "minimum_residual_trades": 5,
            "leave_one_cell_out_count": len(leave_one_cell_out),
            "minimum_leave_one_cell_out_residual_trades": min(
                int(item["residual_trades"]) for item in leave_one_cell_out
            ),
            "worst_leave_one_cell_out_mean_r": (
                min(float(item["residual_realized_trade_mean_r"]) for item in nonempty)
                if nonempty
                else None
            ),
            "worst_leave_one_cell_out_log_loss": 0.60 if nonempty else None,
            "worst_leave_one_cell_out_multiclass_brier": 0.30 if nonempty else None,
            "leave_one_cell_out": leave_one_cell_out,
        }
    buckets = [*supported, *([sparse_pool] if sparse_pool else [])]
    return {
        "schema": INTERACTION_SCHEMA,
        "minimum_trades_per_supported_cell": 5,
        "trade_count": total,
        "observed_cell_count": len(entries),
        "supported_cell_count": len(supported),
        "sparse_cell_count": len(sparse),
        "supported_trade_count": sum(int(item["trades"]) for item in supported),
        "sparse_trade_count": sparse_trades,
        "tested_bucket_count": len(buckets),
        "worst_tested_bucket_mean_r": min(float(item["realized_trade_mean_r"]) for item in buckets),
        "worst_tested_bucket_log_loss": max(float(item["log_loss"]) for item in buckets),
        "worst_tested_bucket_multiclass_brier": max(float(item["multiclass_brier"]) for item in buckets),
        "cells": entries,
        "sparse_pool": sparse_pool,
    }


def test_aggregate_symbol_direction_and_regime_means_can_mask_bad_interaction_cell() -> None:
    _, trades, _ = _masking_frames()
    assert float(trades["realized_r"].mean()) == pytest.approx(0.70)
    assert trades.groupby("symbol")["realized_r"].mean().min() == pytest.approx(0.40)
    assert trades.groupby("direction")["realized_r"].mean().min() == pytest.approx(0.40)
    regime = ["UPTREND"] * 10 + ["RANGE"] * 10 + ["UPTREND"] * 10 + ["RANGE"] * 10
    assert trades.assign(regime=regime).groupby("regime")["realized_r"].mean().min() == pytest.approx(0.40)
    bad_cell = trades[(trades["symbol"] == "BTCUSDT") & (trades["direction"] == "LONG")].iloc[:10]
    assert float(bad_cell["realized_r"].mean()) == pytest.approx(-0.20)


def test_interaction_evidence_exposes_bad_supported_cell() -> None:
    builder = getattr(training, "_policy_interaction_robustness", None)
    assert callable(builder), "policy interaction robustness calculation is missing"
    selected, trades, opportunity_times = _masking_frames()
    evidence = builder(
        selected=selected,
        trades=trades,
        opportunity_times=opportunity_times,
        development_high_volatility_atr_pct_threshold=0.03,
    )
    cells = {(item["symbol"], item["direction"], item["regime"]): item for item in evidence["cells"]}
    assert cells[("BTCUSDT", "LONG", "UPTREND")]["realized_trade_mean_r"] == pytest.approx(-0.20)
    assert evidence["worst_tested_bucket_mean_r"] == pytest.approx(-0.20)


def test_quality_gate_rejects_negative_supported_interaction_cell(tmp_path) -> None:
    metrics = _metrics()
    metrics["policy_interaction_robustness"] = _interaction_evidence()
    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())
    assert result["passed"] is False
    assert "policy_interaction_cell_realized_mean_r_not_above_minimum" in result["reasons"]


def test_quality_gate_rejects_negative_sparse_interaction_pool(tmp_path) -> None:
    metrics = _metrics()
    metrics["policy_interaction_robustness"] = _interaction_evidence(sparse_pool_mean=-0.02)
    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())
    assert result["passed"] is False
    assert "policy_interaction_sparse_pool_realized_mean_r_not_above_minimum" in result["reasons"]



def test_quality_gate_rejects_under_supported_sparse_interaction_pool(tmp_path) -> None:
    metrics = _metrics()
    metrics["policy_interaction_robustness"] = _interaction_evidence(
        sparse_pool_mean=0.02,
        sparse_counts=(2, 2),
    )
    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())
    assert result["passed"] is False
    assert "policy_interaction_sparse_pool_trade_count_below_minimum" in result["reasons"]


def test_quality_gate_rejects_interaction_symbol_set_mismatch(tmp_path) -> None:
    metrics = _metrics()
    evidence = _interaction_evidence()
    for cell in evidence["cells"]:
        if cell["symbol"] == "BTCUSDT":
            cell["symbol"] = "ADAUSDT"
    direction_order = {"LONG": 0, "SHORT": 1}
    regime_order = {
        "DOWNTREND": 0,
        "RANGE": 1,
        "UPTREND": 2,
        "HIGH_VOLATILITY": 3,
    }
    evidence["cells"].sort(
        key=lambda item: (
            item["symbol"],
            direction_order[item["direction"]],
            regime_order[item["regime"]],
        )
    )
    metrics["policy_interaction_robustness"] = evidence
    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())
    assert result["passed"] is False
    assert "policy_interaction_symbol_set_mismatch" in result["reasons"]

def test_quality_gate_rejects_missing_interaction_evidence(tmp_path) -> None:
    metrics = _metrics()
    metrics.pop("policy_interaction_robustness", None)
    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())
    assert result["passed"] is False
    assert "invalid_policy_interaction_robustness" in result["reasons"]


def test_runtime_rejects_artifact_without_interaction_evidence(tmp_path) -> None:
    artifact = tmp_path / "missing-interaction-evidence.joblib"
    _write_artifact(artifact, version="missing-interaction-evidence")
    bundle = joblib.load(artifact)
    metrics = dict(bundle["metrics"])
    metrics.pop("policy_interaction_robustness", None)
    bundle["metrics"] = metrics
    joblib.dump(bundle, artifact)
    runtime = ModelRuntime(artifact, allow_baseline=False)
    with pytest.raises(ValueError, match="interaction robustness"):
        runtime.load(expected_version="missing-interaction-evidence")


def test_runtime_rejects_malformed_interaction_evidence(tmp_path) -> None:
    artifact = tmp_path / "malformed-interaction-evidence.joblib"
    _write_artifact(artifact, version="malformed-interaction-evidence")
    bundle = joblib.load(artifact)
    metrics = dict(bundle["metrics"])
    evidence = _interaction_evidence()
    evidence["cells"][0]["trade_fraction"] = 0.99
    metrics["policy_interaction_robustness"] = evidence
    bundle["metrics"] = metrics
    joblib.dump(bundle, artifact)
    runtime = ModelRuntime(artifact, allow_baseline=False)
    with pytest.raises(ValueError, match="interaction robustness"):
        runtime.load(expected_version="malformed-interaction-evidence")

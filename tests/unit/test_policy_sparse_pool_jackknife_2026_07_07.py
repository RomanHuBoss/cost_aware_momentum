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

INTERACTION_SCHEMA_V2 = "symbol-direction-regime-supported-cells-sparse-pool-jackknife-v2"
SPARSE_JACKKNIFE_SCHEMA = "leave-one-sparse-interaction-cell-out-v1"
POLICY_SCHEMA_V25 = (
    "decision-close-zone-directional-spread-entry-funding-mark-mtm-liquidation-cohort-v25"
)


def _settings() -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@localhost/db")


def _masking_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DatetimeIndex]:
    start = datetime(2026, 2, 1, tzinfo=UTC)
    definitions = (
        ("BTCUSDT", "LONG", "UPTREND", 4, 1.00),
        ("ETHUSDT", "SHORT", "RANGE", 3, -0.20),
        ("SOLUSDT", "LONG", "RANGE", 3, -0.20),
    )
    selected_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    times: list[datetime] = []
    index = 0
    for symbol, direction, regime, count, realized_r in definitions:
        for _ in range(count):
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


def _cell(
    symbol: str,
    direction: str,
    regime: str,
    trades: int,
    mean_r: float,
    support: str,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "direction": direction,
        "regime": regime,
        "support": support,
        "trades": trades,
        "trade_fraction": trades / 80,
        "realized_trade_mean_r": mean_r,
        "calibration_rows": trades,
        "log_loss": 0.60,
        "multiclass_brier": 0.30,
    }


def _evidence(*, weak_residual: bool = True, under_supported: bool = False) -> dict[str, object]:
    supported = [
        _cell("BTCUSDT", "LONG", "RANGE", 20, 0.03, "SUPPORTED"),
        _cell("ETHUSDT", "SHORT", "UPTREND", 20, 0.03, "SUPPORTED"),
        _cell("SOLUSDT", "LONG", "UPTREND", 20, 0.03, "SUPPORTED"),
    ]
    if under_supported:
        supported.append(_cell("SOLUSDT", "SHORT", "RANGE", 12, 0.03, "SUPPORTED"))
        sparse = [
            _cell("BTCUSDT", "SHORT", "RANGE", 4, 0.40, "SPARSE"),
            _cell("ETHUSDT", "LONG", "RANGE", 4, 0.40, "SPARSE"),
        ]
    else:
        supported.append(_cell("SOLUSDT", "SHORT", "RANGE", 10, 0.03, "SUPPORTED"))
        if weak_residual:
            sparse = [
                _cell("BTCUSDT", "SHORT", "RANGE", 4, 1.00, "SPARSE"),
                _cell("ETHUSDT", "LONG", "RANGE", 3, -0.20, "SPARSE"),
                _cell("SOLUSDT", "SHORT", "UPTREND", 3, -0.20, "SPARSE"),
            ]
        else:
            sparse = [
                _cell("BTCUSDT", "SHORT", "RANGE", 4, 0.30, "SPARSE"),
                _cell("ETHUSDT", "LONG", "RANGE", 3, 0.20, "SPARSE"),
                _cell("SOLUSDT", "SHORT", "UPTREND", 3, 0.10, "SPARSE"),
            ]
    direction_order = {"LONG": 0, "SHORT": 1}
    regime_order = {"DOWNTREND": 0, "RANGE": 1, "UPTREND": 2, "HIGH_VOLATILITY": 3}
    cells = sorted(
        [*supported, *sparse],
        key=lambda item: (
            str(item["symbol"]),
            direction_order[str(item["direction"])],
            regime_order[str(item["regime"])],
        ),
    )
    sparse_trades = sum(int(item["trades"]) for item in sparse)
    sparse_mean = sum(
        float(item["realized_trade_mean_r"]) * int(item["trades"]) for item in sparse
    ) / sparse_trades
    leave_one: list[dict[str, object]] = []
    for omitted in sorted(
        sparse,
        key=lambda item: (
            str(item["symbol"]),
            direction_order[str(item["direction"])],
            regime_order[str(item["regime"])],
        ),
    ):
        residual = [item for item in sparse if item is not omitted]
        residual_trades = sum(int(item["trades"]) for item in residual)
        residual_mean = (
            sum(float(item["realized_trade_mean_r"]) * int(item["trades"]) for item in residual)
            / residual_trades
            if residual_trades
            else None
        )
        leave_one.append(
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
    nonempty = [item for item in leave_one if int(item["residual_trades"]) > 0]
    sparse_pool = {
        "cell_count": len(sparse),
        "trades": sparse_trades,
        "trade_fraction": sparse_trades / 80,
        "realized_trade_mean_r": sparse_mean,
        "calibration_rows": sparse_trades,
        "log_loss": 0.60,
        "multiclass_brier": 0.30,
        "jackknife_schema": SPARSE_JACKKNIFE_SCHEMA,
        "minimum_residual_trades": 5,
        "leave_one_cell_out_count": len(leave_one),
        "minimum_leave_one_cell_out_residual_trades": min(
            int(item["residual_trades"]) for item in leave_one
        ),
        "worst_leave_one_cell_out_mean_r": min(
            float(item["residual_realized_trade_mean_r"]) for item in nonempty
        ),
        "worst_leave_one_cell_out_log_loss": max(float(item["log_loss"]) for item in nonempty),
        "worst_leave_one_cell_out_multiclass_brier": max(
            float(item["multiclass_brier"]) for item in nonempty
        ),
        "leave_one_cell_out": leave_one,
    }
    buckets = [*supported, sparse_pool]
    return {
        "schema": INTERACTION_SCHEMA_V2,
        "minimum_trades_per_supported_cell": 5,
        "trade_count": 80,
        "observed_cell_count": len(cells),
        "supported_cell_count": len(supported),
        "sparse_cell_count": len(sparse),
        "supported_trade_count": sum(int(item["trades"]) for item in supported),
        "sparse_trade_count": sparse_trades,
        "tested_bucket_count": len(buckets),
        "worst_tested_bucket_mean_r": min(float(item["realized_trade_mean_r"]) for item in buckets),
        "worst_tested_bucket_log_loss": 0.60,
        "worst_tested_bucket_multiclass_brier": 0.30,
        "cells": cells,
        "sparse_pool": sparse_pool,
    }


def _metrics_with(evidence: dict[str, object]) -> dict[str, object]:
    metrics = _metrics()
    metrics["policy_metric_schema"] = POLICY_SCHEMA_V25
    metrics["policy_interaction_robustness"] = evidence
    return metrics


def test_positive_sparse_pool_can_depend_on_one_profitable_cell() -> None:
    evidence = _evidence(weak_residual=True)
    pool = evidence["sparse_pool"]
    assert isinstance(pool, dict)
    assert float(pool["realized_trade_mean_r"]) == pytest.approx(0.28)
    leave_one = pool["leave_one_cell_out"]
    btc_omission = next(item for item in leave_one if item["omitted_symbol"] == "BTCUSDT")
    assert int(btc_omission["residual_trades"]) == 6
    assert float(btc_omission["residual_realized_trade_mean_r"]) == pytest.approx(-0.20)


def test_builder_exposes_sparse_pool_leave_one_cell_out() -> None:
    builder = getattr(training, "_policy_interaction_robustness", None)
    assert callable(builder)
    selected, trades, opportunities = _masking_frames()
    evidence = builder(
        selected=selected,
        trades=trades,
        opportunity_times=opportunities,
        development_high_volatility_atr_pct_threshold=0.03,
    )
    pool = evidence["sparse_pool"]
    assert pool["jackknife_schema"] == SPARSE_JACKKNIFE_SCHEMA
    assert pool["minimum_leave_one_cell_out_residual_trades"] == 6
    assert pool["worst_leave_one_cell_out_mean_r"] == pytest.approx(-0.20)


def test_quality_gate_rejects_sparse_pool_dependent_on_one_cell(tmp_path) -> None:
    result = evaluate_quality_gate(
        _candidate(tmp_path, metrics=_metrics_with(_evidence(weak_residual=True))),
        _settings(),
    )
    assert result["passed"] is False
    assert (
        "policy_interaction_sparse_leave_one_cell_out_realized_mean_r_not_above_minimum"
        in result["reasons"]
    )


def test_quality_gate_rejects_under_supported_sparse_jackknife_residual(tmp_path) -> None:
    result = evaluate_quality_gate(
        _candidate(tmp_path, metrics=_metrics_with(_evidence(under_supported=True))),
        _settings(),
    )
    assert result["passed"] is False
    assert (
        "policy_interaction_sparse_leave_one_cell_out_trade_count_below_minimum"
        in result["reasons"]
    )


def test_validator_requires_sparse_jackknife_evidence() -> None:
    evidence = _evidence(weak_residual=False)
    pool = evidence["sparse_pool"]
    assert isinstance(pool, dict)
    pool.pop("leave_one_cell_out")
    with pytest.raises(ValueError, match="sparse leave-one-cell-out"):
        training.validate_policy_interaction_robustness(evidence, policy_trades=80)


def test_quality_gate_accepts_robust_sparse_jackknife(tmp_path) -> None:
    result = evaluate_quality_gate(
        _candidate(tmp_path, metrics=_metrics_with(_evidence(weak_residual=False))),
        _settings(),
    )
    assert result["passed"] is True
    assert result["reasons"] == []


def test_runtime_rejects_artifact_missing_sparse_jackknife(tmp_path) -> None:
    artifact = tmp_path / "missing-sparse-jackknife.joblib"
    _write_artifact(artifact, version="missing-sparse-jackknife")
    bundle = joblib.load(artifact)
    metrics = dict(bundle["metrics"])
    interaction = _evidence(weak_residual=False)
    sparse_pool = dict(interaction["sparse_pool"])
    sparse_pool.pop("leave_one_cell_out", None)
    interaction["sparse_pool"] = sparse_pool
    metrics["policy_interaction_robustness"] = interaction
    bundle["metrics"] = metrics
    joblib.dump(bundle, artifact)
    runtime = ModelRuntime(artifact, allow_baseline=False)
    with pytest.raises(ValueError, match="interaction robustness"):
        runtime.load(expected_version="missing-sparse-jackknife")

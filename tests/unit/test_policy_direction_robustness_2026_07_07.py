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

DIRECTION_SCHEMA = "actionable-policy-direction-opportunity-cohort-v1"


def _settings() -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@localhost/db")


def _direction_evidence(
    *,
    policy_trades: int = 80,
    policy_cohorts: int = 80,
    short_mean_r: float = 0.02,
    short_trades: int | None = None,
) -> dict[str, object]:
    resolved_short_trades = policy_trades // 2 if short_trades is None else short_trades
    long_trades = policy_trades - resolved_short_trades
    directions: list[dict[str, object]] = []
    for direction, trades, mean_r, log_loss, brier in (
        ("LONG", long_trades, 0.03, 0.55, 0.28),
        ("SHORT", resolved_short_trades, short_mean_r, 0.60, 0.30),
    ):
        trade_cohorts = min(trades, policy_cohorts)
        directions.append(
            {
                "direction": direction,
                "opportunities": policy_cohorts,
                "trade_cohorts": trade_cohorts,
                "no_trade_cohorts": policy_cohorts - trade_cohorts,
                "trades": trades,
                "trade_fraction": trades / policy_trades if policy_trades else 0.0,
                "realized_mean_r": mean_r if trades else 0.0,
                "calibration_rows": trades,
                "log_loss": log_loss if trades else None,
                "multiclass_brier": brier if trades else None,
            }
        )
    traded = [item for item in directions if int(item["trades"]) > 0]
    return {
        "schema": DIRECTION_SCHEMA,
        "minimum_trades_per_traded_direction": 5,
        "opportunity_count": policy_cohorts,
        "trade_count": policy_trades,
        "direction_count": 2,
        "traded_direction_count": len(traded),
        "worst_traded_direction_mean_r": min(
            float(item["realized_mean_r"]) for item in traded
        ) if traded else None,
        "worst_traded_direction_log_loss": max(
            float(item["log_loss"]) for item in traded
        ) if traded else None,
        "worst_traded_direction_multiclass_brier": max(
            float(item["multiclass_brier"]) for item in traded
        ) if traded else None,
        "directions": directions,
    }


def _masking_frames() -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    times: list[datetime] = []
    for index in range(20):
        decision_time = start + timedelta(hours=index)
        times.append(decision_time)
        is_long = index < 10
        rows.append(
            {
                "symbol": "BTCUSDT",
                "decision_time": decision_time,
                "direction": "LONG" if is_long else "SHORT",
                "realized_r": 1.0 if is_long else -0.20,
                "target": "TP" if is_long else "TIMEOUT",
                "p_tp": 0.80 if is_long else 0.10,
                "p_sl": 0.10,
                "p_timeout": 0.10 if is_long else 0.80,
            }
        )
    return pd.DataFrame.from_records(rows), pd.DatetimeIndex(times)


def test_aggregate_profit_can_mask_negative_traded_direction() -> None:
    trades, _ = _masking_frames()
    aggregate = float(trades["realized_r"].mean())
    short_mean = float(trades[trades["direction"].eq("SHORT")]["realized_r"].mean())

    assert aggregate == pytest.approx(0.40)
    assert short_mean == pytest.approx(-0.20)


def test_direction_evidence_exposes_negative_short_policy() -> None:
    builder = getattr(training, "_policy_direction_robustness", None)
    assert callable(builder), "policy direction robustness calculation is missing"
    trades, opportunity_times = _masking_frames()

    evidence = builder(trades=trades, opportunity_times=opportunity_times)

    assert evidence["schema"] == DIRECTION_SCHEMA
    by_direction = {item["direction"]: item for item in evidence["directions"]}
    assert by_direction["LONG"]["realized_mean_r"] == pytest.approx(0.50)
    assert by_direction["SHORT"]["realized_mean_r"] == pytest.approx(-0.10)
    assert evidence["worst_traded_direction_mean_r"] == pytest.approx(-0.10)


def test_quality_gate_rejects_negative_traded_direction(tmp_path) -> None:
    metrics = _metrics()
    metrics["policy_direction_robustness"] = _direction_evidence(
        policy_trades=int(metrics["policy_trades"]),
        policy_cohorts=int(metrics["policy_cohorts"]),
        short_mean_r=-0.01,
    )

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is False
    assert "policy_direction_realized_mean_r_not_above_minimum" in result["reasons"]


def test_quality_gate_rejects_under_supported_traded_direction(tmp_path) -> None:
    metrics = _metrics()
    metrics["policy_direction_robustness"] = _direction_evidence(
        policy_trades=int(metrics["policy_trades"]),
        policy_cohorts=int(metrics["policy_cohorts"]),
        short_trades=4,
    )

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is False
    assert "policy_direction_trade_count_below_minimum" in result["reasons"]


def test_quality_gate_rejects_missing_direction_evidence(tmp_path) -> None:
    metrics = _metrics()
    metrics.pop("policy_direction_robustness", None)
    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is False
    assert "invalid_policy_direction_robustness" in result["reasons"]


def test_runtime_rejects_artifact_without_direction_evidence(tmp_path) -> None:
    artifact = tmp_path / "missing-direction-evidence.joblib"
    _write_artifact(artifact, version="missing-direction-evidence")
    bundle = joblib.load(artifact)
    metrics = dict(bundle["metrics"])
    metrics.pop("policy_direction_robustness", None)
    bundle["metrics"] = metrics
    joblib.dump(bundle, artifact)

    runtime = ModelRuntime(artifact, allow_baseline=False)
    with pytest.raises(ValueError, match="direction robustness"):
        runtime.load(expected_version="missing-direction-evidence")


def test_runtime_rejects_malformed_direction_evidence(tmp_path) -> None:
    artifact = tmp_path / "malformed-direction-evidence.joblib"
    _write_artifact(artifact, version="malformed-direction-evidence")
    bundle = joblib.load(artifact)
    metrics = dict(bundle["metrics"])
    evidence = _direction_evidence(
        policy_trades=int(metrics["policy_trades"]),
        policy_cohorts=int(metrics.get("policy_cohorts", metrics["policy_trades"])),
    )
    evidence["directions"][0]["trade_fraction"] = 0.99
    metrics["policy_direction_robustness"] = evidence
    bundle["metrics"] = metrics
    joblib.dump(bundle, artifact)

    runtime = ModelRuntime(artifact, allow_baseline=False)
    with pytest.raises(ValueError, match="direction robustness"):
        runtime.load(expected_version="malformed-direction-evidence")

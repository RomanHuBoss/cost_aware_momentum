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

REGIME_SCHEMA = "decision-time-development-quantile-market-regimes-v1"


def _settings() -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@localhost/db")


def _regime_evidence(
    *,
    policy_trades: int = 80,
    policy_cohorts: int = 80,
    range_mean_r: float = 0.02,
    range_trades: int | None = None,
) -> dict[str, object]:
    first_trades = policy_trades // 2 if range_trades is None else range_trades
    second_trades = policy_trades - first_trades
    first_opportunities = policy_cohorts // 2
    second_opportunities = policy_cohorts - first_opportunities
    regimes = [
        {
            "regime": "RANGE",
            "opportunities": first_opportunities,
            "trade_cohorts": min(first_trades, first_opportunities),
            "no_trade_cohorts": max(first_opportunities - first_trades, 0),
            "trades": first_trades,
            "trade_fraction": first_trades / policy_trades,
            "realized_mean_r": range_mean_r,
            "calibration_rows": first_trades,
            "log_loss": 0.60,
            "multiclass_brier": 0.30,
        },
        {
            "regime": "UPTREND",
            "opportunities": second_opportunities,
            "trade_cohorts": min(second_trades, second_opportunities),
            "no_trade_cohorts": max(second_opportunities - second_trades, 0),
            "trades": second_trades,
            "trade_fraction": second_trades / policy_trades,
            "realized_mean_r": 0.03,
            "calibration_rows": second_trades,
            "log_loss": 0.55,
            "multiclass_brier": 0.28,
        },
    ]
    return {
        "schema": REGIME_SCHEMA,
        "volatility_quantile": 0.75,
        "development_high_volatility_atr_pct_threshold": 0.03,
        "trend_score_threshold": 1.0,
        "minimum_trades_per_traded_regime": 5,
        "opportunity_count": policy_cohorts,
        "trade_count": policy_trades,
        "regime_count": len(regimes),
        "traded_regime_count": len(regimes),
        "worst_traded_regime_mean_r": min(float(item["realized_mean_r"]) for item in regimes),
        "worst_traded_regime_log_loss": max(float(item["log_loss"]) for item in regimes),
        "worst_traded_regime_multiclass_brier": max(
            float(item["multiclass_brier"]) for item in regimes
        ),
        "regimes": regimes,
    }


def _masking_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DatetimeIndex]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    selected_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    times: list[datetime] = []
    for index in range(20):
        decision_time = start + timedelta(hours=index)
        times.append(decision_time)
        uptrend = index < 10
        selected_rows.append(
            {
                "decision_time": decision_time,
                "regime_ret_24h": 0.02 if uptrend else 0.001,
                "regime_atr_pct_14": 0.01,
            }
        )
        trade_rows.append(
            {
                "symbol": "BTCUSDT",
                "decision_time": decision_time,
                "realized_r": 1.0 if uptrend else -0.20,
                "target": "TP" if uptrend else "TIMEOUT",
                "p_tp": 0.80 if uptrend else 0.10,
                "p_sl": 0.10,
                "p_timeout": 0.10 if uptrend else 0.80,
            }
        )
    return (
        pd.DataFrame.from_records(selected_rows),
        pd.DataFrame.from_records(trade_rows),
        pd.DatetimeIndex(times),
    )


def test_aggregate_profit_can_mask_negative_traded_regime() -> None:
    _, trades, _ = _masking_frames()
    aggregate = float(trades["realized_r"].mean())
    range_mean = float(trades.iloc[10:]["realized_r"].mean())

    assert aggregate == pytest.approx(0.40)
    assert range_mean == pytest.approx(-0.20)


def test_regime_evidence_exposes_negative_traded_regime() -> None:
    builder = getattr(training, "_policy_regime_robustness", None)
    assert callable(builder), "market-regime robustness calculation is missing"
    selected, trades, opportunity_times = _masking_frames()

    evidence = builder(
        selected=selected,
        trades=trades,
        opportunity_times=opportunity_times,
        development_high_volatility_atr_pct_threshold=0.03,
    )

    assert evidence["schema"] == REGIME_SCHEMA
    assert evidence["traded_regime_count"] == 2
    by_regime = {item["regime"]: item for item in evidence["regimes"]}
    assert by_regime["UPTREND"]["realized_mean_r"] == pytest.approx(1.0)
    assert by_regime["RANGE"]["realized_mean_r"] == pytest.approx(-0.20)
    assert evidence["worst_traded_regime_mean_r"] == pytest.approx(-0.20)


def test_quality_gate_rejects_negative_traded_regime(tmp_path) -> None:
    metrics = _metrics()
    metrics["policy_regime_robustness"] = _regime_evidence(
        policy_trades=int(metrics["policy_trades"]),
        policy_cohorts=int(metrics["policy_cohorts"]),
        range_mean_r=-0.01,
    )

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is False
    assert "policy_regime_realized_mean_r_not_above_minimum" in result["reasons"]


def test_quality_gate_rejects_under_supported_traded_regime(tmp_path) -> None:
    metrics = _metrics()
    metrics["policy_regime_robustness"] = _regime_evidence(
        policy_trades=int(metrics["policy_trades"]),
        policy_cohorts=int(metrics["policy_cohorts"]),
        range_trades=4,
    )

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is False
    assert "policy_regime_trade_count_below_minimum" in result["reasons"]


def test_quality_gate_rejects_missing_regime_evidence(tmp_path) -> None:
    metrics = _metrics()
    metrics.pop("policy_regime_robustness", None)

    result = evaluate_quality_gate(_candidate(tmp_path, metrics=metrics), _settings())

    assert result["passed"] is False
    assert "invalid_policy_regime_robustness" in result["reasons"]


def test_runtime_rejects_artifact_without_regime_evidence(tmp_path) -> None:
    artifact = tmp_path / "missing-regime-evidence.joblib"
    _write_artifact(artifact, version="missing-regime-evidence")
    bundle = joblib.load(artifact)
    metrics = dict(bundle["metrics"])
    metrics.pop("policy_regime_robustness", None)
    bundle["metrics"] = metrics
    joblib.dump(bundle, artifact)

    runtime = ModelRuntime(artifact, allow_baseline=False)
    with pytest.raises(ValueError, match="regime robustness"):
        runtime.load(expected_version="missing-regime-evidence")


def test_runtime_rejects_malformed_regime_evidence(tmp_path) -> None:
    artifact = tmp_path / "malformed-regime-evidence.joblib"
    _write_artifact(artifact, version="malformed-regime-evidence")
    bundle = joblib.load(artifact)
    metrics = dict(bundle["metrics"])
    evidence = _regime_evidence(
        policy_trades=int(metrics["policy_trades"]),
        policy_cohorts=int(metrics.get("policy_cohorts", metrics["policy_trades"])),
    )
    evidence["regimes"][0]["trade_fraction"] = 0.99
    metrics["policy_regime_robustness"] = evidence
    bundle["metrics"] = metrics
    joblib.dump(bundle, artifact)

    runtime = ModelRuntime(artifact, allow_baseline=False)
    with pytest.raises(ValueError, match="regime robustness"):
        runtime.load(expected_version="malformed-regime-evidence")

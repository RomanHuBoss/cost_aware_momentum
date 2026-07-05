from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.ml.data_profile import profile_from_symbol_rows
from app.ml.lifecycle import ModelCandidate, evaluate_quality_gate
from tests.drift_reference import valid_production_drift_reference


def _candidate(tmp_path: Path, *, lower_bound: float) -> ModelCandidate:
    now = datetime(2026, 7, 4, tzinfo=UTC)
    profile = profile_from_symbol_rows(
        [("BTCUSDT", 10_000, now, now)],
        unique_timestamps=2_000,
        minimum_rows_for_coverage=300,
    )
    metrics = {
        "rows": 1_000,
        "holdout_span_hours": 336.0,
        "log_loss": 0.90,
        "class_prior_log_loss": 1.05,
        "log_loss_skill_vs_prior": 0.15,
        "multiclass_brier": 0.55,
        "ece_tp": 0.05,
        "ece_sl": 0.06,
        "ece_timeout": 0.07,
        "class_distribution": {"TP": 0.35, "SL": 0.40, "TIMEOUT": 0.25},
        "production_drift_reference": valid_production_drift_reference(),
        "market_context": {
            "schema": "hourly-oi-basis-settled-funding-turnover-v1",
            "availability_schema": "exchange-event-close-live-receipt-v1",
            "historical_receipt_time_reconstructed": False,
            "complete_rows": 300,
            "incomplete_rows": 0,
        },
        "market_context_ablation": {
            "schema": "same-split-zeroed-context-v1",
            "core_log_loss": 0.91,
            "enriched_log_loss": 0.90,
            "log_loss_benefit": 0.01,
            "noninferiority_tolerance": 0.005,
        },
        "walk_forward_market_context_noninferior_folds": 3,
        "entry_execution_model": {
            "schema": "directional-half-spread-on-next-hour-open-v1",
            "entry_spread_bps": 18.0,
        },
        "historical_funding_schema": "bybit-settlement-timestamp-replay-v1",
        "historical_funding_timeline": {
            "schema": "bybit-settlement-timestamp-replay-v1",
            "symbols": 3,
            "settlements": 100,
            "start_time": "2024-01-01T00:00:00+00:00",
            "end_time": "2025-12-31T00:00:00+00:00",
        },
        "intrahorizon_margin_path": {
            "schema": "bybit-mark-price-hourly-isolated-margin-proxy-v1",
            "required": True,
            "status": "complete",
            "mark_price_source": "bybit_hourly_mark_price_ohlc",
            "research_leverage": 3,
            "equity_reserve_fraction": 0.10,
            "same_bar_ordering": "liquidation_before_unordered_last_price_exit",
            "liquidation_loss": "full_initial_margin",
        },
        "walk_forward_schema": "expanding-train-rolling-calibration-purged-v1",
        "walk_forward_folds_requested": 3,
        "walk_forward_folds_completed": 3,
        "walk_forward_fold_results": [
            {
                "fold": 1,
                "test_rows": 120,
                "test_start_time": "2025-01-01T00:00:00+00:00",
                "test_end_time": "2025-01-07T23:00:00+00:00",
                "log_loss": 0.90,
                "class_prior_log_loss": 1.05,
                "log_loss_skill_vs_prior": 0.15,
                "multiclass_brier": 0.55,
                "policy_realized_mean_r": 0.03,
            },
            {
                "fold": 2,
                "test_rows": 120,
                "test_start_time": "2025-01-08T00:00:00+00:00",
                "test_end_time": "2025-01-14T23:00:00+00:00",
                "log_loss": 0.92,
                "class_prior_log_loss": 1.06,
                "log_loss_skill_vs_prior": 0.14,
                "multiclass_brier": 0.57,
                "policy_realized_mean_r": 0.02,
            },
            {
                "fold": 3,
                "test_rows": 120,
                "test_start_time": "2025-01-15T00:00:00+00:00",
                "test_end_time": "2025-01-21T23:00:00+00:00",
                "log_loss": 0.94,
                "class_prior_log_loss": 1.07,
                "log_loss_skill_vs_prior": 0.13,
                "multiclass_brier": 0.59,
                "policy_realized_mean_r": 0.01,
            },
        ],
        "policy_metric_schema": "decision-open-directional-spread-entry-funding-mark-mtm-liquidation-cohort-v15",
        "policy_funding_timeline_complete": True,
        "policy_expected_funding_source": "none-no-point-in-time-forecast",
        "policy_realized_funding_source": "bybit-settlement-timestamp-replay-v1",
        "policy_intrahorizon_margin_schema": "bybit-mark-price-hourly-isolated-margin-proxy-v1",
        "policy_intrahorizon_margin_complete": True,
        "policy_research_leverage": 3,
        "policy_liquidation_equity_reserve_fraction": 0.10,
        "policy_liquidation_events": 4,
        "policy_liquidation_rate": 0.05,
        "policy_horizon_hours": 8,
        "policy_capital_sleeves": 8,
        "policy_horizon_phase_count": 8,
        "policy_horizon_phase_expected": 8,
        "policy_candidates": 1_000,
        "policy_trades": 80,
        "policy_trade_rate": 0.08,
        "policy_cohorts": 80,
        "policy_independent_cohorts": 40,
        "policy_realized_mean_r": 0.05,
        "policy_independent_mean_r": 0.04,
        "policy_mean_r_lcb": lower_bound,
        "policy_mean_r_confidence_level": 0.95,
        "policy_mean_r_bootstrap_samples": 2_000,
        "policy_mean_r_bootstrap_block_length": 6,
        "policy_mean_r_uncertainty_schema": "all-horizon-phases-circular-moving-block-v2",
        "policy_profit_factor": 1.2,
        "policy_gross_gain_r": 12.0,
        "policy_gross_loss_r": 10.0,
        "policy_profit_factor_unbounded": False,
        "policy_max_drawdown_r": 5.0,
    }
    return ModelCandidate(
        path=tmp_path / "candidate.joblib",
        version="candidate-uncertainty-v1",
        model_type="logistic",
        horizon=8,
        training_start=now,
        training_end=now,
        dataset_rows=10_000,
        unique_timestamps=2_000,
        symbol_count=1,
        symbol_sample=("BTCUSDT",),
        training_data_profile=profile,
        metrics=metrics,
        incumbent_metrics=None,
        incumbent_version=None,
    )


def test_quality_gate_rejects_positive_point_estimate_with_negative_lcb(tmp_path: Path) -> None:
    result = evaluate_quality_gate(
        _candidate(tmp_path, lower_bound=-0.02),
        Settings(database_url="postgresql+psycopg://u:p@localhost/db"),
    )

    assert result["passed"] is False
    assert "policy_mean_r_lcb_not_above_minimum" in result["reasons"]


def test_quality_gate_accepts_candidate_with_positive_lcb(tmp_path: Path) -> None:
    result = evaluate_quality_gate(
        _candidate(tmp_path, lower_bound=0.01),
        Settings(database_url="postgresql+psycopg://u:p@localhost/db"),
    )

    assert result["passed"] is True
    assert result["absolute"]["policy_mean_r_lcb"] == 0.01
    assert result["absolute"]["min_policy_mean_r_lcb"] == 0.0


def test_policy_uncertainty_configuration_fails_closed() -> None:
    invalid_cases = (
        {"auto_train_policy_bootstrap_samples": 99},
        {"auto_train_policy_confidence_level": 0.5},
        {"auto_train_policy_confidence_level": 1.0},
        {"auto_train_min_policy_mean_r_lcb": -0.01},
    )
    for overrides in invalid_cases:
        try:
            Settings(
                database_url="postgresql+psycopg://u:p@localhost/db",
                **overrides,
            )
        except ValueError as exc:
            assert "POLICY" in str(exc).upper() or "confidence" in str(exc).lower()
        else:
            raise AssertionError(f"invalid uncertainty settings accepted: {overrides!r}")


def test_policy_bootstrap_is_deterministic_and_conservative() -> None:
    import numpy as np

    from app.ml.training import _policy_mean_r_bootstrap

    returns = np.asarray([0.12, -0.08, 0.04, 0.01, -0.03, 0.09, 0.02, -0.01, 0.05])
    first = _policy_mean_r_bootstrap(returns, samples=2_000, confidence_level=0.95)
    second = _policy_mean_r_bootstrap(returns, samples=2_000, confidence_level=0.95)

    assert first == second
    mean_r, lower_bound, block_length = first
    assert mean_r == np.mean(returns)
    assert lower_bound <= mean_r
    assert block_length == 3


def test_policy_bootstrap_rejects_non_finite_or_too_short_series() -> None:
    import numpy as np
    import pytest

    from app.ml.training import _policy_mean_r_bootstrap

    with pytest.raises(ValueError, match="At least two finite"):
        _policy_mean_r_bootstrap(np.asarray([0.1]), samples=2_000, confidence_level=0.95)
    with pytest.raises(ValueError, match="At least two finite"):
        _policy_mean_r_bootstrap(np.asarray([0.1, np.nan]), samples=2_000, confidence_level=0.95)


def test_quality_gate_rejects_incomplete_horizon_phase_evidence(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path, lower_bound=0.01)
    candidate.metrics["policy_horizon_phase_count"] = 7

    result = evaluate_quality_gate(
        candidate,
        Settings(database_url="postgresql+psycopg://u:p@localhost/db"),
    )

    assert result["passed"] is False
    assert "incomplete_policy_horizon_phase_coverage" in result["reasons"]

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.ml.data_profile import profile_from_symbol_rows
from app.ml.lifecycle import ModelCandidate, evaluate_quality_gate
from tests.drift_reference import valid_production_drift_reference


def _candidate(
    tmp_path: Path,
    *,
    policy_candidates: int = 100_000,
    policy_trades: int = 80,
    policy_trade_rate: float = 0.0008,
) -> ModelCandidate:
    now = datetime.now(UTC)
    profile = profile_from_symbol_rows(
        [("BTCUSDT", 100_000, now, now)],
        unique_timestamps=100_000,
        minimum_rows_for_coverage=300,
    )
    metrics = {
        "rows": 100_000,
        "holdout_span_hours": 10_000.0,
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
            "schema": "hourly-oi-basis-settled-funding-turnover-v2",
                "funding_interval_schedule_schema": "instrument-spec-point-in-time-v1",
                "funding_interval_source": "instrument_spec_history_point_in_time",
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
        "historical_funding_schema": "bybit-settlement-timestamp-replay-v2",
        "historical_funding_timeline": {
            "schema": "bybit-settlement-timestamp-replay-v2",
                "funding_interval_schedule_schema": "instrument-spec-point-in-time-v1",
                "interval_source": "instrument_spec_history_point_in_time",
                "interval_history_symbols": 3,
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
        "policy_metric_schema": "decision-open-directional-spread-entry-funding-mark-mtm-liquidation-cohort-v17",
        "policy_funding_timeline_complete": True,
        "policy_expected_funding_source": "none-no-point-in-time-forecast",
        "policy_realized_funding_source": "bybit-settlement-timestamp-replay-v2",
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
        "policy_candidates": policy_candidates,
        "policy_trades": policy_trades,
        "policy_trade_rate": policy_trade_rate,
        "policy_cohorts": 80,
        "policy_trade_cohorts": 80,
        "policy_no_trade_cohorts": 0,
        "policy_independent_cohorts": 80,
        "policy_independent_mean_r": 0.04,
        "policy_mean_r_lcb": 0.01,
        "policy_mean_r_confidence_level": 0.95,
        "policy_mean_r_bootstrap_samples": 2_000,
        "policy_mean_r_bootstrap_block_length": 1,
        "policy_mean_r_uncertainty_schema": "observed-opportunity-zero-return-all-horizon-phases-circular-moving-block-v3",
        "policy_realized_mean_r": 0.05,
        "policy_profit_factor": 1.2,
        "policy_max_drawdown_r": 5.0,
    }
    return ModelCandidate(
        path=tmp_path / "candidate.joblib",
        version="candidate-sparse-v1",
        model_type="logistic",
        horizon=8,
        training_start=now,
        training_end=now,
        dataset_rows=100_000,
        unique_timestamps=100_000,
        symbol_count=1,
        symbol_sample=("BTCUSDT",),
        training_data_profile=profile,
        metrics=metrics,
        incumbent_metrics=None,
        incumbent_version=None,
    )


def test_quality_gate_rejects_statistically_sparse_policy(tmp_path: Path) -> None:
    result = evaluate_quality_gate(
        _candidate(tmp_path),
        Settings(database_url="postgresql+psycopg://u:p@localhost/db"),
    )

    assert result["passed"] is False
    assert "policy_trade_rate_below_minimum" in result["reasons"]


def test_quality_gate_accepts_policy_at_density_boundary(tmp_path: Path) -> None:
    result = evaluate_quality_gate(
        _candidate(
            tmp_path,
            policy_candidates=8_000,
            policy_trades=80,
            policy_trade_rate=0.01,
        ),
        Settings(database_url="postgresql+psycopg://u:p@localhost/db"),
    )

    assert result["passed"] is True
    assert result["absolute"]["policy_trade_rate"] == 0.01
    assert result["absolute"]["min_policy_trade_rate"] == 0.01


def test_quality_gate_rejects_inconsistent_policy_trade_rate(tmp_path: Path) -> None:
    result = evaluate_quality_gate(
        _candidate(
            tmp_path,
            policy_candidates=1_000,
            policy_trades=80,
            policy_trade_rate=0.5,
        ),
        Settings(database_url="postgresql+psycopg://u:p@localhost/db"),
    )

    assert result["passed"] is False
    assert "inconsistent_policy_trade_rate" in result["reasons"]


def test_policy_trade_rate_threshold_must_be_positive_and_bounded() -> None:
    for invalid in (0.0, -0.01, 1.01, float("nan")):
        try:
            Settings(
                database_url="postgresql+psycopg://u:p@localhost/db",
                auto_train_min_policy_trade_rate=invalid,
            )
        except ValueError as exc:
            assert "AUTO_TRAIN_MIN_POLICY_TRADE_RATE" in str(exc) or "finite" in str(exc)
        else:
            raise AssertionError(f"invalid threshold accepted: {invalid!r}")

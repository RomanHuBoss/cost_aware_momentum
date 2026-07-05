from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import joblib
import numpy as np
import pandas as pd
import pytest

import app.ml.lifecycle as lifecycle
import app.services.signals as signals
from app.config import Settings
from app.ml.data_profile import profile_from_symbol_rows
from app.ml.features import FEATURE_NAMES
from app.ml.lifecycle import IncumbentSnapshot, ModelCandidate, evaluate_quality_gate
from app.ml.runtime import ModelRuntime, Prediction
from app.ml.training import (
    LABEL_PATH_SCHEMA_VERSION,
    MODEL_FEATURE_NAMES,
    MODEL_FEATURE_SCHEMA_VERSION,
    OUTCOME_CLASSES,
    TEMPORAL_SPLIT_SCHEMA_VERSION,
    TIMEOUT_RETURN_SCHEMA_VERSION,
    WALK_FORWARD_SCHEMA_VERSION,
)
from tests.drift_reference import valid_production_drift_reference


class _ScalarsResult:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def scalars(self) -> _ScalarsResult:
        return self

    def all(self) -> list[object]:
        return self._values


class _ProfilesOnlySession:
    async def execute(self, _query) -> _ScalarsResult:
        return _ScalarsResult([])


@pytest.mark.asyncio
async def test_signal_policy_uses_the_exact_model_atr_without_hidden_clipping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_time = datetime.now(UTC)
    event_time = current_time.replace(minute=0, second=0, microsecond=0)
    frame = pd.DataFrame(
        [
            {
                "close_time": event_time,
            }
        ]
    )
    ticker = SimpleNamespace(
        source_time=current_time,
        bid_price=Decimal("99.9"),
        ask_price=Decimal("100.0"),
        last_price=Decimal("99.95"),
        funding_rate=Decimal("0"),
        next_funding_time=event_time + timedelta(hours=8),
    )
    spec = SimpleNamespace(
        funding_interval_minutes=480,
        tick_size=Decimal("0.1"),
    )
    feature_values = {name: 0.0 for name in FEATURE_NAMES}
    feature_values["atr_pct_14"] = 0.001
    captured: dict[str, Decimal] = {}

    async def no_expire(_session) -> int:
        return 0

    async def latest_ticker(_session, _symbol):
        return ticker

    async def latest_spec(_session, _symbol, *, available_cutoff):
        del available_cutoff
        return spec

    async def candles_frame(_session, _symbol, **_kwargs):
        return frame

    def capture_scenario(_predictions, **kwargs):
        captured["atr_pct"] = kwargs["atr_pct"]
        raise ValueError("stop after ATR capture")

    monkeypatch.setattr(signals, "expire_old_signals", no_expire)
    monkeypatch.setattr(signals, "_latest_ticker", latest_ticker)
    monkeypatch.setattr(signals, "_latest_spec", latest_spec)
    monkeypatch.setattr(signals, "_candles_frame", candles_frame)
    monkeypatch.setattr(
        signals,
        "latest_feature_snapshot",
        lambda _frame: SimpleNamespace(values=feature_values, quality_flags=()),
    )
    monkeypatch.setattr(signals, "select_cost_aware_scenario", capture_scenario)

    runtime = SimpleNamespace(
        predict_scenarios=lambda _features: (
            Prediction("LONG", 0.4, 0.4, 0.2, 0.0, "m", "c", ()),
            Prediction("SHORT", 0.4, 0.4, 0.2, 0.0, "m", "c", ()),
        ),
        stop_atr_multiplier=1.15,
        tp_atr_multiplier=2.20,
    )
    settings = SimpleNamespace(
        symbols=["BTCUSDT"],
        max_ticker_age_seconds=180,
        initial_backfill_bars=1,
        universe_min_history_bars=1,
        max_candle_age_seconds=7200,
        max_spread_bps=100,
        default_horizon_hours=8,
        base_slippage_bps=3.0,
        fee_rate_taker=0.00055,
        stop_gap_reserve_bps=5.0,
    )

    published = await signals.publish_hourly_signals(
        _ProfilesOnlySession(),
        settings=settings,
        runtime=runtime,
        event_time=event_time,
    )

    assert published == []
    assert captured["atr_pct"] == Decimal("0.001")


class _ArtifactModel:
    classes_ = OUTCOME_CLASSES

    def predict_timeout_return_r(self, values) -> list[float]:
        return [0.0] * len(values)


def _artifact_bundle(**updates: object) -> dict[str, object]:
    bundle: dict[str, object] = {
        "task": "barrier_outcome_v1",
        "model": _ArtifactModel(),
        "model_type": "logistic",
        "version": "artifact-v1",
        "calibration_version": "cal-v1",
        "feature_names": MODEL_FEATURE_NAMES,
        "feature_schema_version": MODEL_FEATURE_SCHEMA_VERSION,
        "market_context_schema": "hourly-oi-basis-settled-funding-turnover-v2",
        "market_context_availability_schema": "exchange-event-close-live-receipt-v1",
        "market_context": {
            "schema": "hourly-oi-basis-settled-funding-turnover-v2",
                "funding_interval_schedule_schema": "instrument-spec-point-in-time-v1",
                "funding_interval_source": "instrument_spec_history_point_in_time",
            "availability_schema": "exchange-event-close-live-receipt-v1",
            "historical_receipt_time_reconstructed": False,
        },
        "market_context_ablation_schema": "same-split-zeroed-context-v1",
        "production_drift_reference": valid_production_drift_reference(),
        "label_path_schema_version": LABEL_PATH_SCHEMA_VERSION,
        "entry_spread_bps": 18.0,
        "entry_execution_model": {
            "schema": "directional-half-spread-on-next-hour-open-v1",
            "entry_spread_bps": 18.0,
        },
        "temporal_split_schema": TEMPORAL_SPLIT_SCHEMA_VERSION,
        "walk_forward_schema": WALK_FORWARD_SCHEMA_VERSION,
        "historical_funding_schema": "bybit-settlement-timestamp-replay-v2",
        "historical_funding_timeline": {
            "schema": "bybit-settlement-timestamp-replay-v2",
                "funding_interval_schedule_schema": "instrument-spec-point-in-time-v1",
                "interval_source": "instrument_spec_history_point_in_time",
                "interval_history_symbols": 3,
            "symbols": 1,
            "settlements": 10,
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
        "timeout_return_schema_version": TIMEOUT_RETURN_SCHEMA_VERSION,
        "horizon_hours": 8,
        "stop_atr_multiplier": 1.15,
        "tp_atr_multiplier": 2.20,
    }
    bundle.update(updates)
    return bundle


@pytest.mark.parametrize(
    ("field", "invalid_value", "expected_message"),
    [
        ("label_path_schema_version", None, "label path schema"),
        ("label_path_schema_version", "legacy-close-first-v0", "label path schema"),
        ("label_path_schema_version", "ohlc-open-first-stop-gap-v1", "label path schema"),
        ("temporal_split_schema", None, "temporal split schema"),
        ("temporal_split_schema", "random-split-v0", "temporal split schema"),
        ("walk_forward_schema", None, "walk-forward schema"),
        ("walk_forward_schema", "single-split-v0", "walk-forward schema"),
        ("entry_spread_bps", None, "entry_spread_bps"),
        ("entry_spread_bps", -0.1, "entry_spread_bps"),
    ],
)
def test_runtime_rejects_artifacts_with_incompatible_training_semantics(
    tmp_path: Path,
    field: str,
    invalid_value: object,
    expected_message: str,
) -> None:
    bundle = _artifact_bundle()
    if invalid_value is None:
        bundle.pop(field)
    else:
        bundle[field] = invalid_value
    path = tmp_path / "invalid.joblib"
    joblib.dump(bundle, path)

    with pytest.raises(ValueError, match=expected_message):
        ModelRuntime(path, allow_baseline=False).load()


def test_runtime_rejects_inconsistent_entry_execution_metadata(tmp_path: Path) -> None:
    wrong_schema = _artifact_bundle(
        entry_execution_model={
            "schema": "legacy-frictionless-open-v0",
            "entry_spread_bps": 18.0,
        }
    )
    wrong_schema_path = tmp_path / "wrong-entry-schema.joblib"
    joblib.dump(wrong_schema, wrong_schema_path)
    with pytest.raises(ValueError, match="entry execution schema mismatch"):
        ModelRuntime(wrong_schema_path, allow_baseline=False).load()

    inconsistent = _artifact_bundle(
        entry_execution_model={
            "schema": "directional-half-spread-on-next-hour-open-v1",
            "entry_spread_bps": 12.0,
        }
    )
    inconsistent_path = tmp_path / "inconsistent-entry-spread.joblib"
    joblib.dump(inconsistent, inconsistent_path)
    with pytest.raises(ValueError, match="conflicts with entry execution metadata"):
        ModelRuntime(inconsistent_path, allow_baseline=False).load()


def _candidate(tmp_path: Path, metrics: dict[str, object]) -> ModelCandidate:
    now = datetime(2026, 7, 2, tzinfo=UTC)
    metrics = dict(metrics)
    metrics.setdefault("production_drift_reference", valid_production_drift_reference())
    return ModelCandidate(
        path=tmp_path / "candidate.joblib",
        version="candidate-v1",
        model_type="logistic",
        horizon=8,
        training_start=now,
        training_end=now,
        dataset_rows=1000,
        unique_timestamps=500,
        symbol_count=1,
        symbol_sample=("BTCUSDT",),
        training_data_profile=profile_from_symbol_rows(
            [("BTCUSDT", 500, now, now)],
            unique_timestamps=500,
            minimum_rows_for_coverage=300,
        ),
        metrics=metrics,
        incumbent_metrics=None,
        incumbent_version=None,
    )


def test_quality_gate_treats_positive_no_loss_profit_factor_as_unbounded(
    tmp_path: Path,
) -> None:
    metrics: dict[str, object] = {
        "rows": 300,
        "holdout_span_hours": 336.0,
        "log_loss": 0.9,
        "class_prior_log_loss": 1.05,
        "log_loss_skill_vs_prior": 0.15,
        "multiclass_brier": 0.55,
        "ece_tp": 0.05,
        "ece_sl": 0.05,
        "ece_timeout": 0.05,
        "class_distribution": {"TP": 0.35, "SL": 0.40, "TIMEOUT": 0.25},
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
        "policy_candidates": 1_000,
        "policy_trades": 80,
        "policy_trade_rate": 0.08,
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
        "policy_profit_factor": None,
        "policy_profit_factor_unbounded": True,
        "policy_gross_gain_r": 4.0,
        "policy_gross_loss_r": 0.0,
        "policy_max_drawdown_r": 0.0,
    }

    result = evaluate_quality_gate(
        _candidate(tmp_path, metrics),
        Settings(database_url="postgresql+psycopg://u:p@localhost/db"),
    )

    assert result["passed"] is True
    assert "missing_or_non_finite_policy_profit_factor" not in result["reasons"]
    assert result["absolute"]["policy_profit_factor_unbounded"] is True


def test_backtest_loader_enforces_runtime_artifact_contract(tmp_path: Path) -> None:
    from scripts.backtest import load_validated_artifact

    path = tmp_path / "backtest-model.joblib"
    joblib.dump(_artifact_bundle(), path)

    runtime = load_validated_artifact(path)
    assert runtime.bundle is not None
    assert runtime.sha256 is not None

    with pytest.raises(RuntimeError, match="SHA256 mismatch"):
        load_validated_artifact(path, expected_sha256="0" * 64)


class _TrainableArtifactModel(_ArtifactModel):
    def __init__(self, _model_type: str = "logistic") -> None:
        pass

    def fit(self, *_args: object, **_kwargs: object) -> _TrainableArtifactModel:
        return self

    def predict_proba(self, values) -> np.ndarray:
        return np.repeat(np.array([[0.34, 0.33, 0.33]], dtype=float), len(values), axis=0)


def test_incumbent_with_different_barrier_geometry_is_not_compared_on_candidate_labels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incumbent_path = tmp_path / "incumbent.joblib"
    joblib.dump(
        _artifact_bundle(
            version="incumbent-v1",
            stop_atr_multiplier=1.50,
            tp_atr_multiplier=3.00,
        ),
        incumbent_path,
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    dataset = pd.DataFrame(
        [
            {
                "decision_time": now,
                "label_end_time": now + timedelta(hours=8),
                "source_open_time": now - timedelta(hours=1),
                "open_time": now - timedelta(hours=1),
                "symbol": "BTCUSDT",
            }
        ]
    )
    dataset.attrs["hourly_continuity"] = {}
    split = SimpleNamespace(
        x_train=[],
        y_train=[],
        x_cal=[],
        y_cal=[],
        x_test=np.zeros((3, len(MODEL_FEATURE_NAMES)), dtype=float),
        y_test=np.array(["TP", "SL", "TIMEOUT"], dtype=object),
        train_meta=pd.DataFrame(
            {
                "target": [],
                "realized_gross_return": [],
                "barrier_downside_rate": [],
            }
        ),
    )

    monkeypatch.setattr(lifecycle, "make_barrier_dataset", lambda *_args, **_kwargs: dataset)
    monkeypatch.setattr(lifecycle, "chronological_split", lambda *_args, **_kwargs: split)
    monkeypatch.setattr(lifecycle, "TemporalCalibratedBarrierModel", _TrainableArtifactModel)
    monkeypatch.setattr(
        lifecycle,
        "evaluate_model",
        lambda *_args, **_kwargs: {"rows": 1, "log_loss": 0.9, "multiclass_brier": 0.55},
    )
    monkeypatch.setattr(
        lifecycle,
        "evaluate_market_context_ablation",
        lambda *_args, **_kwargs: {
            "schema": "same-split-zeroed-context-v1",
            "core_log_loss": 1.0,
            "core_multiclass_brier": 0.7,
        },
    )
    monkeypatch.setattr(
        lifecycle,
        "evaluate_walk_forward_validation",
        lambda *_args, **_kwargs: {
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
            "walk_forward_fold_results": [],
        },
    )
    monkeypatch.setattr(
        lifecycle,
        "profile_training_frame",
        lambda *_args, **_kwargs: profile_from_symbol_rows(
            [("BTCUSDT", 1, now, now)],
            unique_timestamps=1,
            minimum_rows_for_coverage=1,
        ),
    )

    candidate = lifecycle.build_model_candidate(
        pd.DataFrame([{"present": True}]),
        horizon=8,
        model_type="logistic",
        model_dir=tmp_path,
        output=tmp_path / "candidate.joblib",
        entry_spread_bps=18.0,
        incumbent=IncumbentSnapshot(
            version="incumbent-v1",
            model_type="logistic",
            artifact_path=str(incumbent_path),
            artifact_sha256=None,
            training_end=now,
        ),
    )

    assert candidate.incumbent_metrics == {
        "comparison_skipped": "incumbent_execution_geometry_mismatch",
        "candidate_stop_atr_multiplier": 1.15,
        "candidate_tp_atr_multiplier": 2.2,
        "candidate_entry_spread_bps": 18.0,
        "incumbent_stop_atr_multiplier": 1.5,
        "incumbent_tp_atr_multiplier": 3.0,
        "incumbent_entry_spread_bps": 18.0,
        "candidate_research_leverage": None,
        "incumbent_research_leverage": 3,
        "candidate_liquidation_equity_reserve_fraction": None,
        "incumbent_liquidation_equity_reserve_fraction": 0.10,
    }


def test_runtime_rejects_artifact_without_market_context_contract(tmp_path: Path) -> None:
    bundle = _artifact_bundle()
    bundle.pop("market_context_schema")
    path = tmp_path / "missing-market-context.joblib"
    joblib.dump(bundle, path)

    with pytest.raises(ValueError, match="market context schema mismatch"):
        ModelRuntime(path, allow_baseline=False).load()


def test_runtime_rejects_drift_reference_from_unselected_calibration_cohort(
    tmp_path: Path,
) -> None:
    bundle = _artifact_bundle()
    bundle["production_drift_reference"]["calibration"]["schema"] = (
        "all-direction-final-holdout-v0"
    )
    path = tmp_path / "unselected-drift-calibration.joblib"
    joblib.dump(bundle, path)

    with pytest.raises(ValueError, match="drift calibration cohort"):
        ModelRuntime(path, allow_baseline=False).load()

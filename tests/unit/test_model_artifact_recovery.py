from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import joblib
import pytest

from app.config import Settings
from app.ml.artifact_recovery import load_recovery_candidate
from app.ml.data_profile import profile_from_symbol_rows
from app.ml.lifecycle import evaluate_quality_gate
from app.ml.training import (
    LABEL_PATH_SCHEMA_VERSION,
    MODEL_FEATURE_NAMES,
    MODEL_FEATURE_SCHEMA_VERSION,
    OUTCOME_CLASSES,
    TEMPORAL_SPLIT_SCHEMA_VERSION,
    TIMEOUT_RETURN_SCHEMA_VERSION,
)
from tests.drift_reference import valid_production_drift_reference
from tests.model_artifact_metrics import (
    valid_policy_cluster_robustness,
    valid_policy_direction_robustness,
    valid_policy_interaction_robustness,
    valid_policy_regime_robustness,
    valid_policy_symbol_robustness,
)


class _RecoveryArtifactModel:
    classes_ = OUTCOME_CLASSES

    def predict_timeout_return_r(self, values) -> list[float]:
        return [0.0] * len(values)


def _passing_metrics() -> dict[str, object]:
    return {
        "rows": 300,
        "holdout_span_hours": 336.0,
        "log_loss": 0.90,
        "class_prior_log_loss": 1.05,
        "log_loss_skill_vs_prior": 0.15,
        "multiclass_brier": 0.55,
        "ece_tp": 0.05,
        "ece_sl": 0.06,
        "ece_timeout": 0.07,
        "class_distribution": {"TP": 0.35, "SL": 0.40, "TIMEOUT": 0.25},
        "production_drift_reference": valid_production_drift_reference(
            directional_rows=300,
            selected_rows=150,
            actionability_rate=80 / 150,
        ),
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
            "schema": "decision-close-tick-zone-next-hour-open-directional-half-spread-v3",
            "entry_spread_bps": 18.0,
            "entry_zone_atr_fraction": 0.12,
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
        "policy_metric_schema": "decision-close-tick-zone-directional-spread-entry-funding-mark-mtm-liquidation-cohort-v26",
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
        "policy_candidates": 150,
        "policy_trades": 80,
        "policy_direction_robustness": valid_policy_direction_robustness(
            policy_trades=80,
            policy_cohorts=80,
        ),
        "policy_symbol_robustness": valid_policy_symbol_robustness(policy_trades=80),
        "policy_cluster_robustness": valid_policy_cluster_robustness(policy_trades=80),
        "policy_regime_robustness": valid_policy_regime_robustness(
            policy_trades=80,
            policy_cohorts=80,
        ),
        "policy_interaction_robustness": valid_policy_interaction_robustness(
            policy_trades=80
        ),
        "policy_actionable_calibration_schema": "actionable-policy-trades-final-holdout-v1",
        "policy_actionable_calibration_rows": 80,
        "policy_actionable_log_loss": 0.60,
        "policy_actionable_multiclass_brier": 0.30,
        "policy_trade_rate": 80 / 150,
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


def _write_artifact(path: Path, *, version: str | None = None, horizon: int = 8) -> None:
    now = datetime.now(UTC)
    resolved_version = version or path.stem
    profile = profile_from_symbol_rows(
        [
            ("BTCUSDT", 900, now, now),
            ("ETHUSDT", 900, now, now),
        ],
        unique_timestamps=900,
        minimum_rows_for_coverage=300,
    )
    joblib.dump(
        {
            "task": "barrier_outcome_v1",
            "model": _RecoveryArtifactModel(),
            "model_type": "logistic",
            "version": resolved_version,
            "calibration_version": f"sigmoid-ovr-{resolved_version}",
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
            "production_drift_reference": valid_production_drift_reference(
                directional_rows=300,
                selected_rows=150,
                actionability_rate=80 / 150,
            ),
            "label_path_schema_version": LABEL_PATH_SCHEMA_VERSION,
            "entry_spread_bps": 18.0,
            "entry_zone_atr_fraction": 0.12,
            "maximum_signal_publication_delay_seconds": 600,
            "entry_execution_model": {
                "schema": "decision-close-tick-zone-next-hour-open-directional-half-spread-v3",
                "entry_spread_bps": 18.0,
                "entry_zone_atr_fraction": 0.12,
            },
            "temporal_split_schema": TEMPORAL_SPLIT_SCHEMA_VERSION,
            "walk_forward_schema": "expanding-train-rolling-calibration-purged-v1",
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
            "intrahorizon_margin_schema": "bybit-mark-price-hourly-isolated-margin-proxy-v1",
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
            "research_leverage": 3,
            "liquidation_equity_reserve_fraction": 0.10,
            "timeout_return_schema_version": TIMEOUT_RETURN_SCHEMA_VERSION,
            "horizon_hours": horizon,
            "metrics": _passing_metrics(),
            "training_start": now.isoformat(),
            "training_end": now.isoformat(),
            "dataset_rows": 1000,
            "unique_timestamps": 500,
            "symbol_count": 2,
            "symbol_sample": ["BTCUSDT", "ETHUSDT"],
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "training_data_profile": profile.to_dict(),
            "source": "background_trainer",
            "created_at": now.isoformat(),
        },
        path,
    )


def test_recovery_loader_reconstructs_candidate_and_absolute_gate(tmp_path: Path) -> None:
    path = tmp_path / "barrier-logistic-h8-20260628T072708Z.joblib"
    _write_artifact(path)

    candidate = load_recovery_candidate(path, expected_horizon_hours=8)
    gate = evaluate_quality_gate(
        candidate,
        Settings(database_url="postgresql+psycopg://u:p@localhost/db"),
    )

    assert candidate.version == path.stem
    assert candidate.path == path.resolve()
    assert candidate.incumbent_version is None
    assert candidate.feature_schema_version == MODEL_FEATURE_SCHEMA_VERSION
    assert candidate.training_data_profile.symbols == ("BTCUSDT", "ETHUSDT")
    assert gate["passed"] is True
    assert gate["relative"] is None


def test_recovery_loader_rejects_filename_version_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "barrier-logistic-h8-new.joblib"
    _write_artifact(path, version="barrier-logistic-h8-other")

    with pytest.raises(RuntimeError, match="filename/version mismatch"):
        load_recovery_candidate(path, expected_horizon_hours=8)


def test_recovery_loader_rejects_wrong_horizon(tmp_path: Path) -> None:
    path = tmp_path / "barrier-logistic-h12-test.joblib"
    _write_artifact(path, horizon=12)

    with pytest.raises(RuntimeError, match="DEFAULT_HORIZON_HOURS=8"):
        load_recovery_candidate(path, expected_horizon_hours=8)


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value


class _FakeSession:
    def __init__(self, values: list[object]) -> None:
        self.values = iter(values)

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _statement: object) -> _ScalarResult:
        return _ScalarResult(next(self.values))


@pytest.mark.asyncio
async def test_recover_artifact_registers_and_activates_gate_passed_orphan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import model_registry

    path = tmp_path / "barrier-logistic-h8-recovery.joblib"
    path.write_bytes(b"artifact")
    active = SimpleNamespace(
        id="active-id",
        version="missing-active-v1",
        model_type="barrier_logistic",
        artifact_path=str(tmp_path / "deleted.joblib"),
    )
    candidate = SimpleNamespace(version=path.stem, path=path.resolve(), horizon=8)
    registered = SimpleNamespace(id="candidate-id", version=path.stem)
    activations: list[tuple[str, str | None]] = []

    monkeypatch.setattr(
        model_registry,
        "get_settings",
        lambda: Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            app_mode="paper",
            allow_baseline_model=True,
            model_dir=tmp_path,
        ),
    )
    monkeypatch.setattr(model_registry, "SessionFactory", lambda: _FakeSession([active, None]))
    monkeypatch.setattr(model_registry, "load_recovery_candidate", lambda *_args, **_kwargs: candidate)
    monkeypatch.setattr(
        model_registry,
        "evaluate_quality_gate",
        lambda *_args, **_kwargs: {"passed": True, "reasons": [], "relative": None},
    )

    async def register_inactive(
        candidate_value: object,
        *,
        source: str,
        quality_gate: dict[str, object] | None,
        activation_requested: bool,
        actor: str,
        incumbent_recovery: dict[str, object] | None,
        experiment_promotion_gate: dict[str, object] | None,
    ) -> object:
        assert source == "operator_artifact_recovery"
        assert quality_gate and quality_gate["passed"] is True
        assert activation_requested is True
        assert incumbent_recovery is not None
        assert experiment_promotion_gate and experiment_promotion_gate["passed"] is False
        assert actor == "operator-artifact-recovery"
        assert candidate_value.version == path.stem
        return registered

    async def activate(
        version: str,
        *,
        actor: str,
        expected_previous_version: str | None,
        emergency_gate_override: bool,
        override_reason: str,
    ) -> dict[str, object]:
        assert actor == "operator-artifact-recovery"
        assert emergency_gate_override is True
        assert override_reason
        activations.append((version, expected_previous_version))
        return {"version": version, "actor": actor}

    monkeypatch.setattr(model_registry, "register_model_candidate", register_inactive)
    monkeypatch.setattr(model_registry, "activate_registered_model", activate)

    result = await model_registry.recover_artifact(path)

    assert result["activated"] is True
    assert result["reason"] == "orphan_recovery_activated"
    assert activations == [(path.stem, active.version)]


@pytest.mark.asyncio
async def test_recover_artifact_does_not_override_failed_registered_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import model_registry

    path = tmp_path / "barrier-logistic-h8-rejected.joblib"
    path.write_bytes(b"artifact")
    active = SimpleNamespace(
        id="active-id",
        version="missing-active-v1",
        model_type="barrier_logistic",
        artifact_path=str(tmp_path / "deleted.joblib"),
    )
    candidate = SimpleNamespace(version=path.stem, path=path.resolve())
    existing = SimpleNamespace(
        id="candidate-id",
        version=path.stem,
        artifact_path=str(path.resolve()),
        metrics={
            "quality_gate": {
                "passed": False,
                "reasons": ["policy_profit_factor_below_minimum"],
            }
        },
    )

    monkeypatch.setattr(
        model_registry,
        "get_settings",
        lambda: Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            app_mode="paper",
            allow_baseline_model=True,
            model_dir=tmp_path,
        ),
    )
    monkeypatch.setattr(model_registry, "SessionFactory", lambda: _FakeSession([active, existing]))
    monkeypatch.setattr(model_registry, "load_recovery_candidate", lambda *_args, **_kwargs: candidate)

    async def unexpected_activation(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("failed gate must not activate")

    monkeypatch.setattr(model_registry, "activate_registered_model", unexpected_activation)

    result = await model_registry.recover_artifact(path)

    assert result["activated"] is False
    assert result["reason"] == "registered_candidate_did_not_pass_quality_gate"

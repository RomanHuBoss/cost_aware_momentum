from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import joblib
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
)


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


def _artifact_bundle(**updates: object) -> dict[str, object]:
    bundle: dict[str, object] = {
        "task": "barrier_outcome_v1",
        "model": _ArtifactModel(),
        "model_type": "logistic",
        "version": "artifact-v1",
        "calibration_version": "cal-v1",
        "feature_names": MODEL_FEATURE_NAMES,
        "feature_schema_version": MODEL_FEATURE_SCHEMA_VERSION,
        "label_path_schema_version": LABEL_PATH_SCHEMA_VERSION,
        "temporal_split_schema": TEMPORAL_SPLIT_SCHEMA_VERSION,
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
        ("temporal_split_schema", None, "temporal split schema"),
        ("temporal_split_schema", "random-split-v0", "temporal split schema"),
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


def _candidate(tmp_path: Path, metrics: dict[str, object]) -> ModelCandidate:
    now = datetime(2026, 7, 2, tzinfo=UTC)
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
        "policy_metric_schema": "exit-time-open-gap-horizon-independent-cohort-v8",
        "policy_horizon_hours": 8,
        "policy_capital_sleeves": 8,
        "policy_trades": 80,
        "policy_cohorts": 80,
        "policy_independent_cohorts": 80,
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

    def fit(self, *_args: object) -> _TrainableArtifactModel:
        return self


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
    split = SimpleNamespace(x_train=[], y_train=[], x_cal=[], y_cal=[])

    monkeypatch.setattr(lifecycle, "make_barrier_dataset", lambda *_args, **_kwargs: dataset)
    monkeypatch.setattr(lifecycle, "chronological_split", lambda *_args, **_kwargs: split)
    monkeypatch.setattr(lifecycle, "TemporalCalibratedBarrierModel", _TrainableArtifactModel)
    monkeypatch.setattr(lifecycle, "evaluate_model", lambda *_args, **_kwargs: {"rows": 1})
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
        incumbent=IncumbentSnapshot(
            version="incumbent-v1",
            model_type="logistic",
            artifact_path=str(incumbent_path),
            artifact_sha256=None,
            training_end=now,
        ),
    )

    assert candidate.incumbent_metrics == {
        "comparison_skipped": "incumbent_barrier_geometry_mismatch",
        "candidate_stop_atr_multiplier": 1.15,
        "candidate_tp_atr_multiplier": 2.2,
        "incumbent_stop_atr_multiplier": 1.5,
        "incumbent_tp_atr_multiplier": 3.0,
    }

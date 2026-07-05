from pathlib import Path

import joblib
import numpy as np
import pytest

from app.api.deps import sign_session, verify_session
from app.bybit.client import BybitClient
from app.config import Settings
from app.ml.context import MARKET_CONTEXT_FEATURE_NAMES
from app.ml.features import FEATURE_NAMES
from app.ml.runtime import ModelRuntime
from app.ml.training import (
    LABEL_PATH_SCHEMA_VERSION,
    MODEL_FEATURE_NAMES,
    MODEL_FEATURE_SCHEMA_VERSION,
    TEMPORAL_SPLIT_SCHEMA_VERSION,
    TIMEOUT_RETURN_SCHEMA_VERSION,
    TemporalCalibratedBarrierModel,
)


class ArtifactStubModel:
    classes_ = np.array(["TP", "SL", "TIMEOUT"])

    def predict_timeout_return_r(self, values: np.ndarray) -> np.ndarray:
        return np.zeros(len(values), dtype=float)


def test_postgresql_is_mandatory() -> None:
    with pytest.raises(ValueError):
        Settings(database_url="sqlite:///bad.db")


def test_session_signature_round_trip() -> None:
    settings = Settings(secret_key="x" * 40, database_url="postgresql+psycopg://u:p@localhost/db")
    token = sign_session(settings, "operator")
    assert verify_session(settings, token) == "operator"
    assert verify_session(settings, token + "x") is None


def test_baseline_prediction_is_normalized() -> None:
    runtime = ModelRuntime(None, allow_baseline=True)
    runtime.load()
    features = {**{name: 0.0 for name in FEATURE_NAMES}, **{name: 0.0 for name in MARKET_CONTEXT_FEATURE_NAMES}}
    features.update({"ret_6h": 0.02, "atr_pct_14": 0.01})
    prediction = runtime.predict(features)
    assert prediction.direction == "LONG"
    assert prediction.p_tp + prediction.p_sl + prediction.p_timeout == pytest.approx(1.0)


def test_bybit_client_has_no_order_methods() -> None:
    public_names = {name for name in dir(BybitClient) if not name.startswith("_")}
    forbidden = {"create_order", "place_order", "amend_order", "cancel_order", "withdraw"}
    assert not (public_names & forbidden)
    source = Path("app/bybit/client.py").read_text(encoding="utf-8")
    for endpoint in ("/v5/order/create", "/v5/order/amend", "/v5/order/cancel", "/v5/asset/withdraw"):
        assert endpoint not in source


def test_empty_active_model_path_is_none() -> None:
    settings = Settings(
        active_model_path="",
        database_url="postgresql+psycopg://u:p@localhost/db",
    )
    assert settings.active_model_path is None


def test_recovery_retry_minutes_must_be_positive() -> None:
    with pytest.raises(ValueError, match="AUTO_TRAIN_RECOVERY_RETRY_MINUTES"):
        Settings(
            auto_train_recovery_retry_minutes=0,
            database_url="postgresql+psycopg://u:p@localhost/db",
        )


def test_production_rejects_demo_and_baseline_defaults() -> None:
    with pytest.raises(ValueError, match="Unsafe production configuration"):
        Settings(
            app_mode="production",
            database_url="postgresql+psycopg://u:p@localhost/db",
        )


def test_runtime_loads_calibrated_barrier_artifact(tmp_path: Path) -> None:
    rng = np.random.default_rng(7)
    width = len(MODEL_FEATURE_NAMES)
    x_train = rng.normal(size=(1200, width))
    x_train[:, -1] = rng.choice([-1.0, 1.0], size=len(x_train))
    signal = x_train[:, 0] * x_train[:, -1]
    y_train = np.where(signal > 0.4, "TP", np.where(signal < -0.4, "SL", "TIMEOUT"))
    x_cal = rng.normal(size=(600, width))
    x_cal[:, -1] = rng.choice([-1.0, 1.0], size=len(x_cal))
    signal_cal = x_cal[:, 0] * x_cal[:, -1]
    y_cal = np.where(signal_cal > 0.4, "TP", np.where(signal_cal < -0.4, "SL", "TIMEOUT"))
    timeout_return_r = np.zeros(len(x_train), dtype=float)
    timeout_return_r[(y_train == "TIMEOUT") & (x_train[:, -1] > 0)] = 0.1
    timeout_return_r[(y_train == "TIMEOUT") & (x_train[:, -1] < 0)] = -0.1
    model = TemporalCalibratedBarrierModel().fit(
        x_train,
        y_train,
        x_cal,
        y_cal,
        timeout_return_r_train=timeout_return_r,
    )
    path = tmp_path / "barrier.joblib"
    joblib.dump(
        {
            "task": "barrier_outcome_v1",
            "model": model,
            "model_type": "logistic",
            "version": "test-barrier-v1",
            "calibration_version": "test-cal-v1",
            "feature_names": MODEL_FEATURE_NAMES,
            "feature_schema_version": MODEL_FEATURE_SCHEMA_VERSION,
            "market_context_schema": "hourly-oi-basis-settled-funding-turnover-v1",
            "market_context_availability_schema": "exchange-event-close-live-receipt-v1",
            "market_context": {
                "schema": "hourly-oi-basis-settled-funding-turnover-v1",
                "availability_schema": "exchange-event-close-live-receipt-v1",
                "historical_receipt_time_reconstructed": False,
            },
            "market_context_ablation_schema": "same-split-zeroed-context-v1",
            "label_path_schema_version": LABEL_PATH_SCHEMA_VERSION,
            "entry_spread_bps": 18.0,
            "entry_execution_model": {
                "schema": "directional-half-spread-on-next-hour-open-v1",
                "entry_spread_bps": 18.0,
            },
            "temporal_split_schema": TEMPORAL_SPLIT_SCHEMA_VERSION,
            "walk_forward_schema": "expanding-train-rolling-calibration-purged-v1",
            "historical_funding_schema": "bybit-settlement-timestamp-replay-v1",
            "historical_funding_timeline": {
                "schema": "bybit-settlement-timestamp-replay-v1",
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
            "stop_atr_multiplier": 1.7,
            "tp_atr_multiplier": 2.9,
        },
        path,
    )

    runtime = ModelRuntime(path, allow_baseline=False)
    runtime.load(expected_version="test-barrier-v1")
    features = {**{name: 0.0 for name in FEATURE_NAMES}, **{name: 0.0 for name in MARKET_CONTEXT_FEATURE_NAMES}}
    features.update({"ret_1h": 0.03, "atr_pct_14": 0.01})
    prediction = runtime.predict(features)

    assert runtime.is_baseline is False
    assert prediction.p_tp + prediction.p_sl + prediction.p_timeout == pytest.approx(1.0)
    assert prediction.model_version == "test-barrier-v1"
    assert runtime.stop_atr_multiplier == pytest.approx(1.7)
    assert runtime.tp_atr_multiplier == pytest.approx(2.9)


def test_runtime_rejects_legacy_direction_artifact(tmp_path: Path) -> None:
    path = tmp_path / "legacy.joblib"
    joblib.dump(
        {
            "model": object(),
            "version": "legacy",
            "feature_names": MODEL_FEATURE_NAMES[:-1],
        },
        path,
    )
    runtime = ModelRuntime(path, allow_baseline=False)
    with pytest.raises(ValueError, match="legacy model task"):
        runtime.load()


def test_runtime_rejects_non_finite_artifact_barrier_multiplier(tmp_path: Path) -> None:
    path = tmp_path / "invalid-multiplier.joblib"
    joblib.dump(
        {
            "task": "barrier_outcome_v1",
            "model": ArtifactStubModel(),
            "model_type": "stub",
            "version": "invalid-multiplier-v1",
            "calibration_version": "stub",
            "feature_names": MODEL_FEATURE_NAMES,
            "feature_schema_version": MODEL_FEATURE_SCHEMA_VERSION,
            "market_context_schema": "hourly-oi-basis-settled-funding-turnover-v1",
            "market_context_availability_schema": "exchange-event-close-live-receipt-v1",
            "market_context": {
                "schema": "hourly-oi-basis-settled-funding-turnover-v1",
                "availability_schema": "exchange-event-close-live-receipt-v1",
                "historical_receipt_time_reconstructed": False,
            },
            "market_context_ablation_schema": "same-split-zeroed-context-v1",
            "label_path_schema_version": LABEL_PATH_SCHEMA_VERSION,
            "entry_spread_bps": 18.0,
            "entry_execution_model": {
                "schema": "directional-half-spread-on-next-hour-open-v1",
                "entry_spread_bps": 18.0,
            },
            "temporal_split_schema": TEMPORAL_SPLIT_SCHEMA_VERSION,
            "walk_forward_schema": "expanding-train-rolling-calibration-purged-v1",
            "historical_funding_schema": "bybit-settlement-timestamp-replay-v1",
            "historical_funding_timeline": {
                "schema": "bybit-settlement-timestamp-replay-v1",
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
            "stop_atr_multiplier": float("nan"),
            "tp_atr_multiplier": 2.2,
        },
        path,
    )

    runtime = ModelRuntime(path, allow_baseline=False)
    with pytest.raises(ValueError, match="stop_atr_multiplier must be positive and finite"):
        runtime.load()
    assert runtime.is_baseline is True

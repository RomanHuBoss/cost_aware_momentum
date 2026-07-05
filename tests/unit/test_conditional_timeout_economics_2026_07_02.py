from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import joblib
import numpy as np
import pytest

from app.ml.features import FEATURE_NAMES
from app.ml.runtime import ModelRuntime, Prediction
from app.ml.training import (
    LABEL_PATH_SCHEMA_VERSION,
    MODEL_FEATURE_NAMES,
    MODEL_FEATURE_SCHEMA_VERSION,
    TEMPORAL_SPLIT_SCHEMA_VERSION,
    TIMEOUT_RETURN_SCHEMA_VERSION,
    TemporalCalibratedBarrierModel,
)
from app.risk.math import CostScenario
from app.services.signals import select_cost_aware_scenario

D = Decimal


def _training_arrays() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(20260702)
    width = len(MODEL_FEATURE_NAMES)
    rows = 360
    x_train = rng.normal(size=(rows, width))
    x_train[:, -1] = np.tile([1.0, -1.0], rows // 2)
    y_train = np.resize(np.array(["TP", "SL", "TIMEOUT"], dtype=object), rows)
    timeout_return_r = np.zeros(rows, dtype=float)
    timeout_mask = y_train == "TIMEOUT"
    timeout_return_r[timeout_mask & (x_train[:, -1] > 0)] = 0.40
    timeout_return_r[timeout_mask & (x_train[:, -1] < 0)] = -0.60

    x_cal = rng.normal(size=(180, width))
    x_cal[:, -1] = np.tile([1.0, -1.0], len(x_cal) // 2)
    y_cal = np.resize(np.array(["TP", "SL", "TIMEOUT"], dtype=object), len(x_cal))
    return x_train, y_train, x_cal, y_cal, timeout_return_r


def test_timeout_return_estimator_is_fit_on_training_timeout_rows_by_direction() -> None:
    x_train, y_train, x_cal, y_cal, timeout_return_r = _training_arrays()

    model = TemporalCalibratedBarrierModel().fit(
        x_train,
        y_train,
        x_cal,
        y_cal,
        timeout_return_r_train=timeout_return_r,
    )
    probe = np.zeros((2, len(MODEL_FEATURE_NAMES)), dtype=float)
    probe[:, -1] = [1.0, -1.0]

    estimates = model.predict_timeout_return_r(probe)

    assert estimates.tolist() == pytest.approx([0.40, -0.60])
    assert model.timeout_return_sample_count_by_direction == {"LONG": 60, "SHORT": 60}


def test_signal_policy_uses_scenario_specific_timeout_return_r() -> None:
    probabilities = {
        "p_tp": 0.30,
        "p_sl": 0.30,
        "p_timeout": 0.40,
        "score": 0.0,
        "model_version": "conditional-timeout-v1",
        "calibration_version": "cal-v1",
        "reasons": (),
    }
    predictions = (
        Prediction(direction="LONG", timeout_return_r=-0.80, **probabilities),
        Prediction(direction="SHORT", timeout_return_r=0.80, **probabilities),
    )

    selected = select_cost_aware_scenario(
        predictions,
        bid_price=D("100"),
        ask_price=D("100"),
        last_price=D("100"),
        atr_pct=D("0.02"),
        costs=CostScenario(D("0"), D("0"), D("0"), D("0")),
        timeout_return_rate=D("-0.002"),
    )

    assert selected.prediction.direction == "SHORT"
    assert selected.timeout_return_rate == D("0.018400")
    assert selected.ev_r > D("0")


def test_runtime_rejects_artifact_without_timeout_return_schema(tmp_path: Path) -> None:
    x_train, y_train, x_cal, y_cal, timeout_return_r = _training_arrays()
    model = TemporalCalibratedBarrierModel().fit(
        x_train,
        y_train,
        x_cal,
        y_cal,
        timeout_return_r_train=timeout_return_r,
    )
    path = tmp_path / "missing-timeout-schema.joblib"
    joblib.dump(
        {
            "task": "barrier_outcome_v1",
            "model": model,
            "model_type": "logistic",
            "version": "missing-timeout-schema-v1",
            "calibration_version": "cal-v1",
            "feature_names": MODEL_FEATURE_NAMES,
            "feature_schema_version": MODEL_FEATURE_SCHEMA_VERSION,
            "label_path_schema_version": LABEL_PATH_SCHEMA_VERSION,
            "entry_spread_bps": 18.0,
            "entry_execution_model": {
                "schema": "directional-half-spread-on-next-hour-open-v1",
                "entry_spread_bps": 18.0,
            },
            "temporal_split_schema": TEMPORAL_SPLIT_SCHEMA_VERSION,
            "horizon_hours": 8,
            "stop_atr_multiplier": 1.15,
            "tp_atr_multiplier": 2.20,
        },
        path,
    )

    runtime = ModelRuntime(path, allow_baseline=False)

    with pytest.raises(ValueError, match="timeout return schema mismatch"):
        runtime.load()


def test_runtime_propagates_artifact_timeout_return_r(tmp_path: Path) -> None:
    x_train, y_train, x_cal, y_cal, timeout_return_r = _training_arrays()
    model = TemporalCalibratedBarrierModel().fit(
        x_train,
        y_train,
        x_cal,
        y_cal,
        timeout_return_r_train=timeout_return_r,
    )
    path = tmp_path / "conditional-timeout.joblib"
    joblib.dump(
        {
            "task": "barrier_outcome_v1",
            "model": model,
            "model_type": "logistic",
            "version": "conditional-timeout-v1",
            "calibration_version": "cal-v1",
            "feature_names": MODEL_FEATURE_NAMES,
            "feature_schema_version": MODEL_FEATURE_SCHEMA_VERSION,
            "label_path_schema_version": LABEL_PATH_SCHEMA_VERSION,
            "entry_spread_bps": 18.0,
            "entry_execution_model": {
                "schema": "directional-half-spread-on-next-hour-open-v1",
                "entry_spread_bps": 18.0,
            },
            "temporal_split_schema": TEMPORAL_SPLIT_SCHEMA_VERSION,
            "timeout_return_schema_version": TIMEOUT_RETURN_SCHEMA_VERSION,
            "horizon_hours": 8,
            "stop_atr_multiplier": 1.15,
            "tp_atr_multiplier": 2.20,
        },
        path,
    )

    runtime = ModelRuntime(path, allow_baseline=False)
    runtime.load()
    long_scenario, short_scenario = runtime.predict_scenarios(
        {name: 0.0 for name in FEATURE_NAMES}
    )

    assert long_scenario.timeout_return_r == pytest.approx(0.40)
    assert short_scenario.timeout_return_r == pytest.approx(-0.60)


def test_policy_evaluation_uses_model_timeout_estimate_for_direction_selection() -> None:
    from datetime import UTC, datetime, timedelta

    import pandas as pd

    from app.ml.training import DatasetSplit, PolicyEvaluationConfig, evaluate_policy_model

    class ConditionalPolicyModel:
        classes_ = np.array(["TP", "SL", "TIMEOUT"])

        def predict_proba(self, values: np.ndarray) -> np.ndarray:
            return np.repeat([[0.30, 0.30, 0.40]], len(values), axis=0)

        def predict_timeout_return_r(self, values: np.ndarray) -> np.ndarray:
            return np.where(values[:, -1] > 0, -0.80, 0.80)

    decision_time = datetime(2026, 1, 1, tzinfo=UTC)
    x_test = np.zeros((2, len(MODEL_FEATURE_NAMES)), dtype=float)
    x_test[:, -1] = [1.0, -1.0]
    meta = pd.DataFrame(
        [
            {
                "decision_time": decision_time,
                "open_time": decision_time - timedelta(hours=1),
                "label_end_time": decision_time + timedelta(hours=1),
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "target": "TIMEOUT",
                "ambiguous": False,
                "exit_index": 0,
                "exit_at_open": False,
                "realized_gross_return": -0.01,
                "barrier_upside_rate": 0.04,
                "barrier_downside_rate": 0.02,
            },
            {
                "decision_time": decision_time,
                "open_time": decision_time - timedelta(hours=1),
                "label_end_time": decision_time + timedelta(hours=1),
                "symbol": "BTCUSDT",
                "direction": "SHORT",
                "target": "TIMEOUT",
                "ambiguous": False,
                "exit_index": 0,
                "exit_at_open": False,
                "realized_gross_return": 0.01,
                "barrier_upside_rate": 0.04,
                "barrier_downside_rate": 0.02,
            },
        ]
    )
    split = DatasetSplit(
        x_train=np.empty((0, len(MODEL_FEATURE_NAMES))),
        y_train=np.empty(0),
        x_cal=np.empty((0, len(MODEL_FEATURE_NAMES))),
        y_cal=np.empty(0),
        x_test=x_test,
        y_test=np.array(["TIMEOUT", "TIMEOUT"]),
        test_meta=meta,
    )

    metrics = evaluate_policy_model(
        ConditionalPolicyModel(),
        split,
        PolicyEvaluationConfig(
            fee_rate_round_trip=0.0,
            slippage_rate=0.0,
            stop_gap_reserve_rate=0.0,
            min_net_rr=0.0,
            min_net_ev_r=-10.0,
            timeout_return_rate=-0.002,
            horizon_hours=1,
        ),
    )

    assert metrics["policy_timeout_return_schema"] == TIMEOUT_RETURN_SCHEMA_VERSION
    assert metrics["policy_trades"] == 1
    assert metrics["policy_realized_mean_r"] == pytest.approx(0.5)


def test_execution_reuses_the_signal_timeout_assumption_and_fails_closed() -> None:
    from types import SimpleNamespace

    from app.services.execution import signal_timeout_return_rate

    signal = SimpleNamespace(
        feature_snapshot={
            "economics_assumptions": {"timeout_gross_return_rate": "-0.013"}
        }
    )
    assert signal_timeout_return_rate(signal, fallback=D("-0.002")) == D("-0.013")

    invalid_signal = SimpleNamespace(
        feature_snapshot={
            "economics_assumptions": {"timeout_gross_return_rate": "NaN"}
        }
    )
    with pytest.raises(ValueError, match="finite"):
        signal_timeout_return_rate(invalid_signal, fallback=D("-0.002"))


def test_research_backtest_uses_artifact_timeout_estimator_unless_overridden() -> None:
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    import pandas as pd

    from scripts.backtest import policy_backtest

    class ConditionalBacktestModel:
        classes_ = np.array(["TP", "SL", "TIMEOUT"])

        def predict_proba(self, values: np.ndarray) -> np.ndarray:
            return np.repeat([[0.30, 0.30, 0.40]], len(values), axis=0)

        def predict_timeout_return_r(self, values: np.ndarray) -> np.ndarray:
            return np.where(values[:, -1] > 0, -0.80, 0.80)

    decision_time = datetime(2026, 1, 1, tzinfo=UTC)
    x_test = np.zeros((2, len(MODEL_FEATURE_NAMES)), dtype=float)
    x_test[:, -1] = [1.0, -1.0]
    meta = pd.DataFrame(
        [
            {
                "decision_time": decision_time,
                "open_time": decision_time - timedelta(hours=1),
                "label_end_time": decision_time + timedelta(hours=1),
                "symbol": "BTCUSDT",
                "direction": direction,
                "target": "TIMEOUT",
                "ambiguous": False,
                "exit_index": 0,
                "exit_at_open": False,
                "realized_gross_return": realized,
                "barrier_upside_rate": 0.04,
                "barrier_downside_rate": 0.02,
            }
            for direction, realized in (("LONG", -0.01), ("SHORT", 0.01))
        ]
    )
    split = SimpleNamespace(x_test=x_test, test_meta=meta)

    metrics = policy_backtest(
        ConditionalBacktestModel(),
        split,
        round_trip_cost_bps=0.0,
        stop_gap_reserve_bps=0.0,
        horizon_hours=1,
        minimum_net_rr=0.0,
        minimum_net_ev_r=-10.0,
    )

    assert metrics["timeout_return_source"] == "artifact_training_direction_median_r"
    assert metrics["trades"] == 1
    assert metrics["mean_net_return_per_trade"] == pytest.approx(0.01)

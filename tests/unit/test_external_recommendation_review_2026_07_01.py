from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import joblib
import pandas as pd
import pytest

from app.ml.features import FEATURE_NAMES, build_feature_frame, latest_feature_snapshot
from app.ml.labels import triple_barrier_outcome
from app.ml.runtime import ModelRuntime
from app.ml.training import (
    LABEL_PATH_SCHEMA_VERSION,
    MODEL_FEATURE_NAMES,
    MODEL_FEATURE_SCHEMA_VERSION,
    TEMPORAL_SPLIT_SCHEMA_VERSION,
    TIMEOUT_RETURN_SCHEMA_VERSION,
)
from app.risk.math import (
    CostScenario,
    break_even_tp_probability,
    projected_funding_rate,
    stress_downside_rate,
    upside_rate,
    validate_probability_simplex,
)

D = Decimal


class StubModel:
    classes_ = ["TP", "SL", "TIMEOUT"]

    def predict_timeout_return_r(self, values) -> list[float]:
        return [0.0] * len(values)


def _features(**updates: float) -> dict[str, float]:
    values = {name: 0.0 for name in FEATURE_NAMES}
    values.update({"atr_pct_14": 0.02, **updates})
    return values


def test_baseline_runtime_rejects_missing_and_nonfinite_features() -> None:
    runtime = ModelRuntime(None, allow_baseline=True)
    runtime.load()

    with pytest.raises(ValueError, match="missing model features"):
        runtime.predict_scenarios({})

    values = _features()
    values["ret_6h"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        runtime.predict_scenarios(values)


@pytest.mark.parametrize("updates", [{}, {"ret_6h": 0.02}, {"ret_6h": -0.02}])
def test_predict_is_exact_best_scenario_compatibility_wrapper(updates: dict[str, float]) -> None:
    runtime = ModelRuntime(None, allow_baseline=True)
    runtime.load()
    values = _features(**updates)

    scenarios = runtime.predict_scenarios(values)
    prediction = runtime.predict(values)

    assert prediction == max(scenarios, key=lambda item: item.score)


def test_artifact_rejects_boolean_barrier_multiplier(tmp_path: Path) -> None:
    path = tmp_path / "bool-multiplier.joblib"
    joblib.dump(
        {
            "task": "barrier_outcome_v1",
            "model": StubModel(),
            "model_type": "stub",
            "version": "bool-multiplier-v1",
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
            "stop_atr_multiplier": True,
            "tp_atr_multiplier": 2.4,
        },
        path,
    )

    with pytest.raises(ValueError, match="stop_atr_multiplier"):
        ModelRuntime(path, allow_baseline=False).load()


def test_short_open_gaps_use_target_for_favorable_gap_and_open_for_adverse_gap() -> None:
    favorable = triple_barrier_outcome(
        pd.DataFrame([{"open": 95.0, "high": 100.0, "low": 94.0, "close": 96.0}]),
        direction="SHORT",
        stop=103.0,
        take_profit=96.0,
    )
    adverse = triple_barrier_outcome(
        pd.DataFrame([{"open": 105.0, "high": 106.0, "low": 100.0, "close": 104.0}]),
        direction="SHORT",
        stop=103.0,
        take_profit=96.0,
    )

    assert favorable.outcome == "TP"
    assert favorable.exit_price == pytest.approx(96.0)
    assert favorable.exit_at_open is True
    assert adverse.outcome == "SL"
    assert adverse.exit_price == pytest.approx(105.0)
    assert adverse.exit_at_open is True


@pytest.mark.parametrize(
    ("direction", "funding_rate", "expected_downside", "expected_upside"),
    [
        ("LONG", D("0.01"), D("0.03"), D("0.03")),
        ("LONG", D("-0.01"), D("0.02"), D("0.04")),
        ("SHORT", D("0.01"), D("0.02"), D("0.04")),
        ("SHORT", D("-0.01"), D("0.03"), D("0.03")),
    ],
)
def test_pretrade_funding_sign_is_directionally_correct(
    direction: str,
    funding_rate: Decimal,
    expected_downside: Decimal,
    expected_upside: Decimal,
) -> None:
    costs = CostScenario(D("0"), D("0"), D("0"), funding_rate)
    stop = D("98") if direction == "LONG" else D("102")
    target = D("104") if direction == "LONG" else D("96")

    assert stress_downside_rate(D("100"), stop, direction, costs) == expected_downside
    assert upside_rate(D("100"), target, direction, costs) == expected_upside


def test_twenty_four_hour_return_requires_twenty_five_hourly_observations() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for hour in range(25):
        price = 100.0 + hour
        rows.append(
            {
                "symbol": "BTCUSDT",
                "open_time": start + timedelta(hours=hour),
                "open": price,
                "high": price + 1.0,
                "low": price - 1.0,
                "close": price,
                "volume": 1_000.0 + hour,
                "turnover": (1_000.0 + hour) * price,
            }
        )

    frame = build_feature_frame(pd.DataFrame(rows))

    assert bool(frame.loc[23, "feature_history_contiguous"]) is False
    assert bool(frame.loc[24, "feature_history_contiguous"]) is True
    assert pd.notna(frame.loc[24, "ret_24h"])



def test_constant_volume_is_flagged_instead_of_used_as_a_valid_z_score() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for hour in range(30):
        price = 100.0 + hour * 0.1
        rows.append(
            {
                "symbol": "BTCUSDT",
                "open_time": start + timedelta(hours=hour),
                "open": price,
                "high": price + 1.0,
                "low": price - 1.0,
                "close": price,
                "volume": 1_000.0,
                "turnover": 1_000.0 * price,
            }
        )

    snapshot = latest_feature_snapshot(pd.DataFrame(rows))

    assert snapshot.values["volume_z_24"] == 0.0
    assert "MISSING_VOLUME_Z_24" in snapshot.quality_flags


def test_negative_break_even_threshold_is_a_valid_infeasibility_signal() -> None:
    threshold = break_even_tp_probability(
        downside_rate=D("0.02"),
        upside_rate=D("0.04"),
        timeout_net_rate=D("0.03"),
        p_timeout=D("0.9"),
    )

    assert threshold == D("-0.416666666666666666666666666666666667")

def test_existing_quant_guards_reject_zero_funding_interval_and_invalid_simplex() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        projected_funding_rate(
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            horizon_hours=8,
            next_settlement=datetime(2026, 1, 1, 1, tzinfo=UTC),
            interval_minutes=0,
            current_rate=D("0.001"),
        )

    with pytest.raises(ValueError, match="sum to 1"):
        validate_probability_simplex(D("0.4"), D("0.4"), D("0.199999"))

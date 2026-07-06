from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from app.ml.labels import triple_barrier_outcome
from app.ml.training import (
    MODEL_FEATURE_NAMES,
    OUTCOME_CLASSES,
    DatasetSplit,
    PolicyEvaluationConfig,
    chronological_split,
    evaluate_policy_model,
    validate_policy_evaluation_metadata,
)
from app.services.outcomes import OutcomeBar, estimate_plan_outcome, evaluate_barrier_outcome
from scripts.backtest import policy_backtest

BASE = datetime(2026, 6, 30, 12, tzinfo=UTC)


class DirectionalModel:
    classes_ = OUTCOME_CLASSES

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        result = []
        for direction_code in x[:, -1]:
            result.append([0.95, 0.04, 0.01] if direction_code > 0 else [0.01, 0.98, 0.01])
        return np.asarray(result, dtype=float)


def _gap_split() -> DatasetSplit:
    meta = pd.DataFrame(
        [
            {
                "decision_time": BASE,
                "label_end_time": BASE + timedelta(hours=1),
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "target": "SL",
                "exit_index": 0,
                "exit_at_open": True,
                "realized_gross_return": -0.04,
                "barrier_upside_rate": 0.04,
                "barrier_downside_rate": 0.02,
            },
            {
                "decision_time": BASE,
                "label_end_time": BASE + timedelta(hours=1),
                "symbol": "BTCUSDT",
                "direction": "SHORT",
                "target": "TP",
                "exit_index": 0,
                "exit_at_open": False,
                "realized_gross_return": 0.04,
                "barrier_upside_rate": 0.04,
                "barrier_downside_rate": 0.02,
            },
        ]
    )
    values = np.zeros((2, len(MODEL_FEATURE_NAMES)), dtype=float)
    values[:, -1] = np.asarray([1.0, -1.0])
    targets = meta["target"].to_numpy()
    return DatasetSplit(values, targets, values, targets, values, targets, meta)


def test_label_resolves_favorable_open_gap_before_same_bar_extremes() -> None:
    bars = pd.DataFrame([{"open": 105.0, "high": 106.0, "low": 97.0, "close": 101.0}])

    result = triple_barrier_outcome(
        bars,
        direction="LONG",
        stop=98.0,
        take_profit=104.0,
    )

    assert result.outcome == "TP"
    assert result.exit_price == pytest.approx(104.0)
    assert result.ambiguous is False
    assert result.exit_at_open is True


def test_label_uses_adverse_open_gap_as_stop_fill() -> None:
    bars = pd.DataFrame([{"open": 97.0, "high": 105.0, "low": 96.0, "close": 100.0}])

    result = triple_barrier_outcome(
        bars,
        direction="LONG",
        stop=98.0,
        take_profit=104.0,
    )

    assert result.outcome == "SL"
    assert result.exit_price == pytest.approx(97.0)
    assert result.ambiguous is False
    assert result.exit_at_open is True


def test_label_rejects_open_outside_ohlc_range() -> None:
    bars = pd.DataFrame([{"open": 106.0, "high": 105.0, "low": 99.0, "close": 101.0}])

    with pytest.raises(ValueError, match="low <= open"):
        triple_barrier_outcome(
            bars,
            direction="LONG",
            stop=98.0,
            take_profit=104.0,
        )


def test_counterfactual_outcome_uses_open_gap_price_and_time() -> None:
    bar = OutcomeBar(
        candle_id=1,
        open_time=BASE,
        close_time=BASE + timedelta(hours=1),
        open=Decimal("97"),
        high=Decimal("105"),
        low=Decimal("96"),
        close=Decimal("100"),
    )

    result = evaluate_barrier_outcome(
        [bar],
        direction="LONG",
        entry=Decimal("100"),
        stop=Decimal("98"),
        take_profit=Decimal("104"),
        window_start=BASE,
        horizon_end=BASE + timedelta(hours=1),
    )

    assert result is not None
    assert result.outcome == "SL"
    assert result.exit_price == Decimal("97")
    assert result.exit_time == BASE
    assert result.ambiguous is False


def test_exact_gap_exit_time_is_preserved_in_policy_metadata() -> None:
    validated = validate_policy_evaluation_metadata(
        _gap_split().test_meta,
        context="Gap regression",
        horizon_hours=1,
        require_barrier_return_consistency=True,
    )

    long_row = validated.loc[validated["direction"] == "LONG"].iloc[0]
    short_row = validated.loc[validated["direction"] == "SHORT"].iloc[0]
    assert long_row["exit_time"] == BASE
    assert short_row["exit_time"] == BASE + timedelta(hours=1)


def test_chronological_split_preserves_open_gap_exit_metadata() -> None:
    rows: list[dict[str, object]] = []
    start = datetime(2025, 1, 1, tzinfo=UTC)
    for hour in range(420):
        decision_time = start + timedelta(hours=hour)
        for direction, direction_code in (("LONG", 1.0), ("SHORT", -1.0)):
            row: dict[str, object] = {name: 0.0 for name in MODEL_FEATURE_NAMES}
            row["scenario_direction"] = direction_code
            row.update(
                {
                    "open_time": decision_time - timedelta(hours=1),
                    "decision_time": decision_time,
                    "label_end_time": decision_time + timedelta(hours=1),
                    "symbol": "BTCUSDT",
                    "direction": direction,
                    "target": "SL" if direction == "LONG" else "TP",
                    "ambiguous": False,
                    "exit_index": 0,
                    "exit_at_open": hour == 419 and direction == "LONG",
                    "realized_gross_return": -0.02 if direction == "LONG" else 0.02,
                    "barrier_upside_rate": 0.02,
                    "barrier_downside_rate": 0.02,
                }
            )
            rows.append(row)

    split = chronological_split(pd.DataFrame(rows), purge_rows=0)

    assert "exit_at_open" in split.test_meta.columns
    final_long = split.test_meta.loc[
        (split.test_meta["decision_time"] == start + timedelta(hours=419))
        & (split.test_meta["direction"] == "LONG")
    ].iloc[0]
    assert bool(final_long["exit_at_open"]) is True
    validated = validate_policy_evaluation_metadata(
        split.test_meta,
        context="Chronological split gap regression",
        horizon_hours=1,
    )
    assert validated.loc[final_long.name, "exit_time"] == final_long["decision_time"]


def test_chronological_split_rejects_missing_open_gap_exit_metadata() -> None:
    rows: list[dict[str, object]] = []
    start = datetime(2025, 1, 1, tzinfo=UTC)
    for hour in range(420):
        decision_time = start + timedelta(hours=hour)
        for direction, direction_code in (("LONG", 1.0), ("SHORT", -1.0)):
            row: dict[str, object] = {name: 0.0 for name in MODEL_FEATURE_NAMES}
            row["scenario_direction"] = direction_code
            row.update(
                {
                    "open_time": decision_time - timedelta(hours=1),
                    "decision_time": decision_time,
                    "label_end_time": decision_time + timedelta(hours=1),
                    "symbol": "BTCUSDT",
                    "direction": direction,
                    "target": "TP",
                    "ambiguous": False,
                    "exit_index": 0,
                    "realized_gross_return": 0.02,
                    "barrier_upside_rate": 0.02,
                    "barrier_downside_rate": 0.02,
                }
            )
            rows.append(row)

    with pytest.raises(ValueError, match="exit_at_open"):
        chronological_split(pd.DataFrame(rows), purge_rows=0)


def test_policy_metadata_rejects_missing_open_gap_exit_contract() -> None:
    legacy_meta = _gap_split().test_meta.drop(columns=["exit_at_open"])

    with pytest.raises(ValueError, match="exit_at_open"):
        validate_policy_evaluation_metadata(
            legacy_meta,
            context="Missing open-gap metadata",
            horizon_hours=1,
        )


def test_policy_gate_uses_realized_gap_loss_without_capping_at_stress_barrier() -> None:
    metrics = evaluate_policy_model(
        DirectionalModel(),
        _gap_split(),
        PolicyEvaluationConfig(
            fee_rate_round_trip=0.0,
            slippage_rate=0.0,
            stop_gap_reserve_rate=0.01,
            min_net_rr=0.0,
            min_net_ev_r=-10.0,
            horizon_hours=1,
        ),
    )

    assert metrics["policy_trades"] == 1
    assert metrics["policy_realized_mean_r"] == pytest.approx(-4.0 / 3.0)
    assert metrics["policy_realized_total_r"] == pytest.approx(-4.0 / 3.0)


def test_backtest_does_not_double_count_gap_already_in_realized_return() -> None:
    metrics = policy_backtest(
        DirectionalModel(),
        _gap_split(),
        round_trip_cost_bps=0.0,
        stop_gap_reserve_bps=100.0,
        slippage_bps=0.0,
        funding_rate=0.0,
        minimum_net_rr=0.0,
        minimum_net_ev_r=-10.0,
        horizon_hours=1,
    )

    assert metrics["trades"] == 1
    assert metrics["net_return"] == pytest.approx(0.0035 / 0.03 * -0.04)
    assert metrics["mean_net_return_per_trade"] == pytest.approx(-0.04)


def test_plan_outcome_does_not_double_count_gap_already_in_exit_price() -> None:
    estimate = estimate_plan_outcome(
        direction="LONG",
        outcome="SL",
        qty=Decimal("1"),
        entry_price=Decimal("100"),
        exit_price=Decimal("96"),
        stop_price=Decimal("98"),
        actual_stress_loss=Decimal("3"),
        fee_rate_round_trip=Decimal("0"),
        slippage_rate=Decimal("0"),
        stop_gap_reserve_rate=Decimal("0.01"),
        funding_rate=Decimal("0"),
    )

    assert estimate.valuation_status == "VALUED"
    assert estimate.gross_pnl == Decimal("-4")
    assert estimate.estimated_trading_costs == Decimal("0")
    assert estimate.estimated_net_pnl == Decimal("-4")

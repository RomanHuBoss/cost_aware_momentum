from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app.ml.training import MODEL_FEATURE_NAMES, OUTCOME_CLASSES, DatasetSplit
from scripts.backtest import policy_backtest


class FixedEdgeModel:
    classes_ = OUTCOME_CLASSES

    def predict_proba(self, x):
        return np.tile(np.asarray([[0.80, 0.10, 0.10]], dtype=float), (len(x), 1))


class CertainTpModel:
    classes_ = OUTCOME_CLASSES

    def predict_proba(self, x):
        return np.tile(np.asarray([[1.0, 0.0, 0.0]], dtype=float), (len(x), 1))


def _split(meta: pd.DataFrame) -> DatasetSplit:
    meta = meta.copy()
    if "exit_at_open" not in meta.columns:
        meta["exit_at_open"] = False
    paired_rows = meta.to_dict(orient="records")
    for (_, _), cohort in meta.groupby(["decision_time", "symbol"], sort=False):
        directions = set(cohort["direction"].astype(str))
        if directions == {"LONG"}:
            counterpart = cohort.iloc[0].to_dict()
            counterpart.update(
                {
                    "direction": "SHORT",
                    "target": "SL",
                    "realized_gross_return": -0.20,
                    "barrier_upside_rate": 0.001,
                    "barrier_downside_rate": 0.20,
                }
            )
            paired_rows.append(counterpart)
    paired_meta = pd.DataFrame(paired_rows)
    values = np.zeros((len(paired_meta), len(MODEL_FEATURE_NAMES)), dtype=float)
    values[:, -1] = np.where(paired_meta["direction"].eq("LONG"), 1.0, -1.0)
    targets = paired_meta["target"].to_numpy()
    return DatasetSplit(values, targets, values, targets, values, targets, paired_meta)


def _run(model, meta: pd.DataFrame, *, horizon_hours: int = 1, round_trip_cost_bps: float = 0.0):
    return policy_backtest(
        model,
        _split(meta),
        round_trip_cost_bps=round_trip_cost_bps,
        stop_gap_reserve_bps=0.0,
        minimum_net_rr=0.0,
        minimum_net_ev_r=-1.0,
        horizon_hours=horizon_hours,
    )


def test_backtest_aggregates_simultaneous_positions_before_compounding() -> None:
    decision_time = datetime(2025, 1, 1, tzinfo=UTC)
    meta = pd.DataFrame(
        [
            {
                "decision_time": decision_time,
                "open_time": decision_time,
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "target": "TP",
                "exit_index": 0,
                "realized_gross_return": 0.10,
                "barrier_upside_rate": 0.10,
                "barrier_downside_rate": 0.05,
            },
            {
                "decision_time": decision_time,
                "open_time": decision_time,
                "symbol": "ETHUSDT",
                "direction": "LONG",
                "target": "SL",
                "exit_index": 0,
                "realized_gross_return": -0.10,
                "barrier_upside_rate": 0.10,
                "barrier_downside_rate": 0.05,
            },
        ]
    )

    metrics = _run(FixedEdgeModel(), meta)

    assert metrics["net_return"] == pytest.approx(0.0)
    assert metrics["portfolio_periods"] == 1
    assert metrics["max_concurrent_trades"] == 2


def test_backtest_drawdown_includes_first_period_loss() -> None:
    decision_time = datetime(2025, 1, 1, tzinfo=UTC)
    meta = pd.DataFrame(
        [
            {
                "decision_time": decision_time,
                "open_time": decision_time,
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "target": "SL",
                "exit_index": 0,
                "realized_gross_return": -0.10,
                "barrier_upside_rate": 0.10,
                "barrier_downside_rate": 0.05,
            }
        ]
    )

    metrics = _run(FixedEdgeModel(), meta)

    assert metrics["max_drawdown"] == pytest.approx(-0.0035 / 0.05 * 0.10)


def test_backtest_blocks_overlapping_positions_for_the_same_symbol() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    meta = pd.DataFrame(
        [
            {
                "decision_time": start,
                "open_time": start,
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "target": "TP",
                "exit_index": 1,
                "realized_gross_return": 0.10,
                "barrier_upside_rate": 0.10,
                "barrier_downside_rate": 0.05,
            },
            {
                "decision_time": start + timedelta(hours=1),
                "open_time": start + timedelta(hours=1),
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "target": "TP",
                "exit_index": 1,
                "realized_gross_return": 0.10,
                "barrier_upside_rate": 0.10,
                "barrier_downside_rate": 0.05,
            },
        ]
    )

    metrics = _run(FixedEdgeModel(), meta, horizon_hours=2)

    # Production acceptance permits only one active plan per symbol/account scope.
    # The second hourly BTC candidate must therefore be blocked until the first exits.
    assert metrics["trades"] == 1
    assert metrics["overlap_blocked_trades"] == 1
    assert metrics["net_return"] == pytest.approx(0.0035 / 0.05 * 0.10)
    assert metrics["capital_sleeves"] == 2
    assert metrics["max_concurrent_trades"] == 1


def test_direction_is_selected_by_ev_r_not_raw_expected_rate() -> None:
    decision_time = datetime(2025, 1, 1, tzinfo=UTC)
    meta = pd.DataFrame(
        [
            {
                "decision_time": decision_time,
                "open_time": decision_time,
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "target": "SL",
                "exit_index": 0,
                "realized_gross_return": -0.10,
                "barrier_upside_rate": 0.03,
                "barrier_downside_rate": 0.10,
            },
            {
                "decision_time": decision_time,
                "open_time": decision_time,
                "symbol": "BTCUSDT",
                "direction": "SHORT",
                "target": "TP",
                "exit_index": 0,
                "realized_gross_return": 0.02,
                "barrier_upside_rate": 0.02,
                "barrier_downside_rate": 0.02,
            },
        ]
    )

    metrics = _run(CertainTpModel(), meta)

    # LONG has the larger raw expected rate (3% vs 2%), but SHORT has the larger
    # EV/R (1.0 vs 0.3) and therefore matches the deployed policy.
    assert metrics["net_return"] == pytest.approx(0.0035 / 0.02 * 0.02)
    assert metrics["win_rate"] == pytest.approx(1.0)


def test_exit_fee_is_charged_on_actual_exit_notional() -> None:
    decision_time = datetime(2025, 1, 1, tzinfo=UTC)
    meta = pd.DataFrame(
        [
            {
                "decision_time": decision_time,
                "open_time": decision_time,
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "target": "TP",
                "exit_index": 0,
                "realized_gross_return": 0.10,
                "barrier_upside_rate": 0.10,
                "barrier_downside_rate": 0.05,
            }
        ]
    )

    metrics = _run(CertainTpModel(), meta, round_trip_cost_bps=100.0)

    # 1% round trip means two 0.5% legs: 0.5% * (entry 1.0 + exit 1.1) = 1.05%.
    assert metrics["mean_net_return_per_trade"] == pytest.approx(0.0895)
    stress_downside = 0.05 + 0.005 * (1.0 + 0.95)
    assert metrics["net_return"] == pytest.approx(0.0035 / stress_downside * 0.0895)


def test_backtest_allows_same_symbol_reentry_at_modeled_exit_boundary() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    meta = pd.DataFrame(
        [
            {
                "decision_time": start,
                "open_time": start,
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "target": "TP",
                "exit_index": 0,
                "realized_gross_return": 0.10,
                "barrier_upside_rate": 0.10,
                "barrier_downside_rate": 0.05,
            },
            {
                "decision_time": start + timedelta(hours=1),
                "open_time": start + timedelta(hours=1),
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "target": "TP",
                "exit_index": 0,
                "realized_gross_return": 0.10,
                "barrier_upside_rate": 0.10,
                "barrier_downside_rate": 0.05,
            },
        ]
    )

    metrics = _run(FixedEdgeModel(), meta, horizon_hours=2)

    assert metrics["trades"] == 2
    assert metrics["overlap_blocked_trades"] == 0
    assert metrics["max_concurrent_trades"] == 1

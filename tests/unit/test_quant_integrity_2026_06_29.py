from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from app.api.v1.trades import validate_close_fill_time
from app.ml.training import (
    OUTCOME_CLASSES,
    DatasetSplit,
    PolicyEvaluationConfig,
    evaluate_policy_model,
    validate_policy_evaluation_metadata,
)
from app.risk.math import assess_liquidation_proximity
from app.services.execution import funding_rate_for_plan
from app.services.outcomes import OutcomeBar, evaluate_barrier_outcome


class _FixedModel:
    classes_ = OUTCOME_CLASSES

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        return np.tile(np.array([[1.0, 0.0, 0.0]]), (len(x), 1))


def _policy_split() -> DatasetSplit:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for hour in range(2):
        decision = start + timedelta(hours=hour)
        for direction in ("LONG", "SHORT"):
            rows.append(
                {
                    "decision_time": decision,
                    "label_end_time": decision + timedelta(hours=2),
                    "symbol": "BTCUSDT",
                    "direction": direction,
                    "target": "TP",
                    "exit_index": 1,
                    "exit_at_open": False,
                    "realized_gross_return": 0.01,
                    "barrier_upside_rate": 0.01,
                    "barrier_downside_rate": 0.01,
                }
            )
    meta = pd.DataFrame(rows)
    x = np.zeros((len(meta), 1))
    y = np.array(meta["target"], dtype=str)
    return DatasetSplit(x, y, x, y, x, y, meta)


def test_policy_evaluation_blocks_same_symbol_overlap_like_live_acceptance() -> None:
    metrics = evaluate_policy_model(
        _FixedModel(),
        _policy_split(),
        PolicyEvaluationConfig(
            fee_rate_round_trip=0.0,
            slippage_rate=0.0,
            stop_gap_reserve_rate=0.0,
            min_net_rr=0.0,
            min_net_ev_r=0.0,
            timeout_return_rate=0.0,
        ),
        horizon_hours=2,
    )
    assert metrics["policy_metric_schema"] == "exit-time-open-gap-single-symbol-cohort-v7"
    assert metrics["policy_capital_sleeves"] == 2
    assert metrics["policy_trades"] == 1
    assert metrics["policy_overlap_blocked_trades"] == 1
    assert metrics["policy_realized_total_r"] == pytest.approx(0.5)


def test_policy_metadata_rejects_tp_below_the_declared_barrier() -> None:
    frame = _policy_split().test_meta.iloc[:2].copy()
    frame["realized_gross_return"] = 0.005
    with pytest.raises(ValueError, match="inconsistent with its barrier"):
        validate_policy_evaluation_metadata(
            frame,
            context="test",
            horizon_hours=2,
            require_barrier_return_consistency=True,
        )


def test_policy_metadata_rejects_label_end_that_does_not_equal_horizon() -> None:
    frame = _policy_split().test_meta.iloc[:2].copy()
    frame["label_end_time"] = pd.to_datetime(frame["decision_time"], utc=True) + timedelta(hours=3)
    with pytest.raises(ValueError, match="configured label horizon"):
        validate_policy_evaluation_metadata(frame, context="test", horizon_hours=2)


def test_fractional_leverage_is_not_silently_truncated() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        assess_liquidation_proximity(entry="100", stop="95", leverage=1.9)  # type: ignore[arg-type]


def test_outcome_rejects_non_hourly_bar_in_hourly_evaluator() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bar = OutcomeBar(1, start, start + timedelta(minutes=30), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"))
    with pytest.raises(ValueError, match="duration"):
        evaluate_barrier_outcome(
            [bar], direction="LONG", entry=Decimal("100"), stop=Decimal("90"),
            take_profit=Decimal("110"), window_start=start, horizon_end=start + timedelta(minutes=30)
        )


def test_outcome_rejects_close_outside_high_low_range() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bar = OutcomeBar(1, start, start + timedelta(hours=1), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("102"))
    with pytest.raises(ValueError, match="OHLC"):
        evaluate_barrier_outcome(
            [bar], direction="LONG", entry=Decimal("100"), stop=Decimal("90"),
            take_profit=Decimal("110"), window_start=start, horizon_end=start + timedelta(hours=1)
        )


def test_manual_fill_cannot_be_recorded_in_the_future() -> None:
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    with pytest.raises(ValueError, match="future"):
        validate_close_fill_time(
            now + timedelta(seconds=1),
            entry_time=now - timedelta(hours=1),
            now=now,
        )


def test_plan_funding_is_reprojected_from_the_plan_time() -> None:
    from app.services.execution import funding_rate_for_plan

    start = datetime(2026, 1, 1, 2, tzinfo=UTC)
    assert funding_rate_for_plan(
        start_time=start,
        horizon_hours=4,
        next_settlement=start + timedelta(hours=1),
        interval_minutes=120,
        current_rate=Decimal("0.0001"),
    ) == Decimal("0.0002")


def test_position_plan_blocks_fractional_leverage_without_truncation() -> None:
    from app.risk.math import CostScenario, InstrumentConstraints, calculate_position_plan

    plan = calculate_position_plan(
        effective_capital=Decimal("1000"),
        risk_rate=Decimal("0.01"),
        entry=Decimal("100"),
        stop=Decimal("99"),
        direction="LONG",
        costs=CostScenario(Decimal("0"), Decimal("0"), Decimal("0")),
        constraints=InstrumentConstraints(
            Decimal("0.001"), Decimal("0.001"), Decimal("5"), None, Decimal("100")
        ),
        leverage=1.9,  # type: ignore[arg-type]
    )
    assert plan.status == "BLOCKED_INVALID_INPUT"
    assert any("positive integer" in warning for warning in plan.warnings)


def test_timeout_metadata_cannot_cross_a_barrier() -> None:
    frame = _policy_split().test_meta.iloc[:2].copy()
    frame["target"] = "TIMEOUT"
    frame["realized_gross_return"] = frame["barrier_upside_rate"]
    with pytest.raises(ValueError, match="inconsistent with its barrier"):
        validate_policy_evaluation_metadata(
            frame,
            context="test",
            horizon_hours=2,
            require_barrier_return_consistency=True,
        )


def test_plan_funding_fails_closed_when_interval_is_unknown() -> None:
    start = datetime(2026, 1, 1, 2, tzinfo=UTC)
    with pytest.raises(ValueError, match="interval"):
        funding_rate_for_plan(
            start_time=start,
            horizon_hours=4,
            next_settlement=start + timedelta(hours=1),
            interval_minutes=None,
            current_rate=Decimal("0.0001"),
        )

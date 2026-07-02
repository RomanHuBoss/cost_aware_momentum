from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest
from sqlalchemy.dialects import postgresql

from app.db.models import PlanOutcome
from app.ml.training import (
    MODEL_FEATURE_NAMES,
    OUTCOME_CLASSES,
    DatasetSplit,
    PolicyEvaluationConfig,
    evaluate_policy_model,
)
from app.risk.math import projected_funding_rate
from app.services.execution import latest_spec
from app.services.outcomes import _record_plan_outcome

BASE = datetime(2026, 7, 2, 0, tzinfo=UTC)
D = Decimal


class _CertainTpModel:
    classes_ = OUTCOME_CLASSES

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        return np.tile(np.asarray([[1.0, 0.0, 0.0]], dtype=float), (len(x), 1))


class _OutcomeSession:
    def __init__(self) -> None:
        self.row = None

    def add(self, row: object) -> None:
        self.row = row

    async def flush(self) -> None:
        return None


async def _none(*_args: object, **_kwargs: object) -> None:
    return None


@pytest.mark.asyncio
async def test_late_execution_plan_does_not_reuse_pre_entry_signal_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later plan has no observed barrier path beginning at its own entry time."""

    monkeypatch.setattr("app.services.outcomes.append_audit_event", _none)
    signal = SimpleNamespace(
        id=uuid4(),
        direction="LONG",
        event_time=BASE,
        entry_reference=D("100"),
        stop_loss=D("98"),
    )
    signal_outcome = SimpleNamespace(
        id=uuid4(),
        outcome="TP",
        exit_price=D("104"),
        exit_time=BASE + timedelta(hours=2),
    )
    plan = SimpleNamespace(
        id=uuid4(),
        version=2,
        qty=D("1"),
        actual_stress_loss=D("3"),
        sizing_snapshot={
            "entry_price": "101",
            "planning_time": (BASE + timedelta(minutes=30)).isoformat(),
            "costs": {
                "fee_rate_round_trip": "0.001",
                "slippage_rate": "0.0005",
                "stop_gap_reserve_rate": "0.001",
                "funding_rate_per_settlement": "0.0001",
                "funding_next_settlement": (BASE + timedelta(hours=1)).isoformat(),
                "funding_interval_minutes": 480,
            },
        },
    )

    row = await _record_plan_outcome(
        _OutcomeSession(),
        signal=signal,
        signal_outcome=signal_outcome,
        plan=plan,
        actor="pytest",
    )

    assert row.valuation_status == "PATH_UNAVAILABLE"
    assert row.qty == D("1")
    assert row.gross_pnl == D("0")
    assert row.estimated_net_pnl == D("0")
    assert row.counterfactual_r is None
    assert row.cost_assumptions["valuation_start_time"] == (
        BASE + timedelta(minutes=30)
    ).isoformat()
    assert "price path" in row.cost_assumptions["validation_error"]


def test_plan_outcome_schema_supports_path_unavailable_status() -> None:
    status_constraint = next(
        constraint
        for constraint in PlanOutcome.__table__.constraints
        if constraint.name == "ck_plan_outcomes_plan_outcome_valuation_status"
    )

    assert "PATH_UNAVAILABLE" in str(status_constraint.sqltext)


def test_profit_factor_does_not_net_simultaneous_winner_and_loser() -> None:
    rows: list[dict[str, object]] = []
    for symbol, long_target, long_return in (
        ("WINUSDT", "TP", 0.01),
        ("LOSSUSDT", "SL", -0.01),
    ):
        rows.extend(
            [
                {
                    "decision_time": BASE,
                    "label_end_time": BASE + timedelta(hours=1),
                    "symbol": symbol,
                    "direction": "LONG",
                    "target": long_target,
                    "exit_index": 0,
                    "exit_at_open": False,
                    "realized_gross_return": long_return,
                    "barrier_upside_rate": 0.01,
                    "barrier_downside_rate": 0.01,
                },
                {
                    "decision_time": BASE,
                    "label_end_time": BASE + timedelta(hours=1),
                    "symbol": symbol,
                    "direction": "SHORT",
                    "target": "SL",
                    "exit_index": 0,
                    "exit_at_open": False,
                    "realized_gross_return": -0.01,
                    "barrier_upside_rate": 0.01,
                    "barrier_downside_rate": 0.01,
                },
            ]
        )
    meta = pd.DataFrame(rows)
    values = np.zeros((len(meta), len(MODEL_FEATURE_NAMES)), dtype=float)
    values[:, -1] = np.where(meta["direction"].eq("LONG"), 1.0, -1.0)
    targets = meta["target"].to_numpy()
    split = DatasetSplit(values, targets, values, targets, values, targets, meta)
    metrics = evaluate_policy_model(
        _CertainTpModel(),
        split,
        PolicyEvaluationConfig(
            fee_rate_round_trip=0.0,
            slippage_rate=0.0,
            stop_gap_reserve_rate=0.0,
            min_net_rr=0.0,
            min_net_ev_r=-1.0,
            timeout_return_rate=0.0,
            horizon_hours=1,
        ),
    )

    assert metrics["policy_realized_total_r"] == pytest.approx(0.0)
    assert metrics["policy_gross_gain_r"] == pytest.approx(0.5)
    assert metrics["policy_gross_loss_r"] == pytest.approx(0.5)
    assert metrics["policy_profit_factor"] == pytest.approx(1.0)


class _CountingDateTime(datetime):
    comparisons = 0

    def __le__(self, other: object) -> bool:
        type(self).comparisons += 1
        if type(self).comparisons > 3:
            raise AssertionError("funding projection iterated settlement-by-settlement")
        return super().__le__(other)

    def __add__(self, other: object):
        result = super().__add__(other)
        if isinstance(result, datetime):
            return type(self).fromtimestamp(result.timestamp(), tz=result.tzinfo)
        return result


def test_funding_projection_advances_stale_anchor_arithmetically() -> None:
    _CountingDateTime.comparisons = 0
    old_anchor = _CountingDateTime(2020, 1, 1, tzinfo=UTC)

    result = projected_funding_rate(
        start_time=BASE,
        horizon_hours=8,
        next_settlement=old_anchor,
        interval_minutes=1,
        current_rate=D("0.0001"),
    )

    assert result == D("0.048")
    assert _CountingDateTime.comparisons <= 3


class _ScalarResult:
    def scalar_one_or_none(self):
        return None


class _CaptureSession:
    def __init__(self) -> None:
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _ScalarResult()


@pytest.mark.asyncio
async def test_execution_spec_query_respects_receipt_cutoff() -> None:
    session = _CaptureSession()

    await latest_spec(session, "BTCUSDT", cutoff=BASE)

    compiled = session.statement.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": False},
    )
    sql = str(compiled)
    assert "reference.instrument_spec_history.valid_from <=" in sql
    assert "reference.instrument_spec_history.received_at <=" in sql
    assert BASE in compiled.params.values()


def test_frontend_marks_unavailable_path_without_numeric_pnl() -> None:
    source = (Path(__file__).parents[2] / "web/js/app.js").read_text(encoding="utf-8")

    assert "PATH_UNAVAILABLE: 'Нет ценового пути от времени плана'" in source
    assert "planOutcome?.valuation_status === 'VALUED'" in source

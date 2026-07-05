from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest

import app.services.execution as execution
from app.config import Settings
from app.ml.data_profile import profile_from_symbol_rows
from app.ml.lifecycle import ModelCandidate, evaluate_quality_gate
from app.ml.training import (
    MODEL_FEATURE_NAMES,
    OUTCOME_CLASSES,
    DatasetSplit,
    PolicyEvaluationConfig,
    evaluate_policy_model,
)
from app.risk.math import CostScenario, net_rr_and_ev

D = Decimal


def _candidate(tmp_path: Path, metrics: dict[str, object]) -> ModelCandidate:
    now = datetime(2026, 1, 1, tzinfo=UTC)
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


def _passing_metrics() -> dict[str, object]:
    return {
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
        "entry_execution_model": {
            "schema": "directional-half-spread-on-next-hour-open-v1",
            "entry_spread_bps": 18.0,
        },
        "policy_metric_schema": "decision-open-directional-spread-entry-exit-time-cohort-v13",
        "policy_horizon_hours": 8,
        "policy_capital_sleeves": 8,
        "policy_horizon_phase_count": 8,
        "policy_horizon_phase_expected": 8,
        "policy_candidates": 1_000,
        "policy_trades": 80,
        "policy_trade_rate": 0.08,
        "policy_cohorts": 80,
        "policy_independent_cohorts": 80,
        "policy_independent_mean_r": 0.04,
        "policy_mean_r_lcb": 0.01,
        "policy_mean_r_confidence_level": 0.95,
        "policy_mean_r_bootstrap_samples": 2_000,
        "policy_mean_r_bootstrap_block_length": 1,
        "policy_mean_r_uncertainty_schema": "all-horizon-phases-circular-moving-block-v2",
        "policy_realized_mean_r": 0.05,
        "policy_profit_factor": 1.2,
        "policy_max_drawdown_r": 5.0,
    }


def test_favorable_funding_cannot_improve_pretrade_rr_or_ev_without_exit_timing() -> None:
    zero = net_rr_and_ev(
        entry=D("100"),
        stop=D("102"),
        take_profit=D("96"),
        direction="SHORT",
        costs=CostScenario(D("0"), D("0"), D("0"), D("0")),
        p_tp=0.5,
        p_sl=0.3,
        p_timeout=0.2,
    )
    favorable = net_rr_and_ev(
        entry=D("100"),
        stop=D("102"),
        take_profit=D("96"),
        direction="SHORT",
        costs=CostScenario(D("0"), D("0"), D("0"), D("0.01")),
        p_tp=0.5,
        p_sl=0.3,
        p_timeout=0.2,
    )

    assert favorable == zero


def test_policy_metrics_weight_hourly_cohorts_not_raw_symbol_count() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    probabilities: list[list[float]] = []

    def add_symbol(decision_time: datetime, symbol: str, gross: float) -> None:
        target = "TP" if gross > 0 else "TIMEOUT"
        rows.extend(
            [
                {
                    "decision_time": decision_time,
                    "label_end_time": decision_time + timedelta(hours=1),
                    "symbol": symbol,
                    "direction": "LONG",
                    "target": target,
                    "exit_index": 0,
                    "exit_at_open": False,
                    "realized_gross_return": gross,
                    "barrier_upside_rate": 0.01,
                    "barrier_downside_rate": 0.01,
                },
                {
                    "decision_time": decision_time,
                    "label_end_time": decision_time + timedelta(hours=1),
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
        probabilities.extend([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])

    add_symbol(start, "WINUSDT", 0.01)  # +1 R in the first hourly cohort.
    for index in range(9):
        add_symbol(start + timedelta(hours=1), f"LOSS{index}USDT", -0.002)  # -0.2 R each.

    meta = pd.DataFrame(rows)
    values = np.zeros((len(meta), len(MODEL_FEATURE_NAMES)), dtype=float)
    values[:, -1] = np.where(meta["direction"].eq("LONG"), 1.0, -1.0)

    class RowProbabilityModel:
        classes_ = OUTCOME_CLASSES

        def predict_proba(self, _: np.ndarray) -> np.ndarray:
            return np.asarray(probabilities, dtype=float)

    split = DatasetSplit(
        values,
        meta["target"].to_numpy(),
        values,
        meta["target"].to_numpy(),
        values,
        meta["target"].to_numpy(),
        meta,
    )
    metrics = evaluate_policy_model(
        RowProbabilityModel(),
        split,
        PolicyEvaluationConfig(
            fee_rate_round_trip=0.0,
            slippage_rate=0.0,
            stop_gap_reserve_rate=0.0,
            min_net_rr=0.0,
            min_net_ev_r=-100.0,
            timeout_return_rate=0.0,
        ),
    )

    assert metrics["policy_cohorts"] == 2
    assert metrics["policy_realized_mean_r"] == pytest.approx(0.4)


def test_quality_gate_uses_independent_cohort_threshold(tmp_path: Path) -> None:
    metrics = _passing_metrics()
    metrics["policy_trades"] = 80
    metrics["policy_cohorts"] = 80
    metrics["policy_independent_cohorts"] = 10

    result = evaluate_quality_gate(
        _candidate(tmp_path, metrics),
        Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            auto_train_min_policy_trades=50,
            auto_train_min_policy_cohorts=10,
        ),
    )

    assert result["passed"] is True
    assert result["absolute"]["min_policy_cohorts"] == 10


def test_quality_gate_rejects_many_cross_sectional_trades_from_one_hour(tmp_path: Path) -> None:
    metrics = _passing_metrics()
    metrics["policy_trades"] = 100
    metrics["policy_trade_rate"] = 0.1
    metrics["policy_cohorts"] = 1
    metrics["policy_independent_cohorts"] = 1

    result = evaluate_quality_gate(
        _candidate(tmp_path, metrics),
        Settings(database_url="postgresql+psycopg://u:p@localhost/db"),
    )

    assert result["passed"] is False
    assert "policy_independent_cohort_count_below_minimum" in result["reasons"]
    assert "invalid_policy_metric_schema" not in result["reasons"]


class _Result:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalars(self) -> _Result:
        return self

    def all(self) -> object:
        return self.value

    def scalar_one_or_none(self) -> object:
        return self.value


@pytest.mark.asyncio
async def test_bulk_recalculation_skips_accepted_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    signal = SimpleNamespace(id="signal-1")
    old_plan = SimpleNamespace(status="ACCEPTED", superseded_by_id=None)
    session = SimpleNamespace(execute=AsyncMock(side_effect=[_Result([signal]), _Result(old_plan)]))
    create = AsyncMock()
    monkeypatch.setattr(execution, "create_execution_plan", create)

    plans = await execution.recalculate_all_active_signals(
        session,
        profile=SimpleNamespace(id="profile-1"),
        settings=SimpleNamespace(),
        actor="test",
    )

    assert plans == []
    create.assert_not_awaited()
    assert old_plan.status == "ACCEPTED"


@pytest.mark.asyncio
async def test_plan_version_allocation_acquires_transaction_lock_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = AsyncMock()
    monkeypatch.setattr(execution, "acquire_advisory_xact_lock", lock)
    session = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("stop after lock")))

    with pytest.raises(RuntimeError, match="stop after lock"):
        await execution.create_execution_plan(
            session,
            signal=SimpleNamespace(id="signal-1"),
            profile=SimpleNamespace(id="profile-1"),
            settings=SimpleNamespace(),
        )

    lock.assert_awaited_once_with(
        session,
        "execution-plan-version",
        "signal-1:profile-1",
    )


def test_default_horizon_must_be_positive_and_declared() -> None:
    with pytest.raises(ValueError, match="DEFAULT_HORIZON_HOURS"):
        Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            horizons_hours=[4, 8],
            default_horizon_hours=0,
        )
    with pytest.raises(ValueError, match="DEFAULT_HORIZON_HOURS"):
        Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            horizons_hours=[4, 8],
            default_horizon_hours=12,
        )

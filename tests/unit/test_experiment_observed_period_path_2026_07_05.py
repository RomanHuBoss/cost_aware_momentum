from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.ml.mtm import INTRAHORIZON_MTM_PATH_SCHEMA_VERSION
from app.ml.training import MODEL_FEATURE_NAMES, OUTCOME_CLASSES, DatasetSplit
from app.services.experiment_ledger import _trial_evidence_from_success
from scripts.backtest import policy_backtest


class CertainTpModel:
    classes_ = OUTCOME_CLASSES

    def predict_proba(self, x):
        return np.tile(np.asarray([[1.0, 0.0, 0.0]], dtype=float), (len(x), 1))


def _paired_split(decision_times: list[datetime]) -> DatasetSplit:
    rows: list[dict[str, object]] = []
    for decision_time in decision_times:
        rows.extend(
            [
                {
                    "decision_time": decision_time,
                    "symbol": "BTCUSDT",
                    "direction": "LONG",
                    "target": "TP",
                    "exit_index": 0,
                    "exit_at_open": False,
                    "realized_gross_return": 0.10,
                    "intrahorizon_mark_to_market_path_complete": True,
                    "intrahorizon_mark_to_market_schema": (
                        INTRAHORIZON_MTM_PATH_SCHEMA_VERSION
                    ),
                    "intrahorizon_mark_to_market_path": [
                        {
                            "timestamp": decision_time.isoformat(),
                            "gross_return_rate": 0.0,
                            "funding_return_rate": 0.0,
                        },
                        {
                            "timestamp": (decision_time + timedelta(hours=1)).isoformat(),
                            "gross_return_rate": 0.10,
                            "funding_return_rate": 0.0,
                        },
                    ],
                    "barrier_upside_rate": 0.10,
                    "barrier_downside_rate": 0.05,
                },
                {
                    "decision_time": decision_time,
                    "symbol": "BTCUSDT",
                    "direction": "SHORT",
                    "target": "SL",
                    "exit_index": 0,
                    "exit_at_open": False,
                    "realized_gross_return": -0.20,
                    "intrahorizon_mark_to_market_path_complete": True,
                    "intrahorizon_mark_to_market_schema": (
                        INTRAHORIZON_MTM_PATH_SCHEMA_VERSION
                    ),
                    "intrahorizon_mark_to_market_path": [
                        {
                            "timestamp": decision_time.isoformat(),
                            "gross_return_rate": 0.0,
                            "funding_return_rate": 0.0,
                        },
                        {
                            "timestamp": (decision_time + timedelta(hours=1)).isoformat(),
                            "gross_return_rate": -0.20,
                            "funding_return_rate": 0.0,
                        },
                    ],
                    "barrier_upside_rate": 0.001,
                    "barrier_downside_rate": 0.20,
                },
            ]
        )
    meta = pd.DataFrame(rows)
    values = np.zeros((len(meta), len(MODEL_FEATURE_NAMES)), dtype=float)
    values[:, -1] = np.where(meta["direction"].eq("LONG"), 1.0, -1.0)
    targets = meta["target"].to_numpy()
    return DatasetSplit(values, targets, values, targets, values, targets, meta)


def test_experiment_return_path_omits_unobserved_calendar_gap() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    split = _paired_split([start, start + timedelta(hours=100)])

    metrics = policy_backtest(
        CertainTpModel(),
        split,
        round_trip_cost_bps=0.0,
        stop_gap_reserve_bps=0.0,
        minimum_net_rr=0.0,
        minimum_net_ev_r=-1.0,
        horizon_hours=1,
        include_experiment_evidence=True,
    )

    evidence = metrics["experiment_evidence"]
    timestamps = [pd.Timestamp(row["timestamp"]) for row in evidence["period_returns"]]
    assert timestamps == [
        pd.Timestamp(start),
        pd.Timestamp(start + timedelta(hours=1)),
        pd.Timestamp(start + timedelta(hours=100)),
        pd.Timestamp(start + timedelta(hours=101)),
    ]
    assert evidence["observed_opportunity_period_count"] == 2
    assert evidence["covered_period_count"] == 4
    assert evidence["omitted_unobserved_calendar_period_count"] == 98


def test_experiment_net_path_recognizes_entry_costs_before_exit() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    metrics = policy_backtest(
        CertainTpModel(),
        _paired_split([start]),
        round_trip_cost_bps=20.0,
        slippage_bps=10.0,
        stop_gap_reserve_bps=0.0,
        minimum_net_rr=0.0,
        minimum_net_ev_r=-1.0,
        horizon_hours=1,
        include_experiment_evidence=True,
    )

    returns = [
        row["return"] for row in metrics["experiment_evidence"]["period_returns"]
    ]
    # 10 bps entry fee + 10 bps conservative slippage are recognized at decision.
    # The 11 bps exit fee on the 1.10 exit-notional ratio is recognized at exit.
    assert returns[0] == pytest.approx(-0.002)
    assert returns[1] == pytest.approx(0.0989 / 0.998)
    assert metrics["net_return"] == pytest.approx(0.0969)


def test_legacy_synthetic_calendar_return_schema_is_rejected() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    row = SimpleNamespace(
        trial_id="11111111-1111-1111-1111-111111111111",
        configuration_hash="a" * 64,
        evidence={
            "period_return_schema": "hourly-realized-capital-return-path-v1",
            "period_returns": [
                {"timestamp": start.isoformat(), "return": 0.0},
                {"timestamp": (start + timedelta(hours=1)).isoformat(), "return": 0.01},
            ],
        },
    )

    with pytest.raises(ValueError, match="period return schema"):
        _trial_evidence_from_success(row)


def test_exit_realized_v2_experiment_return_schema_is_rejected() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    row = SimpleNamespace(
        trial_id="11111111-1111-1111-1111-111111111111",
        configuration_hash="a" * 64,
        evidence={
            "period_return_schema": (
                "observed-opportunity-covered-hourly-capital-return-path-v2"
            ),
            "period_returns": [
                {"timestamp": start.isoformat(), "return": 0.0},
                {"timestamp": (start + timedelta(hours=1)).isoformat(), "return": 0.01},
            ],
        },
    )

    with pytest.raises(ValueError, match="period return schema"):
        _trial_evidence_from_success(row)


def test_experiment_evidence_fails_closed_without_hourly_mark_to_market_path() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    split = _paired_split([start])
    split = replace(
        split,
        test_meta=split.test_meta.drop(
            columns=[
                "intrahorizon_mark_to_market_path_complete",
                "intrahorizon_mark_to_market_schema",
                "intrahorizon_mark_to_market_path",
            ]
        ),
    )

    with pytest.raises(ValueError, match="missing intrahorizon mark-to-market columns"):
        policy_backtest(
            CertainTpModel(),
            split,
            round_trip_cost_bps=0.0,
            stop_gap_reserve_bps=0.0,
            minimum_net_rr=0.0,
            minimum_net_ev_r=-1.0,
            horizon_hours=1,
            include_experiment_evidence=True,
        )


@pytest.mark.asyncio
async def test_promotion_gate_blocks_invalid_period_return_evidence(monkeypatch) -> None:
    from app.services import model_promotion

    async def invalid_report(*args, **kwargs):
        raise ValueError("Successful experiment period return schema is unsupported")

    monkeypatch.setattr(model_promotion, "experiment_governance_report", invalid_report)

    gate = await model_promotion.evaluate_experiment_promotion_gate(
        SimpleNamespace(),
        experiment_family="family-a",
        model_version="model-v1",
        model_sha256="a" * 64,
        horizon_hours=8,
    )

    assert gate["passed"] is False
    assert gate["reasons"] == ["invalid_experiment_return_evidence"]
    assert "unsupported" in gate["error"]

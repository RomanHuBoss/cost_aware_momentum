from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest

from app.bybit.client import BybitClient, BybitResponse
from app.ml.funding import (
    HISTORICAL_FUNDING_SCHEMA_VERSION,
    HistoricalFundingTimeline,
)
from app.ml.training import historical_funding_components


def _funding_frame(*rows: tuple[str, datetime, float]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["symbol", "funding_time", "rate"])


def test_funding_replay_uses_open_closed_settlement_window() -> None:
    timeline = HistoricalFundingTimeline(
        _funding_frame(
            ("BTCUSDT", datetime(2026, 1, 1, 0, tzinfo=UTC), 0.0010),
            ("BTCUSDT", datetime(2026, 1, 1, 8, tzinfo=UTC), -0.0004),
            ("BTCUSDT", datetime(2026, 1, 1, 16, tzinfo=UTC), 0.0002),
        ),
        interval_minutes={"BTCUSDT": 480},
    )

    aggregate = timeline.aggregate(
        "BTCUSDT",
        start_time=datetime(2026, 1, 1, 0, tzinfo=UTC),
        end_time=datetime(2026, 1, 1, 16, tzinfo=UTC),
    )

    assert aggregate.settlements == 2
    assert aggregate.cumulative_rate == pytest.approx(-0.0002)
    assert timeline.describe()["schema"] == HISTORICAL_FUNDING_SCHEMA_VERSION


def test_funding_replay_fails_closed_on_missing_expected_settlement() -> None:
    timeline = HistoricalFundingTimeline(
        _funding_frame(
            ("BTCUSDT", datetime(2026, 1, 1, 0, tzinfo=UTC), 0.0010),
            ("BTCUSDT", datetime(2026, 1, 1, 16, tzinfo=UTC), 0.0002),
        ),
        interval_minutes={"BTCUSDT": 480},
    )

    with pytest.raises(ValueError, match="missing expected settlement"):
        timeline.aggregate(
            "BTCUSDT",
            start_time=datetime(2026, 1, 1, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 16, tzinfo=UTC),
        )


def test_policy_funding_components_preserve_long_short_cashflow_signs() -> None:
    meta = pd.DataFrame(
        {
            "direction": ["LONG", "SHORT"],
            "historical_funding_timeline_complete": [True, True],
            "historical_funding_horizon_rate": [0.0010, 0.0010],
            "historical_funding_horizon_settlements": [2, 2],
            "historical_funding_realized_rate": [0.0004, 0.0004],
            "historical_funding_realized_settlements": [1, 1],
        }
    )

    recognized, adverse, realized, schema = historical_funding_components(
        meta,
        context="test policy",
    )

    np.testing.assert_allclose(recognized, [-0.0010, 0.0])
    np.testing.assert_allclose(adverse, [0.0010, 0.0])
    np.testing.assert_allclose(realized, [-0.0004, 0.0004])
    assert schema == HISTORICAL_FUNDING_SCHEMA_VERSION


def test_policy_funding_components_reject_realized_count_beyond_horizon() -> None:
    meta = pd.DataFrame(
        {
            "direction": ["LONG"],
            "historical_funding_timeline_complete": [True],
            "historical_funding_horizon_rate": [0.0010],
            "historical_funding_horizon_settlements": [1],
            "historical_funding_realized_rate": [0.0010],
            "historical_funding_realized_settlements": [2],
        }
    )

    with pytest.raises(ValueError, match="exceed the horizon"):
        historical_funding_components(meta, context="test policy")


@pytest.mark.asyncio
async def test_bybit_funding_history_uses_bounded_end_time_pagination() -> None:
    client = object.__new__(BybitClient)
    client._get = AsyncMock(  # type: ignore[method-assign]
        return_value=BybitResponse(
            result={"list": [{"fundingRateTimestamp": "1767254400000", "fundingRate": "0.0001"}]},
            server_time_ms=None,
            raw={},
        )
    )

    result = await client.get_funding_history(
        "BTCUSDT",
        limit=500,
        end_ms=1_767_254_400_000,
    )

    assert len(result) == 1
    client._get.assert_awaited_once_with(  # type: ignore[attr-defined]
        "/v5/market/funding/history",
        {
            "category": "linear",
            "symbol": "BTCUSDT",
            "limit": 200,
            "startTime": None,
            "endTime": 1_767_254_400_000,
        },
    )


@pytest.mark.asyncio
async def test_bybit_funding_history_rejects_start_without_end() -> None:
    client = object.__new__(BybitClient)
    client._get = AsyncMock()  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="requires end_ms"):
        await client.get_funding_history("BTCUSDT", start_ms=1)

    client._get.assert_not_awaited()  # type: ignore[attr-defined]

class _EqualProbabilityModel:
    classes_ = np.asarray(["TP", "SL", "TIMEOUT"])

    def predict_proba(self, values: np.ndarray) -> np.ndarray:
        return np.tile(np.asarray([[1.0, 0.0, 0.0]]), (len(values), 1))

    def predict_timeout_return_r(self, values: np.ndarray) -> np.ndarray:
        return np.zeros(len(values), dtype=float)


def test_future_funding_does_not_leak_into_policy_direction_selection() -> None:
    from app.ml.training import DatasetSplit, PolicyEvaluationConfig, evaluate_policy_model

    decision_time = datetime(2026, 1, 1, 0, tzinfo=UTC)
    meta = pd.DataFrame(
        {
            "decision_time": [decision_time, decision_time],
            "label_end_time": [
                decision_time + pd.Timedelta(hours=1),
                decision_time + pd.Timedelta(hours=1),
            ],
            "symbol": ["BTCUSDT", "BTCUSDT"],
            "direction": ["LONG", "SHORT"],
            "target": ["TP", "TP"],
            "exit_index": [0, 0],
            "exit_at_open": [False, False],
            "realized_gross_return": [0.01, 0.01],
            "barrier_upside_rate": [0.01, 0.01],
            "barrier_downside_rate": [0.01, 0.01],
            "historical_funding_timeline_complete": [True, True],
            "historical_funding_horizon_rate": [0.002, 0.002],
            "historical_funding_horizon_settlements": [1, 1],
            "historical_funding_realized_rate": [0.002, 0.002],
            "historical_funding_realized_settlements": [1, 1],
        }
    )
    values = np.zeros((2, 1), dtype=float)
    split = DatasetSplit(
        x_train=values,
        y_train=np.asarray(["TP", "TP"]),
        x_cal=values,
        y_cal=np.asarray(["TP", "TP"]),
        x_test=values,
        y_test=np.asarray(["TP", "TP"]),
        test_meta=meta,
    )
    metrics = evaluate_policy_model(
        _EqualProbabilityModel(),
        split,
        PolicyEvaluationConfig(
            fee_rate_round_trip=0.0,
            slippage_rate=0.0,
            stop_gap_reserve_rate=0.0,
            min_net_rr=0.0,
            min_net_ev_r=0.0,
            timeout_return_rate=0.0,
            horizon_hours=1,
            bootstrap_samples=500,
            confidence_level=0.95,
        ),
        horizon_hours=1,
    )

    # Equal ex-ante economics use the deterministic LONG tiebreak. Positive
    # realized exchange funding then costs LONG 0.002, yielding (0.01-0.002)/0.01.
    assert metrics["policy_trade_mean_r"] == pytest.approx(0.8)
    assert metrics["policy_expected_funding_source"] == "none-no-point-in-time-forecast"
    assert metrics["policy_realized_funding_source"] == HISTORICAL_FUNDING_SCHEMA_VERSION

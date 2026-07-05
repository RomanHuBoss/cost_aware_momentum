from __future__ import annotations

import pandas as pd
import pytest

from app.ml.mtm import (
    INTRAHORIZON_MARGIN_SCHEMA_VERSION,
    INTRAHORIZON_MTM_PATH_SCHEMA_VERSION,
    simulate_intrahorizon_margin_path,
)


def _bars(*rows: tuple[float, float, float, float]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def test_long_mark_path_liquidates_before_later_last_price_exit() -> None:
    result = simulate_intrahorizon_margin_path(
        _bars((100.0, 104.0, 80.0, 90.0), (90.0, 120.0, 89.0, 115.0)),
        direction="LONG",
        entry_price=100.0,
        exit_index=1,
        exit_at_open=False,
        leverage=5,
        equity_reserve_fraction=0.10,
    )

    assert INTRAHORIZON_MARGIN_SCHEMA_VERSION == "bybit-mark-price-hourly-isolated-margin-proxy-v1"
    assert result.liquidated is True
    assert result.liquidation_index == 0
    assert result.liquidation_at_open is False
    assert result.liquidation_exit_offset_hours == 1
    assert result.liquidation_gross_return_rate == pytest.approx(-0.20)
    assert result.maximum_adverse_excursion_rate == pytest.approx(0.20)
    assert result.maximum_favorable_excursion_rate == pytest.approx(0.04)


def test_short_mark_path_preserves_directional_mtm_signs_without_liquidation() -> None:
    result = simulate_intrahorizon_margin_path(
        _bars((100.0, 110.0, 92.0, 95.0), (95.0, 102.0, 88.0, 90.0)),
        direction="SHORT",
        entry_price=100.0,
        exit_index=1,
        exit_at_open=False,
        leverage=3,
        equity_reserve_fraction=0.10,
    )

    assert result.liquidated is False
    assert result.liquidation_index is None
    assert result.maximum_adverse_excursion_rate == pytest.approx(0.10)
    assert result.maximum_favorable_excursion_rate == pytest.approx(0.12)
    assert result.minimum_equity_rate == pytest.approx((1 / 3) - 0.10)


def test_exit_at_open_does_not_use_post_exit_intrabar_mark_extreme() -> None:
    result = simulate_intrahorizon_margin_path(
        _bars((100.0, 101.0, 99.0, 100.0), (90.0, 150.0, 89.0, 120.0)),
        direction="SHORT",
        entry_price=100.0,
        exit_index=1,
        exit_at_open=True,
        leverage=5,
        equity_reserve_fraction=0.10,
    )

    assert result.liquidated is False
    assert result.maximum_adverse_excursion_rate == pytest.approx(0.01)
    assert result.maximum_favorable_excursion_rate == pytest.approx(0.10)


def test_adverse_funding_is_applied_before_conservative_intrabar_liquidation_check() -> None:
    no_funding = simulate_intrahorizon_margin_path(
        _bars((100.0, 101.0, 83.0, 83.0)),
        direction="LONG",
        entry_price=100.0,
        exit_index=0,
        exit_at_open=False,
        leverage=5,
        equity_reserve_fraction=0.10,
    )
    with_adverse_funding = simulate_intrahorizon_margin_path(
        _bars((100.0, 101.0, 83.0, 83.0)),
        direction="LONG",
        entry_price=100.0,
        exit_index=0,
        exit_at_open=False,
        leverage=5,
        equity_reserve_fraction=0.10,
        cumulative_adverse_funding_return_at_open_by_bar=[0.0],
        cumulative_adverse_funding_return_at_close_by_bar=[-0.02],
    )

    assert no_funding.liquidated is False
    assert with_adverse_funding.liquidated is True
    assert with_adverse_funding.minimum_equity_rate == pytest.approx(0.01)


def test_margin_path_rejects_nonfinite_or_misaligned_inputs() -> None:
    with pytest.raises(ValueError, match="funding path length"):
        simulate_intrahorizon_margin_path(
            _bars((100.0, 101.0, 99.0, 100.0)),
            direction="LONG",
            entry_price=100.0,
            exit_index=0,
            exit_at_open=False,
            leverage=3,
            equity_reserve_fraction=0.10,
            cumulative_adverse_funding_return_at_open_by_bar=[],
            cumulative_adverse_funding_return_at_close_by_bar=[],
        )

    with pytest.raises(ValueError, match="low <= open/close <= high"):
        simulate_intrahorizon_margin_path(
            _bars((100.0, 99.0, 98.0, 100.0)),
            direction="LONG",
            entry_price=100.0,
            exit_index=0,
            exit_at_open=False,
            leverage=3,
            equity_reserve_fraction=0.10,
        )


def _training_candles() -> pd.DataFrame:
    from datetime import UTC, datetime, timedelta

    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    for hour in range(29):
        if hour < 25:
            close = 100.0 + (hour % 4) * 0.05
            open_price = close - 0.02
            high = close + 0.40
            low = open_price - 0.40
        else:
            open_price = 110.0 + (hour - 25) * 0.1
            close = open_price + 0.2
            high = open_price + 0.8
            low = open_price - 0.5
        volume = 1000.0 + hour * 7.0
        rows.append(
            {
                "symbol": "TESTUSDT",
                "open_time": start + timedelta(hours=hour),
                "close_time": start + timedelta(hours=hour + 1),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "turnover": volume * close,
            }
        )
    return pd.DataFrame(rows)


def test_barrier_dataset_attaches_exact_hourly_mark_path_and_liquidation() -> None:
    from app.ml.training import make_barrier_dataset

    candles = _training_candles()
    mark = candles[["symbol", "open_time", "close_time", "open", "high", "low", "close"]].copy()
    first_future = pd.Timestamp("2026-01-02T01:00:00Z")
    mark.loc[mark["open_time"].eq(first_future), ["low", "close"]] = [70.0, 90.0]

    dataset = make_barrier_dataset(
        candles,
        horizon=4,
        mark_candles=mark,
        require_mark_timeline=True,
        liquidation_leverage=5,
        liquidation_equity_reserve_fraction=0.10,
    )
    pair = dataset[dataset["decision_time"].eq(first_future)].set_index("direction")

    assert pair.loc["LONG", "mark_liquidated"]
    assert not pair.loc["SHORT", "mark_liquidated"]
    assert pair.loc["LONG", "margin_path_exit_time"] == first_future + pd.Timedelta(hours=1)
    assert pair.loc["LONG", "margin_path_realized_gross_return"] == pytest.approx(-0.20)
    long_path = pair.loc["LONG", "intrahorizon_mark_to_market_path"]
    assert pair.loc["LONG", "intrahorizon_mark_to_market_schema"] == (
        INTRAHORIZON_MTM_PATH_SCHEMA_VERSION
    )
    assert [pd.Timestamp(item["timestamp"]) for item in long_path] == [
        first_future,
        first_future + pd.Timedelta(hours=1),
    ]
    assert long_path[-1]["gross_return_rate"] == pytest.approx(-0.20)
    assert dataset.attrs["intrahorizon_margin_path"]["status"] == "complete"
    assert dataset.attrs["intrahorizon_margin_path"]["mark_to_market_path_schema"] == (
        INTRAHORIZON_MTM_PATH_SCHEMA_VERSION
    )


def test_barrier_dataset_fails_closed_for_missing_mark_bar() -> None:
    from app.ml.training import make_barrier_dataset

    candles = _training_candles()
    mark = candles[["symbol", "open_time", "close_time", "open", "high", "low", "close"]].copy()
    missing_time = pd.Timestamp("2026-01-02T02:00:00Z")
    mark = mark[~mark["open_time"].eq(missing_time)]

    dataset = make_barrier_dataset(
        candles,
        horizon=4,
        mark_candles=mark,
        require_mark_timeline=True,
        liquidation_leverage=5,
    )

    assert dataset.empty or not dataset["decision_time"].eq(pd.Timestamp("2026-01-02T01:00:00Z")).any()
    assert dataset.attrs["hourly_continuity"]["skipped_incomplete_mark_timeline_timestamps"] > 0


def test_future_mark_liquidation_cannot_change_ex_ante_direction_selection() -> None:
    from datetime import UTC, datetime

    import numpy as np

    from app.ml.training import (
        DatasetSplit,
        PolicyEvaluationConfig,
        evaluate_policy_model,
    )

    class _EqualPolicyModel:
        classes_ = np.asarray(["TP", "SL", "TIMEOUT"])

        def predict_proba(self, values: np.ndarray) -> np.ndarray:
            return np.tile(np.asarray([[1.0, 0.0, 0.0]]), (len(values), 1))

        def predict_timeout_return_r(self, values: np.ndarray) -> np.ndarray:
            return np.zeros(len(values), dtype=float)

    decision = datetime(2026, 1, 1, tzinfo=UTC)
    exit_time = pd.Timestamp(decision) + pd.Timedelta(hours=1)
    common = {
        "decision_time": decision,
        "label_end_time": exit_time,
        "symbol": "BTCUSDT",
        "target": "TP",
        "exit_index": 0,
        "exit_at_open": False,
        "realized_gross_return": 0.01,
        "barrier_upside_rate": 0.01,
        "barrier_downside_rate": 0.01,
        "historical_funding_timeline_complete": True,
        "historical_funding_horizon_rate": 0.0,
        "historical_funding_horizon_settlements": 0,
        "historical_funding_realized_rate": 0.0,
        "historical_funding_realized_settlements": 0,
        "intrahorizon_margin_path_complete": True,
        "intrahorizon_margin_schema": INTRAHORIZON_MARGIN_SCHEMA_VERSION,
        "research_leverage": 3,
        "liquidation_equity_reserve_fraction": 0.10,
        "mark_max_adverse_excursion_rate": 0.40,
        "mark_max_favorable_excursion_rate": 0.01,
        "mark_minimum_equity_rate": -0.06,
        "margin_path_exit_index": 0,
        "margin_path_exit_at_open": False,
        "margin_path_exit_time": exit_time,
        "historical_funding_margin_path_rate": 0.0,
        "historical_funding_margin_path_settlements": 0,
    }
    meta = pd.DataFrame(
        [
            {
                **common,
                "direction": "LONG",
                "mark_liquidated": True,
                "margin_path_realized_gross_return": -1.0 / 3.0,
            },
            {
                **common,
                "direction": "SHORT",
                "mark_liquidated": False,
                "mark_max_adverse_excursion_rate": 0.01,
                "mark_minimum_equity_rate": 0.32,
                "margin_path_realized_gross_return": 0.01,
            },
        ]
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
        _EqualPolicyModel(),
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
            research_leverage=3,
            liquidation_equity_reserve_fraction=0.10,
            require_intrahorizon_margin=True,
        ),
        horizon_hours=1,
    )

    # Ex-ante probabilities and economics are tied, so deterministic LONG wins.
    # The future mark path is applied only afterwards to realized evidence.
    assert metrics["policy_liquidation_events"] == 1
    assert metrics["policy_liquidation_rate"] == pytest.approx(1.0)
    assert metrics["policy_trade_mean_r"] < 0.0


@pytest.mark.asyncio
async def test_progressive_history_backfill_persists_explicit_mark_price_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.services import market_data

    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    row_time = now - timedelta(hours=2)
    client = SimpleNamespace(
        get_kline=AsyncMock(
            return_value=[
                [
                    str(int(row_time.timestamp() * 1000)),
                    "100",
                    "101",
                    "99",
                    "100.5",
                    "10",
                    "1005",
                ]
            ]
        )
    )
    captured: list[list[dict[str, object]]] = []

    async def _capture(_session: object, values: list[dict[str, object]]) -> None:
        captured.append(values)

    monkeypatch.setattr(market_data, "_upsert_candle_values", _capture)
    result = await market_data.sync_candle_history(
        SimpleNamespace(),
        client,
        [
            {
                "symbol": "BTCUSDT",
                "earliest": None,
                "target_start": now - timedelta(days=1),
            }
        ],
        interval="60",
        target_days=1,
        page_size=200,
        max_pages_per_symbol=1,
        price_type="mark",
    )

    client.get_kline.assert_awaited_once()
    assert client.get_kline.await_args.kwargs["price_type"] == "mark"
    assert captured and captured[0][0]["price_type"] == "mark"
    assert result["price_type"] == "mark"
    assert result["rows_received"] == 1

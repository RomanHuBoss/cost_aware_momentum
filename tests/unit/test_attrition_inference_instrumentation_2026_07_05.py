from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

import app.services.signals as signals
from app.ml.features import FEATURE_NAMES
from app.ml.runtime import Prediction


class _ScalarsResult:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def scalars(self) -> _ScalarsResult:
        return self

    def all(self) -> list[object]:
        return self._values


class _ProfilesOnlySession:
    async def execute(self, _query) -> _ScalarsResult:
        return _ScalarsResult([])


@pytest.mark.asyncio
async def test_inference_records_one_terminal_outcome_for_every_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    event_time = now.replace(minute=0, second=0, microsecond=0)
    frame = pd.DataFrame([{"close_time": event_time - timedelta(hours=1)}])
    ticker = SimpleNamespace(
        source_time=now,
        bid_price=Decimal("99.9"),
        ask_price=Decimal("100.0"),
        last_price=Decimal("99.95"),
        funding_rate=Decimal("0"),
        next_funding_time=event_time + timedelta(hours=8),
    )
    spec = SimpleNamespace(funding_interval_minutes=480, tick_size=Decimal("0.1"))
    feature_values = {name: 0.0 for name in FEATURE_NAMES}
    feature_values["atr_pct_14"] = 0.01

    async def no_expire(_session) -> int:
        return 0

    async def latest_ticker(_session, _symbol):
        return ticker

    async def latest_spec(_session, _symbol, *, available_cutoff):
        del available_cutoff
        return spec

    async def candles_frame(_session, _symbol, **_kwargs):
        return frame

    monkeypatch.setattr(signals, "expire_old_signals", no_expire)
    monkeypatch.setattr(signals, "_latest_ticker", latest_ticker)
    monkeypatch.setattr(signals, "_latest_spec", latest_spec)
    monkeypatch.setattr(signals, "_candles_frame", candles_frame)
    monkeypatch.setattr(
        signals,
        "latest_feature_snapshot",
        lambda _frame: SimpleNamespace(values=feature_values, quality_flags=()),
    )

    runtime = SimpleNamespace(
        predict_scenarios=lambda _features: (
            Prediction("LONG", 0.4, 0.4, 0.2, 0.0, "m", "c", ()),
            Prediction("SHORT", 0.4, 0.4, 0.2, 0.0, "m", "c", ()),
        ),
        stop_atr_multiplier=1.15,
        tp_atr_multiplier=2.20,
    )
    settings = SimpleNamespace(
        symbols=["BTCUSDT"],
        max_ticker_age_seconds=180,
        initial_backfill_bars=1,
        universe_min_history_bars=1,
        max_candle_age_seconds=4200,
        max_spread_bps=100,
        default_horizon_hours=8,
        base_slippage_bps=3.0,
        fee_rate_taker=0.00055,
        stop_gap_reserve_bps=5.0,
        timeout_gross_return_rate=-0.002,
    )
    diagnostics: dict[str, object] = {}

    published = await signals.publish_hourly_signals(
        _ProfilesOnlySession(),
        settings=settings,
        runtime=runtime,
        event_time=event_time,
        diagnostics=diagnostics,
    )

    assert published == []
    assert diagnostics["attrition_schema"] == "hourly-inference-terminal-outcomes-v1"
    assert diagnostics["symbol_outcomes"] == [
        {
            "symbol": "BTCUSDT",
            "event_time": event_time.isoformat(),
            "terminal_state": "SKIPPED",
            "reason_code": "missing_decision_candle",
            "signal_id": None,
        }
    ]
    assert diagnostics["symbol_outcome_count"] == diagnostics["symbols_total"] == 1

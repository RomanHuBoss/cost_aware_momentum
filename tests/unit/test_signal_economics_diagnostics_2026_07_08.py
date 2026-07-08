from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

import app.services.signals as signals
from app.logging import JsonFormatter
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


def test_json_formatter_preserves_signal_economics_skip_context() -> None:
    record = logging.LogRecord(
        name="app.services.signals",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="Skipping symbol with invalid signal economics",
        args=(),
        exc_info=None,
    )
    record.symbol = "BTCUSDT"
    record.reason_code = "quote_outside_decision_entry_zone"
    record.contract_error = "Executable quote moved outside the decision-time entry zone"
    record.reason_detail = "Quote is outside the immutable decision-time entry band"
    record.event_time = "2026-07-08T18:00:00+00:00"
    record.bid_price = "108420.10"
    record.ask_price = "108420.20"
    record.decision_anchor_price = "108150.00"
    record.entry_low = "108120.00"
    record.entry_high = "108180.00"
    record.tick_size = "0.10"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["symbol"] == "BTCUSDT"
    assert payload["reason_code"] == "quote_outside_decision_entry_zone"
    assert payload["contract_error"] == "Executable quote moved outside the decision-time entry zone"
    assert payload["reason_detail"] == "Quote is outside the immutable decision-time entry band"
    assert payload["bid_price"] == "108420.10"
    assert payload["ask_price"] == "108420.20"
    assert payload["decision_anchor_price"] == "108150.00"
    assert payload["entry_low"] == "108120.00"
    assert payload["entry_high"] == "108180.00"
    assert payload["tick_size"] == "0.10"


@pytest.mark.asyncio
async def test_invalid_signal_economics_skip_is_classified_in_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    event_time = now.replace(minute=0, second=0, microsecond=0)
    frame = pd.DataFrame(
        [
            {
                "close_time": event_time,
                "close": 108_150.0,
            }
        ]
    )
    ticker = SimpleNamespace(
        source_time=now,
        received_at=now,
        bid_price=Decimal("108420.10"),
        ask_price=Decimal("108420.20"),
        last_price=Decimal("108420.15"),
        funding_rate=Decimal("0"),
        next_funding_time=event_time + timedelta(hours=8),
    )
    spec = SimpleNamespace(funding_interval_minutes=480, tick_size=Decimal("0.10"))
    feature_values = {name: 0.0 for name in FEATURE_NAMES}
    feature_values["atr_pct_14"] = 0.01

    async def no_expire(_session) -> int:
        return 0

    async def latest_ticker(_session, _symbol, *, cutoff):
        del cutoff
        return ticker

    async def latest_spec(_session, _symbol, *, available_cutoff):
        del available_cutoff
        return spec

    async def candles_frame(_session, _symbol, **_kwargs):
        return frame

    def quote_outside_entry_zone(*_args, **_kwargs):
        raise ValueError("Executable quote moved outside the decision-time entry zone")

    monkeypatch.setattr(signals, "expire_old_signals", no_expire)
    monkeypatch.setattr(signals, "_latest_ticker", latest_ticker)
    monkeypatch.setattr(signals, "_latest_spec", latest_spec)
    monkeypatch.setattr(signals, "_candles_frame", candles_frame)
    monkeypatch.setattr(signals, "select_cost_aware_scenario", quote_outside_entry_zone)
    monkeypatch.setattr(
        signals,
        "latest_feature_snapshot",
        lambda _frame: SimpleNamespace(values=feature_values, quality_flags=()),
    )

    runtime = SimpleNamespace(
        version="baseline-momentum-v1",
        is_baseline=True,
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
        drift_monitor_enabled=False,
        entry_zone_atr_fraction=Decimal("0.12"),
        max_signal_publication_delay_seconds=5400,
        signal_ttl_minutes=90,
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
    assert diagnostics["skip_counts"] == {"quote_outside_decision_entry_zone": 1}
    assert diagnostics["symbol_outcomes"] == [
        {
            "symbol": "BTCUSDT",
            "event_time": event_time.isoformat(),
            "terminal_state": "SKIPPED",
            "reason_code": "quote_outside_decision_entry_zone",
            "signal_id": None,
            "contract_error": "Executable quote moved outside the decision-time entry zone",
            "reason_detail": "Quote is outside the immutable decision-time entry band",
            "bid_price": "108420.10",
            "ask_price": "108420.20",
            "decision_anchor_price": "108150.0",
            "tick_size": "0.10",
            "entry_low": "108020.30",
            "entry_high": "108279.70",
        }
    ]

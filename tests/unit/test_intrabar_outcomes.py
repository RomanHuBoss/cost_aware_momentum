from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.market_data import CandleWindow, sync_candle_windows
from app.services.outcomes import (
    OutcomeBar,
    evaluate_barrier_outcome_with_intrabar,
    find_ambiguous_intrabar_windows,
)

BASE = datetime(2026, 6, 28, 12, tzinfo=UTC)


def hourly_bar(*, high: str = "105", low: str = "97", close: str = "101") -> OutcomeBar:
    return OutcomeBar(
        candle_id=100,
        open_time=BASE,
        close_time=BASE + timedelta(hours=1),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
    )


def intrabar(
    index: int,
    *,
    high: str,
    low: str,
    close: str,
    minutes: int = 5,
) -> OutcomeBar:
    start = BASE + timedelta(minutes=index * minutes)
    return OutcomeBar(
        candle_id=1000 + index,
        open_time=start,
        close_time=start + timedelta(minutes=minutes),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
    )


def complete_intrabar_path(*, tp_first: bool) -> list[OutcomeBar]:
    rows: list[OutcomeBar] = []
    for index in range(12):
        high = "103"
        low = "99"
        close = "101"
        if tp_first and index == 2:
            high = "104.2"
        if tp_first and index == 7:
            low = "97.8"
        if not tp_first and index == 2:
            low = "97.8"
        if not tp_first and index == 7:
            high = "104.2"
        rows.append(intrabar(index, high=high, low=low, close=close))
    return rows


def test_intrabar_path_resolves_hourly_ambiguity_to_first_tp() -> None:
    result = evaluate_barrier_outcome_with_intrabar(
        [hourly_bar()],
        complete_intrabar_path(tp_first=True),
        direction="LONG",
        entry=Decimal("100"),
        stop=Decimal("98"),
        take_profit=Decimal("104"),
        window_start=BASE,
        horizon_end=BASE + timedelta(hours=4),
        intrabar_interval_minutes=5,
    )

    assert result is not None
    assert result.outcome == "TP"
    assert result.exit_time == BASE + timedelta(minutes=15)
    assert result.source_candle_id == 1002
    assert result.ambiguous is False
    assert result.hourly_ambiguous is True
    assert result.resolution_interval == "5"
    assert result.intrabar_bars_evaluated == 3


def test_intrabar_path_resolves_hourly_ambiguity_to_first_sl() -> None:
    result = evaluate_barrier_outcome_with_intrabar(
        [hourly_bar()],
        complete_intrabar_path(tp_first=False),
        direction="LONG",
        entry=Decimal("100"),
        stop=Decimal("98"),
        take_profit=Decimal("104"),
        window_start=BASE,
        horizon_end=BASE + timedelta(hours=4),
        intrabar_interval_minutes=5,
    )

    assert result is not None
    assert result.outcome == "SL"
    assert result.exit_time == BASE + timedelta(minutes=15)
    assert result.source_candle_id == 1002
    assert result.ambiguous is False
    assert result.hourly_ambiguous is True


def test_short_intrabar_path_preserves_directional_geometry() -> None:
    path = [intrabar(index, high="101", low="97", close="99") for index in range(12)]
    path[1] = intrabar(1, high="101", low="95.8", close="96")
    path[8] = intrabar(8, high="103.2", low="98", close="102")

    result = evaluate_barrier_outcome_with_intrabar(
        [hourly_bar(high="104", low="95", close="99")],
        path,
        direction="SHORT",
        entry=Decimal("100"),
        stop=Decimal("103"),
        take_profit=Decimal("96"),
        window_start=BASE,
        horizon_end=BASE + timedelta(hours=4),
        intrabar_interval_minutes=5,
    )

    assert result is not None
    assert result.outcome == "TP"
    assert result.exit_price == Decimal("96")
    assert result.exit_time == BASE + timedelta(minutes=10)


def test_incomplete_intrabar_path_keeps_ambiguous_hour_pending() -> None:
    path = complete_intrabar_path(tp_first=True)
    del path[5]

    result = evaluate_barrier_outcome_with_intrabar(
        [hourly_bar()],
        path,
        direction="LONG",
        entry=Decimal("100"),
        stop=Decimal("98"),
        take_profit=Decimal("104"),
        window_start=BASE,
        horizon_end=BASE + timedelta(hours=4),
        intrabar_interval_minutes=5,
    )

    assert result is None


def test_same_intrabar_tp_and_sl_remains_conservative() -> None:
    path = [intrabar(index, high="103", low="99", close="101") for index in range(12)]
    path[2] = intrabar(2, high="104.2", low="97.8", close="101")

    result = evaluate_barrier_outcome_with_intrabar(
        [hourly_bar()],
        path,
        direction="LONG",
        entry=Decimal("100"),
        stop=Decimal("98"),
        take_profit=Decimal("104"),
        window_start=BASE,
        horizon_end=BASE + timedelta(hours=4),
        intrabar_interval_minutes=5,
    )

    assert result is not None
    assert result.outcome == "SL"
    assert result.ambiguous is True
    assert result.hourly_ambiguous is True
    assert result.resolution_interval == "5"


@pytest.mark.asyncio
async def test_sync_candle_windows_uses_exact_read_only_kline_window(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    inserted: list[list[dict]] = []

    class FakeClient:
        async def get_kline(self, symbol: str, **kwargs):
            calls.append({"symbol": symbol, **kwargs})
            return [
                [
                    str(int(BASE.timestamp() * 1000)),
                    "100",
                    "101",
                    "99",
                    "100.5",
                    "10",
                    "1000",
                ]
            ]

    async def fake_upsert(session, values_list):
        inserted.append(values_list)

    monkeypatch.setattr("app.services.market_data._upsert_candle_values", fake_upsert)
    result = await sync_candle_windows(
        SimpleNamespace(),
        FakeClient(),
        [CandleWindow(symbol="BTCUSDT", start_time=BASE, end_time=BASE + timedelta(hours=1))],
        interval="5",
        now=BASE + timedelta(hours=2),
    )

    assert calls == [
        {
            "symbol": "BTCUSDT",
            "interval": "5",
            "limit": 12,
            "start_ms": int(BASE.timestamp() * 1000),
            "end_ms": int((BASE + timedelta(hours=1)).timestamp() * 1000) - 1,
            "price_type": "last",
        }
    ]
    assert result == {"windows_requested": 1, "windows_succeeded": 1, "rows_received": 1, "errors": []}
    assert inserted[0][0]["interval"] == "5"
    assert inserted[0][0]["confirmed"] is True


@pytest.mark.asyncio
async def test_ambiguous_window_discovery_targets_only_source_hour() -> None:
    signal = SimpleNamespace(
        id="signal-1",
        symbol="BTCUSDT",
        direction="LONG",
        event_time=BASE,
        horizon_hours=4,
        entry_reference=Decimal("100"),
        stop_loss=Decimal("98"),
        take_profit_1=Decimal("104"),
    )
    candle = SimpleNamespace(
        id=100,
        open_time=BASE,
        close_time=BASE + timedelta(hours=1),
        high=Decimal("105"),
        low=Decimal("97"),
        close=Decimal("101"),
    )

    class FakeResult:
        def __init__(self, rows):
            self.rows = rows

        def scalars(self):
            return self

        def all(self):
            return self.rows

    class FakeSession:
        def __init__(self):
            self.results = iter([FakeResult([signal]), FakeResult([candle])])

        async def execute(self, statement):
            return next(self.results)

    windows = await find_ambiguous_intrabar_windows(
        FakeSession(),
        market_cutoff=BASE + timedelta(hours=2),
        available_cutoff=BASE + timedelta(hours=2),
        max_windows=10,
    )

    assert windows == [
        CandleWindow(
            symbol="BTCUSDT",
            start_time=BASE,
            end_time=BASE + timedelta(hours=1),
        )
    ]

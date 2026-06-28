from datetime import UTC, datetime, timedelta

import pandas as pd

from app.ml.features import FEATURE_NAMES, latest_feature_snapshot
from app.ml.labels import triple_barrier_outcome


def test_ambiguous_bar_is_conservative() -> None:
    bars = pd.DataFrame([{"high": 105.0, "low": 95.0, "close": 102.0}])
    result = triple_barrier_outcome(bars, direction="LONG", stop=98.0, take_profit=104.0)
    assert result.outcome == "SL"
    assert result.ambiguous is True


def test_short_barrier_order() -> None:
    bars = pd.DataFrame(
        [
            {"high": 101.0, "low": 99.0, "close": 100.0},
            {"high": 100.0, "low": 95.0, "close": 96.0},
        ]
    )
    result = triple_barrier_outcome(bars, direction="SHORT", stop=103.0, take_profit=96.0)
    assert result.outcome == "TP"
    assert result.exit_index == 1


def test_feature_snapshot_has_fixed_schema() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    price = 100.0
    for i in range(80):
        price *= 1.001
        rows.append(
            {
                "symbol": "BTCUSDT",
                "open_time": start + timedelta(hours=i),
                "open": price * 0.999,
                "high": price * 1.002,
                "low": price * 0.998,
                "close": price,
                "volume": 1000 + i * 3,
                "turnover": (1000 + i * 3) * price,
            }
        )
    snapshot = latest_feature_snapshot(pd.DataFrame(rows))
    assert list(snapshot.values) == FEATURE_NAMES
    assert all(isinstance(value, float) for value in snapshot.values.values())
    assert "SHORT_HISTORY" not in snapshot.quality_flags


def test_feature_snapshot_fails_closed_on_gap_in_required_hourly_lookback() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    price = 100.0
    for hour in range(90):
        if hour == 75:
            continue
        price *= 1.001
        rows.append(
            {
                "symbol": "BTCUSDT",
                "open_time": start + timedelta(hours=hour),
                "open": price * 0.999,
                "high": price * 1.002,
                "low": price * 0.998,
                "close": price,
                "volume": 1000 + hour * 3,
                "turnover": (1000 + hour * 3) * price,
            }
        )

    snapshot = latest_feature_snapshot(pd.DataFrame(rows))

    assert snapshot.values == {}
    assert "NON_CONTIGUOUS_HOURLY_HISTORY" in snapshot.quality_flags

def test_feature_snapshot_fails_closed_on_duplicate_in_required_hourly_lookback() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    price = 100.0
    for hour in range(90):
        price *= 1.001
        row = {
            "symbol": "BTCUSDT",
            "open_time": start + timedelta(hours=hour),
            "open": price * 0.999,
            "high": price * 1.002,
            "low": price * 0.998,
            "close": price,
            "volume": 1000 + hour * 3,
            "turnover": (1000 + hour * 3) * price,
        }
        rows.append(row)
        if hour == 75:
            rows.append(dict(row))

    snapshot = latest_feature_snapshot(pd.DataFrame(rows))

    assert snapshot.values == {}
    assert "NON_CONTIGUOUS_HOURLY_HISTORY" in snapshot.quality_flags

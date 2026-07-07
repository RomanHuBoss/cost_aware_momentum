from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd
import pytest

from app.ml.training import make_barrier_dataset
from tests.unit.test_execution_aware_training_entry_2026_07_05 import _candles


def _spec_history(*, future_only: bool = False) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if not future_only:
        rows.append(
            {
                "symbol": "TESTUSDT",
                "valid_from": datetime(2025, 12, 1, tzinfo=UTC),
                "received_at": datetime(2025, 12, 1, tzinfo=UTC),
                "tick_size": Decimal("0.1"),
            }
        )
    rows.append(
        {
            "symbol": "TESTUSDT",
            "valid_from": (
                datetime(2025, 12, 1, tzinfo=UTC)
                if future_only
                else datetime(2026, 1, 3, tzinfo=UTC)
            ),
            "received_at": datetime(2026, 1, 3, tzinfo=UTC),
            "tick_size": Decimal("0.5"),
        }
    )
    return pd.DataFrame(rows)


def test_training_barriers_use_point_in_time_exchange_tick_geometry() -> None:
    dataset = make_barrier_dataset(
        _candles(),
        horizon=4,
        entry_spread_bps=10.0,
        instrument_spec_history=_spec_history(),
        require_instrument_spec_timeline=True,
    )

    decision_time = pd.Timestamp("2026-01-02T01:00:00Z")
    pair = dataset[dataset["decision_time"].eq(decision_time)].set_index("direction")

    # Manual Decimal arithmetic, independent of the implementation:
    # raw stressed entries are 100.05 / 99.95 and must move adversely to 100.1 / 99.9.
    assert pair.loc["LONG", "entry_price"] == pytest.approx(100.1)
    assert pair.loc["SHORT", "entry_price"] == pytest.approx(99.9)
    assert pair.loc["LONG", "entry_zone_low"] == pytest.approx(99.9)
    assert pair.loc["LONG", "entry_zone_high"] == pytest.approx(100.1)

    # atr_pct_14 is 0.0102. Conservative exchange rounding widens stops and pulls
    # targets toward entry exactly as the live signal constructor does.
    assert pair.loc["LONG", "stop_price"] == pytest.approx(98.9)
    assert pair.loc["LONG", "take_profit_price"] == pytest.approx(102.3)
    assert pair.loc["SHORT", "stop_price"] == pytest.approx(101.1)
    assert pair.loc["SHORT", "take_profit_price"] == pytest.approx(97.7)
    assert pair["tick_size"].tolist() == pytest.approx([0.1, 0.1])
    assert set(pair["instrument_spec_valid_from"]) == {
        pd.Timestamp("2025-12-01T00:00:00Z")
    }
    assert dataset.attrs["instrument_spec_timeline"]["status"] == "complete"


def test_training_never_backfills_an_instrument_spec_received_in_the_future() -> None:
    dataset = make_barrier_dataset(
        _candles(),
        horizon=4,
        entry_spread_bps=10.0,
        instrument_spec_history=_spec_history(future_only=True),
        require_instrument_spec_timeline=True,
    )

    assert dataset.empty
    diagnostics = dataset.attrs["hourly_continuity"]
    assert diagnostics["skipped_missing_instrument_spec_timestamps"] > 0


def test_training_rejects_ambiguous_duplicate_instrument_specs() -> None:
    history = _spec_history().iloc[[0]].copy()
    history = pd.concat([history, history], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate symbol/valid_from"):
        make_barrier_dataset(
            _candles(),
            horizon=4,
            instrument_spec_history=history,
            require_instrument_spec_timeline=True,
        )

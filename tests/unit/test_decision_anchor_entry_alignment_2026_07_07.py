from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from app.config import Settings
from app.ml.runtime import ModelRuntime, Prediction
from app.ml.training import make_barrier_dataset
from app.risk.math import CostScenario
from app.services import signals
from app.services.model_promotion import experiment_policy_binding_from_settings

D = Decimal
DB_URL = "postgresql+psycopg://u:p@localhost/db"


def _predictions() -> tuple[Prediction, Prediction]:
    return (
        Prediction("LONG", 0.80, 0.10, 0.10, 1.0, "fixed-v1", "fixed-cal-v1", ()),
        Prediction("SHORT", 0.10, 0.80, 0.10, -1.0, "fixed-v1", "fixed-cal-v1", ()),
    )


def _candles(*, gap_open: float) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    for hour in range(25):
        close = 100.0 + (hour % 4) * 0.05
        open_price = close - 0.02
        rows.append(
            {
                "symbol": "TESTUSDT",
                "open_time": start + timedelta(hours=hour),
                "close_time": start + timedelta(hours=hour + 1),
                "open": open_price,
                "high": close + 1.50,
                "low": open_price - 1.50,
                "close": close,
                "volume": 1000.0 + hour * 7.0,
                "turnover": (1000.0 + hour * 7.0) * close,
            }
        )
    for offset in range(25, 29):
        open_price = gap_open + (offset - 25) * 0.05
        close = open_price + 0.02
        rows.append(
            {
                "symbol": "TESTUSDT",
                "open_time": start + timedelta(hours=offset),
                "close_time": start + timedelta(hours=offset + 1),
                "open": open_price,
                "high": open_price + 1.50,
                "low": open_price - 1.50,
                "close": close,
                "volume": 1200.0 + offset * 7.0,
                "turnover": (1200.0 + offset * 7.0) * close,
            }
        )
    return pd.DataFrame(rows)


def test_live_selector_rejects_quote_that_moved_outside_decision_entry_zone() -> None:
    with pytest.raises(ValueError, match="decision-time entry zone"):
        signals.select_cost_aware_scenario(
            _predictions(),
            bid_price=D("102.9"),
            ask_price=D("103.0"),
            decision_anchor_price=D("100"),
            atr_pct=D("0.02"),
            entry_zone_atr_fraction=D("0.12"),
            costs=CostScenario(D("0"), D("0"), D("0"), D("0")),
        )


def test_live_entry_zone_is_anchored_to_decision_close_not_current_quote() -> None:
    selected = signals.select_cost_aware_scenario(
        _predictions(),
        bid_price=D("100.1"),
        ask_price=D("100.2"),
        decision_anchor_price=D("100"),
        atr_pct=D("0.02"),
        entry_zone_atr_fraction=D("0.12"),
        costs=CostScenario(D("0"), D("0"), D("0"), D("0")),
        tick_size=D("0.01"),
    )

    assert selected.reference == D("100.2")
    assert selected.entry_low == D("99.76")
    assert selected.entry_high == D("100.24")


def test_training_excludes_next_hour_entry_outside_same_decision_zone() -> None:
    dataset = make_barrier_dataset(
        _candles(gap_open=110.0),
        horizon=4,
        entry_spread_bps=20.0,
        entry_zone_atr_fraction=0.12,
    )

    decision_time = pd.Timestamp("2026-01-02T01:00:00Z")
    assert dataset.empty or dataset[dataset["decision_time"].eq(decision_time)].empty
    assert dataset.attrs["hourly_continuity"]["skipped_entry_zone_timestamps"] >= 1


def test_training_persists_decision_anchor_entry_contract() -> None:
    dataset = make_barrier_dataset(
        _candles(gap_open=100.10),
        horizon=4,
        entry_spread_bps=20.0,
        entry_zone_atr_fraction=0.12,
    )
    decision_time = pd.Timestamp("2026-01-02T01:00:00Z")
    pair = dataset[dataset["decision_time"].eq(decision_time)]

    assert len(pair) == 2
    assert pair["decision_entry_anchor"].tolist() == pytest.approx([100.0, 100.0])
    assert pair["entry_zone_atr_fraction"].tolist() == pytest.approx([0.12, 0.12])
    assert pair["entry_zone_low"].iloc[0] < 100.10 < pair["entry_zone_high"].iloc[0]
    assert dataset.attrs["entry_execution_model"] == {
        "schema": "decision-close-zone-next-hour-open-directional-half-spread-v2",
        "entry_spread_bps": pytest.approx(20.0),
        "entry_zone_atr_fraction": pytest.approx(0.12),
        "decision_anchor_source": "confirmed_decision_candle_close",
        "entry_price_source": "next_hour_open_directional_half_spread_stress",
        "residual_limitations": [
            "historical_bid_ask_unavailable",
            "operator_latency_within_zone_unmodeled",
            "historical_depth_and_partial_fill_unmodeled",
        ],
    }


def test_signal_publication_boundary_rejects_late_decision_and_anchors_expiry() -> None:
    event_time = datetime(2026, 7, 7, 10, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="publication delay"):
        signals.validate_signal_publication_boundary(
            event_time=event_time,
            publish_time=event_time + timedelta(seconds=601),
            maximum_delay_seconds=600,
            signal_ttl_minutes=90,
        )

    boundary = signals.validate_signal_publication_boundary(
        event_time=event_time,
        publish_time=event_time + timedelta(seconds=75),
        maximum_delay_seconds=600,
        signal_ttl_minutes=90,
    )
    assert boundary.publication_lag_seconds == pytest.approx(75.0)
    assert boundary.expires_at == event_time + timedelta(minutes=90)


def test_entry_timing_contract_is_validated_and_bound_to_promotion_evidence() -> None:
    with pytest.raises(ValueError, match="MAX_SIGNAL_PUBLICATION_DELAY_SECONDS"):
        Settings(
            database_url=DB_URL,
            inference_delay_seconds=75,
            max_signal_publication_delay_seconds=60,
        )

    binding_narrow = experiment_policy_binding_from_settings(
        Settings(database_url=DB_URL, entry_zone_atr_fraction=0.12)
    )
    binding_wide = experiment_policy_binding_from_settings(
        Settings(database_url=DB_URL, entry_zone_atr_fraction=0.20)
    )
    assert binding_narrow["schema"] == "model-promotion-policy-binding-v4"
    assert binding_narrow["entry_zone_atr_fraction"] == pytest.approx(0.12)
    assert binding_narrow["maximum_signal_publication_delay_seconds"] == 600
    assert binding_narrow != binding_wide


def test_active_artifact_entry_contract_must_match_runtime_settings() -> None:
    settings = Settings(
        database_url=DB_URL,
        entry_zone_atr_fraction=0.12,
        max_signal_publication_delay_seconds=600,
    )
    runtime = ModelRuntime()
    runtime.bundle = {"model": object()}
    runtime.entry_zone_atr_fraction = 0.20
    runtime.maximum_signal_publication_delay_seconds = 600

    with pytest.raises(ValueError, match="does not match runtime settings"):
        signals.resolve_decision_execution_contract(settings=settings, runtime=runtime)

    runtime.entry_zone_atr_fraction = 0.12
    assert signals.resolve_decision_execution_contract(settings=settings, runtime=runtime) == (D("0.12"), 600)

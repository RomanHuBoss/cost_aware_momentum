from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from app.config import Settings
from app.ml import lifecycle
from app.ml.universe_replay import (
    apply_point_in_time_universe_replay,
    load_point_in_time_universe_snapshots,
)
from app.services.model_promotion import experiment_policy_binding_from_settings
from app.services.universe import persist_universe_selection, select_dynamic_universe


class _PersistSession:
    def add(self, _value: object) -> None:
        pass

    async def flush(self) -> None:
        pass


class _AsyncMappingStream:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = iter(rows)

    def mappings(self) -> _AsyncMappingStream:
        return self

    def __aiter__(self) -> _AsyncMappingStream:
        return self

    async def __anext__(self) -> dict[str, object]:
        try:
            return next(self._rows)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _StreamingSession:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    async def stream(self, _statement, _params):
        return _AsyncMappingStream(self.rows)


def _instrument(symbol: str, *, now: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        symbol=symbol,
        category="linear",
        base_coin=symbol.removesuffix("USDT"),
        quote_coin="USDT",
        settle_coin="USDT",
        status="Trading",
        launch_time=now - timedelta(days=100),
        delivery_time=None,
        is_pre_listing=False,
        raw={"contractType": "LinearPerpetual", "symbolType": ""},
    )


async def _snapshot_row() -> dict[str, object]:
    observed_at = datetime(2026, 7, 7, 9, 55, tzinfo=UTC)
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        universe_mode="dynamic",
        universe_min_age_days=7,
        universe_min_turnover_24h=1,
        universe_max_spread_bps=30,
        universe_max_symbols=0,
        max_spread_bps=18,
    )
    selection = select_dynamic_universe(
        [
            _instrument("BTCUSDT", now=observed_at),
            _instrument("ETHUSDT", now=observed_at),
        ],
        [
            {
                "symbol": "BTCUSDT",
                "lastPrice": "100",
                "bid1Price": "99.95",
                "ask1Price": "100.05",
                "turnover24h": "1000000",
            },
            {
                "symbol": "ETHUSDT",
                "lastPrice": "100",
                "bid1Price": "99.875",
                "ask1Price": "100.125",
                "turnover24h": "900000",
            },
        ],
        settings,
        now=observed_at,
    )
    assert selection.symbols == ("BTCUSDT", "ETHUSDT")
    snapshot = await persist_universe_selection(
        _PersistSession(),  # type: ignore[arg-type]
        selection,
        recorded_at=observed_at + timedelta(seconds=1),
        release_version="test-release",
    )
    return {
        column.name: getattr(snapshot, column.name)
        for column in snapshot.__table__.columns
    }


@pytest.mark.asyncio
async def test_loader_derives_live_executable_symbols_from_immutable_spread_evidence() -> None:
    row = await _snapshot_row()
    frame = await load_point_in_time_universe_snapshots(
        _StreamingSession([row]),  # type: ignore[arg-type]
        [datetime(2026, 7, 7, 10, tzinfo=UTC)],
        expected_mode="dynamic",
        maximum_executable_spread_bps=18.0,
    )

    record = frame.iloc[0].to_dict()
    assert record["selected_symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert record["execution_eligible_symbols"] == ["BTCUSDT"]
    assert record["spread_ineligible_selected_symbols"] == ["ETHUSDT"]
    assert record["maximum_executable_spread_bps"] == 18.0


def _dataset() -> pd.DataFrame:
    decision_time = datetime(2026, 7, 7, 10, tzinfo=UTC)
    return pd.DataFrame(
        [
            {
                "decision_time": decision_time,
                "symbol": symbol,
                "direction": direction,
            }
            for symbol in ("BTCUSDT", "ETHUSDT")
            for direction in ("LONG", "SHORT")
        ]
    )


def _compact_snapshot(*, limit: float = 18.0) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "observed_at": datetime(2026, 7, 7, 9, 55, tzinfo=UTC),
                "recorded_at": datetime(2026, 7, 7, 9, 55, 1, tzinfo=UTC),
                "selected_symbols": ["BTCUSDT", "ETHUSDT"],
                "execution_eligible_symbols": ["BTCUSDT"],
                "spread_ineligible_selected_symbols": ["ETHUSDT"],
                "maximum_executable_spread_bps": limit,
                "policy_hash": "1" * 64,
                "record_hash": "a" * 64,
            }
        ]
    )


def test_replay_excludes_untradeable_selected_symbols_before_training_and_policy_evaluation() -> None:
    filtered, evidence = apply_point_in_time_universe_replay(
        _dataset(),
        _compact_snapshot(),
        max_snapshot_age_seconds=600,
        maximum_executable_spread_bps=18.0,
        required=True,
    )

    assert set(filtered["symbol"]) == {"BTCUSDT"}
    assert evidence["maximum_executable_spread_bps"] == 18.0
    assert evidence["spread_ineligible_rows_excluded"] == 2
    assert evidence["spread_ineligible_selected_symbols"] == ["ETHUSDT"]


def test_replay_rejects_spread_contract_mismatch_instead_of_silently_reusing_evidence() -> None:
    with pytest.raises(ValueError, match="executable spread limit mismatch"):
        apply_point_in_time_universe_replay(
            _dataset(),
            _compact_snapshot(limit=30.0),
            max_snapshot_age_seconds=600,
            maximum_executable_spread_bps=18.0,
            required=True,
        )


def test_candidate_training_profile_is_built_from_actual_replayed_model_rows() -> None:
    model_rows = pd.DataFrame(
        [
            {
                "symbol": "BTCUSDT",
                "source_open_time": datetime(2026, 7, 7, hour, tzinfo=UTC),
                "direction": direction,
            }
            for hour in (7, 8)
            for direction in ("LONG", "SHORT")
        ]
    )

    profile = lifecycle.training_profile_from_model_dataset(
        model_rows,
        minimum_rows_for_coverage=2,
        expected_symbols=None,
    )

    assert profile.candle_rows == 2
    assert profile.unique_timestamps == 2
    assert profile.symbols == ("BTCUSDT",)
    assert profile.coverage_ratio == 1.0


def test_promotion_binding_changes_when_live_executable_spread_limit_changes() -> None:
    common = {
        "database_url": "postgresql+psycopg://u:p@localhost/db",
        "model_entry_spread_bps": 18.0,
    }
    binding_18 = experiment_policy_binding_from_settings(
        Settings(**common, max_spread_bps=18.0)
    )
    binding_12 = experiment_policy_binding_from_settings(
        Settings(**common, max_spread_bps=12.0)
    )

    assert binding_18["schema"] == "model-promotion-policy-binding-v4"
    assert binding_18["maximum_executable_spread_bps"] == 18.0
    assert binding_12["maximum_executable_spread_bps"] == 12.0
    assert binding_18 != binding_12


@pytest.mark.asyncio
async def test_dynamic_training_profile_forwards_live_spread_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}
    candles = pd.DataFrame(
        [
            {
                "symbol": "BTCUSDT",
                "open_time": datetime(2026, 7, 7, 8, tzinfo=UTC),
                "close_time": datetime(2026, 7, 7, 9, tzinfo=UTC),
            }
        ]
    )

    async def fake_load(*_args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(candles=candles, universe_eligibility=pd.DataFrame())

    monkeypatch.setattr(lifecycle, "load_training_market_data", fake_load)

    profile = await lifecycle.load_training_data_profile(
        None,
        lookback_days=365,
        max_symbols=100,
        horizon=8,
        minimum_rows_for_coverage=300,
        require_universe_replay=True,
        universe_replay_max_age_seconds=600,
        maximum_executable_spread_bps=18.0,
    )

    assert captured["maximum_executable_spread_bps"] == 18.0
    assert profile.unique_timestamps == 0

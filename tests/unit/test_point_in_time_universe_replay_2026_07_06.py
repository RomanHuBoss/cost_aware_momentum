from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from app.ml.universe_replay import apply_point_in_time_universe_replay


def _dataset() -> pd.DataFrame:
    rows = []
    for hour in (9, 10, 11):
        for symbol in ("BTCUSDT", "ETHUSDT"):
            for direction in ("LONG", "SHORT"):
                rows.append(
                    {
                        "decision_time": datetime(2026, 7, 6, hour, tzinfo=UTC),
                        "symbol": symbol,
                        "direction": direction,
                        "target": "TIMEOUT",
                    }
                )
    return pd.DataFrame(rows)


def _snapshots() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "observed_at": datetime(2026, 7, 6, 9, 55, tzinfo=UTC),
                "recorded_at": datetime(2026, 7, 6, 9, 55, 1, tzinfo=UTC),
                "selected_symbols": ["BTCUSDT"],
                "policy_hash": "1" * 64,
                "record_hash": "a" * 64,
            },
            {
                "observed_at": datetime(2026, 7, 6, 10, 55, tzinfo=UTC),
                "recorded_at": datetime(2026, 7, 6, 10, 55, 1, tzinfo=UTC),
                "selected_symbols": ["ETHUSDT"],
                "policy_hash": "2" * 64,
                "record_hash": "b" * 64,
            },
        ]
    )


def test_replay_uses_latest_snapshot_available_at_each_decision_and_excludes_pre_rollout() -> None:
    filtered, evidence = apply_point_in_time_universe_replay(
        _dataset(),
        _snapshots(),
        max_snapshot_age_seconds=600,
        required=True,
    )

    assert set(zip(filtered["decision_time"], filtered["symbol"], strict=True)) == {
        (pd.Timestamp("2026-07-06T10:00:00Z"), "BTCUSDT"),
        (pd.Timestamp("2026-07-06T11:00:00Z"), "ETHUSDT"),
    }
    assert len(filtered) == 4
    assert evidence["schema"] == "point-in-time-universe-replay-v1"
    assert evidence["status"] == "applied"
    assert evidence["pre_rollout_rows_excluded"] == 4
    assert evidence["ineligible_rows_excluded"] == 4
    assert evidence["eligible_rows"] == 4
    assert evidence["decision_timestamps"] == 2
    assert evidence["snapshot_count_used"] == 2


def test_replay_fails_closed_when_post_rollout_snapshot_is_stale() -> None:
    with pytest.raises(ValueError, match="stale universe eligibility snapshot"):
        apply_point_in_time_universe_replay(
            _dataset(),
            _snapshots().iloc[:1],
            max_snapshot_age_seconds=600,
            required=True,
        )


def test_required_replay_never_falls_back_when_snapshot_evidence_is_missing() -> None:
    with pytest.raises(ValueError, match="requires universe eligibility snapshots"):
        apply_point_in_time_universe_replay(
            _dataset(),
            pd.DataFrame(),
            max_snapshot_age_seconds=600,
            required=True,
        )


def test_replay_uses_commit_availability_not_uncommitted_observation_time() -> None:
    dataset = pd.DataFrame(
        [
            {
                "decision_time": datetime(2026, 7, 6, 10, tzinfo=UTC),
                "symbol": symbol,
                "direction": direction,
            }
            for symbol in ("BTCUSDT", "ETHUSDT")
            for direction in ("LONG", "SHORT")
        ]
    )
    snapshots = pd.DataFrame(
        [
            {
                "observed_at": datetime(2026, 7, 6, 9, 55, tzinfo=UTC),
                "recorded_at": datetime(2026, 7, 6, 9, 55, 1, tzinfo=UTC),
                "selected_symbols": ["BTCUSDT"],
                "policy_hash": "1" * 64,
                "record_hash": "a" * 64,
            },
            {
                "observed_at": datetime(2026, 7, 6, 9, 59, 59, tzinfo=UTC),
                "recorded_at": datetime(2026, 7, 6, 10, 0, 1, tzinfo=UTC),
                "selected_symbols": ["ETHUSDT"],
                "policy_hash": "2" * 64,
                "record_hash": "b" * 64,
            },
        ]
    )

    filtered, _ = apply_point_in_time_universe_replay(
        dataset,
        snapshots,
        max_snapshot_age_seconds=600,
        required=True,
    )

    assert set(filtered["symbol"]) == {"BTCUSDT"}


@pytest.mark.asyncio
async def test_background_training_profile_counts_only_replayed_eligible_rows(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.ml import lifecycle

    candles = _dataset().drop(columns=["direction", "target"]).drop_duplicates().copy()
    candles["open_time"] = candles["decision_time"] - pd.Timedelta(1, unit="h")
    candles["close_time"] = candles["decision_time"]
    candles = candles.drop(columns=["decision_time"])
    market_data = SimpleNamespace(
        candles=candles,
        universe_eligibility=_snapshots(),
    )

    async def fake_load(*_args, **_kwargs):
        return market_data

    monkeypatch.setattr(lifecycle, "load_training_market_data", fake_load)

    profile = await lifecycle.load_training_data_profile(
        None,
        lookback_days=365,
        max_symbols=5,
        horizon=0,
        minimum_rows_for_coverage=1,
        require_universe_replay=True,
        universe_replay_max_age_seconds=600,
    )

    assert profile.candle_rows == 2
    assert profile.unique_timestamps == 2
    assert profile.symbols == ("BTCUSDT", "ETHUSDT")
    assert profile.coverage_ratio == 1.0

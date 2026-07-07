from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from app.ml.data_profile import TrainingDataProfile, profile_from_symbol_rows
from app.ml.lifecycle import (
    TRAINING_UNIVERSE_MODE_BOOTSTRAP,
    TRAINING_UNIVERSE_MODE_PROSPECTIVE,
    DynamicBootstrapCohort,
)
from app.ml.training import PointInTimeInstrumentSpecTimeline


def _profile(*, symbols: tuple[str, ...], hours: int = 1_500):
    end = datetime(2026, 7, 7, tzinfo=UTC)
    return profile_from_symbol_rows(
        [(symbol, hours, end - timedelta(hours=hours - 1), end) for symbol in symbols],
        unique_timestamps=hours,
        minimum_rows_for_coverage=300,
    )


def test_pre_observation_tick_bootstrap_is_explicit_and_never_bridges_later_gaps() -> None:
    history = pd.DataFrame(
        [
            {
                "symbol": "BTCUSDT",
                "valid_from": datetime(2026, 7, 7, tzinfo=UTC),
                "received_at": datetime(2026, 7, 7, tzinfo=UTC),
                "tick_size": Decimal("0.1"),
            }
        ]
    )
    strict = PointInTimeInstrumentSpecTimeline(history)
    bootstrap = PointInTimeInstrumentSpecTimeline(history, allow_pre_observation_bootstrap=True)

    before = datetime(2026, 1, 1, tzinfo=UTC)
    after = datetime(2026, 7, 8, tzinfo=UTC)
    assert strict.resolve("BTCUSDT", before) is None
    selected = bootstrap.resolve("BTCUSDT", before)
    assert selected is not None
    assert selected.tick_size == Decimal("0.1")
    assert selected.selection == "pre_observation_bootstrap"
    assert bootstrap.resolve("BTCUSDT", after) is not None
    assert bootstrap.describe()["pre_observation_bootstrap_resolutions"] == 1


def test_training_profile_rejects_tampered_identity_and_naive_time() -> None:
    profile = _profile(symbols=("BTCUSDT", "ETHUSDT"))

    tampered_count = profile.to_dict()
    tampered_count["symbol_count"] = 99
    assert TrainingDataProfile.from_mapping(tampered_count) is None

    tampered_hash = profile.to_dict()
    tampered_hash["symbols_sha256"] = "0" * 64
    assert TrainingDataProfile.from_mapping(tampered_hash) is None

    naive_time = profile.to_dict()
    naive_time["start_time"] = "2026-01-01T00:00:00"
    assert TrainingDataProfile.from_mapping(naive_time) is None


def test_empty_or_nonempty_profile_cannot_forge_timestamp_depth() -> None:
    profile = _profile(symbols=("BTCUSDT",))
    forged = profile.to_dict()
    forged["unique_timestamps"] = forged["candle_rows"] + 1
    assert TrainingDataProfile.from_mapping(forged) is None

    empty = profile_from_symbol_rows([], unique_timestamps=0, minimum_rows_for_coverage=300).to_dict()
    empty["unique_timestamps"] = 1_206
    assert TrainingDataProfile.from_mapping(empty) is None

    with pytest.raises(ValueError, match="Empty training profile"):
        profile_from_symbol_rows([], unique_timestamps=1_206, minimum_rows_for_coverage=300)


def test_profile_builder_rejects_incoherent_per_symbol_ranges() -> None:
    now = datetime(2026, 7, 7, tzinfo=UTC)
    with pytest.raises(ValueError, match="Zero-row symbol"):
        profile_from_symbol_rows(
            [("BTCUSDT", 0, now, now)],
            unique_timestamps=0,
            minimum_rows_for_coverage=300,
        )
    with pytest.raises(ValueError, match="requires an ordered time range"):
        profile_from_symbol_rows(
            [("BTCUSDT", 10, None, None)],
            unique_timestamps=10,
            minimum_rows_for_coverage=300,
        )


def test_bootstrap_scope_requires_hash_bound_unique_symbol_evidence() -> None:
    from app.workers.trainer import require_training_universe_scope

    valid = {
        "training_universe_mode": TRAINING_UNIVERSE_MODE_BOOTSTRAP,
        "training_universe_evidence": {
            "schema": "historical-frozen-dynamic-bootstrap-v1",
            "status": "frozen",
            "record_hash": "a" * 64,
            "policy_hash": "b" * 64,
            "symbols": ["ETHUSDT", "BTCUSDT"],
        },
    }
    mode, evidence = require_training_universe_scope(valid)
    assert mode == TRAINING_UNIVERSE_MODE_BOOTSTRAP
    assert evidence["symbols"] == ["BTCUSDT", "ETHUSDT"]

    invalid = {
        **valid,
        "training_universe_evidence": {
            **valid["training_universe_evidence"],
            "record_hash": "not-a-hash",
        },
    }
    with pytest.raises(RuntimeError, match="invalid record_hash"):
        require_training_universe_scope(invalid)


@pytest.mark.asyncio
async def test_dynamic_scope_uses_frozen_historical_bootstrap_before_rollout_is_long_enough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers import trainer

    profile = _profile(symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    calls: list[dict[str, object]] = []

    async def fake_rollout():
        return {"schema": "dynamic-universe-rollout-coverage-v1", "span_hours": 1.0}

    async def fake_cohort(**_kwargs):
        return DynamicBootstrapCohort(
            symbols=profile.symbols,
            evidence={
                "schema": "historical-frozen-dynamic-bootstrap-v1",
                "status": "frozen",
                "record_hash": "a" * 64,
                "policy_hash": "b" * 64,
                "symbols": list(profile.symbols),
            },
        )

    async def fake_profile(symbols, **kwargs):
        calls.append({"symbols": symbols, **kwargs})
        return profile

    monkeypatch.setattr(trainer.settings, "universe_mode", "dynamic")
    monkeypatch.setattr(trainer.settings, "auto_train_dynamic_bootstrap_enabled", True)
    monkeypatch.setattr(trainer.settings, "auto_train_bootstrap_min_symbols", 3)
    monkeypatch.setattr(trainer, "load_dynamic_universe_rollout_evidence", fake_rollout)
    monkeypatch.setattr(trainer, "load_dynamic_bootstrap_cohort", fake_cohort)
    monkeypatch.setattr(trainer, "load_training_data_profile", fake_profile)

    scope = await trainer.BackgroundTrainer().current_training_scope(minimum_bootstrap_timestamps=1_206)

    assert scope[0] == profile
    assert scope[1] == TRAINING_UNIVERSE_MODE_BOOTSTRAP
    assert calls == [
        pytest.approx(
            {
                "symbols": profile.symbols,
                "max_symbols": 0,
                "lookback_days": trainer.settings.auto_train_lookback_days,
                "horizon": trainer.settings.default_horizon_hours,
                "minimum_rows_for_coverage": trainer.settings.auto_train_min_bars_per_symbol,
                "universe_replay_max_age_seconds": trainer.settings.universe_refresh_seconds * 2,
                "maximum_executable_spread_bps": trainer.settings.max_spread_bps,
                "require_universe_replay": False,
            }
        )
    ]


@pytest.mark.asyncio
async def test_dynamic_scope_upgrades_to_exact_prospective_replay_when_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers import trainer

    profile = _profile(symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"), hours=1_300)
    cohort_called = False

    async def fake_rollout():
        return {"schema": "dynamic-universe-rollout-coverage-v1", "span_hours": 1_299.0}

    async def fake_profile(_symbols, **kwargs):
        assert kwargs["require_universe_replay"] is True
        return profile

    async def fake_cohort(**_kwargs):
        nonlocal cohort_called
        cohort_called = True
        raise AssertionError("bootstrap cohort must not be loaded after exact replay is ready")

    monkeypatch.setattr(trainer.settings, "universe_mode", "dynamic")
    monkeypatch.setattr(trainer, "load_dynamic_universe_rollout_evidence", fake_rollout)
    monkeypatch.setattr(trainer, "load_training_data_profile", fake_profile)
    monkeypatch.setattr(trainer, "load_dynamic_bootstrap_cohort", fake_cohort)

    scope = await trainer.BackgroundTrainer().current_training_scope(minimum_bootstrap_timestamps=1_206)

    assert scope[0] == profile
    assert scope[1] == TRAINING_UNIVERSE_MODE_PROSPECTIVE
    assert scope[2]["status"] == "eligible"
    assert cohort_called is False


@pytest.mark.asyncio
async def test_exact_dynamic_profile_never_applies_full_sample_symbol_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ml import lifecycle

    observed: dict[str, object] = {}

    async def fake_market_data(_symbols, **kwargs):
        observed.update(kwargs)
        raise RuntimeError("sentinel")

    monkeypatch.setattr(lifecycle, "load_training_market_data", fake_market_data)
    with pytest.raises(RuntimeError, match="sentinel"):
        await lifecycle.load_training_data_profile(
            None,
            lookback_days=365,
            max_symbols=25,
            horizon=8,
            minimum_rows_for_coverage=300,
            require_universe_replay=True,
            universe_replay_max_age_seconds=600,
            maximum_executable_spread_bps=12.0,
        )

    assert observed["max_symbols"] == 0
    assert observed["require_universe_replay"] is True

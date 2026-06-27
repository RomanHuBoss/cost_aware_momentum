from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.ml.data_profile import (
    TrainingDataProfile,
    compare_training_profiles,
    profile_from_symbol_rows,
)


def _profile(*, rows: int, symbols: tuple[str, ...], hours: int = 500):
    now = datetime(2026, 6, 28, tzinfo=UTC)
    per_symbol = max(1, rows // max(1, len(symbols)))
    return profile_from_symbol_rows(
        [
            (symbol, per_symbol, now - timedelta(hours=hours), now)
            for symbol in symbols
        ],
        unique_timestamps=hours,
        minimum_rows_for_coverage=300,
    )


def test_missing_profile_forces_dataset_aware_refresh() -> None:
    current = _profile(rows=50000, symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    result = compare_training_profiles(
        current,
        None,
        minimum_new_rows=10000,
        minimum_growth_ratio=0.10,
        minimum_new_symbols=5,
        minimum_universe_change_ratio=0.10,
    )
    assert result["material_change"] is True
    assert "active_model_missing_training_data_profile" in result["reasons"]


def test_large_historical_backfill_triggers_retraining() -> None:
    previous = _profile(rows=50000, symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    current = _profile(rows=70000, symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    result = compare_training_profiles(
        current,
        previous,
        minimum_new_rows=10000,
        minimum_growth_ratio=0.10,
        minimum_new_symbols=5,
        minimum_universe_change_ratio=0.10,
    )
    assert result["material_change"] is True
    assert "material_historical_row_growth" in result["reasons"]


def test_small_backfill_does_not_trigger_retraining() -> None:
    previous = _profile(rows=50000, symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    current = _profile(rows=52000, symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    result = compare_training_profiles(
        current,
        previous,
        minimum_new_rows=10000,
        minimum_growth_ratio=0.10,
        minimum_new_symbols=5,
        minimum_universe_change_ratio=0.10,
    )
    assert result["material_change"] is False


def test_material_universe_change_triggers_retraining() -> None:
    previous_symbols = tuple(f"S{i}USDT" for i in range(20))
    current_symbols = tuple(f"S{i}USDT" for i in range(15, 35))
    result = compare_training_profiles(
        _profile(rows=50000, symbols=current_symbols),
        _profile(rows=50000, symbols=previous_symbols),
        minimum_new_rows=10000,
        minimum_growth_ratio=0.10,
        minimum_new_symbols=5,
        minimum_universe_change_ratio=0.10,
    )
    assert result["material_change"] is True
    assert "material_training_universe_change" in result["reasons"]


def test_profile_round_trip_from_json_mapping_preserves_timestamps() -> None:
    original = _profile(rows=50000, symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    restored = TrainingDataProfile.from_mapping(original.to_dict())

    assert restored == original
    assert restored is not None
    assert restored.start_time is not None
    assert restored.start_time.tzinfo is not None
    assert restored.end_time is not None
    assert restored.end_time.tzinfo is not None


def test_zero_row_expected_symbol_reduces_coverage() -> None:
    now = datetime(2026, 6, 28, tzinfo=UTC)
    profile = profile_from_symbol_rows(
        [
            ("BTCUSDT", 500, now - timedelta(hours=500), now),
            ("NEWUSDT", 0, None, None),
        ],
        unique_timestamps=500,
        minimum_rows_for_coverage=300,
    )

    assert profile.symbol_count == 2
    assert profile.covered_symbols == 1
    assert profile.coverage_ratio == 0.5
    assert "NEWUSDT" in profile.symbols

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.config import Settings
from app.ml.data_profile import profile_from_symbol_rows
from app.ml.lifecycle import ModelCandidate, evaluate_quality_gate, load_training_market_data


class _Result:
    def __init__(self, rows: list[object] | None = None) -> None:
        self._rows = rows or []

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[object]:
        return self._rows


class _Session:
    def __init__(self) -> None:
        self.queries: list[object] = []

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        return None

    async def execute(self, query: object) -> _Result:
        self.queries.append(query)
        return _Result()


def _profile(
    *,
    rows: list[tuple[str, int, datetime | None, datetime | None]],
    unique_timestamps: int = 1_500,
    minimum_rows_for_coverage: int = 300,
):
    return profile_from_symbol_rows(
        rows,
        unique_timestamps=unique_timestamps,
        minimum_rows_for_coverage=minimum_rows_for_coverage,
    )


def _candidate(tmp_path: Path, profile) -> ModelCandidate:
    now = datetime(2026, 7, 7, tzinfo=UTC)
    return ModelCandidate(
        path=tmp_path / "candidate.joblib",
        version="candidate-v1",
        model_type="hist_gradient_boosting",
        horizon=8,
        training_start=profile.start_time or now,
        training_end=profile.end_time or now,
        dataset_rows=profile.candle_rows * 2,
        unique_timestamps=profile.unique_timestamps,
        symbol_count=profile.symbol_count,
        symbol_sample=profile.symbols[:25],
        training_data_profile=profile,
        metrics={},
        incumbent_metrics=None,
        incumbent_version=None,
    )


def test_background_training_resolves_exact_preflight_symbols_and_frozen_cutoff() -> None:
    from app.workers.trainer import require_training_trigger_profile

    end = datetime(2026, 7, 6, 12, tzinfo=UTC)
    profile = _profile(
        rows=[
            ("ETHUSDT", 1_500, end - timedelta(hours=1_499), end),
            ("BTCUSDT", 1_500, end - timedelta(hours=1_499), end),
        ]
    )

    parsed, symbols, maximum_open_time = require_training_trigger_profile(
        {"reason": "bootstrap_training", "training_data_profile": profile.to_dict()},
        horizon_hours=8,
    )

    assert parsed == profile
    assert symbols == ["BTCUSDT", "ETHUSDT"]
    assert maximum_open_time == end + timedelta(hours=8)


@pytest.mark.parametrize(
    "trigger",
    [
        {},
        {"training_data_profile": {"candle_rows": "invalid"}},
    ],
)
def test_background_training_rejects_missing_or_invalid_preflight_profile(
    trigger: dict[str, object],
) -> None:
    from app.workers.trainer import require_training_trigger_profile

    with pytest.raises(RuntimeError, match="preflight training_data_profile"):
        require_training_trigger_profile(trigger, horizon_hours=8)


@pytest.mark.asyncio
async def test_market_data_loader_applies_preflight_upper_bound_to_all_candle_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ml import lifecycle

    session = _Session()
    monkeypatch.setattr(lifecycle, "SessionFactory", lambda: session)
    maximum_open_time = datetime(2026, 7, 7, 8, tzinfo=UTC)

    result = await load_training_market_data(
        ["BTCUSDT"],
        lookback_days=365,
        max_symbols=0,
        horizon=8,
        maximum_open_time=maximum_open_time,
    )

    assert result.candles.empty
    candle_queries = [query for query in session.queries if "market.candles" in str(query)]
    assert len(candle_queries) == 3
    for query in candle_queries:
        sql = str(query)
        assert "market.candles.open_time <=" in sql
        assert maximum_open_time in query.compile().params.values()


def test_quality_gate_rejects_post_feature_symbol_coverage_loss(tmp_path: Path) -> None:
    end = datetime(2026, 7, 6, 12, tzinfo=UTC)
    expected = _profile(
        rows=[
            ("BTCUSDT", 1_500, end - timedelta(hours=1_499), end),
            ("ETHUSDT", 1_500, end - timedelta(hours=1_499), end),
        ],
        minimum_rows_for_coverage=200,
    )
    actual = _profile(
        rows=[
            ("BTCUSDT", 1_400, end - timedelta(hours=1_399), end),
            ("ETHUSDT", 0, None, None),
        ],
        unique_timestamps=1_400,
    )

    gate = evaluate_quality_gate(
        _candidate(tmp_path, actual),
        Settings(),
        expected_training_profile=expected,
    )

    assert not gate["passed"]
    assert "fitted_symbol_history_coverage_below_minimum" in gate["reasons"]
    assert "training_profile_minimum_rows_contract_mismatch" in gate["reasons"]
    assert gate["absolute"]["training_scope"]["expected"]["symbols"] == [
        "BTCUSDT",
        "ETHUSDT",
    ]


def test_quality_gate_rejects_symbol_scope_or_time_advance_after_preflight(tmp_path: Path) -> None:
    end = datetime(2026, 7, 6, 12, tzinfo=UTC)
    expected = _profile(
        rows=[("BTCUSDT", 1_500, end - timedelta(hours=1_499), end)]
    )
    actual_end = end + timedelta(hours=1)
    actual = _profile(
        rows=[("SOLUSDT", 1_500, actual_end - timedelta(hours=1_499), actual_end)]
    )

    gate = evaluate_quality_gate(
        _candidate(tmp_path, actual),
        Settings(),
        expected_training_profile=expected,
    )

    assert "training_symbol_scope_changed_after_preflight" in gate["reasons"]
    assert "training_data_advanced_beyond_preflight_cutoff" in gate["reasons"]

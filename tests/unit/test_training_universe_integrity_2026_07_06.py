from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.ml.lifecycle import _select_training_symbols


class _Result:
    def __init__(
        self,
        *,
        scalar: object | None = None,
        scalars: list[object] | None = None,
        rows: list[tuple[object, ...]] | None = None,
    ) -> None:
        self._scalar = scalar
        self._scalars = scalars or []
        self._rows = rows or []

    def scalar_one_or_none(self) -> object | None:
        return self._scalar

    def scalar_one(self) -> object:
        return self._scalar

    def scalars(self) -> _Result:
        return self

    def __iter__(self):
        return iter(self._scalars)

    def all(self) -> list[object] | list[tuple[object, ...]]:
        return self._rows or self._scalars


class _QueryAwareSession:
    def __init__(self) -> None:
        self.queries: list[object] = []

    async def execute(self, query) -> _Result:
        sql = str(query)
        self.queries.append(query)
        if "ticker_snapshots" in sql:
            return _Result(scalars=["HOT_NEW_USDT"])
        if "GROUP BY market.candles.symbol" in sql:
            return _Result(scalars=["BTCUSDT", "ETHUSDT"])
        if "max(market.candles.open_time)" in sql:
            return _Result(scalar=datetime(2026, 7, 6, 0, 0, tzinfo=UTC))
        raise AssertionError(f"Unexpected SQL: {sql}")


@pytest.mark.asyncio
async def test_dynamic_training_universe_uses_label_eligible_candle_history_not_latest_ticker() -> None:
    session = _QueryAwareSession()

    selected = await _select_training_symbols(
        session,
        None,
        max_symbols=2,
        interval="60",
        lookback_days=365,
        horizon=8,
        minimum_rows_for_coverage=300,
    )

    assert selected == ["BTCUSDT", "ETHUSDT"]
    rendered = [str(query) for query in session.queries]
    assert all("ticker_snapshots" not in query for query in rendered)
    cohort_query = next(query for query in session.queries if "GROUP BY" in str(query))
    cohort_sql = str(cohort_query)
    cohort_params = cohort_query.compile().params
    assert "market.candles.open_time <=" in cohort_sql
    assert "market.candles.open_time >=" in cohort_sql
    assert "HAVING count(market.candles.id) >=" in cohort_sql
    assert "max(market.candles.open_time) >=" in cohort_sql
    assert 300 in cohort_params.values()
    assert datetime(2026, 7, 5, 16, 0, tzinfo=UTC) in cohort_params.values()

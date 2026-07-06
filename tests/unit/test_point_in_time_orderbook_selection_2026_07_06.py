from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.api.v1 import recommendations
from app.services import execution
from app.services.market_snapshots import latest_available_orderbook_query


class _ScalarResult:
    def __init__(self, value: object | None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object | None:
        return self.value


class _PointInTimeOrderbookSession:
    """Return the prior row only when unavailable future rows are excluded."""

    def __init__(self, *, cutoff: datetime) -> None:
        self.cutoff = cutoff
        self.prior = SimpleNamespace(
            symbol="BTCUSDT",
            source_time=cutoff - timedelta(seconds=5),
            received_at=cutoff - timedelta(seconds=4),
        )
        self.future = SimpleNamespace(
            symbol="BTCUSDT",
            source_time=cutoff + timedelta(minutes=5),
            received_at=cutoff + timedelta(minutes=5),
        )
        self.statement = None

    async def execute(self, statement) -> _ScalarResult:
        self.statement = statement
        compiled = statement.compile(dialect=postgresql.dialect())
        sql = str(compiled)
        params = compiled.params
        point_in_time = (
            "market.orderbook_snapshots.source_time <=" in sql
            and "market.orderbook_snapshots.received_at <=" in sql
            and list(params.values()).count(self.cutoff) == 2
        )
        return _ScalarResult(self.prior if point_in_time else self.future)


def _assert_latest_prior_contract(statement, *, cutoff: datetime) -> None:
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = " ".join(str(compiled).split())
    params = compiled.params
    assert "market.orderbook_snapshots.source_time <=" in sql
    assert "market.orderbook_snapshots.received_at <=" in sql
    assert sql.endswith(
        "ORDER BY market.orderbook_snapshots.source_time DESC, "
        "market.orderbook_snapshots.received_at DESC, "
        "market.orderbook_snapshots.id DESC LIMIT %(param_1)s"
    )
    assert list(params.values()).count(cutoff) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "loader",
    [
        execution.latest_orderbook,
        recommendations.latest_orderbook,
    ],
)
async def test_latest_orderbook_uses_latest_row_available_at_cutoff(loader) -> None:
    cutoff = datetime(2026, 7, 6, 18, 0, tzinfo=UTC)
    session = _PointInTimeOrderbookSession(cutoff=cutoff)

    selected = await loader(session, "btcusdt", cutoff=cutoff)

    assert selected is session.prior
    assert session.statement is not None
    _assert_latest_prior_contract(session.statement, cutoff=cutoff)


@pytest.mark.parametrize(
    ("symbol", "cutoff", "message"),
    [
        ("", datetime(2026, 7, 6, 18, 0, tzinfo=UTC), "symbol"),
        ("BTCUSDT", datetime(2026, 7, 6, 18, 0), "timezone-aware"),
    ],
)
def test_latest_orderbook_query_rejects_invalid_point_in_time_inputs(
    symbol: str, cutoff: datetime, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        latest_available_orderbook_query(symbol, cutoff=cutoff)

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.services.execution import effective_capital
from app.services.market_snapshots import latest_available_account_equity_query


class _ScalarResult:
    def __init__(self, value: object | None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object | None:
        return self.value


class _PointInTimeAccountSession:
    def __init__(self, *, cutoff: datetime) -> None:
        self.cutoff = cutoff
        self.prior = SimpleNamespace(
            account_id="account-1",
            equity=Decimal("1200"),
            day_start_equity=Decimal("1100"),
            available_margin=Decimal("800"),
            source_time=cutoff - timedelta(seconds=5),
            received_at=cutoff - timedelta(seconds=4),
        )
        self.future = SimpleNamespace(
            account_id="account-1",
            equity=Decimal("1"),
            day_start_equity=Decimal("1"),
            available_margin=Decimal("0"),
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
            "advisory.account_equity_snapshots.source_time <=" in sql
            and "advisory.account_equity_snapshots.received_at <=" in sql
            and list(params.values()).count(self.cutoff) == 2
        )
        return _ScalarResult(self.prior if point_in_time else self.future)


def _assert_latest_prior_contract(statement, *, cutoff: datetime) -> None:
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = " ".join(str(compiled).split())
    assert "advisory.account_equity_snapshots.source_time <=" in sql
    assert "advisory.account_equity_snapshots.received_at <=" in sql
    assert sql.endswith(
        "ORDER BY advisory.account_equity_snapshots.source_time DESC, "
        "advisory.account_equity_snapshots.received_at DESC, "
        "advisory.account_equity_snapshots.id DESC LIMIT %(param_1)s"
    )
    assert list(compiled.params.values()).count(cutoff) == 2


@pytest.mark.asyncio
async def test_effective_capital_uses_latest_account_snapshot_available_at_cutoff() -> None:
    cutoff = datetime(2026, 7, 6, 18, 0, tzinfo=UTC)
    session = _PointInTimeAccountSession(cutoff=cutoff)
    profile = SimpleNamespace(
        mode="bybit_read_only",
        source_account_id="account-1",
        allocated_capital=Decimal("1000"),
        capital_verified=True,
    )

    capital, available_margin, verified, diagnostics = await effective_capital(
        session,
        profile,
        now=cutoff,
        max_snapshot_age_seconds=180,
    )

    assert capital == Decimal("1000")
    assert available_margin == Decimal("800")
    assert verified is True
    assert diagnostics["snapshot_age_seconds"] == pytest.approx(5.0)
    assert session.statement is not None
    _assert_latest_prior_contract(session.statement, cutoff=cutoff)


@pytest.mark.parametrize(
    ("account_id", "cutoff", "message"),
    [
        ("", datetime(2026, 7, 6, 18, 0, tzinfo=UTC), "Account id"),
        ("account-1", datetime(2026, 7, 6, 18, 0), "timezone-aware"),
    ],
)
def test_account_snapshot_query_rejects_invalid_point_in_time_inputs(
    account_id: str, cutoff: datetime, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        latest_available_account_equity_query(account_id, cutoff=cutoff)

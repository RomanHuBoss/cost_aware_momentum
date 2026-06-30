from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

import app.services.execution as execution
from app.db.models import PositionSnapshot

D = Decimal
PROFILE_A = UUID("11111111-1111-1111-1111-111111111111")
PROFILE_B = UUID("22222222-2222-2222-2222-222222222222")


class _Result:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one(self) -> object:
        return self._value

    def scalar_one_or_none(self) -> object:
        return self._value

    def scalars(self) -> _Result:
        return self

    def all(self) -> object:
        return self._value


def _profile(
    profile_id: UUID,
    *,
    mode: str,
    source_account_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=profile_id,
        mode=mode,
        source_account_id=source_account_id,
    )


def test_position_snapshot_persists_account_identity() -> None:
    assert "account_id" in PositionSnapshot.__table__.columns
    assert PositionSnapshot.__table__.columns["account_id"].nullable is False


def test_risk_scope_key_is_profile_local_but_account_shared() -> None:
    manual_a = _profile(PROFILE_A, mode="manual")
    manual_b = _profile(PROFILE_B, mode="manual")
    account_a = _profile(PROFILE_A, mode="bybit_read_only", source_account_id="account-1")
    account_b = _profile(PROFILE_B, mode="bybit_read_only", source_account_id="account-1")

    assert execution.risk_scope_key(manual_a) != execution.risk_scope_key(manual_b)
    assert execution.risk_scope_key(account_a) == execution.risk_scope_key(account_b)
    assert execution.risk_scope_key(account_a) == "account:account-1"


async def test_open_risk_is_filtered_to_manual_profile() -> None:
    profile = _profile(PROFILE_A, mode="manual")
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[_Result(D("7.5")), _Result(D("4.25"))])
    )

    result = await execution.open_risk_usdt(session, profile=profile)

    assert result == D("11.75")
    statements = [str(call.args[0]) for call in session.execute.await_args_list]
    assert all("execution_plans.profile_id" in statement for statement in statements)
    assert all(str(PROFILE_A) not in statement for statement in statements)


async def test_open_risk_is_filtered_to_shared_bybit_account() -> None:
    profile = _profile(
        PROFILE_A,
        mode="bybit_read_only",
        source_account_id="account-1",
    )
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[_Result(D("5")), _Result(D("2"))])
    )

    assert await execution.open_risk_usdt(session, profile=profile) == D("7")
    statements = [str(call.args[0]) for call in session.execute.await_args_list]
    assert all("capital_profiles.source_account_id" in statement for statement in statements)
    assert all("capital_profiles.mode" in statement for statement in statements)


async def test_reconciliation_is_filtered_to_profile_account() -> None:
    timestamp = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    profile = _profile(
        PROFILE_A,
        mode="bybit_read_only",
        source_account_id="account-1",
    )
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Result(SimpleNamespace(source_time=timestamp)),
                _Result([SimpleNamespace(symbol="BTCUSDT", side="BUY", qty=D("1"))]),
                _Result([SimpleNamespace(symbol="BTCUSDT", direction="LONG", remaining_qty=D("1"))]),
            ]
        )
    )

    assert await execution.reconciliation_issues(session, profile=profile) == []
    statements = [str(call.args[0]) for call in session.execute.await_args_list]
    assert "account_equity_snapshots.account_id" in statements[0]
    assert "position_snapshots.account_id" in statements[1]
    assert "capital_profiles.source_account_id" in statements[2]


@pytest.mark.parametrize("mode", ["manual", "paper"])
async def test_non_exchange_profiles_do_not_run_exchange_reconciliation(mode: str) -> None:
    session = SimpleNamespace(execute=AsyncMock())
    profile = _profile(PROFILE_A, mode=mode)

    assert await execution.reconciliation_issues(session, profile=profile) == []
    session.execute.assert_not_awaited()


def test_read_only_scope_rejects_missing_account_identity() -> None:
    profile = _profile(PROFILE_A, mode="bybit_read_only", source_account_id=None)

    with pytest.raises(ValueError, match="source_account_id"):
        execution.risk_scope_key(profile)
    with pytest.raises(ValueError, match="source_account_id"):
        execution.execution_plan_scope_clause(profile)


async def test_account_sync_stamps_positions_with_same_account_id() -> None:
    from app.config import Settings
    from app.db.models import AccountEquitySnapshot, OutboxEvent
    from app.services.market_data import (
        BYBIT_READ_ONLY_ACCOUNT_ID,
        sync_read_only_account,
    )

    class _Session:
        def __init__(self) -> None:
            self.execute = AsyncMock(side_effect=[_Result(None), _Result(None)])
            self.added: list[object] = []

        def add(self, value: object) -> None:
            self.added.append(value)

    client = SimpleNamespace(
        get_wallet_balance=AsyncMock(
            return_value={
                "list": [
                    {
                        "totalEquity": "1000",
                        "totalAvailableBalance": "750",
                    }
                ]
            }
        ),
        get_positions=AsyncMock(
            return_value=[
                {
                    "symbol": "BTCUSDT",
                    "side": "Buy",
                    "size": "0.1",
                    "avgPrice": "60000",
                    "markPrice": "60100",
                    "unrealisedPnl": "10",
                }
            ]
        ),
    )
    session = _Session()
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        bybit_read_only_account=True,
    )

    result = await sync_read_only_account(session, client, settings)

    equity = next(item for item in session.added if isinstance(item, AccountEquitySnapshot))
    position = next(item for item in session.added if isinstance(item, PositionSnapshot))
    assert any(isinstance(item, OutboxEvent) for item in session.added)
    assert equity.account_id == BYBIT_READ_ONLY_ACCOUNT_ID
    assert position.account_id == equity.account_id
    assert result["positions"] == 1


async def test_portfolio_api_filters_manual_journal_to_active_profile() -> None:
    from app.api.v1.portfolio import portfolio_risk

    profile = SimpleNamespace(
        id=PROFILE_A,
        name="Manual A",
        mode="manual",
        source_account_id=None,
        allocated_capital=D("1000"),
        max_total_risk_rate=D("0.02"),
    )
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[_Result(profile), _Result([])])
    )

    result = await portfolio_risk(session)

    journal_statement = str(session.execute.await_args_list[1].args[0])
    assert "execution_plans.profile_id" in journal_statement
    assert result["profile"]["id"] == str(PROFILE_A)
    assert result["exchange_positions"] == []
    assert result["reconciliation_issues"] == []

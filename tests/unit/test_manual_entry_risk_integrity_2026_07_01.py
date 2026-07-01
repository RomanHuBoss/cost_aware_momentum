from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.schemas import ManualEntryRequest
from app.api.v1 import trades as trades_module
from app.config import Settings
from app.risk.math import (
    CostScenario,
    InstrumentConstraints,
    actual_fill_stress_loss,
    calculate_position_plan,
)
from app.services.execution import (
    effective_capital,
    reserved_margin_usdt,
    validate_execution_plan_for_acceptance,
)

D = Decimal
BASE = datetime(2026, 6, 30, 0, tzinfo=UTC)


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value


class _ManualEntrySession:
    def __init__(self, plan: object, signal: object) -> None:
        self.results = [_ScalarResult(plan), _ScalarResult(None)]
        self.signal = signal
        self.added: list[object] = []
        self.committed = False

    async def execute(self, _query: object) -> _ScalarResult:
        return self.results.pop(0)

    async def get(self, _model: object, _key: object) -> object:
        return self.signal

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


class _NoQuerySession:
    async def execute(self, _query: object) -> object:
        raise AssertionError("manual/paper effective capital must not query external account state")


async def _none(*_args: object, **_kwargs: object) -> None:
    return None


@pytest.fixture(autouse=True)
def _isolate_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trades_module, "_cached_or_none", _none)
    monkeypatch.setattr(trades_module, "append_audit_event", _none)
    monkeypatch.setattr(trades_module, "publish_outbox", _none)
    monkeypatch.setattr(trades_module, "store_cached", _none)


def _signal() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        symbol="BTCUSDT",
        direction="LONG",
        publish_time=BASE,
        expires_at=BASE + timedelta(hours=1),
        entry_low=D("99"),
        entry_high=D("101"),
        stop_loss=D("98"),
    )


def _snapshot() -> dict[str, object]:
    return {
        "entry_price": "100",
        "planning_time": BASE.isoformat(),
        "instrument": {
            "qty_step": "0.001",
            "min_qty": "0.001",
            "min_notional": "5",
            "max_qty": "1000",
            "max_leverage": "100",
        },
        "costs": {
            "fee_rate_round_trip": "0.001",
            "slippage_rate": "0",
            "stop_gap_reserve_rate": "0",
            "funding_rate": "0",
        },
    }


def _plan(signal: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        status="ACCEPTED",
        signal_id=signal.id,
        qty=D("1"),
        leverage=3,
        risk_budget=D("10"),
        actual_stress_loss=D("2.099"),
        margin_estimate=D("33.3333333333333333333333333333333333"),
        sizing_snapshot=_snapshot(),
    )


def _payload(plan: SimpleNamespace, **updates: object) -> ManualEntryRequest:
    values: dict[str, object] = {
        "plan_id": plan.id,
        "entry_time": BASE + timedelta(minutes=1),
        "entry_price": D("100"),
        "qty": D("1"),
        "leverage": 3,
        "fee": D("0.05"),
    }
    values.update(updates)
    return ManualEntryRequest(**values)


@pytest.mark.asyncio
async def test_manual_profile_allocated_capital_is_theoretical_margin_capacity() -> None:
    profile = SimpleNamespace(
        mode="manual",
        allocated_capital=D("1000"),
        capital_verified=False,
    )

    capital, available_margin, verified, diagnostics = await effective_capital(
        _NoQuerySession(), profile
    )

    assert capital == D("1000")
    assert available_margin == D("1000")
    assert verified is False
    assert diagnostics["available_margin_basis"] == "allocated_capital"


def test_actual_fill_stress_loss_replaces_only_the_modeled_entry_fee() -> None:
    loss = actual_fill_stress_loss(
        qty=D("1"),
        entry=D("100"),
        stop=D("98"),
        direction="LONG",
        costs=CostScenario(D("0.001"), D("0"), D("0"), D("0")),
        actual_entry_fee=D("1"),
    )

    # Price loss 2.00 + modeled exit fee 0.049 + actual entry fee 1.00.
    assert loss == D("3.049")


@pytest.mark.asyncio
async def test_manual_profile_margin_capacity_limits_position_sizing() -> None:
    profile = SimpleNamespace(
        mode="paper",
        allocated_capital=D("1000"),
        capital_verified=False,
    )
    capital, available_margin, verified, _ = await effective_capital(
        _NoQuerySession(), profile
    )

    plan = calculate_position_plan(
        effective_capital=capital,
        risk_rate=D("0.02"),
        entry=D("100"),
        stop=D("99.9"),
        direction="LONG",
        costs=CostScenario(D("0"), D("0"), D("0"), D("0")),
        constraints=InstrumentConstraints(
            qty_step=D("0.1"),
            min_qty=D("0.1"),
            min_notional=D("5"),
            max_qty=None,
            max_leverage=D("10"),
        ),
        leverage=1,
        available_margin=available_margin,
        margin_reserve_rate=D("0.25"),
        capital_verified=verified,
    )

    assert plan.limiting_cap == "MARGIN"
    assert plan.notional == D("750.0")
    assert plan.margin_estimate == D("750.0")


@pytest.mark.asyncio
async def test_manual_entry_rejects_actual_fee_that_exceeds_reserved_stress_loss() -> None:
    signal = _signal()
    plan = _plan(signal)
    session = _ManualEntrySession(plan, signal)

    # Modeled entry fee is 0.05 USDT, but the actual fee is 1 USDT. The true
    # stop-scenario loss is 3.049 USDT: still below the loose risk_budget=10,
    # but above the 2.099 USDT actually reserved by the accepted plan.
    with pytest.raises(HTTPException) as exc_info:
        await trades_module.manual_entry(
            _payload(plan, fee=D("1")),
            session,
            "operator",
            "actual-fee-risk-1",
        )

    assert exc_info.value.status_code == 422
    assert "stress-loss reservation" in str(exc_info.value.detail)
    assert session.added == []
    assert session.committed is False
    assert plan.status == "ACCEPTED"


@pytest.mark.asyncio
async def test_manual_entry_rejects_margin_above_accepted_plan() -> None:
    signal = _signal()
    plan = _plan(signal)
    session = _ManualEntrySession(plan, signal)

    # Lower leverage is not automatically capacity-safe: at 1x this fill needs
    # 100 USDT of margin versus 33.33 USDT reserved by the accepted plan.
    with pytest.raises(HTTPException) as exc_info:
        await trades_module.manual_entry(
            _payload(plan, leverage=1),
            session,
            "operator",
            "actual-margin-risk-1",
        )

    assert exc_info.value.status_code == 422
    assert "accepted margin reservation" in str(exc_info.value.detail)
    assert session.added == []
    assert session.committed is False
    assert plan.status == "ACCEPTED"


def test_manual_entry_fee_label_declares_cash_unit() -> None:
    from pathlib import Path

    html = Path("web/index.html").read_text(encoding="utf-8")
    assert "Комиссия входа, USDT" in html


def test_existing_margin_reservations_reduce_new_position_capacity() -> None:
    plan = calculate_position_plan(
        effective_capital=D("1000"),
        risk_rate=D("0.20"),
        entry=D("100"),
        stop=D("99.9"),
        direction="LONG",
        costs=CostScenario(D("0"), D("0"), D("0"), D("0")),
        constraints=InstrumentConstraints(
            qty_step=D("0.1"),
            min_qty=D("0.1"),
            min_notional=D("5"),
            max_qty=None,
            max_leverage=D("10"),
        ),
        leverage=1,
        available_margin=D("1000"),
        margin_reserve_rate=D("0.25"),
        reserved_margin=D("600"),
        capital_verified=True,
    )

    # Global margin capacity is 1000 * (1 - 25%) - 600 = 150 USDT.
    assert plan.limiting_cap == "MARGIN"
    assert plan.notional == D("150.0")
    assert plan.margin_estimate == D("150.0")


def test_acceptance_rejects_plan_when_other_reservations_exhaust_margin() -> None:
    plan = SimpleNamespace(
        qty=D("2"),
        leverage=1,
        sizing_snapshot={"costs": {"funding_rate": "0"}},
    )
    signal = SimpleNamespace(
        direction="LONG",
        entry_reference=D("100"),
        entry_low=D("99"),
        entry_high=D("101"),
        stop_loss=D("98"),
        take_profit_1=D("104"),
        fee_rate_round_trip=D("0.001"),
        slippage_rate=D("0"),
        p_tp=0.70,
        p_sl=0.20,
        p_timeout=0.10,
    )
    profile = SimpleNamespace(
        risk_rate=D("0.10"),
        margin_reserve_rate=D("0.25"),
        max_leverage=5,
        mode="manual",
    )
    risk_state = SimpleNamespace(
        effective_capital=D("1000"),
        available_margin=D("1000"),
        reserved_margin_usdt=D("700"),
    )
    spec = SimpleNamespace(
        qty_step=D("0.001"),
        min_qty=D("0.001"),
        min_notional=D("5"),
        max_qty=D("1000"),
        max_leverage=D("100"),
        tick_size=D("0.1"),
    )

    with pytest.raises(ValueError, match="reserved margin"):
        validate_execution_plan_for_acceptance(
            plan=plan,
            signal=signal,
            profile=profile,
            risk_state=risk_state,
            spec=spec,
            executable_price=D("100"),
            current_funding_rate=D("0"),
            current_liquidity_notional_cap=D("100000"),
            settings=Settings(
                database_url="postgresql+psycopg://u:p@localhost/db",
                min_net_rr=0,
                min_net_ev_r=0,
            ),
        )


class _ScalarOneResult:
    def __init__(self, value: Decimal) -> None:
        self.value = value

    def scalar_one(self) -> Decimal:
        return self.value


class _ReservationSession:
    def __init__(self, values: list[Decimal]) -> None:
        self.values = list(values)
        self.calls = 0

    async def execute(self, _query: object) -> _ScalarOneResult:
        self.calls += 1
        return _ScalarOneResult(self.values.pop(0))


@pytest.mark.asyncio
async def test_manual_margin_reservation_includes_open_journal_trades() -> None:
    session = _ReservationSession([D("600"), D("100")])
    profile = SimpleNamespace(id=uuid4(), mode="manual", source_account_id=None)

    reserved = await reserved_margin_usdt(session, profile=profile)

    assert reserved == D("700")
    assert session.calls == 2


@pytest.mark.asyncio
async def test_read_only_margin_reservation_does_not_double_count_open_positions() -> None:
    session = _ReservationSession([D("125")])
    profile = SimpleNamespace(
        id=uuid4(),
        mode="bybit_read_only",
        source_account_id="account-1",
    )

    reserved = await reserved_margin_usdt(session, profile=profile)

    assert reserved == D("125")
    assert session.calls == 1

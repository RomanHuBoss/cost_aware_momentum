from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.schemas import ManualEntryRequest
from app.api.v1 import trades as trades_module
from app.services.outcomes import _funding_rate_for_holding_period, _record_plan_outcome
from scripts import replay as replay_module

BASE = datetime(2026, 7, 1, 0, tzinfo=UTC)
D = Decimal


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value


class _ScalarsResult:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def scalars(self) -> _ScalarsResult:
        return self

    def all(self) -> list[object]:
        return self.values


class _OutcomeSession:
    def __init__(self) -> None:
        self.row = None

    def add(self, row: object) -> None:
        self.row = row

    async def flush(self) -> None:
        return None


async def _none(*_args: object, **_kwargs: object) -> None:
    return None


def _signal() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        natural_key="BTCUSDT:2026-07-01T12:00:00+00:00:h4",
        symbol="BTCUSDT",
        direction="LONG",
        event_time=BASE,
        publish_time=BASE,
        expires_at=BASE + timedelta(hours=1),
        entry_reference=D("100"),
        entry_low=D("99"),
        entry_high=D("102"),
        stop_loss=D("98"),
        take_profit_1=D("104"),
        model_version="model-v1",
        calibration_version="cal-v1",
        feature_schema_version="features-v1",
        data_cutoff=BASE,
        feature_snapshot={},
    )


def _complete_snapshot() -> dict[str, object]:
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
            "slippage_rate": "0.0005",
            "stop_gap_reserve_rate": "0.001",
            "funding_rate": "0.0001",
            "funding_rate_per_settlement": "0.0001",
            "funding_next_settlement": (BASE + timedelta(hours=1)).isoformat(),
            "funding_interval_minutes": 480,
        },
    }


@pytest.mark.parametrize(
    "missing_key",
    ["fee_rate_round_trip", "slippage_rate", "stop_gap_reserve_rate"],
)
@pytest.mark.asyncio
async def test_plan_outcome_missing_cost_field_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
    missing_key: str,
) -> None:
    monkeypatch.setattr("app.services.outcomes.append_audit_event", _none)
    snapshot = _complete_snapshot()
    del snapshot["costs"][missing_key]  # type: ignore[index]
    signal = _signal()
    plan = SimpleNamespace(
        id=uuid4(),
        version=1,
        qty=D("1"),
        actual_stress_loss=D("3"),
        sizing_snapshot=snapshot,
    )
    signal_outcome = SimpleNamespace(
        id=uuid4(),
        outcome="TP",
        exit_price=D("104"),
        exit_time=BASE + timedelta(hours=2),
    )

    row = await _record_plan_outcome(
        _OutcomeSession(),
        signal=signal,
        signal_outcome=signal_outcome,
        plan=plan,
        actor="pytest",
    )

    assert row.valuation_status == "INVALID_INPUT"
    assert row.qty == D("0")
    assert row.estimated_net_pnl == D("0")
    assert missing_key in row.cost_assumptions["validation_error"]


@pytest.mark.parametrize("missing_key", ["entry_price", "planning_time"])
@pytest.mark.asyncio
async def test_plan_outcome_does_not_fabricate_missing_valuation_anchor(
    monkeypatch: pytest.MonkeyPatch,
    missing_key: str,
) -> None:
    monkeypatch.setattr("app.services.outcomes.append_audit_event", _none)
    snapshot = _complete_snapshot()
    del snapshot[missing_key]
    signal = _signal()
    plan = SimpleNamespace(
        id=uuid4(),
        version=1,
        qty=D("1"),
        actual_stress_loss=D("3"),
        sizing_snapshot=snapshot,
    )
    signal_outcome = SimpleNamespace(
        id=uuid4(),
        outcome="TP",
        exit_price=D("104"),
        exit_time=BASE + timedelta(hours=2),
    )

    row = await _record_plan_outcome(
        _OutcomeSession(),
        signal=signal,
        signal_outcome=signal_outcome,
        plan=plan,
        actor="pytest",
    )

    assert row.valuation_status == "INVALID_INPUT"
    assert row.qty == D("0")
    assert missing_key in row.cost_assumptions["validation_error"]


def test_null_funding_snapshot_is_unavailable_not_complete() -> None:
    snapshot = _complete_snapshot()
    snapshot["costs"]["funding_rate_per_settlement"] = None  # type: ignore[index]
    plan = SimpleNamespace(sizing_snapshot=snapshot)

    rate, complete, details = _funding_rate_for_holding_period(
        plan,
        start_time=BASE,
        exit_time=BASE + timedelta(hours=2),
    )

    assert rate == D("0")
    assert complete is False
    assert details["source"] == "plan_snapshot_incomplete"


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


@pytest.mark.parametrize(
    ("section", "missing_key"),
    [
        ("instrument", "qty_step"),
        ("instrument", "min_notional"),
        ("costs", "fee_rate_round_trip"),
        ("costs", "stop_gap_reserve_rate"),
    ],
)
@pytest.mark.asyncio
async def test_manual_entry_rejects_incomplete_accepted_plan_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    section: str,
    missing_key: str,
) -> None:
    monkeypatch.setattr(trades_module, "_cached_or_none", _none)
    monkeypatch.setattr(trades_module, "append_audit_event", _none)
    monkeypatch.setattr(trades_module, "publish_outbox", _none)
    monkeypatch.setattr(trades_module, "store_cached", _none)

    signal = _signal()
    snapshot = _complete_snapshot()
    del snapshot[section][missing_key]  # type: ignore[index]
    plan = SimpleNamespace(
        id=uuid4(),
        status="ACCEPTED",
        signal_id=signal.id,
        qty=D("1"),
        leverage=3,
        risk_budget=D("10"),
        sizing_snapshot=snapshot,
    )
    session = _ManualEntrySession(plan, signal)
    payload = ManualEntryRequest(
        plan_id=plan.id,
        entry_time=BASE + timedelta(minutes=1),
        entry_price=D("100"),
        qty=D("1"),
        leverage=3,
        fee=D("0.01"),
    )

    with pytest.raises(HTTPException) as exc_info:
        await trades_module.manual_entry(
            payload,
            session,
            "operator",
            "snapshot-integrity-1",
        )

    assert exc_info.value.status_code == 409
    assert "snapshot" in str(exc_info.value.detail).lower()
    assert missing_key in str(exc_info.value.detail)
    assert session.added == []
    assert session.committed is False
    assert plan.status == "ACCEPTED"


class _ReplaySession:
    def __init__(self, signal: object, plans: list[object]) -> None:
        self.signal = signal
        self.results = [_ScalarsResult(plans), _ScalarsResult([])]

    async def __aenter__(self) -> _ReplaySession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def get(self, _model: object, _key: object) -> object:
        return self.signal

    async def execute(self, _query: object) -> _ScalarsResult:
        return self.results.pop(0)


@pytest.mark.asyncio
async def test_replay_uses_immutable_plan_entry_not_signal_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signal = _signal()
    snapshot = _complete_snapshot()
    snapshot["entry_price"] = "101"
    snapshot["instrument"] = {
        "qty_step": "0.1",
        "min_qty": "0.1",
        "min_notional": "5",
        "max_qty": "1000",
        "max_leverage": "100",
    }
    snapshot["costs"] = {
        "fee_rate_round_trip": "0",
        "slippage_rate": "0",
        "stop_gap_reserve_rate": "0",
        "funding_rate": "0",
    }
    plan = SimpleNamespace(
        id=uuid4(),
        signal_id=signal.id,
        profile_id=uuid4(),
        version=1,
        status="ACTIONABLE",
        qty=D("5.0"),
        actual_stress_loss=D("10"),
        effective_capital=D("1000"),
        risk_rate=D("0.01"),
        leverage=1,
        capital_verified=True,
        sizing_snapshot=snapshot,
    )
    session = _ReplaySession(signal, [plan])
    monkeypatch.setattr(replay_module, "SessionFactory", lambda: session)

    payload = await replay_module.replay(signal.id)

    replayed = payload["plans"][0]
    assert replayed["replay_status"] == "RECOMPUTED"
    assert replayed["replay_entry_price"] == "101"
    assert replayed["recomputed_qty_without_dynamic_caps"] == "3.3"


@pytest.mark.asyncio
async def test_replay_marks_incomplete_snapshot_instead_of_zero_cost_recompute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signal = _signal()
    snapshot = _complete_snapshot()
    del snapshot["costs"]["fee_rate_round_trip"]  # type: ignore[index]
    plan = SimpleNamespace(
        id=uuid4(),
        signal_id=signal.id,
        profile_id=uuid4(),
        version=1,
        status="ACTIONABLE",
        qty=D("1"),
        actual_stress_loss=D("2"),
        effective_capital=D("1000"),
        risk_rate=D("0.01"),
        leverage=1,
        capital_verified=True,
        sizing_snapshot=snapshot,
    )
    session = _ReplaySession(signal, [plan])
    monkeypatch.setattr(replay_module, "SessionFactory", lambda: session)

    payload = await replay_module.replay(signal.id)

    replayed = payload["plans"][0]
    assert replayed["replay_status"] == "INVALID_SNAPSHOT"
    assert replayed["recomputed_qty_without_dynamic_caps"] is None
    assert "fee_rate_round_trip" in replayed["validation_error"]

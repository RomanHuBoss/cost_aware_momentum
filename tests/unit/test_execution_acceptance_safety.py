from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import app.services.execution as execution
from app.config import Settings
from app.risk.math import assess_liquidation_proximity
from app.services.execution import (
    effective_capital,
    executable_entry_price,
    liquidity_notional_cap,
    load_acceptance_risk_state,
)

D = Decimal
DEFAULT_CURRENT_CAPITAL = D("10000")
DEFAULT_AVAILABLE_MARGIN = D("5000")
DEFAULT_ACTUAL_STRESS_LOSS = D("50")
DEFAULT_MARGIN_ESTIMATE = D("100")
DEFAULT_QTY = D("1")
DEFAULT_QTY_STEP = D("0.001")
DEFAULT_MIN_QTY = D("0.001")
DEFAULT_MIN_NOTIONAL = D("5")
DEFAULT_MAX_QTY = D("1000")
DEFAULT_MAX_LEVERAGE = D("100")
DEFAULT_PROFILE_MAX_TOTAL_RISK_RATE = D("0.02")
DEFAULT_FUNDING_RATE = D("0")
DEFAULT_TURNOVER_24H = D("100000000")
DEFAULT_ORDERBOOK_SIZE = D("100000")
DEFAULT_BID_PRICE = D("99.9")
DEFAULT_ASK_PRICE = D("100.1")
DEFAULT_PLAN_ENTRY_PRICE = D("100")


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


@pytest.mark.parametrize(
    ("direction", "bid", "ask", "expected"),
    [
        ("LONG", D("100.00"), D("101.25"), D("101.25")),
        ("SHORT", D("99.75"), D("101.00"), D("99.75")),
    ],
)
def test_executable_entry_uses_adverse_order_book_side(
    direction: str,
    bid: Decimal,
    ask: Decimal,
    expected: Decimal,
) -> None:
    assert executable_entry_price(direction=direction, bid_price=bid, ask_price=ask) == expected


@pytest.mark.parametrize(
    ("direction", "bid", "ask"),
    [
        ("LONG", D("100"), None),
        ("SHORT", None, D("101")),
        ("LONG", D("100"), D("NaN")),
        ("SHORT", D("0"), D("101")),
    ],
)
def test_executable_entry_fails_closed_on_missing_or_invalid_side(
    direction: str,
    bid: Decimal | None,
    ask: Decimal | None,
) -> None:
    with pytest.raises(ValueError, match="executable"):
        executable_entry_price(direction=direction, bid_price=bid, ask_price=ask)


async def test_effective_capital_rejects_stale_exchange_snapshot() -> None:
    now = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)
    snapshot = SimpleNamespace(
        equity=D("1200"),
        day_start_equity=D("1100"),
        available_margin=D("800"),
        source_time=now - timedelta(seconds=181),
    )
    session = SimpleNamespace(execute=AsyncMock(return_value=_ScalarResult(snapshot)))
    profile = SimpleNamespace(
        mode="bybit_read_only",
        source_account_id="account-1",
        allocated_capital=D("1000"),
        capital_verified=True,
    )

    capital, available_margin, verified, diagnostics = await effective_capital(
        session,
        profile,
        now=now,
        max_snapshot_age_seconds=180,
    )

    assert capital == D("0")
    assert available_margin == D("0")
    assert verified is False
    assert diagnostics["stale_snapshot"] is True
    assert diagnostics["snapshot_age_seconds"] == pytest.approx(181.0)


async def test_acceptance_risk_state_acquires_account_lock_before_reading_risk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def fake_lock(session: object, namespace: str, value: str) -> None:
        del session
        events.append(f"lock:{namespace}:{value}")

    async def fake_open_risk(session: object, *, profile: object) -> Decimal:
        del session, profile
        events.append("open-risk")
        return D("12.5")

    async def fake_reserved_margin(session: object, *, profile: object) -> Decimal:
        del session, profile
        events.append("reserved-margin")
        return D("25")

    async def fake_effective_capital(*args: object, **kwargs: object) -> tuple:
        del args, kwargs
        events.append("capital")
        return D("1000"), D("500"), True, {"source": "bybit"}

    monkeypatch.setattr(execution, "acquire_advisory_xact_lock", fake_lock)
    monkeypatch.setattr(execution, "open_risk_usdt", fake_open_risk)
    monkeypatch.setattr(execution, "reserved_margin_usdt", fake_reserved_margin)
    monkeypatch.setattr(execution, "effective_capital", fake_effective_capital)

    profile = SimpleNamespace(
        id="profile-1",
        mode="bybit_read_only",
        source_account_id="account-1",
    )
    state = await load_acceptance_risk_state(
        object(),
        profile=profile,
        now=datetime(2026, 6, 29, 12, 0, tzinfo=UTC),
        max_snapshot_age_seconds=180,
    )

    assert events == [
        "lock:execution_risk_accept:account:account-1",
        "open-risk",
        "reserved-margin",
        "capital",
    ]
    assert state.open_risk_usdt == D("12.5")
    assert state.reserved_margin_usdt == D("25")
    assert state.effective_capital == D("1000")
    assert state.capital_verified is True


def test_stop_beyond_estimated_liquidation_is_detected_at_low_leverage() -> None:
    assessment = assess_liquidation_proximity(
        entry=D("100"),
        stop=D("65"),
        leverage=3,
    )

    assert assessment.stop_distance_rate == D("0.35")
    assert assessment.estimated_liquidation_distance_rate == D("0.3")
    assert assessment.buffer_rate == D("0")
    assert assessment.stop_beyond_estimated_liquidation is True


def test_account_snapshot_age_policy_rejects_unsafe_threshold() -> None:
    with pytest.raises(ValueError, match="MAX_ACCOUNT_SNAPSHOT_AGE_SECONDS"):
        Settings(
            max_account_snapshot_age_seconds=29,
            database_url="postgresql+psycopg://u:p@localhost/db",
        )


def test_liquidity_notional_cap_uses_exact_policy_fraction() -> None:
    assert liquidity_notional_cap(D("1000000")) == D("100")


@pytest.mark.parametrize("turnover", [None, D("0"), D("-1"), D("NaN"), D("Infinity")])
def test_liquidity_notional_cap_rejects_incomplete_or_invalid_turnover(
    turnover: Decimal | None,
) -> None:
    with pytest.raises(ValueError, match="turnover_24h"):
        liquidity_notional_cap(turnover)


class _ScalarOneResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one(self) -> object:
        return self._value


async def _build_plan_for_safety_case(
    monkeypatch: pytest.MonkeyPatch,
    *,
    profile_mode: str,
    stop_loss: Decimal,
    capital_result: tuple[Decimal, Decimal | None, bool, dict],
    funding_snapshot_complete: bool = True,
    turnover_24h: Decimal | None = DEFAULT_TURNOVER_24H,
    bid_price: Decimal | None = DEFAULT_BID_PRICE,
    ask_price: Decimal | None = DEFAULT_ASK_PRICE,
    signal_status: str = "PUBLISHED",
    baseline: bool = False,
    profile_max_total_risk_rate: Decimal = DEFAULT_PROFILE_MAX_TOTAL_RISK_RATE,
    orderbook_bids: list[list[str]] | None = None,
    orderbook_asks: list[list[str]] | None = None,
    max_vwap_impact_bps: float = 12.0,
    drift_blocked: bool = False,
    timeout_return_r: Decimal | None = None,
    timeout_gross_return_rate: Decimal | None = None,
):
    from uuid import uuid4

    signal = SimpleNamespace(
        id=uuid4(),
        symbol="BTCUSDT",
        warnings=[],
        fee_rate_round_trip=D("0.0011"),
        slippage_rate=D("0.0003"),
        funding_rate_scenario=D("0"),
        stress_downside_rate=D("0.36"),
        status=signal_status,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        net_rr=D("1.5"),
        net_ev_r=D("0.1"),
        gross_edge_rate=D("0.02"),
        p_tp=0.60,
        p_sl=0.25,
        p_timeout=0.15,
        entry_reference=D("100"),
        entry_low=D("99"),
        entry_high=D("101"),
        stop_loss=stop_loss,
        take_profit_1=D("120"),
        direction="LONG",
        model_version="baseline-momentum-v1" if baseline else "model-v1",
        calibration_version=("uncalibrated-baseline-v1" if baseline else "calibrated-v1"),
        feature_snapshot={
            "model_runtime": {"baseline": baseline, "source": "test"},
            **(
                {
                    "economics_assumptions": {
                        "timeout_return_r": str(timeout_return_r),
                        "timeout_gross_return_rate": str(timeout_gross_return_rate),
                    }
                }
                if timeout_return_r is not None and timeout_gross_return_rate is not None
                else {}
            ),
        },
    )
    profile = SimpleNamespace(
        id=uuid4(),
        mode=profile_mode,
        source_account_id="account-1" if profile_mode == "bybit_read_only" else None,
        allocated_capital=D("10000"),
        capital_verified=profile_mode != "bybit_read_only",
        max_leverage=3,
        default_leverage=3,
        max_total_risk_rate=profile_max_total_risk_rate,
        risk_rate=D("0.01"),
        margin_reserve_rate=D("0.25"),
        version=1,
    )
    ticker_time = datetime.now(UTC)
    ticker = SimpleNamespace(
        source_time=ticker_time,
        bid_price=bid_price,
        ask_price=ask_price,
        turnover_24h=turnover_24h,
        funding_rate=D("0") if funding_snapshot_complete else None,
        next_funding_time=(ticker_time + timedelta(hours=8) if funding_snapshot_complete else None),
    )
    orderbook = (
        SimpleNamespace(
            id=1,
            source_time=ticker_time,
            received_at=ticker_time,
            update_id=1,
            sequence=1,
            depth=200,
            best_bid=bid_price,
            best_ask=ask_price,
            bids=orderbook_bids or [[str(bid_price), "100000"]],
            asks=orderbook_asks or [[str(ask_price), "100000"]],
        )
        if bid_price is not None and ask_price is not None
        else None
    )
    spec = SimpleNamespace(
        tick_size=D("0.1"),
        qty_step=D("0.001"),
        min_qty=D("0.001"),
        min_notional=D("5"),
        max_qty=D("100000"),
        max_leverage=D("100"),
        funding_interval_minutes=480,
    )
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarOneResult(0)),
        add=lambda value: None,
        flush=AsyncMock(),
    )

    monkeypatch.setattr(execution, "latest_ticker", AsyncMock(return_value=ticker))
    monkeypatch.setattr(execution, "latest_orderbook", AsyncMock(return_value=orderbook))
    monkeypatch.setattr(execution, "latest_spec", AsyncMock(return_value=spec))
    monkeypatch.setattr(execution, "effective_capital", AsyncMock(return_value=capital_result))
    monkeypatch.setattr(execution, "open_risk_usdt", AsyncMock(return_value=D("0")))
    monkeypatch.setattr(execution, "reconciliation_issues", AsyncMock(return_value=[]))
    monkeypatch.setattr(execution, "append_audit_event", AsyncMock())
    monkeypatch.setattr(execution, "publish_outbox", AsyncMock())
    drift_guard = {
        "schema": "production-drift-critical-quarantine-v1",
        "blocked": drift_blocked,
        "model_version": "model-v1",
        "reason_code": "critical_production_drift" if drift_blocked else None,
        "critical_report_generated_at": (
            "2026-07-06T12:00:00+00:00" if drift_blocked else None
        ),
        "critical_alerts": ["calibration_drift"] if drift_blocked else [],
        "release_condition": "activate_different_model_version" if drift_blocked else None,
    }

    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        max_vwap_impact_bps=max_vwap_impact_bps,
    )
    return await execution.create_execution_plan(
        session,
        signal=signal,
        profile=profile,
        settings=settings,
        drift_guard=drift_guard,
    )


async def test_unvalidated_baseline_plan_is_diagnostic_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = await _build_plan_for_safety_case(
        monkeypatch,
        profile_mode="manual",
        stop_loss=D("98"),
        capital_result=(D("10000"), None, True, {"source": "manual"}),
        baseline=True,
    )

    assert plan.status == "NO_TRADE"
    assert any("baseline" in warning.lower() for warning in plan.warnings)
    assert plan.sizing_snapshot["attrition"]["schema"] == "execution-plan-attrition-v1"
    assert (
        plan.sizing_snapshot["attrition"]["primary_reason_code"]
        == "baseline_actionability_disabled"
    )


async def test_critical_drift_forces_execution_plan_to_no_trade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = await _build_plan_for_safety_case(
        monkeypatch,
        profile_mode="manual",
        stop_loss=D("98"),
        capital_result=(D("10000"), None, True, {"source": "manual"}),
        drift_blocked=True,
    )

    assert plan.status == "NO_TRADE"
    assert plan.sizing_snapshot["attrition"]["primary_reason_code"] == "critical_production_drift"
    assert plan.sizing_snapshot["production_drift_interlock"]["blocked"] is True
    assert any("production drift" in warning for warning in plan.warnings)


async def test_execution_plan_reprices_from_current_executable_quote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = await _build_plan_for_safety_case(
        monkeypatch,
        profile_mode="manual",
        stop_loss=D("98"),
        capital_result=(D("10000"), None, True, {"source": "manual"}),
        bid_price=D("99.8"),
        ask_price=D("100.4"),
    )

    assert D(plan.sizing_snapshot["entry_price"]) == D("100.4")


async def test_execution_plan_reprojects_timeout_r_at_current_vwap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = await _build_plan_for_safety_case(
        monkeypatch,
        profile_mode="manual",
        stop_loss=D("98"),
        capital_result=(D("10000"), None, True, {"source": "manual"}),
        bid_price=D("99.8"),
        ask_price=D("100.4"),
        timeout_return_r=D("-0.5"),
        timeout_gross_return_rate=D("-0.01"),
    )

    entry = D(plan.sizing_snapshot["entry_price"])
    expected = D("-0.5") * abs(entry - D("98")) / entry
    actual = D(plan.sizing_snapshot["timeout_gross_return_rate"])

    assert abs(actual - expected) <= D("1e-36")
    assert actual != D("-0.01")
    assert (
        plan.sizing_snapshot["economics_schema_version"]
        == "tp-sl-timeout-current-entry-r-v2"
    )




async def test_execution_plan_uses_full_depth_vwap_and_persists_fill_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = await _build_plan_for_safety_case(
        monkeypatch,
        profile_mode="manual",
        stop_loss=D("98"),
        capital_result=(D("10000"), None, True, {"source": "manual"}),
        bid_price=D("100.0"),
        ask_price=D("100.1"),
        orderbook_bids=[["100.0", "100000"]],
        orderbook_asks=[["100.1", "20"], ["100.2", "100000"]],
    )

    entry = D(plan.sizing_snapshot["entry_price"])
    evidence = plan.sizing_snapshot["execution_quality"]
    assert D("100.1") < entry < D("100.2")
    assert plan.status in {"ACTIONABLE", "LIMITED"}
    assert plan.sizing_snapshot["attrition"]["terminal_stage"] == "ACTIONABLE"
    assert evidence["fill_status"] == "FULL"
    assert D(evidence["vwap"]) == entry
    assert D(evidence["impact_bps"]) > 0
    assert evidence["levels_used"] == 2
    assert plan.sizing_snapshot["entry_price_source"] == "orderbook_depth_vwap"


async def test_execution_plan_is_depth_limited_instead_of_rounding_up_to_unfillable_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = await _build_plan_for_safety_case(
        monkeypatch,
        profile_mode="manual",
        stop_loss=D("98"),
        capital_result=(D("10000"), None, True, {"source": "manual"}),
        bid_price=D("100.0"),
        ask_price=D("100.1"),
        orderbook_bids=[["100.0", "100000"]],
        orderbook_asks=[["100.1", "1"], ["102", "100000"]],
    )

    assert plan.qty <= D("1")
    assert plan.notional <= D("100.1")
    assert plan.sizing_snapshot["execution_quality"]["fill_status"] == "FULL"
    assert D(plan.sizing_snapshot["caps"]["orderbook_depth_notional"]) == D("100.1")

async def test_execution_plan_fails_closed_when_executable_quote_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = await _build_plan_for_safety_case(
        monkeypatch,
        profile_mode="manual",
        stop_loss=D("98"),
        capital_result=(D("10000"), None, True, {"source": "manual"}),
        ask_price=None,
    )

    assert plan.status == "BLOCKED_STALE_DATA"
    assert any("глубины рынка" in warning for warning in plan.warnings)


async def test_execution_plan_marks_quote_outside_entry_zone_as_no_trade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = await _build_plan_for_safety_case(
        monkeypatch,
        profile_mode="manual",
        stop_loss=D("98"),
        capital_result=(D("10000"), None, True, {"source": "manual"}),
        bid_price=D("101.9"),
        ask_price=D("102"),
    )

    assert plan.status == "NO_TRADE"
    assert any("вне зоны входа" in warning for warning in plan.warnings)


async def test_terminal_signal_status_is_not_overwritten_by_liquidation_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = await _build_plan_for_safety_case(
        monkeypatch,
        profile_mode="manual",
        stop_loss=D("65"),
        capital_result=(D("10000"), None, True, {"source": "manual"}),
        signal_status="EXPIRED",
    )

    assert plan.status == "EXPIRED"
    assert "Стоп находится за оценочной областью ликвидации" not in plan.warnings


async def test_execution_plan_blocks_stop_beyond_liquidation_at_leverage_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = await _build_plan_for_safety_case(
        monkeypatch,
        profile_mode="manual",
        stop_loss=D("65"),
        capital_result=(D("10000"), None, True, {"source": "manual"}),
    )

    assert plan.status == "BLOCKED_LIQUIDATION"
    assert "Стоп находится за оценочной областью ликвидации" in plan.warnings


async def test_execution_plan_blocks_unverified_bybit_capital_as_stale_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = await _build_plan_for_safety_case(
        monkeypatch,
        profile_mode="bybit_read_only",
        stop_loss=D("98"),
        capital_result=(
            D("0"),
            D("0"),
            False,
            {"source": "bybit", "stale_snapshot": True},
        ),
    )

    assert plan.status == "BLOCKED_STALE_DATA"
    assert any("Снимок капитала" in warning for warning in plan.warnings)


async def test_execution_plan_blocks_profile_above_global_total_risk_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = await _build_plan_for_safety_case(
        monkeypatch,
        profile_mode="manual",
        stop_loss=D("98"),
        capital_result=(D("10000"), None, True, {"source": "manual"}),
        profile_max_total_risk_rate=D("0.20"),
    )

    assert plan.status == "BLOCKED_INVALID_INPUT"
    assert any("MAX_TOTAL_OPEN_RISK_RATE" in warning for warning in plan.warnings)


async def test_execution_plan_snapshot_persists_three_outcome_economics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = await _build_plan_for_safety_case(
        monkeypatch,
        profile_mode="manual",
        stop_loss=D("98"),
        capital_result=(D("10000"), None, True, {"source": "manual"}),
    )

    snapshot = plan.sizing_snapshot
    assert snapshot["economics_schema_version"] == "tp-sl-timeout-current-entry-r-v2"
    assert D(snapshot["upside_rate"]).is_finite()
    assert D(snapshot["timeout_net_rate"]).is_finite()
    assert D(snapshot["break_even_tp_probability"]).is_finite()
    assert snapshot["break_even_probability_semantics"] == ("P_SL=1-P_TP-P_TIMEOUT; P_TIMEOUT fixed")


class _NoRowsResult:
    def scalar_one_or_none(self) -> object | None:
        return None


async def _run_acceptance_case(
    monkeypatch: pytest.MonkeyPatch,
    *,
    current_capital: Decimal = DEFAULT_CURRENT_CAPITAL,
    available_margin: Decimal | None = DEFAULT_AVAILABLE_MARGIN,
    actual_stress_loss: Decimal = DEFAULT_ACTUAL_STRESS_LOSS,
    margin_estimate: Decimal = DEFAULT_MARGIN_ESTIMATE,
    qty: Decimal = DEFAULT_QTY,
    plan_leverage: int = 3,
    spec_qty_step: Decimal = DEFAULT_QTY_STEP,
    spec_min_qty: Decimal = DEFAULT_MIN_QTY,
    spec_min_notional: Decimal = DEFAULT_MIN_NOTIONAL,
    spec_max_qty: Decimal | None = DEFAULT_MAX_QTY,
    spec_max_leverage: Decimal = DEFAULT_MAX_LEVERAGE,
    current_funding_rate: Decimal | None = DEFAULT_FUNDING_RATE,
    next_funding_time: datetime | None = None,
    stored_funding_rate: Decimal = DEFAULT_FUNDING_RATE,
    funding_snapshot_complete: bool = True,
    turnover_24h: Decimal | None = DEFAULT_TURNOVER_24H,
    reconciliation_failures: list[str] | None = None,
    profile_max_total_risk_rate: Decimal = DEFAULT_PROFILE_MAX_TOTAL_RISK_RATE,
    orderbook_ask_size: Decimal = DEFAULT_ORDERBOOK_SIZE,
    orderbook_bids: list[list[str]] | None = None,
    orderbook_asks: list[list[str]] | None = None,
    plan_entry_price: Decimal = DEFAULT_PLAN_ENTRY_PRICE,
    plan_has_orderbook_evidence: bool = True,
    plan_planning_offset_seconds: int = -5,
    drift_blocked: bool = False,
    timeout_return_r: Decimal | None = None,
    timeout_gross_return_rate: Decimal | None = None,
):
    from uuid import uuid4

    import app.api.v1.recommendations as recommendations
    from app.api.schemas import DecisionRequest
    from app.services.execution import AcceptanceRiskState

    now = datetime.now(UTC)
    signal = SimpleNamespace(
        id=uuid4(),
        symbol="BTCUSDT",
        direction="LONG",
        status="PUBLISHED",
        expires_at=now + timedelta(hours=2),
        publish_time=now,
        horizon_hours=4,
        entry_reference=D("100"),
        entry_low=D("99"),
        entry_high=D("102"),
        stop_loss=D("98"),
        take_profit_1=D("104"),
        fee_rate_round_trip=D("0.0011"),
        slippage_rate=D("0.0003"),
        p_tp=0.60,
        p_sl=0.25,
        p_timeout=0.15,
        model_version="model-v2",
    )
    sizing_snapshot = {
        "entry_price": str(plan_entry_price),
        "planning_time": (now + timedelta(seconds=plan_planning_offset_seconds)).isoformat(),
        "costs": {"funding_rate": str(stored_funding_rate)},
    }
    if plan_has_orderbook_evidence:
        sizing_snapshot["execution_quality"] = {
            "schema": "bybit-rest-depth-vwap-fill-v1",
            "fill_status": "FULL",
            "requested_qty": str(qty),
            "filled_qty": str(qty),
            "vwap": str(plan_entry_price),
        }
    plan = SimpleNamespace(
        id=uuid4(),
        signal_id=signal.id,
        profile_id=uuid4(),
        profile_version=1,
        version=1,
        status="ACTIONABLE",
        actual_stress_loss=actual_stress_loss,
        margin_estimate=margin_estimate,
        qty=qty,
        notional=qty * plan_entry_price,
        leverage=plan_leverage,
        sizing_snapshot=sizing_snapshot,
        accepted_at=None,
        superseded_by_id=None,
    )
    profile = SimpleNamespace(
        id=plan.profile_id,
        mode="bybit_read_only",
        source_account_id="account-1",
        version=1,
        risk_rate=D("0.01"),
        max_total_risk_rate=profile_max_total_risk_rate,
        margin_reserve_rate=D("0.25"),
        default_leverage=3,
        max_leverage=5,
        capital_verified=True,
    )
    ticker = SimpleNamespace(
        source_time=now,
        last_price=D("100"),
        bid_price=D("99.9"),
        ask_price=D("100"),
        turnover_24h=turnover_24h,
        funding_rate=current_funding_rate if funding_snapshot_complete else None,
        next_funding_time=(
            next_funding_time or now + timedelta(hours=8) if funding_snapshot_complete else None
        ),
    )
    orderbook = SimpleNamespace(
        id=1,
        source_time=now,
        received_at=now,
        update_id=1,
        sequence=1,
        depth=200,
        best_bid=D((orderbook_bids or [["99.9", "100000"]])[0][0]),
        best_ask=D((orderbook_asks or [["100", str(orderbook_ask_size)]])[0][0]),
        bids=orderbook_bids or [["99.9", "100000"]],
        asks=orderbook_asks or [["100", str(orderbook_ask_size)]],
    )
    spec = SimpleNamespace(
        valid_from=now - timedelta(hours=1),
        tick_size=D("0.1"),
        qty_step=spec_qty_step,
        min_qty=spec_min_qty,
        min_notional=spec_min_notional,
        max_qty=spec_max_qty,
        max_leverage=spec_max_leverage,
        funding_interval_minutes=480,
    )
    risk_state = AcceptanceRiskState(
        open_risk_usdt=D("0"),
        reserved_margin_usdt=D("0"),
        effective_capital=current_capital,
        available_margin=available_margin,
        capital_verified=True,
        capital_snapshot={"source": "bybit"},
    )
    replacement_plan = SimpleNamespace(id=uuid4(), status="ACTIONABLE")
    added_records: list[object] = []
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_NoRowsResult()),
        add=added_records.append,
        commit=AsyncMock(),
    )

    monkeypatch.setattr(
        recommendations,
        "production_drift_publication_guard",
        AsyncMock(
            return_value={
                "schema": "production-drift-critical-quarantine-v1",
                "blocked": drift_blocked,
                "model_version": signal.model_version,
                "reason_code": "critical_production_drift" if drift_blocked else None,
                "critical_report_generated_at": (
                    "2026-07-06T12:00:00+00:00" if drift_blocked else None
                ),
                "critical_alerts": ["calibration_drift"] if drift_blocked else [],
                "release_condition": (
                    "activate_different_model_version" if drift_blocked else None
                ),
            }
        ),
    )
    monkeypatch.setattr(recommendations, "_idempotent_response", AsyncMock(return_value=None))
    monkeypatch.setattr(
        recommendations,
        "_select_plan_for_action",
        AsyncMock(return_value=(signal, plan, profile)),
    )
    monkeypatch.setattr(recommendations, "latest_ticker", AsyncMock(return_value=ticker))
    monkeypatch.setattr(recommendations, "latest_orderbook", AsyncMock(return_value=orderbook))
    monkeypatch.setattr(
        recommendations,
        "latest_spec",
        AsyncMock(return_value=spec),
        raising=False,
    )
    monkeypatch.setattr(
        recommendations,
        "load_acceptance_risk_state",
        AsyncMock(return_value=risk_state),
    )
    monkeypatch.setattr(
        recommendations,
        "reconciliation_issues",
        AsyncMock(return_value=reconciliation_failures or []),
        raising=False,
    )
    monkeypatch.setattr(
        recommendations,
        "create_execution_plan",
        AsyncMock(return_value=replacement_plan),
    )
    monkeypatch.setattr(recommendations, "store_cached", AsyncMock())
    monkeypatch.setattr(recommendations, "append_audit_event", AsyncMock())
    monkeypatch.setattr(recommendations, "publish_outbox", AsyncMock())

    response = await recommendations.accept_recommendation(
        signal.id,
        DecisionRequest(plan_id=plan.id),
        session,
        Settings(database_url="postgresql+psycopg://u:p@localhost/db"),
        "test-operator",
        "acceptance-safety-test",
    )
    plan.added_records = added_records
    return response, plan


async def test_acceptance_persists_exact_orderbook_fill_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.models import OperatorDecision
    from app.risk.liquidity import ORDERBOOK_EXECUTION_SCHEMA_VERSION

    response, plan = await _run_acceptance_case(monkeypatch, qty=D("2"))

    assert response.status_code == 200
    decision = next(
        record for record in plan.added_records if isinstance(record, OperatorDecision)
    )
    evidence = decision.context_snapshot["execution_quality"]
    assert evidence["schema"] == ORDERBOOK_EXECUTION_SCHEMA_VERSION
    assert evidence["fill_status"] == "FULL"
    assert D(evidence["requested_qty"]) == D("2")
    assert D(evidence["filled_qty"]) == D("2")
    assert D(evidence["vwap"]) == D("100")
    assert evidence["update_id"] == 1
    assert decision.context_snapshot["operator_latency_seconds"] >= 5


async def test_acceptance_uses_exact_multilevel_depth_and_allows_between_tick_vwap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.models import OperatorDecision

    response, plan = await _run_acceptance_case(
        monkeypatch,
        qty=D("2"),
        orderbook_asks=[["100", "1"], ["100.1", "1"]],
        plan_entry_price=D("100.05"),
    )

    assert response.status_code == 200
    decision = next(
        record for record in plan.added_records if isinstance(record, OperatorDecision)
    )
    evidence = decision.context_snapshot["execution_quality"]
    assert D(evidence["vwap"]) == D("100.05")


async def test_acceptance_rejects_actionable_plan_after_critical_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response, plan = await _run_acceptance_case(
        monkeypatch,
        drift_blocked=True,
    )

    assert response.status_code == 409
    assert b"PLAN_RECALCULATION_REQUIRED" in response.body
    assert b"quarantined by critical production drift" in response.body
    assert plan.status == "SUPERSEDED"


async def test_acceptance_recalculates_legacy_plan_without_depth_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response, plan = await _run_acceptance_case(
        monkeypatch,
        plan_has_orderbook_evidence=False,
    )

    assert response.status_code == 409
    assert b"PLAN_RECALCULATION_REQUIRED" in response.body
    assert b"point-in-time orderbook evidence" in response.body
    assert plan.status == "SUPERSEDED"


async def test_acceptance_recalculates_plan_with_future_planning_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response, plan = await _run_acceptance_case(
        monkeypatch,
        plan_planning_offset_seconds=5,
    )

    assert response.status_code == 409
    assert b"PLAN_RECALCULATION_REQUIRED" in response.body
    assert b"planning time is in the future" in response.body
    assert plan.status == "SUPERSEDED"


async def test_acceptance_rejects_profile_above_global_total_risk_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response, plan = await _run_acceptance_case(
        monkeypatch,
        profile_max_total_risk_rate=D("0.20"),
    )

    assert response.status_code == 409
    assert b"PLAN_RECALCULATION_REQUIRED" in response.body
    assert b"MAX_TOTAL_OPEN_RISK_RATE" in response.body
    assert plan.status == "SUPERSEDED"


async def test_acceptance_recalculates_when_fresh_capital_breaks_per_trade_risk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response, plan = await _run_acceptance_case(
        monkeypatch,
        current_capital=D("1000"),
        actual_stress_loss=D("50"),
        qty=D("5"),
    )

    assert response.status_code == 409
    assert b"PLAN_RECALCULATION_REQUIRED" in response.body
    assert b"per-trade risk" in response.body
    assert plan.status == "SUPERSEDED"


async def test_acceptance_recalculates_when_fresh_available_margin_is_insufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response, plan = await _run_acceptance_case(
        monkeypatch,
        current_capital=D("10000"),
        available_margin=D("100"),
        actual_stress_loss=D("50"),
        margin_estimate=D("100"),
        qty=D("3"),
    )

    assert response.status_code == 409
    assert b"PLAN_RECALCULATION_REQUIRED" in response.body
    assert b"available margin" in response.body
    assert plan.status == "SUPERSEDED"


async def test_acceptance_recalculates_when_current_instrument_spec_invalidates_qty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response, plan = await _run_acceptance_case(
        monkeypatch,
        qty=D("0.01"),
        spec_qty_step=D("0.1"),
        spec_min_qty=D("0.1"),
    )

    assert response.status_code == 409
    assert b"PLAN_RECALCULATION_REQUIRED" in response.body
    assert b"instrument constraints" in response.body
    assert plan.status == "SUPERSEDED"


async def test_acceptance_recalculates_when_adverse_funding_cost_increases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response, plan = await _run_acceptance_case(
        monkeypatch,
        current_funding_rate=D("0.01"),
        next_funding_time=datetime.now(UTC) + timedelta(minutes=30),
        stored_funding_rate=D("0"),
    )

    assert response.status_code == 409
    assert b"PLAN_RECALCULATION_REQUIRED" in response.body
    assert b"funding cost" in response.body
    assert plan.status == "SUPERSEDED"


async def test_acceptance_recalculates_when_current_funding_snapshot_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response, plan = await _run_acceptance_case(
        monkeypatch,
        funding_snapshot_complete=False,
    )

    assert response.status_code == 409
    assert b"PLAN_RECALCULATION_REQUIRED" in response.body
    assert b"funding snapshot" in response.body
    assert plan.status == "SUPERSEDED"


async def test_acceptance_recalculates_when_account_reconciliation_is_not_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response, plan = await _run_acceptance_case(
        monkeypatch,
        reconciliation_failures=["Unknown exchange position BTCUSDT"],
    )

    assert response.status_code == 409
    assert b"PLAN_RECALCULATION_REQUIRED" in response.body
    assert b"Account reconciliation failed" in response.body
    assert plan.status == "SUPERSEDED"


async def test_acceptance_recalculates_when_current_liquidity_cap_is_too_low(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response, plan = await _run_acceptance_case(
        monkeypatch,
        qty=D("3"),
        turnover_24h=D("1000000"),
    )

    assert response.status_code == 409
    assert b"PLAN_RECALCULATION_REQUIRED" in response.body
    assert b"liquidity cap" in response.body
    assert plan.status == "SUPERSEDED"




async def test_acceptance_recalculates_when_current_depth_cannot_fill_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response, plan = await _run_acceptance_case(
        monkeypatch,
        qty=D("3"),
        orderbook_ask_size=D("1"),
    )

    assert response.status_code == 409
    assert b"cannot fully fill" in response.body
    assert plan.status == "SUPERSEDED"

async def test_acceptance_succeeds_only_after_fresh_state_revalidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response, plan = await _run_acceptance_case(monkeypatch)

    assert response.status_code == 200
    assert b'"status": "ACCEPTED"' in response.body
    assert plan.status == "ACCEPTED"


async def test_execution_plan_blocks_signal_prices_outside_current_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = await _build_plan_for_safety_case(
        monkeypatch,
        profile_mode="manual",
        stop_loss=D("98.05"),
        capital_result=(D("10000"), None, True, {"source": "manual"}),
    )

    assert plan.status == "BLOCKED_DATA"
    assert any("шагу цены" in warning for warning in plan.warnings)


async def test_execution_plan_blocks_missing_funding_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = await _build_plan_for_safety_case(
        monkeypatch,
        profile_mode="manual",
        stop_loss=D("98"),
        capital_result=(D("10000"), None, True, {"source": "manual"}),
        funding_snapshot_complete=False,
    )

    assert plan.status == "BLOCKED_DATA"
    assert any("funding" in warning.lower() for warning in plan.warnings)


async def test_execution_plan_blocks_missing_liquidity_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = await _build_plan_for_safety_case(
        monkeypatch,
        profile_mode="manual",
        stop_loss=D("98"),
        capital_result=(D("10000"), None, True, {"source": "manual"}),
        turnover_24h=None,
    )

    assert plan.status == "BLOCKED_DATA"
    assert any("ликвидност" in warning.lower() for warning in plan.warnings)


async def test_execution_plan_records_ex_ante_selection_experiment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = SimpleNamespace(
        ledger_schema="selection-experiment-ledger-v1",
        eligible=True,
        eligibility_status="ACTIONABLE",
        feature_schema="operator-selection-predecision-v1",
        feature_hash="a" * 64,
    )
    builder = Mock(return_value=sentinel)
    monkeypatch.setattr(execution, "build_selection_ledger_row", builder)

    plan = await _build_plan_for_safety_case(
        monkeypatch,
        profile_mode="manual",
        stop_loss=D("98"),
        capital_result=(D("10000"), None, True, {"source": "manual"}),
    )

    builder.assert_called_once()
    kwargs = builder.call_args.kwargs
    assert kwargs["plan"] is plan
    assert kwargs["signal"].id == plan.signal_id
    assert kwargs["release_version"] == execution.__version__
    assert kwargs["observed_at"].tzinfo is not None

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.db.models import (
    CapitalProfile,
    ExecutionPlan,
    MarketSignal,
    PlanOutcome,
    SignalOutcome,
    TickerSnapshot,
)
from app.risk.math import (
    CostScenario,
    break_even_tp_probability,
    finite_decimal,
    net_outcome_rates,
    net_rr_and_ev,
    positive_finite_decimal,
)
from app.services.execution import executable_entry_price

BREAK_EVEN_SEMANTICS = "P_SL=1-P_TP-P_TIMEOUT; P_TIMEOUT fixed"
_ECONOMICS_TOLERANCE = Decimal("1e-12")


def number(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _close_decimal(left: Decimal, right: Decimal) -> bool:
    return abs(left - right) <= _ECONOMICS_TOLERANCE


def _break_even_payload(
    *,
    downside_rate: Decimal,
    upside_rate: Decimal,
    timeout_net_rate: Decimal,
    p_timeout: float | Decimal,
) -> dict:
    threshold = break_even_tp_probability(
        downside_rate=downside_rate,
        upside_rate=upside_rate,
        timeout_net_rate=timeout_net_rate,
        p_timeout=p_timeout,
    )
    timeout_probability = finite_decimal(p_timeout, "p_timeout")
    maximum = Decimal("1") - timeout_probability
    return {
        "break_even_tp_probability": number(threshold),
        "break_even_probability": number(threshold),
        "break_even_probability_semantics": BREAK_EVEN_SEMANTICS,
        "break_even_probability_feasible": Decimal("0") <= threshold <= maximum,
        "max_feasible_tp_probability": number(maximum),
    }



def _signal_timeout_return_rate(signal: MarketSignal) -> Decimal:
    snapshot = getattr(signal, "feature_snapshot", None)
    if isinstance(snapshot, dict):
        assumptions = snapshot.get("economics_assumptions")
        if isinstance(assumptions, dict) and assumptions.get(
            "timeout_gross_return_rate"
        ) is not None:
            return finite_decimal(
                assumptions["timeout_gross_return_rate"],
                "timeout_gross_return_rate",
            )
    return Decimal("-0.002")

def signal_economics_dict(signal: MarketSignal) -> dict:
    """Serialize capital-independent signal economics with three-outcome break-even math."""

    try:
        costs = CostScenario(
            fee_rate_round_trip=finite_decimal(
                signal.fee_rate_round_trip, "fee_rate_round_trip"
            ),
            slippage_rate=finite_decimal(signal.slippage_rate, "slippage_rate"),
            # The stored signal downside already includes the configured reserve.
            # This zero is used only to recover TP and TIMEOUT net outcomes.
            stop_gap_reserve_rate=Decimal("0"),
            funding_rate=finite_decimal(
                signal.funding_rate_scenario, "funding_rate_scenario"
            ),
        )
        outcome_rates = net_outcome_rates(
            entry=signal.entry_reference,
            stop=signal.stop_loss,
            take_profit=signal.take_profit_1,
            direction=signal.direction,
            costs=costs,
            timeout_return_rate=_signal_timeout_return_rate(signal),
        )
        downside = positive_finite_decimal(
            signal.stress_downside_rate, "stress_downside_rate"
        )
        break_even = _break_even_payload(
            downside_rate=downside,
            upside_rate=outcome_rates.upside_rate,
            timeout_net_rate=outcome_rates.timeout_net_rate,
            p_timeout=signal.p_timeout,
        )
    except (ArithmeticError, TypeError, ValueError):
        break_even = {
            "break_even_tp_probability": None,
            "break_even_probability": None,
            "break_even_probability_semantics": BREAK_EVEN_SEMANTICS,
            "break_even_probability_feasible": False,
            "max_feasible_tp_probability": None,
        }
    return {
        "scope": "MARKET_SIGNAL_REFERENCE",
        "gross_rr": signal.gross_rr,
        "net_rr": signal.net_rr,
        "net_ev_r": signal.net_ev_r,
        "gross_edge_rate": signal.gross_edge_rate,
        "fee_rate_round_trip": signal.fee_rate_round_trip,
        "slippage_rate": signal.slippage_rate,
        "funding_rate_scenario": signal.funding_rate_scenario,
        "stress_downside_rate": signal.stress_downside_rate,
        "timeout_gross_return_rate": number(_signal_timeout_return_rate(signal)),
        **break_even,
    }


def execution_plan_economics_dict(signal: MarketSignal, plan: ExecutionPlan) -> dict:
    """Recompute and verify economics from the immutable execution-plan snapshot."""

    invalid = {
        "scope": "EXECUTION_PLAN_SNAPSHOT",
        "available": False,
        "integrity_status": "INVALID_SNAPSHOT",
        "entry_price": None,
        "net_rr": None,
        "net_ev_r": None,
        "stress_downside_rate": None,
        "upside_rate": None,
        "timeout_net_rate": None,
        "break_even_tp_probability": None,
        "break_even_probability": None,
        "break_even_probability_semantics": BREAK_EVEN_SEMANTICS,
        "break_even_probability_feasible": False,
        "max_feasible_tp_probability": None,
    }
    try:
        snapshot = plan.sizing_snapshot
        if not isinstance(snapshot, dict):
            return invalid
        cost_values = snapshot.get("costs")
        if not isinstance(cost_values, dict):
            return invalid
        entry = positive_finite_decimal(snapshot.get("entry_price"), "entry_price")
        timeout_return_rate = finite_decimal(
            snapshot.get("timeout_gross_return_rate", "-0.002"),
            "timeout_gross_return_rate",
        )
        costs = CostScenario(
            fee_rate_round_trip=finite_decimal(
                cost_values.get("fee_rate_round_trip"), "fee_rate_round_trip"
            ),
            slippage_rate=finite_decimal(cost_values.get("slippage_rate"), "slippage_rate"),
            stop_gap_reserve_rate=finite_decimal(
                cost_values.get("stop_gap_reserve_rate"), "stop_gap_reserve_rate"
            ),
            funding_rate=finite_decimal(cost_values.get("funding_rate"), "funding_rate"),
        )
        net_rr, net_ev_r, downside, upside = net_rr_and_ev(
            entry=entry,
            stop=signal.stop_loss,
            take_profit=signal.take_profit_1,
            direction=signal.direction,
            costs=costs,
            p_tp=signal.p_tp,
            p_sl=signal.p_sl,
            p_timeout=signal.p_timeout,
            timeout_return_rate=timeout_return_rate,
        )
        outcome_rates = net_outcome_rates(
            entry=entry,
            stop=signal.stop_loss,
            take_profit=signal.take_profit_1,
            direction=signal.direction,
            costs=costs,
            timeout_return_rate=timeout_return_rate,
        )
        stored_values = {
            "net_rr": finite_decimal(snapshot.get("net_rr"), "stored net_rr"),
            "net_ev_r": finite_decimal(snapshot.get("net_ev_r"), "stored net_ev_r"),
            "stress_downside_rate": finite_decimal(
                snapshot.get("stress_downside_rate"), "stored stress_downside_rate"
            ),
        }
        expected_values = {
            "net_rr": net_rr,
            "net_ev_r": net_ev_r,
            "stress_downside_rate": downside,
        }
        if any(
            not _close_decimal(stored_values[key], expected_values[key])
            for key in expected_values
        ):
            return invalid
        break_even = _break_even_payload(
            downside_rate=downside,
            upside_rate=upside,
            timeout_net_rate=outcome_rates.timeout_net_rate,
            p_timeout=signal.p_timeout,
        )
    except (ArithmeticError, TypeError, ValueError):
        return invalid

    return {
        "scope": "EXECUTION_PLAN_SNAPSHOT",
        "available": True,
        "integrity_status": "VERIFIED",
        "economics_schema_version": snapshot.get("economics_schema_version", "legacy-recomputed"),
        "entry_price": number(entry),
        "timeout_gross_return_rate": number(timeout_return_rate),
        "net_rr": number(net_rr),
        "net_ev_r": number(net_ev_r),
        "stress_downside_rate": number(downside),
        "upside_rate": number(upside),
        "timeout_net_rate": number(outcome_rates.timeout_net_rate),
        **break_even,
    }


def profile_dict(profile: CapitalProfile) -> dict:
    return {
        "id": str(profile.id),
        "name": profile.name,
        "mode": profile.mode,
        "allocated_capital": number(profile.allocated_capital),
        "risk_rate_pct": number(profile.risk_rate * 100),
        "max_total_risk_rate_pct": number(profile.max_total_risk_rate * 100),
        "default_leverage": profile.default_leverage,
        "max_leverage": profile.max_leverage,
        "margin_reserve_rate_pct": number(profile.margin_reserve_rate * 100),
        "source_account_id": profile.source_account_id,
        "active": profile.active,
        "version": profile.version,
        "capital_verified": profile.capital_verified,
        "updated_at": profile.updated_at.isoformat(),
    }


def entry_state(signal: MarketSignal, ticker: TickerSnapshot | None) -> str:
    now = datetime.now(UTC)
    if signal.expires_at <= now:
        return "EXPIRED"
    if ticker is None:
        return "NO_PRICE"
    try:
        price = executable_entry_price(
            direction=signal.direction,
            bid_price=ticker.bid_price,
            ask_price=ticker.ask_price,
        )
    except ValueError:
        return "NO_PRICE"
    if signal.entry_low <= price <= signal.entry_high:
        return "IN_ENTRY_ZONE"
    if signal.direction == "LONG":
        if price < signal.entry_low:
            return "WAITING_ENTRY"
        return "MISSED_ENTRY"
    if price > signal.entry_high:
        return "WAITING_ENTRY"
    return "MISSED_ENTRY"


def tile_dict(
    signal: MarketSignal, plan: ExecutionPlan, profile: CapitalProfile, ticker: TickerSnapshot | None
) -> dict:
    now = datetime.now(UTC)
    seconds = max(0, int((signal.expires_at - now).total_seconds()))
    state = entry_state(signal, ticker)
    presentation_direction = "NO_TRADE" if plan.status == "NO_TRADE" else signal.direction
    plan_economics = execution_plan_economics_dict(signal, plan)
    return {
        "signal_id": str(signal.id),
        "plan_id": str(plan.id),
        "plan_version": plan.version,
        "symbol": signal.symbol,
        "direction": presentation_direction,
        "market_direction": signal.direction,
        "signal_status": signal.status,
        "executability_status": plan.status,
        "entry_state": state,
        "seconds_to_expiry": seconds,
        "expires_at": signal.expires_at.isoformat(),
        "current_price": number(ticker.last_price) if ticker else None,
        "mark_price": number(ticker.mark_price) if ticker else None,
        "entry": {
            "low": number(signal.entry_low),
            "high": number(signal.entry_high),
            "reference": number(signal.entry_reference),
        },
        "stop_loss": number(signal.stop_loss),
        "main_take_profit": number(signal.take_profit_1),
        "economics_scope": "MARKET_SIGNAL_REFERENCE",
        "net_rr": signal.net_rr,
        "net_ev_r": signal.net_ev_r,
        "execution_net_rr": plan_economics["net_rr"],
        "execution_net_ev_r": plan_economics["net_ev_r"],
        "execution_economics_integrity": plan_economics["integrity_status"],
        "risk_usdt": number(plan.actual_stress_loss),
        "risk_budget_usdt": number(plan.risk_budget),
        "notional": number(plan.notional),
        "qty": number(plan.qty),
        "margin_estimate": number(plan.margin_estimate),
        "leverage": plan.leverage,
        "primary_warning": plan.primary_warning,
        "profile": {
            "id": str(profile.id),
            "name": profile.name,
            "allocated_capital": number(profile.allocated_capital),
            "effective_capital": number(plan.effective_capital),
            "capital_verified": plan.capital_verified,
        },
        "help_keys": ["rr_net", "ev_net_r", "risk_usdt", "notional"],
    }


def detail_dict(
    signal: MarketSignal, plan: ExecutionPlan, profile: CapitalProfile, ticker: TickerSnapshot | None
) -> dict:
    tile = tile_dict(signal, plan, profile, ticker)
    signal_economics = signal_economics_dict(signal)
    plan_economics = execution_plan_economics_dict(signal, plan)
    tile.update(
        {
            "trading_plan": {
                "direction": signal.direction,
                "entry": {
                    "low": number(signal.entry_low),
                    "high": number(signal.entry_high),
                    "reference": number(signal.entry_reference),
                },
                "stop_loss": number(signal.stop_loss),
                # The current outcome model, EV/R policy and sizing contract use one
                # terminal TP barrier. Legacy TP2 columns remain nullable for schema
                # compatibility but are not presented as an executable partial-exit plan.
                "take_profits": [
                    {"price": number(signal.take_profit_1), "weight": 1.0},
                ],
                "horizon_hours": signal.horizon_hours,
                "expires_at": signal.expires_at.isoformat(),
                "recommended_order_type": "LIMIT_INSIDE_ENTRY_ZONE",
                "cancellation_conditions": [
                    "Срок действия истек",
                    "Цена вышла за зону входа и требуется новый расчет",
                    "Обязательные рыночные или счетовые данные устарели",
                    "Сработал портфельный или ликвидностный блок",
                ],
            },
            "risk": {
                "effective_capital": number(plan.effective_capital),
                "risk_rate_pct": number(plan.risk_rate * 100),
                "risk_budget_usdt": number(plan.risk_budget),
                "actual_stress_loss_usdt": number(plan.actual_stress_loss),
                "qty_raw": number(plan.qty_raw),
                "qty": number(plan.qty),
                "notional": number(plan.notional),
                "leverage": plan.leverage,
                "margin_estimate": number(plan.margin_estimate),
                "liquidation_buffer_rate": plan.liquidation_buffer_rate,
                "limiting_cap": plan.limiting_cap,
                "warnings": plan.warnings,
                "sizing_snapshot": plan.sizing_snapshot,
            },
            "economics": {
                **signal_economics,
                "execution_plan": plan_economics,
            },
            "model": {
                "p_tp_before_sl": signal.p_tp,
                "p_sl_before_tp": signal.p_sl,
                "p_timeout": signal.p_timeout,
                "model_version": signal.model_version,
                "calibration_version": signal.calibration_version,
                "feature_schema_version": signal.feature_schema_version,
                "reasons": signal.reasons,
                "feature_snapshot": signal.feature_snapshot,
            },
            "audit": {
                "signal_natural_key": signal.natural_key,
                "signal_created_at": signal.created_at.isoformat(),
                "publish_time": signal.publish_time.isoformat(),
                "data_cutoff": signal.data_cutoff.isoformat(),
                "profile_version": plan.profile_version,
                "plan_version": plan.version,
                "plan_created_at": plan.created_at.isoformat(),
            },
        }
    )
    return tile


def counterfactual_outcome_dict(
    signal_outcome: SignalOutcome | None, plan_outcome: PlanOutcome | None
) -> dict | None:
    if signal_outcome is None:
        return None
    payload = {
        "outcome": signal_outcome.outcome,
        "exit_price": number(signal_outcome.exit_price),
        "exit_time": signal_outcome.exit_time.isoformat(),
        "horizon_end": signal_outcome.horizon_end.isoformat(),
        "bars_evaluated": signal_outcome.bars_evaluated,
        "ambiguous": signal_outcome.ambiguous,
        "evaluation_version": signal_outcome.evaluation_version,
        "resolved_at": signal_outcome.resolved_at.isoformat(),
        "details": signal_outcome.details,
        "plan": None,
    }
    if plan_outcome is not None:
        payload["plan"] = {
            "plan_id": str(plan_outcome.plan_id),
            "plan_version": plan_outcome.plan_version,
            "valuation_status": plan_outcome.valuation_status,
            "qty": number(plan_outcome.qty),
            "entry_price": number(plan_outcome.entry_price),
            "exit_price": number(plan_outcome.exit_price),
            "gross_pnl": number(plan_outcome.gross_pnl),
            "estimated_trading_costs": number(plan_outcome.estimated_trading_costs),
            "estimated_funding_cash_flow": number(plan_outcome.estimated_funding_cash_flow),
            "estimated_net_pnl": number(plan_outcome.estimated_net_pnl),
            "counterfactual_r": number(plan_outcome.counterfactual_r),
            "cost_assumptions": plan_outcome.cost_assumptions,
        }
    return payload

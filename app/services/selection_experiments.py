from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    OperatorDecision,
    PlanOutcome,
    SelectionExperimentLedger,
)
from app.research.selection_bias import (
    SELECTION_FEATURE_NAMES,
    SELECTION_FEATURE_SCHEMA,
    SelectionObservation,
    analyze_operator_selection,
)

ELIGIBLE_PLAN_STATUSES = frozenset({"ACTIONABLE", "LIMITED"})
SELECTION_LEDGER_SCHEMA = "selection-experiment-ledger-v1"


def _finite_float(value: Any, name: str) -> float:
    try:
        result = float(Decimal(str(value)))
    except Exception as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _ratio(numerator: Any, denominator: Any, name: str) -> float:
    top = _finite_float(numerator, f"{name} numerator")
    bottom = _finite_float(denominator, f"{name} denominator")
    if bottom <= 0:
        return 0.0
    return top / bottom


def _selection_feature_snapshot(*, signal: Any, plan: Any, observed_at: datetime) -> dict[str, float]:
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("Selection observed_at must be timezone-aware")
    direction = str(signal.direction)
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("Selection direction must be LONG or SHORT")
    snapshot = plan.sizing_snapshot if isinstance(plan.sizing_snapshot, dict) else {}
    execution_quality = (
        snapshot.get("execution_quality") if isinstance(snapshot.get("execution_quality"), dict) else {}
    )
    caps = snapshot.get("caps") if isinstance(snapshot.get("caps"), dict) else {}
    net_rr = snapshot.get("net_rr", signal.net_rr)
    net_ev_r = snapshot.get("net_ev_r", signal.net_ev_r)
    depth_cap = caps.get("orderbook_depth_notional")
    impact = execution_quality.get("impact_bps")
    expiry_seconds = max(0.0, (signal.expires_at - observed_at).total_seconds())
    hour_angle = 2.0 * math.pi * observed_at.hour / 24.0
    weekday_angle = 2.0 * math.pi * observed_at.weekday() / 7.0
    features = {
        "p_tp": _finite_float(signal.p_tp, "p_tp"),
        "p_sl": _finite_float(signal.p_sl, "p_sl"),
        "p_timeout": _finite_float(signal.p_timeout, "p_timeout"),
        "net_rr": _finite_float(net_rr, "net_rr"),
        "net_ev_r": _finite_float(net_ev_r, "net_ev_r"),
        "gross_edge_rate": _finite_float(signal.gross_edge_rate, "gross_edge_rate"),
        "risk_rate": _finite_float(plan.risk_rate, "risk_rate"),
        "notional_to_capital": _ratio(plan.notional, plan.effective_capital, "notional_to_capital"),
        "stress_to_budget": _ratio(plan.actual_stress_loss, plan.risk_budget, "stress_to_budget"),
        "leverage": _finite_float(plan.leverage, "leverage"),
        "liquidation_buffer_rate": _finite_float(
            plan.liquidation_buffer_rate, "liquidation_buffer_rate"
        ),
        "warning_count": float(len(plan.warnings or [])),
        "limited_status": float(str(plan.status) == "LIMITED"),
        "entry_inside_zone": float(bool(snapshot.get("entry_inside_signal_zone"))),
        "vwap_impact_bps": _finite_float(impact if impact is not None else 0, "vwap_impact_bps"),
        "depth_utilization": (
            _ratio(plan.notional, depth_cap, "depth_utilization")
            if depth_cap not in {None, "", 0, "0"}
            else 0.0
        ),
        "seconds_to_expiry": float(expiry_seconds),
        "hour_sin": math.sin(hour_angle),
        "hour_cos": math.cos(hour_angle),
        "weekday_sin": math.sin(weekday_angle),
        "weekday_cos": math.cos(weekday_angle),
        "direction_long": float(direction == "LONG"),
    }
    if tuple(features) != SELECTION_FEATURE_NAMES:
        raise RuntimeError("Selection feature ordering diverged from schema")
    return features


def _ledger_hash_payload(row: SelectionExperimentLedger) -> dict:
    return {
        "ledger_schema": row.ledger_schema,
        "plan_id": str(row.plan_id),
        "signal_id": str(row.signal_id),
        "profile_id": str(row.profile_id),
        "plan_version": int(row.plan_version),
        "observed_at": row.observed_at.astimezone(UTC).isoformat(),
        "eligible": bool(row.eligible),
        "eligibility_status": row.eligibility_status,
        "feature_schema": row.feature_schema,
        "features": row.features,
        "release_version": row.release_version,
    }


def _hash_ledger_row(row: SelectionExperimentLedger) -> str:
    encoded = json.dumps(
        _ledger_hash_payload(row),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_selection_ledger_row(
    *,
    signal: Any,
    plan: Any,
    observed_at: datetime,
    release_version: str,
) -> SelectionExperimentLedger:
    status = str(plan.status)
    row = SelectionExperimentLedger(
        plan_id=plan.id,
        signal_id=signal.id,
        profile_id=plan.profile_id,
        plan_version=int(plan.version),
        observed_at=observed_at,
        eligible=status in ELIGIBLE_PLAN_STATUSES,
        eligibility_status=status,
        ledger_schema=SELECTION_LEDGER_SCHEMA,
        feature_schema=SELECTION_FEATURE_SCHEMA,
        features=_selection_feature_snapshot(signal=signal, plan=plan, observed_at=observed_at),
        feature_hash="",
        release_version=release_version,
    )
    row.feature_hash = _hash_ledger_row(row)
    return row


def verify_selection_ledger_integrity(row: SelectionExperimentLedger) -> bool:
    try:
        return bool(row.feature_hash) and row.feature_hash == _hash_ledger_row(row)
    except (TypeError, ValueError, OverflowError):
        return False


async def selection_bias_report(
    session: AsyncSession,
    *,
    since: datetime,
    minimum_total: int = 60,
    minimum_selected: int = 15,
    minimum_unselected: int = 15,
    dependence_block_clusters: int = 5,
    minimum_independent_clusters: int = 30,
    bootstrap_replicates: int = 500,
    confidence_level: float = 0.95,
) -> dict:
    if since.tzinfo is None or since.utcoffset() is None:
        raise ValueError("Selection report since must be timezone-aware")
    rows = (
        await session.execute(
            select(SelectionExperimentLedger, OperatorDecision, PlanOutcome)
            .outerjoin(OperatorDecision, OperatorDecision.plan_id == SelectionExperimentLedger.plan_id)
            .outerjoin(PlanOutcome, PlanOutcome.plan_id == SelectionExperimentLedger.plan_id)
            .where(SelectionExperimentLedger.observed_at >= since)
            .order_by(SelectionExperimentLedger.observed_at, SelectionExperimentLedger.plan_id)
        )
    ).all()
    observations: list[SelectionObservation] = []
    integrity_errors: list[str] = []
    eligible_count = 0
    pending_outcome_count = 0
    ineligible_status_counts: dict[str, int] = {}
    for ledger, decision, outcome in rows:
        if not verify_selection_ledger_integrity(ledger):
            integrity_errors.append(str(ledger.plan_id))
            continue
        if not ledger.eligible:
            ineligible_status_counts[ledger.eligibility_status] = (
                ineligible_status_counts.get(ledger.eligibility_status, 0) + 1
            )
            continue
        eligible_count += 1
        if outcome is None or outcome.valuation_status != "VALUED" or outcome.counterfactual_r is None:
            pending_outcome_count += 1
            continue
        action = decision.action if decision is not None else "NO_DECISION"
        observations.append(
            SelectionObservation(
                plan_id=str(ledger.plan_id),
                cluster_id=str(ledger.signal_id),
                observed_at=ledger.observed_at,
                decision_action=action,
                counterfactual_r=float(outcome.counterfactual_r),
                features=ledger.features,
            )
        )
    if integrity_errors:
        analysis = {
            "schema": "operator-selection-ipsw-clustered-report-v2",
            "status": "LEDGER_INTEGRITY_ERROR",
            "ipsw_selected_mean_r": None,
            "causal_effect_claimed": False,
            "integrity_error_plan_ids": integrity_errors,
        }
    else:
        analysis = analyze_operator_selection(
            observations,
            minimum_total=minimum_total,
            minimum_selected=minimum_selected,
            minimum_unselected=minimum_unselected,
            dependence_block_clusters=dependence_block_clusters,
            minimum_independent_clusters=minimum_independent_clusters,
            bootstrap_replicates=bootstrap_replicates,
            confidence_level=confidence_level,
        )
    analysis["window_start"] = since.astimezone(UTC).isoformat()
    analysis["ledger"] = {
        "row_count": len(rows),
        "eligible_count": eligible_count,
        "eligible_valued_count": len(observations),
        "pending_or_unvalued_outcome_count": pending_outcome_count,
        "ineligible_status_counts": dict(sorted(ineligible_status_counts.items())),
        "prospective_since_release": "1.15.0",
        "operator_exposure_observed": False,
    }
    analysis["limitations"] = [
        "Plan creation is the opportunity unit; UI exposure is not yet directly observed.",
        "Counterfactual plan outcomes are estimates, not exchange-confirmed fills.",
        "IPSW is descriptive selection diagnostics and not a causal treatment-effect estimate.",
        "Confidence intervals use chronological signal-cluster moving blocks and condition on fitted OOS propensities.",
    ]
    return analysis

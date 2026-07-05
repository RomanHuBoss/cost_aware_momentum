from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest

from app.db.models import SelectionExperimentLedger
from app.research.selection_bias import (
    SELECTION_FEATURE_NAMES,
    SelectionObservation,
    analyze_operator_selection,
)
from app.services.selection_experiments import (
    build_selection_ledger_row,
    selection_bias_report,
    verify_selection_ledger_integrity,
)
from app.services.ui_exposures import build_selection_exposure_row

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _signal() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        direction="LONG",
        p_tp=0.58,
        p_sl=0.27,
        p_timeout=0.15,
        net_rr=1.42,
        net_ev_r=0.11,
        gross_edge_rate=0.018,
        expires_at=BASE + timedelta(hours=1),
    )


def _plan() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        profile_id=uuid4(),
        version=3,
        status="ACTIONABLE",
        effective_capital=10_000,
        risk_rate=0.005,
        risk_budget=50,
        actual_stress_loss=44,
        notional=2_200,
        leverage=3,
        liquidation_buffer_rate=0.21,
        warnings=["one warning"],
        sizing_snapshot={
            "entry_inside_signal_zone": True,
            "net_rr": "1.38",
            "net_ev_r": "0.09",
            "execution_quality": {"impact_bps": "3.5"},
            "caps": {"orderbook_depth_notional": "5000"},
        },
    )


def test_selection_ledger_is_predecision_and_tamper_evident() -> None:
    row = build_selection_ledger_row(
        signal=_signal(),
        plan=_plan(),
        observed_at=BASE,
        release_version="1.15.0",
    )

    assert row.eligible is True
    assert row.eligibility_status == "ACTIONABLE"
    assert tuple(row.features) == SELECTION_FEATURE_NAMES
    forbidden = {"outcome", "counterfactual_r", "accepted", "decision_action", "realized_pnl"}
    assert forbidden.isdisjoint(row.features)
    assert verify_selection_ledger_integrity(row) is True

    row.features["net_ev_r"] = 999.0
    assert verify_selection_ledger_integrity(row) is False


def _synthetic_observations() -> list[SelectionObservation]:
    rng = np.random.default_rng(20260705)
    observations: list[SelectionObservation] = []
    for index in range(360):
        latent = float(rng.normal())
        propensity = 1.0 / (1.0 + np.exp(-(-0.35 + 1.15 * latent)))
        selected = int(rng.uniform() < propensity)
        outcome_r = 0.08 + 0.55 * latent + float(rng.normal(scale=0.22))
        features = {name: 0.0 for name in SELECTION_FEATURE_NAMES}
        features["net_ev_r"] = latent
        features["net_rr"] = 1.2 + 0.15 * latent
        features["p_tp"] = min(0.95, max(0.05, 0.5 + 0.08 * latent))
        features["p_sl"] = 0.3
        features["p_timeout"] = 1.0 - features["p_tp"] - features["p_sl"]
        features["notional_to_capital"] = 0.15 + 0.02 * abs(latent)
        features["stress_to_budget"] = 0.8
        features["risk_rate"] = 0.005
        features["leverage"] = 3.0
        features["liquidation_buffer_rate"] = 0.2
        features["warning_count"] = 0.0
        features["limited_status"] = 0.0
        features["entry_inside_zone"] = 1.0
        features["vwap_impact_bps"] = 2.0 + abs(latent)
        features["depth_utilization"] = 0.4
        features["seconds_to_expiry"] = 3600.0
        features["hour_sin"] = 0.0
        features["hour_cos"] = 1.0
        features["weekday_sin"] = 0.0
        features["weekday_cos"] = 1.0
        features["direction_long"] = 1.0
        observations.append(
            SelectionObservation(
                plan_id=f"plan-{index}",
                observed_at=BASE + timedelta(hours=index),
                decision_action="ACCEPT" if selected else ("REJECT" if index % 2 else "NO_DECISION"),
                counterfactual_r=outcome_r,
                features=features,
            )
        )
    return observations


def test_ipsw_reduces_selected_subset_bias_against_observed_eligible_benchmark() -> None:
    report = analyze_operator_selection(
        _synthetic_observations(),
        minimum_total=120,
        minimum_selected=30,
        minimum_unselected=30,
        warmup_observations=80,
        block_size=40,
    )

    assert report["status"] == "READY"
    eligible_mean = report["eligible_counterfactual_mean_r"]
    selected_mean = report["selected_counterfactual_mean_r"]
    corrected = report["ipsw_selected_mean_r"]
    assert eligible_mean is not None
    assert selected_mean is not None
    assert corrected is not None
    assert abs(corrected - eligible_mean) < abs(selected_mean - eligible_mean)
    assert report["decision_counts"]["NO_DECISION"] > 0
    assert report["propensity"]["out_of_sample_count"] > 0
    assert report["propensity"]["effective_sample_size"] > 20
    assert report["causal_effect_claimed"] is False


def test_selection_analysis_fails_closed_on_class_collapse() -> None:
    rows = _synthetic_observations()[:140]
    collapsed = [
        SelectionObservation(
            plan_id=row.plan_id,
            observed_at=row.observed_at,
            decision_action="ACCEPT",
            counterfactual_r=row.counterfactual_r,
            features=row.features,
        )
        for row in rows
    ]

    report = analyze_operator_selection(
        collapsed,
        minimum_total=100,
        minimum_selected=20,
        minimum_unselected=20,
    )

    assert report["status"] == "CLASS_COLLAPSE"
    assert report["ipsw_selected_mean_r"] is None


def test_selection_analysis_rejects_outcome_leakage_in_features() -> None:
    row = _synthetic_observations()[0]
    bad_features = dict(row.features)
    bad_features["counterfactual_r"] = row.counterfactual_r

    with pytest.raises(ValueError, match="feature schema"):
        analyze_operator_selection(
            [
                SelectionObservation(
                    plan_id=row.plan_id,
                    observed_at=row.observed_at,
                    decision_action=row.decision_action,
                    counterfactual_r=row.counterfactual_r,
                    features=bad_features,
                )
            ],
            minimum_total=1,
            minimum_selected=0,
            minimum_unselected=0,
        )


class _RowsResult:
    def __init__(self, rows: list[tuple[object, object, object, object]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, object, object, object]]:
        return self._rows


class _RowsSession:
    def __init__(self, rows: list[tuple[object, object, object, object]]) -> None:
        self.rows = rows

    async def execute(self, _statement: object) -> _RowsResult:
        return _RowsResult(self.rows)


def _exposure_for(ledger: SelectionExperimentLedger, index: int = 0):
    exposed_at = ledger.observed_at + timedelta(seconds=2)
    return build_selection_exposure_row(
        ledger=ledger,
        operator_id="local-operator",
        exposed_at=exposed_at,
        received_at=exposed_at + timedelta(milliseconds=200),
        viewport_ratio=Decimal("0.75"),
        dwell_ms=1200,
        surface="RECOMMENDATION_TILE",
        client_event_id=uuid4(),
        page_instance_id=uuid4(),
        release_version="1.21.0",
    )


@pytest.mark.asyncio
async def test_selection_report_counts_accept_reject_and_no_decision() -> None:
    rows: list[tuple[object, object, object, object]] = []
    actions = ["ACCEPT", "REJECT", None]
    for index, action in enumerate(actions):
        signal = _signal()
        plan = _plan()
        plan.id = uuid4()
        ledger = build_selection_ledger_row(
            signal=signal,
            plan=plan,
            observed_at=BASE + timedelta(hours=index),
            release_version="1.15.0",
        )
        decision = SimpleNamespace(action=action) if action is not None else None
        outcome = SimpleNamespace(valuation_status="VALUED", counterfactual_r=Decimal(str(index - 1)))
        rows.append((ledger, _exposure_for(ledger, index), decision, outcome))

    report = await selection_bias_report(
        _RowsSession(rows),
        since=BASE - timedelta(hours=1),
        minimum_total=1,
        minimum_selected=0,
        minimum_unselected=0,
    )

    assert report["decision_counts"] == {"ACCEPT": 1, "NO_DECISION": 1, "REJECT": 1}
    assert report["ledger"]["eligible_count"] == 3
    assert report["ledger"]["eligible_valued_count"] == 3
    assert report["ledger"]["operator_exposure_observed"] is True


@pytest.mark.asyncio
async def test_selection_report_fails_closed_on_ledger_tampering() -> None:
    signal = _signal()
    plan = _plan()
    ledger = build_selection_ledger_row(
        signal=signal,
        plan=plan,
        observed_at=BASE,
        release_version="1.15.0",
    )
    ledger.features["net_ev_r"] = 42.0
    outcome = SimpleNamespace(valuation_status="VALUED", counterfactual_r=Decimal("1"))

    report = await selection_bias_report(
        _RowsSession([(ledger, _exposure_for(ledger), None, outcome)]),
        since=BASE - timedelta(hours=1),
        minimum_total=1,
        minimum_selected=0,
        minimum_unselected=0,
    )

    assert report["status"] == "LEDGER_INTEGRITY_ERROR"
    assert report["ipsw_selected_mean_r"] is None


def test_selection_ledger_model_enforces_one_row_per_plan_and_hash_length() -> None:
    unique_names = {constraint.name for constraint in SelectionExperimentLedger.__table__.constraints}
    assert "uq_selection_experiment_plan" in unique_names
    assert "ck_selection_experiment_ledger_selection_experiment_hash_length" in unique_names

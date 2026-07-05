from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.services.experiment_ledger import experiment_configuration_hash
from app.services.model_promotion import (
    EXPERIMENT_POLICY_BINDING_SCHEMA,
    EXPERIMENT_PROMOTION_GATE_SCHEMA,
    build_experiment_policy_binding,
    evaluate_experiment_promotion_gate,
    require_passed_experiment_promotion_gate,
)

NOW = datetime(2026, 7, 5, 21, tzinfo=UTC)
TRIAL_ID = UUID("22222222-2222-2222-2222-222222222222")
MODEL_SHA256 = "b" * 64


def _passed_cost_stress() -> dict[str, object]:
    return {
        "schema": "hourly-mark-to-market-cost-stress-v1",
        "minimum_terminal_return": 0.0,
        "scenarios": {
            "x1_5": {
                "period_count": 60,
                "terminal_return": 0.08,
                "max_drawdown": -0.04,
            },
            "x2": {
                "period_count": 60,
                "terminal_return": 0.03,
                "max_drawdown": -0.07,
            },
        },
        "passed": True,
    }


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value


class _Session:
    def __init__(self, value: object) -> None:
        self.value = value

    async def execute(self, _statement: object) -> _ScalarResult:
        return _ScalarResult(self.value)


def _policy_values() -> dict[str, object]:
    return {
        "entry_spread_bps": 18.0,
        "research_leverage": 3,
        "liquidation_equity_reserve_fraction": 0.10,
        "round_trip_cost_bps": 11.0,
        "slippage_bps": 3.0,
        "stop_gap_reserve_bps": 10.0,
        "funding_rate_override": 0.0,
        "timeout_return_rate_override": None,
        "minimum_net_rr": 1.2,
        "minimum_net_ev_r": 0.05,
        "policy_source": "cost_aware_ev_r_v1",
        "portfolio_accounting": "horizon_sleeves_single_active_symbol_v2",
    }


def _policy_binding() -> dict[str, object]:
    return build_experiment_policy_binding(**_policy_values())


def _configuration(**overrides: object) -> dict[str, object]:
    result = {
        "model_version": "candidate-v1",
        "model_sha256": MODEL_SHA256,
        "horizon": 8,
        **_policy_values(),
    }
    result.update(overrides)
    return result


def _started_event(configuration: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        trial_id=TRIAL_ID,
        experiment_family="family-v1",
        event_sequence=0,
        event_type="STARTED",
        observed_at=NOW,
        configuration_hash=experiment_configuration_hash(configuration),
        configuration=configuration,
        evidence={"preregistration_record_hash": "d" * 64},
        previous_event_hash=None,
        record_hash="e" * 64,
    )


def _ready_report(configuration: dict[str, object]) -> dict[str, object]:
    return {
        "schema": "experiment-selection-preregistered-governance-v4",
        "experiment_family": "family-v1",
        "status": "READY",
        "selected_trial_id": str(TRIAL_ID),
        "selected_configuration_hash": experiment_configuration_hash(configuration),
        "pbo": {"pbo": 0.10},
        "deflated_sharpe": {"probability": 0.98},
        "dependence_aware_inference": {"dependence_supported": True},
        "cost_stress": _passed_cost_stress(),
        "preregistration": {"record_hash": "d" * 64},
    }


@pytest.mark.asyncio
async def test_promotion_rejects_ready_trial_using_nonproduction_costs_and_thresholds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import model_promotion

    selected = _configuration(slippage_bps=0.0, minimum_net_ev_r=-1.0)

    async def report(*_args: object, **_kwargs: object) -> dict[str, object]:
        return _ready_report(selected)

    monkeypatch.setattr(model_promotion, "experiment_governance_report", report)
    monkeypatch.setattr(model_promotion, "verify_experiment_event_integrity", lambda _row: True)

    gate = await evaluate_experiment_promotion_gate(
        _Session(_started_event(selected)),
        experiment_family="family-v1",
        model_version="candidate-v1",
        model_sha256=MODEL_SHA256,
        horizon_hours=8,
        expected_policy_binding=_policy_binding(),
    )

    assert gate["passed"] is False
    assert gate["reasons"] == [
        "selected_trial_policy_mismatch:minimum_net_ev_r",
        "selected_trial_policy_mismatch:slippage_bps",
    ]


@pytest.mark.asyncio
async def test_promotion_accepts_ready_trial_with_exact_production_policy_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import model_promotion

    selected = _configuration()

    async def report(*_args: object, **_kwargs: object) -> dict[str, object]:
        return _ready_report(selected)

    monkeypatch.setattr(model_promotion, "experiment_governance_report", report)
    monkeypatch.setattr(model_promotion, "verify_experiment_event_integrity", lambda _row: True)

    gate = await evaluate_experiment_promotion_gate(
        _Session(_started_event(selected)),
        experiment_family="family-v1",
        model_version="candidate-v1",
        model_sha256=MODEL_SHA256,
        horizon_hours=8,
        expected_policy_binding=_policy_binding(),
    )

    assert gate["passed"] is True
    assert gate["policy_binding"]["expected"] == _policy_binding()
    assert gate["policy_binding"]["selected"] == _policy_values()
    assert gate["policy_binding"]["mismatches"] == []


def _passed_gate(policy_binding: dict[str, object]) -> dict[str, object]:
    return {
        "schema": EXPERIMENT_PROMOTION_GATE_SCHEMA,
        "passed": True,
        "reasons": [],
        "experiment_family": "family-v1",
        "selected_configuration_hash": "c" * 64,
        "preregistration_record_hash": "d" * 64,
        "binding": {
            "model_version": "candidate-v1",
            "model_sha256": MODEL_SHA256,
            "horizon_hours": 8,
        },
        "policy_binding": {
            "schema": EXPERIMENT_POLICY_BINDING_SCHEMA,
            "expected": policy_binding,
            "selected": _policy_values(),
            "mismatches": [],
        },
        "cost_stress": _passed_cost_stress(),
    }


def test_activation_rejects_gate_after_deployment_policy_changes() -> None:
    original = _policy_binding()
    changed = build_experiment_policy_binding(
        **{**_policy_values(), "slippage_bps": 4.0}
    )

    with pytest.raises(RuntimeError, match="deployment policy mismatch"):
        require_passed_experiment_promotion_gate(
            _passed_gate(original),
            expected_model_version="candidate-v1",
            expected_model_sha256=MODEL_SHA256,
            expected_horizon_hours=8,
            expected_policy_binding=changed,
        )


def test_activation_rejects_legacy_gate_without_policy_binding() -> None:
    legacy_gate = _passed_gate(_policy_binding())
    legacy_gate.pop("policy_binding")

    with pytest.raises(RuntimeError, match="lacks deployment policy binding"):
        require_passed_experiment_promotion_gate(
            legacy_gate,
            expected_model_version="candidate-v1",
            expected_model_sha256=MODEL_SHA256,
            expected_horizon_hours=8,
            expected_policy_binding=_policy_binding(),
        )

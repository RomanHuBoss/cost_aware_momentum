from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.research.preregistration import (
    PREREGISTRATION_SPEC_SCHEMA_VERSION,
    build_preregistration_record_hash,
    build_preregistration_template,
    normalize_preregistration_spec,
    validate_preregistered_trial,
    validate_stopping_rule,
    verify_preregistration_integrity,
)

NOW = datetime(2026, 7, 5, 12, tzinfo=UTC)


def _configuration() -> dict[str, object]:
    return {
        "schema": "barrier-policy-experiment-configuration-v1",
        "dataset_fingerprint": "a" * 64,
        "model_sha256": "b" * 64,
        "horizon": 8,
        "minimum_net_rr": 1.2,
        "minimum_net_ev_r": 0.05,
        "policy_source": "cost_aware_ev_r_v1",
        "portfolio_accounting": "risk_budgeted_hourly_mark_to_market_single_active_symbol_v4",
    }


def _governance() -> dict[str, object]:
    return {
        "pbo_segments": 6,
        "minimum_trials": 4,
        "minimum_periods": 60,
        "maximum_pbo": 0.20,
        "minimum_dsr_probability": 0.95,
        "dependence_block_periods": 8,
        "minimum_independent_blocks": 6,
        "bootstrap_replicates": 1000,
        "confidence_level": 0.95,
    }


def _spec() -> dict[str, object]:
    configuration = _configuration()
    return {
        "schema": PREREGISTRATION_SPEC_SCHEMA_VERSION,
        "experiment_family": "momentum-policy-study-01",
        "hypothesis": (
            "Increasing the minimum net reward-to-risk threshold improves the "
            "out-of-sample nonannualized Sharpe without violating the preregistered PBO and DSR limits."
        ),
        "primary_metric": {
            "name": "nonannualized_sharpe",
            "direction": "maximize",
        },
        "configuration_contract": {
            "fixed_parameters": {
                key: value
                for key, value in configuration.items()
                if key not in {"minimum_net_rr", "minimum_net_ev_r"}
            },
            "search_space": {
                "minimum_net_rr": {"values": [1.1, 1.2]},
                "minimum_net_ev_r": {"values": [0.03, 0.05]},
            },
        },
        "governance": _governance(),
        "stopping_rule": {
            "max_unique_configurations": 4,
            "stop_after_utc": (NOW + timedelta(days=30)).isoformat(),
        },
        "exclusion_criteria": [
            {
                "code": "INVALID_INPUT_DATA",
                "description": "Exclude only when point-in-time input validation fails before model evaluation.",
            }
        ],
    }


def test_preregistration_normalizes_complete_formal_contract() -> None:
    normalized = normalize_preregistration_spec(_spec(), expected_family="momentum-policy-study-01")

    assert normalized["schema"] == PREREGISTRATION_SPEC_SCHEMA_VERSION
    assert normalized["primary_metric"] == {
        "name": "nonannualized_sharpe",
        "direction": "maximize",
    }
    assert normalized["stopping_rule"]["max_unique_configurations"] == 4
    assert normalized["configuration_contract"]["fixed_parameters"]["dataset_fingerprint"] == "a" * 64


def test_preregistration_rejects_placeholder_or_posthoc_ambiguous_contract() -> None:
    spec = _spec()
    spec["hypothesis"] = "REPLACE_WITH_HYPOTHESIS"
    with pytest.raises(ValueError, match="hypothesis"):
        normalize_preregistration_spec(spec, expected_family="momentum-policy-study-01")

    spec = _spec()
    spec["configuration_contract"]["fixed_parameters"].pop("dataset_fingerprint")
    with pytest.raises(ValueError, match="dataset_fingerprint"):
        normalize_preregistration_spec(spec, expected_family="momentum-policy-study-01")

    spec = _spec()
    spec["stopping_rule"]["max_unique_configurations"] = 5
    with pytest.raises(ValueError, match="search space"):
        normalize_preregistration_spec(spec, expected_family="momentum-policy-study-01")


def test_trial_must_match_fixed_parameters_and_enumerated_search_space() -> None:
    spec = normalize_preregistration_spec(_spec(), expected_family="momentum-policy-study-01")
    configuration = _configuration()

    validated = validate_preregistered_trial(spec, configuration)
    assert validated["minimum_net_rr"] == 1.2

    changed_dataset = {**configuration, "dataset_fingerprint": "c" * 64}
    with pytest.raises(ValueError, match="fixed parameter dataset_fingerprint"):
        validate_preregistered_trial(spec, changed_dataset)

    undeclared = {**configuration, "slippage_bps": 3.0}
    with pytest.raises(ValueError, match="undeclared configuration parameters"):
        validate_preregistered_trial(spec, undeclared)

    outside_space = {**configuration, "minimum_net_rr": 1.3}
    with pytest.raises(ValueError, match="outside the preregistered values"):
        validate_preregistered_trial(spec, outside_space)


def test_stopping_rule_blocks_deadline_and_new_configuration_after_budget() -> None:
    spec = normalize_preregistration_spec(_spec(), expected_family="momentum-policy-study-01")

    validate_stopping_rule(
        spec,
        attempted_configuration_hashes=("1" * 64, "2" * 64, "3" * 64),
        candidate_configuration_hash="3" * 64,
        observed_at=NOW,
    )
    with pytest.raises(ValueError, match="maximum unique configuration"):
        validate_stopping_rule(
            spec,
            attempted_configuration_hashes=("1" * 64, "2" * 64, "3" * 64, "4" * 64),
            candidate_configuration_hash="5" * 64,
            observed_at=NOW,
        )
    with pytest.raises(ValueError, match="stop_after_utc"):
        validate_stopping_rule(
            spec,
            attempted_configuration_hashes=(),
            candidate_configuration_hash="1" * 64,
            observed_at=NOW + timedelta(days=31),
        )


def test_preregistration_record_hash_detects_mutation() -> None:
    spec = normalize_preregistration_spec(_spec(), expected_family="momentum-policy-study-01")
    record_hash = build_preregistration_record_hash(
        experiment_family="momentum-policy-study-01",
        registered_at=NOW,
        specification=spec,
        release_version="1.20.0",
    )
    row = SimpleNamespace(
        experiment_family="momentum-policy-study-01",
        registered_at=NOW,
        specification=spec,
        release_version="1.20.0",
        record_hash=record_hash,
    )
    assert verify_preregistration_integrity(row)

    row.specification = {**spec, "hypothesis": "Mutated after the results were observed."}
    assert not verify_preregistration_integrity(row)


def test_template_is_generated_before_evaluation_but_cannot_be_registered_unedited() -> None:
    template = build_preregistration_template(
        experiment_family="momentum-policy-study-01",
        configuration=_configuration(),
        search_parameters=("minimum_net_rr", "minimum_net_ev_r"),
        governance=_governance(),
        created_at=NOW,
    )

    assert template["experiment_family"] == "momentum-policy-study-01"
    assert template["configuration_contract"]["search_space"]["minimum_net_rr"]["values"] == [1.2]
    assert template["template_created_at"] == NOW.isoformat()
    with pytest.raises(ValueError, match="hypothesis"):
        normalize_preregistration_spec(template, expected_family="momentum-policy-study-01")


@pytest.mark.asyncio
async def test_started_event_embeds_preregistration_hash_before_append(monkeypatch) -> None:
    from uuid import uuid4

    from app.services import experiment_ledger

    class EmptyResult:
        def scalars(self):
            return ()

    class FakeSession:
        def __init__(self) -> None:
            self.added = []

        async def execute(self, _statement):
            return EmptyResult()

        def add(self, row) -> None:
            self.added.append(row)

        async def flush(self) -> None:
            return None

    async def require_registration(*_args, **_kwargs):
        return SimpleNamespace(record_hash="d" * 64), {"minimum_net_rr": 1.2}

    monkeypatch.setattr(
        experiment_ledger,
        "require_trial_preregistration",
        require_registration,
    )
    session = FakeSession()
    row = await experiment_ledger.append_experiment_event(
        session,
        trial_id=uuid4(),
        experiment_family="momentum-policy-study-01",
        event_type="STARTED",
        observed_at=NOW,
        configuration=_configuration(),
        evidence={"release_version": "1.20.0"},
    )

    assert row.evidence["preregistration_record_hash"] == "d" * 64
    assert row.evidence["preregistered_search_values"] == {"minimum_net_rr": 1.2}
    assert experiment_ledger.verify_experiment_event_integrity(row)


@pytest.mark.asyncio
async def test_report_rejects_posthoc_governance_override(monkeypatch) -> None:
    from app.services import experiment_ledger

    spec = normalize_preregistration_spec(_spec(), expected_family="momentum-policy-study-01")
    record_hash = build_preregistration_record_hash(
        experiment_family="momentum-policy-study-01",
        registered_at=NOW,
        specification=spec,
        release_version="1.20.0",
    )
    registration = SimpleNamespace(
        experiment_family="momentum-policy-study-01",
        registered_at=NOW,
        registration_schema="immutable-experiment-family-registration-v1",
        specification=spec,
        release_version="1.20.0",
        record_hash=record_hash,
    )

    async def load_registration(*_args, **_kwargs):
        return registration

    monkeypatch.setattr(
        experiment_ledger,
        "load_experiment_preregistration",
        load_registration,
    )
    report = await experiment_ledger.experiment_governance_report(
        SimpleNamespace(),
        experiment_family="momentum-policy-study-01",
        requested_governance={"maximum_pbo": 0.50},
    )

    assert report["status"] == "BLOCKED_PREREGISTRATION_POLICY_MISMATCH"
    assert report["mismatches"]["maximum_pbo"] == {
        "preregistered": 0.20,
        "requested": 0.50,
    }


def test_migration_and_model_make_family_registration_immutable() -> None:
    from pathlib import Path

    from app.db.models import ResearchExperimentFamilyRegistration

    columns = set(ResearchExperimentFamilyRegistration.__table__.columns.keys())
    assert columns == {
        "experiment_family",
        "registered_at",
        "registration_schema",
        "specification",
        "release_version",
        "record_hash",
    }
    migration = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "0013_experiment_preregistration.py"
    ).read_text(encoding="utf-8")
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "preregistrations are immutable" in migration

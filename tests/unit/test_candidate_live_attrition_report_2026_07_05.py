from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.attrition import (
    build_attrition_report_from_records,
    build_candidate_live_attrition_report,
    execution_plan_attrition_evidence,
)
from app.services.model_promotion import EXPERIMENT_PROMOTION_GATE_SCHEMA


def _experiment_gate(*, passed: bool, reasons: list[str]) -> dict[str, object]:
    return {
        "schema": EXPERIMENT_PROMOTION_GATE_SCHEMA,
        "passed": passed,
        "reasons": reasons,
        "experiment_family": "family-v1",
        "selected_configuration_hash": "c" * 64 if passed else None,
        "preregistration_record_hash": "d" * 64 if passed else None,
        "binding": {
            "model_version": "candidate",
            "model_sha256": "b" * 64,
            "horizon_hours": 8,
        },
    }


def test_report_deduplicates_retries_and_attributes_candidate_and_live_losses() -> None:
    since = datetime(2026, 7, 1, tzinfo=UTC)
    event_time = since + timedelta(hours=1)
    inference_jobs = [
        {
            "job_name": "hourly_inference",
            "status": "SUCCESS",
            "scheduled_for": event_time,
            "finished_at": event_time + timedelta(minutes=2),
            "details": {
                "attrition_schema": "hourly-inference-terminal-outcomes-v1",
                "symbols_total": 2,
                "published": 1,
                "profiles_total": 1,
                "symbol_outcomes": [
                    {
                        "symbol": "BTCUSDT",
                        "event_time": event_time.isoformat(),
                        "terminal_state": "SKIPPED",
                        "reason_code": "missing_decision_candle",
                        "signal_id": None,
                    },
                    {
                        "symbol": "ETHUSDT",
                        "event_time": event_time.isoformat(),
                        "terminal_state": "PUBLISHED",
                        "reason_code": "signal_published",
                        "signal_id": "signal-eth",
                    },
                ],
                "plan_outcomes": [
                    {
                        "plan_id": "plan-eth",
                        "signal_id": "signal-eth",
                        "profile_id": "profile-1",
                        "status": "NO_TRADE",
                        "schema": "execution-plan-attrition-v1",
                        "terminal_stage": "POLICY_ECONOMICS",
                        "primary_reason_code": "net_edge_below_policy",
                        "reason_codes": ["net_edge_below_policy"],
                    }
                ],
            },
        },
        {
            "job_name": "universe_catchup_inference",
            "status": "SUCCESS",
            "scheduled_for": event_time + timedelta(minutes=5),
            "finished_at": event_time + timedelta(minutes=6),
            "details": {
                "attrition_schema": "hourly-inference-terminal-outcomes-v1",
                "symbols_total": 2,
                "published": 1,
                "profiles_total": 1,
                "symbol_outcomes": [
                    {
                        "symbol": "BTCUSDT",
                        "event_time": event_time.isoformat(),
                        "terminal_state": "PUBLISHED",
                        "reason_code": "signal_published",
                        "signal_id": "signal-btc",
                    },
                    {
                        "symbol": "ETHUSDT",
                        "event_time": event_time.isoformat(),
                        "terminal_state": "EXISTING_CURRENT_HOUR",
                        "reason_code": "signal_already_exists",
                        "signal_id": "signal-eth",
                    },
                ],
                "plan_outcomes": [
                    {
                        "plan_id": "plan-btc",
                        "signal_id": "signal-btc",
                        "profile_id": "profile-1",
                        "status": "BLOCKED_MIN_SIZE",
                        "schema": "execution-plan-attrition-v1",
                        "terminal_stage": "RISK_EXECUTION",
                        "primary_reason_code": "position_plan.blocked_min_size",
                        "reason_codes": ["position_plan.blocked_min_size", "limiting_cap.min_order"],
                    }
                ],
            },
        },
    ]
    training_jobs = [
        {
            "status": "SUCCESS",
            "started_at": since + timedelta(hours=2),
            "details": {
                "candidate_version": "candidate-a",
                "quality_gate": {
                    "passed": False,
                    "reasons": [
                        "log_loss_above_limit",
                        "policy_trade_rate_below_minimum",
                    ],
                },
                "experiment_promotion_gate": _experiment_gate(
                    passed=False,
                    reasons=["quality_gate_failed_before_experiment_promotion"],
                ),
                "activated": False,
                "activation_skipped": "quality_gate_failed",
            },
        },
        {
            "status": "SUCCESS",
            "started_at": since + timedelta(hours=3),
            "details": {
                "candidate_version": "candidate-b",
                "quality_gate": {"passed": True, "reasons": []},
                "experiment_promotion_gate": _experiment_gate(passed=True, reasons=[]),
                "activated": True,
                "activation_skipped": None,
            },
        },
    ]

    report = build_attrition_report_from_records(
        inference_jobs=inference_jobs,
        training_jobs=training_jobs,
        since=since,
        until=since + timedelta(days=1),
    )

    assert report["status"] == "OK"
    assert report["live"]["signal_opportunities"]["unique_total"] == 2
    assert report["live"]["signal_opportunities"]["signal_available"] == 2
    assert report["live"]["signal_opportunities"]["retry_recovered"] == 1
    assert report["live"]["plan_opportunities"]["total"] == 2
    assert report["live"]["plan_opportunities"]["reason_counts"] == {
        "net_edge_below_policy": 1,
        "position_plan.blocked_min_size": 1,
    }
    assert report["training"]["terminal_outcome_counts"] == {
        "ACTIVATED": 1,
        "QUALITY_GATE_FAILED": 1,
    }
    assert report["training"]["quality_gate_stage_counts"] == {
        "MODEL_QUALITY": 1,
        "POLICY_ECONOMICS": 1,
    }


def test_report_blocks_incomplete_terminal_evidence() -> None:
    now = datetime(2026, 7, 1, tzinfo=UTC)
    report = build_attrition_report_from_records(
        inference_jobs=[
            {
                "job_name": "hourly_inference",
                "status": "SUCCESS",
                "scheduled_for": now,
                "finished_at": now,
                "details": {
                    "attrition_schema": "hourly-inference-terminal-outcomes-v1",
                    "symbols_total": 2,
                    "symbol_outcomes": [
                        {
                            "symbol": "BTCUSDT",
                            "event_time": now.isoformat(),
                            "terminal_state": "SKIPPED",
                            "reason_code": "missing_ticker",
                            "signal_id": None,
                        }
                    ],
                    "plan_outcomes": [],
                },
            }
        ],
        training_jobs=[],
        since=now - timedelta(hours=1),
        until=now + timedelta(hours=1),
    )

    assert report["status"] == "BLOCKED"
    assert "inference_job_symbol_outcome_count_mismatch" in report["integrity_errors"]


def test_report_attributes_full_horizon_outcomes_to_plan_filters() -> None:
    since = datetime(2026, 7, 1, tzinfo=UTC)
    event_time = since + timedelta(hours=1)
    until = since + timedelta(days=1)
    inference_jobs = [
        {
            "job_name": "hourly_inference",
            "status": "SUCCESS",
            "scheduled_for": event_time,
            "finished_at": event_time + timedelta(minutes=2),
            "details": {
                "attrition_schema": "hourly-inference-terminal-outcomes-v1",
                "symbols_total": 3,
                "published": 3,
                "profiles_total": 1,
                "symbol_outcomes": [
                    {
                        "symbol": "BTCUSDT",
                        "event_time": event_time.isoformat(),
                        "terminal_state": "PUBLISHED",
                        "reason_code": "signal_published",
                        "signal_id": "signal-actionable",
                    },
                    {
                        "symbol": "ETHUSDT",
                        "event_time": event_time.isoformat(),
                        "terminal_state": "PUBLISHED",
                        "reason_code": "signal_published",
                        "signal_id": "signal-no-trade",
                    },
                    {
                        "symbol": "SOLUSDT",
                        "event_time": event_time.isoformat(),
                        "terminal_state": "PUBLISHED",
                        "reason_code": "signal_published",
                        "signal_id": "signal-blocked",
                    },
                ],
                "plan_outcomes": [
                    {
                        "plan_id": "plan-actionable",
                        "signal_id": "signal-actionable",
                        "profile_id": "profile-1",
                        "status": "ACTIONABLE",
                        "schema": "execution-plan-attrition-v1",
                        "terminal_stage": "ACTIONABLE",
                        "primary_reason_code": "position_plan.actionable",
                        "reason_codes": ["position_plan.actionable"],
                    },
                    {
                        "plan_id": "plan-no-trade",
                        "signal_id": "signal-no-trade",
                        "profile_id": "profile-1",
                        "status": "NO_TRADE",
                        "schema": "execution-plan-attrition-v1",
                        "terminal_stage": "POLICY_ECONOMICS",
                        "primary_reason_code": "net_edge_below_policy",
                        "reason_codes": ["net_edge_below_policy"],
                    },
                    {
                        "plan_id": "plan-blocked",
                        "signal_id": "signal-blocked",
                        "profile_id": "profile-1",
                        "status": "BLOCKED_MIN_SIZE",
                        "schema": "execution-plan-attrition-v1",
                        "terminal_stage": "RISK_EXECUTION",
                        "primary_reason_code": "position_plan.blocked_min_size",
                        "reason_codes": ["position_plan.blocked_min_size"],
                    },
                ],
            },
        }
    ]
    signals = [
        {"id": "signal-actionable", "event_time": event_time, "horizon_hours": 4},
        {"id": "signal-no-trade", "event_time": event_time, "horizon_hours": 4},
        {"id": "signal-blocked", "event_time": event_time, "horizon_hours": 4},
    ]
    signal_outcomes = [
        {
            "signal_id": "signal-actionable",
            "outcome": "SL",
            "ambiguous": False,
            "resolved_at": until - timedelta(hours=1),
        },
        {
            "signal_id": "signal-no-trade",
            "outcome": "TP",
            "ambiguous": False,
            "resolved_at": until - timedelta(hours=1),
        },
        {
            "signal_id": "signal-blocked",
            "outcome": "TIMEOUT",
            "ambiguous": True,
            "resolved_at": until - timedelta(hours=1),
        },
    ]
    plan_outcomes = [
        {
            "plan_id": "plan-actionable",
            "plan_version": 1,
            "outcome": "SL",
            "valuation_status": "VALUED",
            "counterfactual_r": "-1.25",
            "resolved_at": until - timedelta(hours=1),
        },
        {
            "plan_id": "plan-no-trade",
            "plan_version": 1,
            "outcome": "TP",
            "valuation_status": "NOT_SIZED",
            "counterfactual_r": None,
            "resolved_at": until - timedelta(hours=1),
        },
        {
            "plan_id": "plan-blocked",
            "plan_version": 1,
            "outcome": "TIMEOUT",
            "valuation_status": "NOT_SIZED",
            "counterfactual_r": None,
            "resolved_at": until - timedelta(hours=1),
        },
    ]

    report = build_attrition_report_from_records(
        inference_jobs=inference_jobs,
        training_jobs=[],
        signals=signals,
        signal_outcomes=signal_outcomes,
        plan_outcomes=plan_outcomes,
        since=since,
        until=until,
    )

    attribution = report["live"]["outcome_attribution"]
    assert attribution["status"] == "OK"
    assert attribution["signal_cohort"] == {
        "instrumented": 3,
        "records_loaded": 3,
        "mature": 3,
        "immature": 0,
        "resolved_mature": 3,
        "unresolved_mature": 0,
        "coverage_rate": 1.0,
        "outcome_counts": {"SL": 1, "TIMEOUT": 1, "TP": 1},
        "ambiguous": 1,
        "post_cutoff_outcomes_excluded": 0,
    }
    assert attribution["by_plan_status"]["ACTIONABLE"]["signal_outcome_counts"] == {"SL": 1}
    assert attribution["by_plan_status"]["ACTIONABLE"]["valued_counterfactual_r"] == {
        "count": 1,
        "positive": 0,
        "zero": 0,
        "negative": 1,
        "mean": -1.25,
        "median": -1.25,
        "sum": -1.25,
    }
    assert attribution["by_primary_reason"]["net_edge_below_policy"]["signal_outcome_counts"] == {"TP": 1}
    assert attribution["by_primary_reason"]["position_plan.blocked_min_size"]["signal_outcome_counts"] == {
        "TIMEOUT": 1
    }
    assert attribution["actual_execution_pnl"] is False
    assert attribution["causal_claim"] is False


def test_report_blocks_missing_mature_outcome_evidence() -> None:
    now = datetime(2026, 7, 1, tzinfo=UTC)
    report = build_attrition_report_from_records(
        inference_jobs=[
            {
                "job_name": "hourly_inference",
                "status": "SUCCESS",
                "scheduled_for": now,
                "finished_at": now,
                "details": {
                    "attrition_schema": "hourly-inference-terminal-outcomes-v1",
                    "symbols_total": 1,
                    "published": 1,
                    "profiles_total": 1,
                    "symbol_outcomes": [
                        {
                            "symbol": "BTCUSDT",
                            "event_time": now.isoformat(),
                            "terminal_state": "PUBLISHED",
                            "reason_code": "signal_published",
                            "signal_id": "signal-missing-outcome",
                        }
                    ],
                    "plan_outcomes": [
                        {
                            "plan_id": "plan-missing-outcome",
                            "signal_id": "signal-missing-outcome",
                            "profile_id": "profile-1",
                            "status": "ACTIONABLE",
                            "schema": "execution-plan-attrition-v1",
                            "terminal_stage": "ACTIONABLE",
                            "primary_reason_code": "position_plan.actionable",
                            "reason_codes": ["position_plan.actionable"],
                        }
                    ],
                },
            }
        ],
        training_jobs=[],
        signals=[{"id": "signal-missing-outcome", "event_time": now, "horizon_hours": 1}],
        signal_outcomes=[],
        plan_outcomes=[],
        since=now - timedelta(hours=1),
        until=now + timedelta(hours=2),
    )

    assert report["status"] == "BLOCKED"
    assert report["live"]["outcome_attribution"]["status"] == "BLOCKED"
    assert "outcome_attribution_mature_signal_unresolved" in report["integrity_errors"]
    assert "outcome_attribution_mature_plan_outcome_missing" in report["integrity_errors"]


def test_report_excludes_outcomes_resolved_after_report_cutoff() -> None:
    event_time = datetime(2026, 7, 1, tzinfo=UTC)
    until = event_time + timedelta(hours=2)
    report = build_attrition_report_from_records(
        inference_jobs=[
            {
                "job_name": "hourly_inference",
                "status": "SUCCESS",
                "scheduled_for": event_time,
                "finished_at": event_time,
                "details": {
                    "attrition_schema": "hourly-inference-terminal-outcomes-v1",
                    "symbols_total": 1,
                    "published": 1,
                    "profiles_total": 1,
                    "symbol_outcomes": [
                        {
                            "symbol": "BTCUSDT",
                            "event_time": event_time.isoformat(),
                            "terminal_state": "PUBLISHED",
                            "reason_code": "signal_published",
                            "signal_id": "signal-post-cutoff",
                        }
                    ],
                    "plan_outcomes": [
                        {
                            "plan_id": "plan-post-cutoff",
                            "signal_id": "signal-post-cutoff",
                            "profile_id": "profile-1",
                            "status": "ACTIONABLE",
                            "schema": "execution-plan-attrition-v1",
                            "terminal_stage": "ACTIONABLE",
                            "primary_reason_code": "position_plan.actionable",
                            "reason_codes": ["position_plan.actionable"],
                        }
                    ],
                },
            }
        ],
        training_jobs=[],
        signals=[{"id": "signal-post-cutoff", "event_time": event_time, "horizon_hours": 1}],
        signal_outcomes=[
            {
                "signal_id": "signal-post-cutoff",
                "outcome": "TP",
                "ambiguous": False,
                "resolved_at": until + timedelta(hours=1),
            }
        ],
        plan_outcomes=[
            {
                "plan_id": "plan-post-cutoff",
                "plan_version": 1,
                "outcome": "TP",
                "valuation_status": "VALUED",
                "counterfactual_r": "1.2",
                "resolved_at": until + timedelta(hours=1),
            }
        ],
        since=event_time - timedelta(hours=1),
        until=until,
    )

    attribution = report["live"]["outcome_attribution"]
    assert report["status"] == "BLOCKED"
    assert attribution["signal_cohort"]["resolved_mature"] == 0
    assert attribution["signal_cohort"]["post_cutoff_outcomes_excluded"] == 1
    assert attribution["plan_cohort"]["post_cutoff_outcomes_excluded"] == 1
    assert attribution["signal_cohort"]["outcome_counts"] == {}
    assert "outcome_attribution_mature_signal_unresolved" in report["integrity_errors"]


def test_report_excludes_early_resolved_immature_outcomes() -> None:
    event_time = datetime(2026, 7, 1, tzinfo=UTC)
    report = build_attrition_report_from_records(
        inference_jobs=[
            {
                "job_name": "hourly_inference",
                "status": "SUCCESS",
                "scheduled_for": event_time,
                "finished_at": event_time,
                "details": {
                    "attrition_schema": "hourly-inference-terminal-outcomes-v1",
                    "symbols_total": 1,
                    "published": 1,
                    "profiles_total": 1,
                    "symbol_outcomes": [
                        {
                            "symbol": "BTCUSDT",
                            "event_time": event_time.isoformat(),
                            "terminal_state": "PUBLISHED",
                            "reason_code": "signal_published",
                            "signal_id": "signal-early-tp",
                        }
                    ],
                    "plan_outcomes": [
                        {
                            "plan_id": "plan-early-tp",
                            "signal_id": "signal-early-tp",
                            "profile_id": "profile-1",
                            "status": "ACTIONABLE",
                            "schema": "execution-plan-attrition-v1",
                            "terminal_stage": "ACTIONABLE",
                            "primary_reason_code": "position_plan.actionable",
                            "reason_codes": ["position_plan.actionable"],
                        }
                    ],
                },
            }
        ],
        training_jobs=[],
        signals=[{"id": "signal-early-tp", "event_time": event_time, "horizon_hours": 8}],
        signal_outcomes=[
            {
                "signal_id": "signal-early-tp",
                "outcome": "TP",
                "ambiguous": False,
                "resolved_at": event_time + timedelta(hours=1),
            }
        ],
        plan_outcomes=[
            {
                "plan_id": "plan-early-tp",
                "plan_version": 1,
                "outcome": "TP",
                "valuation_status": "VALUED",
                "counterfactual_r": "1.1",
                "resolved_at": event_time + timedelta(hours=1),
            }
        ],
        since=event_time - timedelta(hours=1),
        until=event_time + timedelta(hours=2),
    )

    attribution = report["live"]["outcome_attribution"]
    assert report["status"] == "OK"
    assert attribution["status"] == "INSUFFICIENT_DATA"
    assert attribution["signal_cohort"]["mature"] == 0
    assert attribution["signal_cohort"]["immature"] == 1
    assert attribution["signal_cohort"]["outcome_counts"] == {}
    assert attribution["by_plan_status"]["ACTIONABLE"]["resolved_signal_outcomes"] == 0
    assert "no_mature_outcome_cohort" in report["alerts"]


@pytest.mark.asyncio
async def test_database_report_loads_exact_instrumented_outcome_rows() -> None:
    now = datetime(2026, 7, 1, tzinfo=UTC)
    signal_id = uuid4()
    plan_id = uuid4()
    inference_job = SimpleNamespace(
        job_name="hourly_inference",
        status="SUCCESS",
        scheduled_for=now,
        started_at=now,
        finished_at=now + timedelta(minutes=1),
        details={
            "attrition_schema": "hourly-inference-terminal-outcomes-v1",
            "symbols_total": 1,
            "published": 1,
            "profiles_total": 1,
            "symbol_outcomes": [
                {
                    "symbol": "BTCUSDT",
                    "event_time": now.isoformat(),
                    "terminal_state": "PUBLISHED",
                    "reason_code": "signal_published",
                    "signal_id": str(signal_id),
                }
            ],
            "plan_outcomes": [
                {
                    "plan_id": str(plan_id),
                    "signal_id": str(signal_id),
                    "profile_id": str(uuid4()),
                    "status": "ACTIONABLE",
                    "schema": "execution-plan-attrition-v1",
                    "terminal_stage": "ACTIONABLE",
                    "primary_reason_code": "position_plan.actionable",
                    "reason_codes": ["position_plan.actionable"],
                }
            ],
        },
    )
    signal = SimpleNamespace(id=signal_id, event_time=now, horizon_hours=1)
    signal_outcome = SimpleNamespace(
        signal_id=signal_id,
        outcome="TP",
        ambiguous=False,
        resolved_at=now + timedelta(hours=1),
    )
    plan_outcome = SimpleNamespace(
        plan_id=plan_id,
        plan_version=1,
        outcome="TP",
        valuation_status="VALUED",
        counterfactual_r=Decimal("1.40"),
        resolved_at=now + timedelta(hours=1),
    )

    class _Scalars:
        def __init__(self, rows: list[object]) -> None:
            self.rows = rows

        def all(self) -> list[object]:
            return self.rows

    class _Result:
        def __init__(self, rows: list[object]) -> None:
            self.rows = rows

        def scalars(self) -> _Scalars:
            return _Scalars(self.rows)

    class _Session:
        def __init__(self) -> None:
            self.rows = [[inference_job], [], [signal], [signal_outcome], [plan_outcome]]

        async def execute(self, _statement: object) -> _Result:
            return _Result(self.rows.pop(0))

    report = await build_candidate_live_attrition_report(
        _Session(),  # type: ignore[arg-type]
        since=now - timedelta(hours=1),
        until=now + timedelta(hours=2),
    )

    assert report["status"] == "OK"
    attribution = report["live"]["outcome_attribution"]
    assert attribution["status"] == "OK"
    assert attribution["signal_cohort"]["outcome_counts"] == {"TP": 1}
    assert attribution["plan_cohort"]["valued_counterfactual_r"]["mean"] == 1.4


def test_execution_plan_evidence_is_machine_readable_and_single_terminal() -> None:
    evidence = execution_plan_attrition_evidence(
        status="BLOCKED_PORTFOLIO",
        reason_codes=["position_plan.blocked_portfolio", "limiting_cap.portfolio"],
        limiting_cap="PORTFOLIO",
    )

    assert evidence == {
        "schema": "execution-plan-attrition-v1",
        "terminal_stage": "RISK_EXECUTION",
        "primary_reason_code": "position_plan.blocked_portfolio",
        "reason_codes": ["position_plan.blocked_portfolio", "limiting_cap.portfolio"],
        "limiting_cap": "PORTFOLIO",
    }

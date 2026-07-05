from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.attrition import (
    build_attrition_report_from_records,
    execution_plan_attrition_evidence,
)


def _experiment_gate(*, passed: bool, reasons: list[str]) -> dict[str, object]:
    return {
        "schema": "model-promotion-experiment-governance-v1",
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

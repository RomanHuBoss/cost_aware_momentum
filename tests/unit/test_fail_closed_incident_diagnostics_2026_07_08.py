from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from app.logging import JsonFormatter
from app.ml.data_profile import profile_from_symbol_rows
from app.ml.features import FEATURE_NAMES
from app.ml.training import expanding_walk_forward_splits
from app.workers import trainer as trainer_module


def _labeled_frame(hours: int = 180) -> pd.DataFrame:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    outcomes = ("TP", "SL", "TIMEOUT")
    for hour in range(hours):
        decision_time = start + timedelta(hours=hour)
        for direction, direction_code in (("LONG", 1.0), ("SHORT", -1.0)):
            row = {name: 0.0 for name in FEATURE_NAMES}
            row[FEATURE_NAMES[0]] = float(hour)
            row.update(
                {
                    "scenario_direction": direction_code,
                    "open_time": decision_time + timedelta(hours=1),
                    "decision_time": decision_time,
                    "label_end_time": decision_time + timedelta(hours=8),
                    "symbol": "BTCUSDT",
                    "direction": direction,
                    "target": outcomes[(hour + (direction == "SHORT")) % 3],
                    "ambiguous": False,
                    "exit_index": 7,
                    "exit_at_open": False,
                    "realized_gross_return": 0.0,
                    "barrier_upside_rate": 0.02,
                    "barrier_downside_rate": 0.01,
                }
            )
            rows.append(row)
    return pd.DataFrame(rows)


def test_walk_forward_shortage_exposes_structured_capacity() -> None:
    with pytest.raises(ValueError) as exc_info:
        expanding_walk_forward_splits(
            _labeled_frame(),
            folds=3,
            purge_hours=8,
        )

    capacity = exc_info.value.capacity
    assert capacity.actual_timestamps == 180
    assert capacity.required_timestamps == 366
    assert capacity.block_size == 30
    assert capacity.minimum_block_timestamps == 61
    assert capacity.initial_train_timestamps == 60
    assert capacity.minimum_initial_train_timestamps == 90
    assert capacity.reason_code == "insufficient_walk_forward_history_after_filtering"


class _ScalarResult:
    def __init__(self, value: bool) -> None:
        self._value = value

    def scalar(self) -> bool:
        return self._value


class _FakeConnection:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement, params=None):
        return _ScalarResult(True)

    async def commit(self) -> None:
        return None


class _FakeEngine:
    def connect(self) -> _FakeConnection:
        return _FakeConnection()


@pytest.mark.asyncio
async def test_background_trainer_defers_post_filter_walk_forward_shortage(monkeypatch) -> None:
    now = datetime(2026, 7, 7, 20, tzinfo=UTC)
    profile = profile_from_symbol_rows(
        [("BTCUSDT", 1_206, now - timedelta(hours=1_205), now)],
        unique_timestamps=1_206,
        minimum_rows_for_coverage=300,
    )
    trigger = {
        "reason": "bootstrap_training",
        "training_data_profile": profile.to_dict(),
        "training_universe_mode": "static_configured",
        "training_universe_evidence": {
            "schema": "static-configured-training-cohort-v1",
            "status": "configured",
        },
    }
    trainer = trainer_module.BackgroundTrainer()
    finished: dict[str, object] = {}

    async def create_job(scheduled_for, details):
        return SimpleNamespace(id="job-1")

    async def finish_job(job_id, *, status, details):
        finished.update({"job_id": job_id, "status": status, "details": details})

    async def active_model():
        return None

    async def load_market_data(*args, **kwargs):
        return SimpleNamespace(
            candles=pd.DataFrame({"unused": [1]}),
            mark_candles=None,
            index_candles=None,
            open_interest=None,
            funding=None,
            funding_interval_minutes=None,
            funding_interval_history=None,
            instrument_spec_history=None,
            universe_eligibility=None,
        )

    def fail_candidate(*args, **kwargs):
        return expanding_walk_forward_splits(
            _labeled_frame(),
            folds=3,
            purge_hours=8,
        )

    monkeypatch.setattr(trainer_module, "engine", _FakeEngine())
    monkeypatch.setattr(trainer, "create_job", create_job)
    monkeypatch.setattr(trainer, "finish_job", finish_job)
    monkeypatch.setattr(trainer, "active_model", active_model)
    monkeypatch.setattr(trainer_module, "load_training_market_data", load_market_data)
    monkeypatch.setattr(trainer_module, "build_model_candidate", fail_candidate)

    result = await trainer.run_training_once(trigger)

    assert finished["status"] == "SUCCESS"
    assert result["status"] == "DEFERRED"
    assert result["reason_code"] == "insufficient_walk_forward_history_after_filtering"
    assert result["retryable"] is True
    assert "error" not in result
    assert trainer.state["phase"] == "WAITING"
    assert trainer.state["healthy"] is True


def test_json_formatter_preserves_safe_contract_diagnostics() -> None:
    record = logging.LogRecord(
        name="app.services.signals",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="Signal publication blocked by decision-time execution contract",
        args=(),
        exc_info=None,
    )
    record.reason_code = "decision_execution_contract_mismatch"
    record.contract_error = "artifact delay=600; runtime delay=900"
    record.event_time = "2026-07-07T20:00:00+00:00"
    record.publish_time = "2026-07-07T20:00:05+00:00"
    record.publication_lag_seconds = 5.0
    record.maximum_delay_seconds = 900

    payload = json.loads(JsonFormatter().format(record))

    assert payload["reason_code"] == "decision_execution_contract_mismatch"
    assert payload["contract_error"] == "artifact delay=600; runtime delay=900"
    assert payload["event_time"] == "2026-07-07T20:00:00+00:00"
    assert payload["publish_time"] == "2026-07-07T20:00:05+00:00"
    assert payload["publication_lag_seconds"] == 5.0
    assert payload["maximum_delay_seconds"] == 900

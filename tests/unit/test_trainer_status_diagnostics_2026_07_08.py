from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.api.v1.status import trainer_effective_wait_reason


def test_trainer_wait_reason_prefers_heartbeat_contract() -> None:
    heartbeat = SimpleNamespace(
        details={
            "wait_reason": {
                "reason": "training_cooldown_not_elapsed",
                "next_due_at": "2026-07-08T08:00:00+00:00",
            },
            "last_result": {"error": "older failure"},
        }
    )
    latest_job = SimpleNamespace(
        status="FAILED",
        started_at=datetime(2026, 7, 8, 4, 0, tzinfo=UTC),
        finished_at=None,
        details={"error": "No direction-specific barrier labels could be built from PostgreSQL candles"},
    )

    result = trainer_effective_wait_reason(heartbeat, latest_job)

    assert result == {
        "reason": "training_cooldown_not_elapsed",
        "next_due_at": "2026-07-08T08:00:00+00:00",
        "source": "heartbeat_wait_reason",
    }


def test_trainer_wait_reason_derives_direction_label_failure_from_latest_job() -> None:
    started_at = datetime(2026, 7, 8, 4, 29, 16, tzinfo=UTC)
    heartbeat = SimpleNamespace(details={"phase": "WAITING", "healthy": True})
    latest_job = SimpleNamespace(
        status="FAILED",
        started_at=started_at,
        finished_at=None,
        details={"error": "No direction-specific barrier labels could be built from PostgreSQL candles"},
    )

    result = trainer_effective_wait_reason(heartbeat, latest_job)

    assert result == {
        "reason": "no_direction_specific_barrier_labels",
        "source": "latest_training_job",
        "error": "No direction-specific barrier labels could be built from PostgreSQL candles",
        "last_status": "FAILED",
        "last_started_at": started_at.isoformat(),
        "last_finished_at": None,
    }

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.api.schemas import RecommendationExposureBatchRequest
from app.api.v1.recommendations import record_recommendation_exposures
from app.services.selection_experiments import build_selection_ledger_row

BASE = datetime.now(UTC) - timedelta(seconds=3)


class _ScalarResult:
    def __init__(self, value: object | None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object | None:
        return self.value


class _ExposureBatchSession:
    def __init__(self, ledgers: dict[UUID, object]) -> None:
        self.ledgers = ledgers
        self.commits = 0
        self.inserted: list[UUID] = []

    async def execute(self, statement) -> _ScalarResult:
        if statement.__class__.__name__ == "Insert":
            inserted_id = uuid4()
            self.inserted.append(inserted_id)
            return _ScalarResult(inserted_id)
        params = statement.compile().params
        plan_id = next((value for value in params.values() if isinstance(value, UUID)), None)
        return _ScalarResult(self.ledgers.get(plan_id))

    async def commit(self) -> None:
        self.commits += 1


def _ledger():
    signal = SimpleNamespace(
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
    plan = SimpleNamespace(
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
        warnings=[],
        sizing_snapshot={
            "entry_inside_signal_zone": True,
            "net_rr": "1.38",
            "net_ev_r": "0.09",
            "execution_quality": {"impact_bps": "3.5"},
            "caps": {"orderbook_depth_notional": "5000"},
        },
    )
    return build_selection_ledger_row(
        signal=signal,
        plan=plan,
        observed_at=BASE,
        release_version="1.35.4",
    )


def _event(plan_id: UUID, plan_version: int) -> dict[str, object]:
    return {
        "plan_id": plan_id,
        "plan_version": plan_version,
        "client_event_id": uuid4(),
        "page_instance_id": uuid4(),
        "observed_at": BASE + timedelta(seconds=2),
        "viewport_ratio": Decimal("0.75"),
        "dwell_ms": 1250,
        "surface": "RECOMMENDATION_TILE",
    }


@pytest.mark.asyncio
async def test_stale_exposure_item_does_not_roll_back_valid_batch_item() -> None:
    valid = _ledger()
    unknown_plan_id = uuid4()
    session = _ExposureBatchSession({valid.plan_id: valid})
    payload = RecommendationExposureBatchRequest(
        exposures=[
            _event(unknown_plan_id, 1),
            _event(valid.plan_id, valid.plan_version),
        ]
    )

    result = await record_recommendation_exposures(
        payload=payload,
        session=session,
        operator="local-operator",
    )

    assert result["created"] == 1
    assert result["ignored"] == 1
    assert result["rejected"] == 0
    assert result["ok"] is True
    assert [item["status"] for item in result["recorded"]] == [
        "IGNORED_UNKNOWN_PLAN",
        "RECORDED",
    ]
    assert len(session.inserted) == 1
    assert session.commits == 1

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.config import Settings
from app.db.models import SelectionExposureLedger
from app.services.selection_experiments import (
    build_selection_ledger_row,
    selection_bias_report,
)
from app.services.ui_exposures import (
    UI_EXPOSURE_SCHEMA,
    build_selection_exposure_row,
    validate_ui_exposure_evidence,
    verify_selection_exposure_integrity,
)

BASE = datetime(2026, 1, 1, 12, tzinfo=UTC)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
        warnings=[],
        sizing_snapshot={
            "entry_inside_signal_zone": True,
            "net_rr": "1.38",
            "net_ev_r": "0.09",
            "execution_quality": {"impact_bps": "3.5"},
            "caps": {"orderbook_depth_notional": "5000"},
        },
    )


def _exposure(ledger, *, exposed_at: datetime = BASE + timedelta(seconds=2)):
    return build_selection_exposure_row(
        ledger=ledger,
        operator_id="local-operator",
        exposed_at=exposed_at,
        received_at=exposed_at + timedelta(milliseconds=250),
        viewport_ratio=Decimal("0.75"),
        dwell_ms=1250,
        surface="RECOMMENDATION_TILE",
        client_event_id=uuid4(),
        page_instance_id=uuid4(),
        release_version="1.21.0",
    )


def test_ui_exposure_row_is_tamper_evident_and_predecision() -> None:
    ledger = build_selection_ledger_row(
        signal=_signal(), plan=_plan(), observed_at=BASE, release_version="1.21.0"
    )
    row = _exposure(ledger)

    assert row.exposure_schema == UI_EXPOSURE_SCHEMA
    assert row.plan_id == ledger.plan_id
    assert row.plan_version == ledger.plan_version
    assert row.viewport_ratio == Decimal("0.75")
    assert verify_selection_exposure_integrity(row) is True

    row.dwell_ms = 9999
    assert verify_selection_exposure_integrity(row) is False


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"dwell_ms": 999}, "dwell"),
        ({"viewport_ratio": Decimal("0.49")}, "viewport"),
        ({"surface": "DETAIL_MODAL"}, "surface"),
        ({"exposed_at": BASE - timedelta(minutes=16)}, "old"),
        ({"exposed_at": BASE + timedelta(seconds=6)}, "future"),
    ],
)
def test_ui_exposure_validation_fails_closed(changes: dict, message: str) -> None:
    values = {
        "plan_observed_at": BASE - timedelta(minutes=20),
        "exposed_at": BASE,
        "received_at": BASE,
        "viewport_ratio": Decimal("0.75"),
        "dwell_ms": 1250,
        "surface": "RECOMMENDATION_TILE",
    }
    values.update(changes)
    with pytest.raises(ValueError, match=message):
        validate_ui_exposure_evidence(**values)


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


@pytest.mark.asyncio
async def test_selection_report_uses_only_exposed_opportunities() -> None:
    rows: list[tuple[object, object, object, object]] = []
    for index, exposed in enumerate([True, False, True]):
        signal = _signal()
        plan = _plan()
        ledger = build_selection_ledger_row(
            signal=signal,
            plan=plan,
            observed_at=BASE + timedelta(minutes=index),
            release_version="1.21.0",
        )
        exposure = _exposure(ledger, exposed_at=BASE + timedelta(minutes=index, seconds=2)) if exposed else None
        decision = SimpleNamespace(action=["ACCEPT", "REJECT", None][index]) if index < 2 else None
        outcome = SimpleNamespace(
            valuation_status="VALUED", counterfactual_r=Decimal(str(index - 1))
        )
        rows.append((ledger, exposure, decision, outcome))

    report = await selection_bias_report(
        _RowsSession(rows),
        since=BASE - timedelta(hours=1),
        minimum_total=1,
        minimum_selected=0,
        minimum_unselected=0,
        minimum_exposure_coverage=Decimal("0.50"),
    )

    assert report["decision_counts"] == {"ACCEPT": 1, "NO_DECISION": 1, "REJECT": 0}
    assert report["ledger"]["eligible_created_count"] == 3
    assert report["ledger"]["eligible_exposed_count"] == 2
    assert report["ledger"]["eligible_unexposed_count"] == 1
    assert report["ledger"]["decision_without_exposure_count"] == 1
    assert report["ledger"]["operator_exposure_observed"] is True


@pytest.mark.asyncio
async def test_selection_report_blocks_low_exposure_coverage() -> None:
    rows: list[tuple[object, object, object, object]] = []
    for index in range(4):
        ledger = build_selection_ledger_row(
            signal=_signal(),
            plan=_plan(),
            observed_at=BASE + timedelta(minutes=index),
            release_version="1.21.0",
        )
        exposure = _exposure(ledger) if index == 0 else None
        outcome = SimpleNamespace(valuation_status="VALUED", counterfactual_r=Decimal("0.1"))
        rows.append((ledger, exposure, None, outcome))

    report = await selection_bias_report(
        _RowsSession(rows),
        since=BASE - timedelta(hours=1),
        minimum_total=1,
        minimum_selected=0,
        minimum_unselected=0,
        minimum_exposure_coverage=Decimal("0.80"),
    )

    assert report["status"] == "LOW_EXPOSURE_COVERAGE"
    assert report["ipsw_selected_mean_r"] is None
    assert report["ledger"]["exposure_coverage_rate"] == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_selection_report_does_not_treat_legacy_uninstrumented_rows_as_unexposed() -> None:
    legacy = build_selection_ledger_row(
        signal=_signal(), plan=_plan(), observed_at=BASE, release_version="1.20.0"
    )
    current = build_selection_ledger_row(
        signal=_signal(),
        plan=_plan(),
        observed_at=BASE + timedelta(minutes=1),
        release_version="1.21.0",
    )
    current_exposure = _exposure(current, exposed_at=current.observed_at + timedelta(seconds=2))
    outcome = SimpleNamespace(valuation_status="VALUED", counterfactual_r=Decimal("0.1"))

    report = await selection_bias_report(
        _RowsSession(
            [
                (legacy, None, None, outcome),
                (current, current_exposure, None, outcome),
            ]
        ),
        since=BASE - timedelta(hours=1),
        minimum_total=1,
        minimum_selected=0,
        minimum_unselected=0,
        minimum_exposure_coverage=Decimal("0.80"),
    )

    assert report["ledger"]["legacy_pre_exposure_count"] == 1
    assert report["ledger"]["eligible_created_count"] == 1
    assert report["ledger"]["eligible_exposed_count"] == 1
    assert report["ledger"]["exposure_coverage_rate"] == pytest.approx(1.0)
    assert report["status"] != "LOW_EXPOSURE_COVERAGE"


@pytest.mark.asyncio
async def test_selection_report_fails_closed_on_exposure_tampering() -> None:
    ledger = build_selection_ledger_row(
        signal=_signal(), plan=_plan(), observed_at=BASE, release_version="1.21.0"
    )
    exposure = _exposure(ledger)
    exposure.viewport_ratio = Decimal("0.99")
    outcome = SimpleNamespace(valuation_status="VALUED", counterfactual_r=Decimal("1"))

    report = await selection_bias_report(
        _RowsSession([(ledger, exposure, None, outcome)]),
        since=BASE - timedelta(hours=1),
        minimum_total=1,
        minimum_selected=0,
        minimum_unselected=0,
        minimum_exposure_coverage=Decimal("0"),
    )

    assert report["status"] == "EXPOSURE_LEDGER_INTEGRITY_ERROR"
    assert report["ipsw_selected_mean_r"] is None


def test_exposure_model_and_migration_are_immutable() -> None:
    unique_names = {constraint.name for constraint in SelectionExposureLedger.__table__.constraints}
    assert "uq_selection_exposure_plan" in unique_names
    assert "uq_selection_exposure_client_event" in unique_names
    assert "ck_selection_exposure_ledger_selection_exposure_hash_length" in unique_names

    migration = (PROJECT_ROOT / "migrations/versions/0014_ui_exposure_ledger.py").read_text(
        encoding="utf-8"
    )
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "selection_exposure_ledger" in migration



def test_exposure_configuration_fails_closed() -> None:
    with pytest.raises(ValueError, match="SELECTION_MIN_EXPOSURE_COVERAGE"):
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg://u:p@localhost/db",
            selection_min_exposure_coverage=1.01,
        )


def test_exposure_endpoint_is_authenticated_and_idempotent_by_plan() -> None:
    source = (PROJECT_ROOT / "app/api/v1/recommendations.py").read_text(encoding="utf-8")

    assert '@router.post("/exposures")' in source
    assert "operator: MutatingOperatorDep" in source
    assert ".on_conflict_do_nothing" in source
    assert "SelectionExposureLedger.plan_id" in source

def test_frontend_records_only_visible_dwell_exposures() -> None:
    source = (PROJECT_ROOT / "web/js/app.js").read_text(encoding="utf-8")

    assert "IntersectionObserver" in source
    assert "document.visibilityState" in source
    assert "data-plan-id" in source
    assert "dwell_ms" in source
    assert "viewport_ratio" in source
    assert "/api/v1/recommendations/exposures" in source

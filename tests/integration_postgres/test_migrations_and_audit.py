from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, select, text

from app.config import Settings
from app.db.engine import rebuild_engine
from app.db.models import (
    AuditEvent,
    Candle,
    CapitalProfile,
    ExecutionPlan,
    JobRun,
    MarketSignal,
    OutboxEvent,
    PlanOutcome,
    ServiceHeartbeat,
    SignalOutcome,
    UIGlossary,
)
from app.services.audit import append_audit_event
from app.services.idempotency import IdempotencyConflict, get_cached, store_cached
from app.services.outcomes import resolve_counterfactual_outcomes
from app.services.trainer_control import (
    TRAINER_CONTROL_JOB_NAME,
    acquire_trainer_control_lock,
    recover_stale_trainer_control,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is not configured")
    return value


@pytest.fixture(scope="session", autouse=True)
def migrate(database_url: str) -> None:
    env = {**os.environ, "DATABASE_URL": database_url}
    project_root = Path(__file__).parents[2]
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        cwd=project_root,
        env=env,
        check=False,
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=project_root,
        env=env,
        check=True,
    )


@pytest.mark.asyncio
async def test_seeded_reference_data(database_url: str) -> None:
    settings = Settings(database_url=database_url)
    engine, factory = rebuild_engine(settings)
    async with factory() as session:
        assert (await session.execute(select(CapitalProfile))).scalars().all()
        assert len((await session.execute(select(UIGlossary))).scalars().all()) >= 10
        revision = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
        assert revision == "0009_candle_receipt_availability"
        account_column = (
            await session.execute(
                text(
                    """
                    SELECT is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'advisory'
                      AND table_name = 'position_snapshots'
                      AND column_name = 'account_id'
                    """
                )
            )
        ).scalar_one()
        assert account_column == "NO"
        position_index_definition = (
            await session.execute(
                text(
                    """
                    SELECT indexdef
                    FROM pg_indexes
                    WHERE schemaname = 'advisory'
                      AND indexname = 'ix_position_account_time'
                    """
                )
            )
        ).scalar_one()
        assert "account_id" in position_index_definition
        assert "source_time" in position_index_definition
        index_definition = (
            await session.execute(
                text(
                    """
                    SELECT indexdef
                    FROM pg_indexes
                    WHERE schemaname = 'advisory'
                      AND indexname = 'uq_market_signal_one_published_per_symbol'
                    """
                )
            )
        ).scalar_one()
        assert "UNIQUE INDEX" in index_definition
        assert "WHERE" in index_definition
        assert "PUBLISHED" in index_definition
        model_index_definition = (
            await session.execute(
                text(
                    """
                    SELECT indexdef
                    FROM pg_indexes
                    WHERE schemaname = 'model'
                      AND indexname = 'uq_model_registry_single_active'
                    """
                )
            )
        ).scalar_one()
        assert "UNIQUE INDEX" in model_index_definition
        assert "WHERE" in model_index_definition
        assert "active" in model_index_definition
        tables = {
            row[0]
            for row in (
                await session.execute(
                    text(
                        """
                        SELECT tablename
                        FROM pg_tables
                        WHERE schemaname = 'advisory'
                          AND tablename IN ('signal_outcomes', 'plan_outcomes')
                        """
                    )
                )
            ).all()
        }
        assert tables == {"signal_outcomes", "plan_outcomes"}
        assert SignalOutcome.__table__.schema == "advisory"
        assert PlanOutcome.__table__.schema == "advisory"
        valuation_constraint = (
            await session.execute(
                text(
                    """
                    SELECT pg_get_constraintdef(oid)
                    FROM pg_constraint
                    WHERE conname = 'ck_plan_outcomes_plan_outcome_valuation_status'
                    """
                )
            )
        ).scalar_one()
        assert "INVALID_INPUT" in valuation_constraint
        assert "PATH_UNAVAILABLE" in valuation_constraint
    await engine.dispose()


@pytest.mark.asyncio
async def test_stale_trainer_control_is_failed_and_requeued_atomically(database_url: str) -> None:
    settings = Settings(
        database_url=database_url,
        heartbeat_seconds=15,
        trainer_id="trainer-recovery-integration",
    )
    engine, factory = rebuild_engine(settings)
    now = datetime.now(UTC)
    accepted_at = now - timedelta(minutes=10)
    stale_owner = "trainer-stale-integration"

    async with factory() as session, session.begin():
        await session.execute(
            delete(JobRun).where(JobRun.job_name == TRAINER_CONTROL_JOB_NAME)
        )
        await session.execute(
            delete(ServiceHeartbeat).where(
                ServiceHeartbeat.service_name == "trainer",
                ServiceHeartbeat.instance_id == stale_owner,
            )
        )
        abandoned = JobRun(
            job_name=TRAINER_CONTROL_JOB_NAME,
            scheduled_for=accepted_at,
            started_at=accepted_at,
            status="RUNNING",
            worker_id=stale_owner,
            details={
                "action": "CHECK_NOW",
                "requested_by": "integration-operator",
                "requested_at": (accepted_at - timedelta(seconds=5)).isoformat(),
                "accepted_at": accepted_at.isoformat(),
                "accepted_by": stale_owner,
                "claim_token": "abandoned-claim",
            },
        )
        session.add(abandoned)
        session.add(
            ServiceHeartbeat(
                service_name="trainer",
                instance_id=stale_owner,
                last_seen_at=accepted_at,
                status="RUNNING",
                details={},
            )
        )
        await session.flush()
        abandoned_id = abandoned.id

    async with factory() as session, session.begin():
        await acquire_trainer_control_lock(session)
        replacement = await recover_stale_trainer_control(
            session,
            settings,
            recovered_by=settings.trainer_id,
        )
        assert replacement is not None
        replacement_id = replacement.id

    async with factory() as session:
        abandoned = await session.get(JobRun, abandoned_id)
        replacement = await session.get(JobRun, replacement_id)
        assert abandoned is not None
        assert abandoned.status == "FAILED"
        assert abandoned.details["result"]["error"] == "stale_trainer_control_owner"
        assert replacement is not None
        assert replacement.status == "PENDING"
        assert replacement.details["retry_of"] == str(abandoned_id)
        audit_types = set(
            (
                await session.execute(
                    select(AuditEvent.event_type).where(
                        AuditEvent.entity_id.in_([str(abandoned_id), str(replacement_id)])
                    )
                )
            ).scalars()
        )
        outbox_types = set(
            (
                await session.execute(
                    select(OutboxEvent.event_type).where(
                        OutboxEvent.aggregate_id.in_([str(abandoned_id), str(replacement_id)])
                    )
                )
            ).scalars()
        )
        assert audit_types == {
            "TRAINER_CONTROL_STALE_RECOVERED",
            "TRAINER_CONTROL_REQUEUED",
        }
        assert outbox_types == audit_types
    await engine.dispose()


@pytest.mark.asyncio
async def test_audit_chain_and_idempotency(database_url: str) -> None:
    settings = Settings(database_url=database_url)
    engine, factory = rebuild_engine(settings)
    async with factory() as session:
        first = await append_audit_event(
            session, event_type="TEST_A", entity_type="test", entity_id="1", actor="pytest", payload={"a": 1}
        )
        await session.flush()
        second = await append_audit_event(
            session, event_type="TEST_B", entity_type="test", entity_id="1", actor="pytest", payload={"b": 2}
        )
        await store_cached(
            session,
            key="pytest-key-0001",
            scope="pytest-scope",
            request_payload={"x": 1},
            response_status=200,
            response_body=b'{"ok":true}',
        )
        await session.commit()
        assert second.previous_hash == first.event_hash
        assert len(second.event_hash) == 64

    async with factory() as session:
        cached = await get_cached(
            session, key="pytest-key-0001", scope="pytest-scope", request_payload={"x": 1}
        )
        assert cached == (200, b'{"ok":true}')
        with pytest.raises(IdempotencyConflict):
            await get_cached(session, key="pytest-key-0001", scope="pytest-scope", request_payload={"x": 2})
        events = (
            (await session.execute(select(AuditEvent).where(AuditEvent.actor == "pytest"))).scalars().all()
        )
        assert len(events) >= 2
    await engine.dispose()


@pytest.mark.asyncio
async def test_counterfactual_outcome_is_idempotent_for_all_plan_versions(
    database_url: str,
) -> None:
    settings = Settings(database_url=database_url)
    engine, factory = rebuild_engine(settings)
    base = datetime(2026, 6, 1, 12, tzinfo=UTC)
    async with factory() as session, session.begin():
        profile = (await session.execute(select(CapitalProfile).limit(1))).scalar_one()
        signal = MarketSignal(
            natural_key="pytest-counterfactual-outcome-v1",
            symbol="PYTESTOUTCOMEUSDT",
            direction="LONG",
            status="SUPERSEDED",
            event_time=base,
            publish_time=base,
            expires_at=base + timedelta(hours=1),
            horizon_hours=2,
            entry_reference=Decimal("100"),
            entry_low=Decimal("99"),
            entry_high=Decimal("101"),
            stop_loss=Decimal("98"),
            take_profit_1=Decimal("104"),
            take_profit_2=Decimal("106"),
            tp1_weight=Decimal("0.7"),
            p_tp=0.4,
            p_sl=0.4,
            p_timeout=0.2,
            gross_rr=2.0,
            net_rr=1.5,
            net_ev_r=0.1,
            gross_edge_rate=0.04,
            fee_rate_round_trip=0.001,
            slippage_rate=0.0005,
            funding_rate_scenario=0.0001,
            stress_downside_rate=0.03,
            model_version="pytest",
            calibration_version="pytest",
            feature_schema_version="hourly-barrier-v1",
            data_cutoff=base,
            reasons=[],
            warnings=[],
            feature_snapshot={},
        )
        session.add(signal)
        await session.flush()
        session.add(
            Candle(
                symbol=signal.symbol,
                interval="60",
                open_time=base,
                close_time=base + timedelta(hours=1),
                available_at=base + timedelta(hours=1),
                price_type="last",
                open=Decimal("100"),
                high=Decimal("104.5"),
                low=Decimal("99"),
                close=Decimal("104"),
                volume=Decimal("1"),
                turnover=Decimal("100"),
                confirmed=True,
            )
        )
        for version, qty in ((1, Decimal("1")), (2, Decimal("2"))):
            session.add(
                ExecutionPlan(
                    signal_id=signal.id,
                    profile_id=profile.id,
                    profile_version=profile.version,
                    version=version,
                    status="SUPERSEDED",
                    effective_capital=Decimal("1000"),
                    capital_verified=False,
                    risk_rate=Decimal("0.0035"),
                    risk_budget=Decimal("3.5"),
                    actual_stress_loss=Decimal("3.5"),
                    qty_raw=qty,
                    qty=qty,
                    notional=qty * Decimal("100"),
                    leverage=3,
                    margin_estimate=qty * Decimal("100") / Decimal("3"),
                    liquidation_buffer_rate=0.2,
                    warnings=[],
                    sizing_snapshot={
                        "costs": {
                            "fee_rate_round_trip": "0.001",
                            "slippage_rate": "0.0005",
                            "stop_gap_reserve_rate": "0.001",
                            "funding_rate": "0.0001",
                            "funding_rate_per_settlement": "0.0001",
                            "funding_next_settlement": (base + timedelta(hours=3)).isoformat(),
                            "funding_interval_minutes": 480,
                        }
                    },
                )
            )

    async with factory() as session, session.begin():
        first = await resolve_counterfactual_outcomes(
            session,
            market_cutoff=base + timedelta(hours=2),
            available_cutoff=base + timedelta(hours=2),
            actor="pytest",
        )
        second = await resolve_counterfactual_outcomes(
            session,
            market_cutoff=base + timedelta(hours=2),
            available_cutoff=base + timedelta(hours=2),
            actor="pytest",
        )
        outcomes = (
            (
                await session.execute(
                    select(PlanOutcome)
                    .join(ExecutionPlan, ExecutionPlan.id == PlanOutcome.plan_id)
                    .where(ExecutionPlan.signal_id == signal.id)
                )
            )
            .scalars()
            .all()
        )
        signal_outcome = (
            await session.execute(select(SignalOutcome).where(SignalOutcome.signal_id == signal.id))
        ).scalar_one()

        assert first["signals_resolved"] == 1
        assert first["plan_outcomes_recorded"] == 2
        assert second["signals_resolved"] == 0
        assert second["plan_outcomes_recorded"] == 0
        assert signal_outcome.outcome == "TP"
        assert len(outcomes) == 2
        assert {row.plan_version for row in outcomes} == {1, 2}

    await engine.dispose()

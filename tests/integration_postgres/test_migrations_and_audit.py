from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError

from app.config import Settings
from app.db.engine import rebuild_engine
from app.db.models import (
    AuditEvent,
    Candle,
    CapitalProfile,
    ExecutionPlan,
    JobRun,
    MarketSignal,
    ModelArtifactBlob,
    ModelRegistry,
    OutboxEvent,
    PlanOutcome,
    ServiceHeartbeat,
    SignalOutcome,
    UIGlossary,
    UniverseEligibilitySnapshot,
)
from app.ml.universe_replay import load_point_in_time_universe_snapshots
from app.services.audit import append_audit_event
from app.services.idempotency import IdempotencyConflict, get_cached, store_cached
from app.services.outcomes import resolve_counterfactual_outcomes
from app.services.trainer_control import (
    TRAINER_CONTROL_JOB_NAME,
    acquire_trainer_control_lock,
    claim_automatic_experiment_cancel,
    enqueue_trainer_control,
    finish_automatic_experiment_cancel,
    recover_stale_trainer_control,
)
from app.services.universe import persist_universe_selection, select_dynamic_universe

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
        assert revision == "0017_model_artifact_blobs"
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
        artifact_table = (
            await session.execute(
                text(
                    """
                    SELECT tablename
                    FROM pg_tables
                    WHERE schemaname = 'model'
                      AND tablename = 'model_artifact_blobs'
                    """
                )
            )
        ).scalar_one()
        assert artifact_table == "model_artifact_blobs"
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
async def test_model_artifact_blob_is_append_only(database_url: str) -> None:
    settings = Settings(database_url=database_url)
    engine, factory = rebuild_engine(settings)
    payload = b"integration-immutable-model-artifact"
    import hashlib

    digest = hashlib.sha256(payload).hexdigest()
    version = f"integration-artifact-{datetime.now(UTC).timestamp()}"
    async with factory() as session, session.begin():
        registry = ModelRegistry(
            name="Integration artifact",
            version=version,
            model_type="barrier_logistic",
            artifact_path="missing.joblib",
            artifact_sha256=digest,
            feature_schema_version="integration-v1",
            metrics={},
            active=False,
        )
        session.add(registry)
        await session.flush()
        blob = ModelArtifactBlob(
            model_registry_id=registry.id,
            version=version,
            artifact_sha256=digest,
            size_bytes=len(payload),
            payload=payload,
        )
        session.add(blob)
        await session.flush()
        registry_id = registry.id

    async with factory() as session:
        with pytest.raises(DBAPIError, match="model artifact blobs are immutable"):
            await session.execute(
                update(ModelArtifactBlob)
                .where(ModelArtifactBlob.model_registry_id == registry_id)
                .values(size_bytes=len(payload) + 1)
            )
            await session.commit()
        await session.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_universe_eligibility_snapshot_is_append_only(database_url: str) -> None:
    settings = Settings(database_url=database_url)
    engine, factory = rebuild_engine(settings)
    observed_at = datetime.now(UTC)
    snapshot = UniverseEligibilitySnapshot(
        observed_at=observed_at,
        recorded_at=observed_at,
        mode="static",
        eligibility_schema="universe-eligibility-snapshot-v1",
        policy={"schema": "universe-selection-policy-v1", "mode": "static"},
        policy_hash="a" * 64,
        decisions=[
            {
                "symbol": "PYTESTUSDT",
                "eligible_before_limit": True,
                "selected": True,
                "rank": 1,
                "reason_code": "static_configured",
            }
        ],
        selected_symbols=["PYTESTUSDT"],
        total_instruments=1,
        ticker_count=0,
        eligible_before_limit=1,
        selected_count=1,
        release_version="integration-test",
        record_hash="b" * 64,
    )
    async with factory() as session, session.begin():
        session.add(snapshot)
        await session.flush()
        snapshot_id = snapshot.id

    async with factory() as session:
        with pytest.raises(DBAPIError, match="universe eligibility snapshots are immutable"):
            await session.execute(
                update(UniverseEligibilitySnapshot)
                .where(UniverseEligibilitySnapshot.id == snapshot_id)
                .values(selected_count=0)
            )
            await session.commit()
        await session.rollback()
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
async def test_exact_automatic_experiment_cancel_claim_is_audited_and_terminal(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import trainer_control as trainer_control_module

    settings = Settings(database_url=database_url)
    engine, factory = rebuild_engine(settings)
    family = "auto-integration-family"
    candidate = "candidate-integration-v1"
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        await session.execute(delete(JobRun).where(JobRun.job_name == TRAINER_CONTROL_JOB_NAME))
        pending_check = JobRun(
            job_name=TRAINER_CONTROL_JOB_NAME,
            scheduled_for=now - timedelta(seconds=1),
            started_at=now - timedelta(seconds=1),
            status="PENDING",
            worker_id="operator:integration",
            details={
                "action": "CHECK_NOW",
                "requested_by": "integration-operator",
                "requested_at": (now - timedelta(seconds=1)).isoformat(),
            },
        )
        session.add(pending_check)
        await session.flush()
        pending_check_id = pending_check.id
        request, created = await enqueue_trainer_control(
            session,
            action="CANCEL_EXPERIMENT",
            operator="integration-operator",
            settings=settings,
            experiment_family=family,
            candidate_version=candidate,
        )
        assert created is True
        request_id = request.id

    monkeypatch.setattr(trainer_control_module, "SessionFactory", factory)
    claim = await claim_automatic_experiment_cancel(
        experiment_family=family,
        candidate_version=candidate,
        accepted_by="trainer-integration",
    )
    assert claim is not None
    assert claim.request_id == request_id
    assert claim.experiment_family == family
    assert claim.candidate_version == candidate

    completed = await finish_automatic_experiment_cancel(
        claim,
        status="SUCCESS",
        result={"action": "CANCEL_EXPERIMENT", "cancelled": True},
        actor="trainer-integration",
    )
    assert completed is True

    async with factory() as session:
        row = await session.get(JobRun, request_id)
        assert row is not None
        assert row.status == "SUCCESS"
        assert row.details["result"]["cancelled"] is True
        superseded = await session.get(JobRun, pending_check_id)
        assert superseded is not None
        assert superseded.status == "FAILED"
        assert superseded.details["result"]["error"] == (
            "superseded_by_automatic_experiment_cancel"
        )
        audit_types = set(
            (
                await session.execute(
                    select(AuditEvent.event_type).where(AuditEvent.entity_id == str(request_id))
                )
            ).scalars()
        )
        outbox_types = set(
            (
                await session.execute(
                    select(OutboxEvent.event_type).where(
                        OutboxEvent.aggregate_id == str(request_id)
                    )
                )
            ).scalars()
        )
        assert {
            "AUTOMATIC_EXPERIMENT_CANCEL_ACCEPTED",
            "AUTOMATIC_EXPERIMENT_CANCEL_COMPLETED",
        }.issubset(audit_types)
        assert {
            "AUTOMATIC_EXPERIMENT_CANCEL_ACCEPTED",
            "AUTOMATIC_EXPERIMENT_CANCEL_COMPLETED",
        }.issubset(outbox_types)
        superseded_audit = set(
            (
                await session.execute(
                    select(AuditEvent.event_type).where(
                        AuditEvent.entity_id == str(pending_check_id)
                    )
                )
            ).scalars()
        )
        superseded_outbox = set(
            (
                await session.execute(
                    select(OutboxEvent.event_type).where(
                        OutboxEvent.aggregate_id == str(pending_check_id)
                    )
                )
            ).scalars()
        )
        assert "TRAINER_CONTROL_SUPERSEDED" in superseded_audit
        assert "TRAINER_CONTROL_SUPERSEDED" in superseded_outbox
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


@pytest.mark.asyncio
async def test_postgres_native_universe_asof_loader_is_indexed_and_reduced(
    database_url: str,
) -> None:
    settings = Settings(
        database_url=database_url,
        universe_mode="dynamic",
        universe_min_age_days=7,
        universe_min_turnover_24h=1,
        universe_max_spread_bps=100,
        universe_max_symbols=1,
    )
    engine, factory = rebuild_engine(settings)
    start = datetime(2040, 1, 1, 9, tzinfo=UTC)
    instrument = SimpleNamespace(
        symbol="PGASOFUSDT",
        category="linear",
        base_coin="PGASOF",
        quote_coin="USDT",
        settle_coin="USDT",
        status="Trading",
        launch_time=start - timedelta(days=100),
        delivery_time=None,
        is_pre_listing=False,
        raw={"contractType": "LinearPerpetual", "symbolType": ""},
    )
    ticker = {
        "symbol": "PGASOFUSDT",
        "lastPrice": "100",
        "bid1Price": "99.9",
        "ask1Price": "100.1",
        "turnover24h": "1000000",
    }

    async with factory() as session:
        transaction = await session.begin()
        try:
            for offset in range(24):
                observed_at = start + timedelta(minutes=5 * offset)
                selection = select_dynamic_universe(
                    [instrument],
                    [ticker],
                    settings,
                    now=observed_at,
                )
                await persist_universe_selection(
                    session,
                    selection,
                    recorded_at=observed_at + timedelta(seconds=1),
                    release_version="integration-test",
                )

            decision_times = [
                start + timedelta(hours=1),
                start + timedelta(hours=2),
            ]
            compact = await load_point_in_time_universe_snapshots(
                session,
                decision_times,
                expected_mode="dynamic",
            )

            assert len(compact) == 3
            assert compact.attrs["universe_snapshot_loader"] == {
                "schema": "postgresql-native-universe-asof-loader-v1",
                "requested_decision_timestamps": 2,
                "snapshot_rows_streamed": 3,
                "compact_rows_retained": 3,
            }
            assert list(compact["recorded_at"]) == [
                start + timedelta(seconds=1),
                start + timedelta(minutes=55, seconds=1),
                start + timedelta(minutes=115, seconds=1),
            ]

            await session.execute(text("SET LOCAL enable_seqscan = off"))
            plan = (
                await session.execute(
                    text(
                        """
                        EXPLAIN (FORMAT JSON)
                        SELECT recorded_at
                        FROM market.universe_eligibility_snapshots
                        WHERE mode = 'dynamic'
                          AND recorded_at <= :decision_time
                        ORDER BY recorded_at DESC
                        LIMIT 1
                        """
                    ),
                    {"decision_time": decision_times[0]},
                )
            ).scalar_one()
            assert "ix_universe_eligibility_mode_recorded_at" in str(plan)
        finally:
            await transaction.rollback()
    await engine.dispose()

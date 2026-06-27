from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.asyncio_compat import run_with_compatible_event_loop
from app.bybit.client import BybitClient
from app.config import get_settings
from app.db.engine import SessionFactory, dispose_engine
from app.db.locks import advisory_lock
from app.db.models import JobRun, ModelRegistry, ServiceHeartbeat, TickerSnapshot
from app.logging import configure_logging
from app.ml.runtime import ModelRuntime
from app.services.market_data import (
    symbols_needing_history_backfill,
    sync_candle_history,
    sync_candle_windows,
    sync_candles,
    sync_funding_and_oi,
    sync_instruments,
    sync_read_only_account,
    sync_tickers,
)
from app.services.outcomes import find_ambiguous_intrabar_windows, resolve_counterfactual_outcomes
from app.services.signals import expire_old_signals, publish_hourly_signals
from app.services.universe import UniverseSelection, resolve_universe

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


class Worker:
    def __init__(self) -> None:
        self.stop_event = asyncio.Event()
        self.client = BybitClient(
            base_url=settings.bybit_base_url,
            api_key=settings.bybit_api_key,
            api_secret=settings.bybit_api_secret,
            recv_window=settings.bybit_recv_window,
        )
        self.runtime = ModelRuntime(None, settings.allow_baseline_model)
        self.last_instrument_sync: datetime | None = None
        self.last_market_sync: datetime | None = None
        self.last_history_backfill: datetime | None = None
        self.history_backfill_summary: dict | None = None
        self.last_account_sync: datetime | None = None
        self.last_universe_refresh: datetime | None = None
        self.last_model_refresh: datetime | None = None
        self.active_model_registry_id: str | None = None
        self.active_symbols: tuple[str, ...] = tuple(settings.symbols)
        self.universe_summary: dict = {
            "mode": settings.universe_mode,
            "selected_count": len(self.active_symbols),
            "selected_symbols": list(self.active_symbols),
            "selected_sample": list(self.active_symbols[:25]),
        }

    def request_stop(self) -> None:
        self.stop_event.set()

    async def refresh_model_runtime(self, *, force: bool = False) -> bool:
        now = datetime.now(UTC)
        if (
            not force
            and self.last_model_refresh is not None
            and (now - self.last_model_refresh).total_seconds() < settings.model_refresh_seconds
        ):
            return False

        async with SessionFactory() as session:
            registry = (
                await session.execute(
                    select(ModelRegistry)
                    .where(ModelRegistry.active.is_(True))
                    .order_by(ModelRegistry.updated_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

        if settings.active_model_path is not None:
            candidate = ModelRuntime(Path(settings.active_model_path), allow_baseline=False)
            candidate.load(source="environment_override")
            if candidate.horizon_hours != settings.default_horizon_hours:
                raise RuntimeError(
                    f"Model override horizon {candidate.horizon_hours} does not match "
                    f"DEFAULT_HORIZON_HOURS={settings.default_horizon_hours}"
                )
            registry_id = None
        elif registry is None:
            candidate = ModelRuntime(None, allow_baseline=settings.allow_baseline_model)
            candidate.load(source="baseline")
            registry_id = None
        elif registry.model_type == "deterministic_baseline":
            candidate = ModelRuntime(None, allow_baseline=settings.allow_baseline_model)
            candidate.load(source="registry_baseline")
            candidate.version = registry.version
            candidate.calibration_version = registry.calibration_version or "uncalibrated-baseline-v1"
            registry_id = str(registry.id)
        else:
            if not registry.artifact_path:
                raise RuntimeError(f"Active model {registry.version} has no artifact_path")
            candidate = ModelRuntime(Path(registry.artifact_path), allow_baseline=False)
            candidate.load(
                expected_sha256=registry.artifact_sha256,
                expected_version=registry.version,
                source="model_registry",
            )
            if candidate.horizon_hours != settings.default_horizon_hours:
                raise RuntimeError(
                    f"Active model horizon {candidate.horizon_hours} does not match "
                    f"DEFAULT_HORIZON_HOURS={settings.default_horizon_hours}"
                )
            registry_id = str(registry.id)

        changed = candidate.metadata() != self.runtime.metadata()
        self.runtime = candidate
        self.active_model_registry_id = registry_id
        self.last_model_refresh = now
        if changed:
            logger.info("Model runtime loaded", extra={"model": self.runtime.metadata()})
        return changed

    async def heartbeat(self, status: str = "RUNNING", details: dict | None = None) -> None:
        async with SessionFactory() as session:
            now = datetime.now(UTC)
            stmt = (
                insert(ServiceHeartbeat)
                .values(
                    service_name="worker",
                    instance_id=settings.worker_id,
                    last_seen_at=now,
                    status=status,
                    details=details or {},
                )
                .on_conflict_do_update(
                    index_elements=[ServiceHeartbeat.service_name, ServiceHeartbeat.instance_id],
                    set_={"last_seen_at": now, "status": status, "details": details or {}},
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def _record_job_failure(self, job_name: str, scheduled_for: datetime, exc: Exception) -> None:
        async with SessionFactory() as session, session.begin():
            job = (
                await session.execute(
                    select(JobRun)
                    .where(JobRun.job_name == job_name, JobRun.scheduled_for == scheduled_for)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            now = datetime.now(UTC)
            if job is None:
                job = JobRun(
                    job_name=job_name,
                    scheduled_for=scheduled_for,
                    started_at=now,
                    status="FAILED",
                    worker_id=settings.worker_id,
                    details={"error": str(exc)},
                    finished_at=now,
                )
                session.add(job)
            else:
                job.status = "FAILED"
                job.finished_at = now
                job.details = {"error": str(exc)}

    async def run_job(self, job_name: str, scheduled_for: datetime, coro) -> dict:
        try:
            async with (
                SessionFactory() as session,
                session.begin(),
                advisory_lock(session, job_name, scheduled_for.isoformat()) as acquired,
            ):
                if not acquired:
                    return {"skipped": "lock_not_acquired"}
                existing = (
                    await session.execute(
                        select(JobRun).where(
                            JobRun.job_name == job_name, JobRun.scheduled_for == scheduled_for
                        )
                    )
                ).scalar_one_or_none()
                if existing and existing.status == "SUCCESS":
                    return {"skipped": "already_completed"}
                now = datetime.now(UTC)
                job = existing or JobRun(
                    job_name=job_name,
                    scheduled_for=scheduled_for,
                    started_at=now,
                    status="RUNNING",
                    worker_id=settings.worker_id,
                    details={},
                )
                if existing is None:
                    session.add(job)
                else:
                    job.started_at = now
                    job.finished_at = None
                    job.status = "RUNNING"
                    job.worker_id = settings.worker_id
                result = await coro(session)
                job.status = "SUCCESS"
                job.finished_at = datetime.now(UTC)
                job.details = result or {}
                return result or {}
        except Exception as exc:
            await self._record_job_failure(job_name, scheduled_for, exc)
            logger.exception("Worker job failed", extra={"job": job_name})
            raise

    async def instrument_job(self) -> dict:
        scheduled = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)

        async def task(session):
            count = await sync_instruments(session, self.client)
            return {"instruments": count}

        return await self.run_job("instrument_sync", scheduled, task)

    def _universe_refresh_due(self, now: datetime, backfill: bool) -> bool:
        return (
            backfill
            or settings.universe_mode == "static"
            or self.last_universe_refresh is None
            or (now - self.last_universe_refresh).total_seconds() >= settings.universe_refresh_seconds
        )

    async def market_job(self, backfill: bool = False) -> dict:
        scheduled = datetime.now(UTC).replace(second=0, microsecond=0)

        async def task(session):
            now = datetime.now(UTC)
            ticker_items = await self.client.get_tickers("linear")
            selection: UniverseSelection | None = None
            previous_symbols = set(self.active_symbols)

            if self._universe_refresh_due(now, backfill):
                selection = await resolve_universe(session, ticker_items, settings, now=now)
                self.active_symbols = selection.symbols
                self.universe_summary = selection.summary()
                self.last_universe_refresh = now

            selected = set(self.active_symbols)
            tickers = await sync_tickers(
                session,
                self.client,
                selected,
                items=ticker_items,
            )

            newly_admitted = selected if backfill else selected - previous_symbols
            candles = 0
            funding = 0
            oi = 0
            if newly_admitted:
                price_types = ("last", "mark") if settings.universe_sync_mark_price else ("last",)
                candles = await sync_candles(
                    session,
                    self.client,
                    sorted(newly_admitted),
                    interval=settings.candle_interval,
                    limit=settings.initial_backfill_bars,
                    price_types=price_types,
                    request_batch_size=settings.universe_backfill_batch_size,
                )
                if settings.universe_enrich_funding_oi:
                    funding, oi = await sync_funding_and_oi(
                        session, self.client, sorted(newly_admitted)
                    )

            summary = selection.summary() if selection else self.universe_summary
            return {
                "tickers": tickers,
                "backfilled_symbols": len(newly_admitted),
                "candles": candles,
                "funding": funding,
                "open_interest": oi,
                "universe": summary,
            }

        return await self.run_job("market_sync", scheduled, task)

    async def hourly_market_close_job(self, event_time: datetime) -> dict:
        async def task(session):
            symbols = self.active_symbols
            if not symbols:
                return {"symbols": 0, "candles": 0}
            price_types = ("last", "mark") if settings.universe_sync_mark_price else ("last",)
            candles = await sync_candles(
                session,
                self.client,
                symbols,
                interval=settings.candle_interval,
                limit=3,
                price_types=price_types,
                request_batch_size=settings.universe_backfill_batch_size,
            )
            return {"symbols": len(symbols), "candles": candles}

        return await self.run_job("hourly_market_close", event_time, task)

    async def history_backfill_job(self) -> dict:
        scheduled = datetime.now(UTC).replace(second=0, microsecond=0)

        async def task(session):
            candidates = await symbols_needing_history_backfill(
                session,
                self.active_symbols,
                interval=settings.candle_interval,
                target_days=settings.history_backfill_target_days,
                limit=settings.history_backfill_symbols_per_cycle,
            )
            if not candidates:
                return {
                    "enabled": True,
                    "status": "COMPLETE",
                    "symbols_processed": 0,
                    "rows_received": 0,
                    "target_days": settings.history_backfill_target_days,
                }
            result = await sync_candle_history(
                session,
                self.client,
                candidates,
                interval=settings.candle_interval,
                target_days=settings.history_backfill_target_days,
                page_size=settings.history_backfill_page_size,
                max_pages_per_symbol=settings.history_backfill_pages_per_symbol,
            )
            return {
                "enabled": True,
                "status": "RUNNING",
                "target_days": settings.history_backfill_target_days,
                **result,
            }

        result = await self.run_job("history_backfill", scheduled, task)
        if not result.get("skipped"):
            self.history_backfill_summary = result
            self.last_history_backfill = datetime.now(UTC)
        return result

    async def account_job(self) -> dict:
        scheduled = datetime.now(UTC).replace(second=0, microsecond=0)

        async def task(session):
            return await sync_read_only_account(session, self.client, settings)

        return await self.run_job("account_sync", scheduled, task)

    async def inference_job(self, event_time: datetime) -> dict:
        async def task(session):
            published = await publish_hourly_signals(
                session,
                settings=settings,
                runtime=self.runtime,
                event_time=event_time,
                symbols=self.active_symbols,
            )
            return {
                "universe_symbols": len(self.active_symbols),
                "published": len(published),
                "signal_ids": [str(item.id) for item in published],
            }

        return await self.run_job("hourly_inference", event_time, task)

    async def catchup_inference_job(self, reason: str) -> dict:
        """Publish missing current-hour signals after a universe bootstrap/change.

        The normal hourly job is intentionally idempotent.  After switching from a
        small static universe to a dynamic one, the current hour may already be marked
        SUCCESS for the old symbols.  This separate job fills only missing natural keys
        and therefore does not duplicate existing recommendations.
        """
        now = datetime.now(UTC)
        event_time = now.replace(minute=0, second=0, microsecond=0)
        scheduled = now.replace(second=0, microsecond=0)

        async def task(session):
            published = await publish_hourly_signals(
                session,
                settings=settings,
                runtime=self.runtime,
                event_time=event_time,
                symbols=self.active_symbols,
            )
            return {
                "reason": reason,
                "event_time": event_time.isoformat(),
                "universe_symbols": len(self.active_symbols),
                "published": len(published),
                "signal_ids": [str(item.id) for item in published],
            }

        return await self.run_job("universe_catchup_inference", scheduled, task)

    async def counterfactual_outcome_job(self, event_time: datetime) -> dict:
        async def task(session):
            available_cutoff = datetime.now(UTC)
            windows = await find_ambiguous_intrabar_windows(
                session,
                market_cutoff=event_time,
                available_cutoff=available_cutoff,
                max_windows=settings.outcome_intrabar_max_windows_per_cycle,
            )
            intrabar_sync = await sync_candle_windows(
                session,
                self.client,
                windows,
                interval=settings.outcome_intrabar_interval,
                now=available_cutoff,
            )
            result = await resolve_counterfactual_outcomes(
                session,
                market_cutoff=event_time,
                available_cutoff=available_cutoff,
                intrabar_interval=settings.outcome_intrabar_interval,
                actor="worker",
            )
            return {**result, "intrabar_sync": intrabar_sync}

        return await self.run_job("counterfactual_outcomes", event_time, task)

    async def retention_job(self, event_time: datetime) -> dict:
        async def task(session):
            cutoff = datetime.now(UTC) - timedelta(hours=max(1, settings.ticker_retention_hours))
            result = await session.execute(delete(TickerSnapshot).where(TickerSnapshot.source_time < cutoff))
            return {"ticker_rows_deleted": int(result.rowcount or 0), "cutoff": cutoff.isoformat()}

        return await self.run_job("ticker_retention", event_time, task)

    async def expiry_job(self) -> None:
        async with SessionFactory() as session:
            count = await expire_old_signals(session)
            if count:
                await session.commit()

    async def run(self) -> None:
        await self.refresh_model_runtime(force=True)
        await self.heartbeat(
            "STARTING",
            {
                "model": self.runtime.metadata(),
                "model_registry_id": self.active_model_registry_id,
                "universe": self.universe_summary,
            },
        )
        try:
            await self.instrument_job()
            self.last_instrument_sync = datetime.now(UTC)
            market_result = await self.market_job(backfill=True)
            self.last_market_sync = datetime.now(UTC)
            if settings.history_backfill_enabled and self.active_symbols:
                await self.history_backfill_job()
            startup_event_time = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
            await self.counterfactual_outcome_job(startup_event_time)
            if self.active_symbols and not market_result.get("skipped"):
                await self.catchup_inference_job("startup_backfill")
            if settings.bybit_read_only_account:
                await self.account_job()
                self.last_account_sync = datetime.now(UTC)
        except Exception:
            logger.exception("Initial worker synchronization failed")

        while not self.stop_event.is_set():
            now = datetime.now(UTC)
            try:
                await self.refresh_model_runtime()
                if (
                    self.last_instrument_sync is None
                    or (now - self.last_instrument_sync).total_seconds()
                    >= settings.instrument_refresh_seconds
                ):
                    await self.instrument_job()
                    self.last_instrument_sync = now
                if (
                    self.last_market_sync is None
                    or (now - self.last_market_sync).total_seconds() >= settings.market_poll_seconds
                ):
                    market_result = await self.market_job(backfill=False)
                    self.last_market_sync = now
                    if market_result.get("backfilled_symbols", 0) > 0:
                        await self.catchup_inference_job("universe_expanded")
                if settings.history_backfill_enabled and self.active_symbols and (
                    self.last_history_backfill is None
                    or (now - self.last_history_backfill).total_seconds()
                    >= settings.history_backfill_interval_seconds
                ):
                    await self.history_backfill_job()
                if settings.bybit_read_only_account and (
                    self.last_account_sync is None
                    or (now - self.last_account_sync).total_seconds() >= settings.market_poll_seconds
                ):
                    await self.account_job()
                    self.last_account_sync = now

                event_time = now.replace(minute=0, second=0, microsecond=0)
                run_after = event_time + timedelta(seconds=settings.inference_delay_seconds)
                if now >= run_after:
                    await self.hourly_market_close_job(event_time)
                    await self.counterfactual_outcome_job(event_time)
                    await self.inference_job(event_time)
                    await self.retention_job(event_time)
                await self.expiry_job()
                await self.heartbeat(
                    "RUNNING",
                    {
                        "model": self.runtime.metadata(),
                        "model_registry_id": self.active_model_registry_id,
                        "last_market_sync": self.last_market_sync.isoformat()
                        if self.last_market_sync
                        else None,
                        "universe": self.universe_summary,
                        "history_backfill": self.history_backfill_summary,
                    },
                )
            except Exception as exc:
                logger.exception("Worker loop iteration failed")
                await self.heartbeat(
                    "DEGRADED",
                    {
                        "error": str(exc),
                        "model": self.runtime.metadata(),
                        "model_registry_id": self.active_model_registry_id,
                        "universe": self.universe_summary,
                        "history_backfill": self.history_backfill_summary,
                    },
                )
            with suppress(TimeoutError):
                await asyncio.wait_for(self.stop_event.wait(), timeout=settings.heartbeat_seconds)

        await self.heartbeat("STOPPED", {"universe": self.universe_summary})
        await self.client.close()
        await dispose_engine()


async def async_main() -> None:
    worker = Worker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.request_stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_args: loop.call_soon_threadsafe(worker.request_stop))
    await worker.run()


def run() -> None:
    run_with_compatible_event_loop(async_main())


if __name__ == "__main__":
    run()

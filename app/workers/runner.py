from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Iterable
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.asyncio_compat import run_with_compatible_event_loop
from app.bybit.client import BybitClient
from app.config import get_settings
from app.db.engine import SessionFactory, dispose_engine
from app.db.locks import advisory_lock
from app.db.models import JobRun, ModelRegistry, OrderBookSnapshot, ServiceHeartbeat, TickerSnapshot
from app.logging import configure_logging
from app.ml.artifact_store import ensure_registry_artifact_durable
from app.ml.runtime import ModelRuntime
from app.ml.runtime_selection import select_model_runtime
from app.services.drift_monitor import build_production_drift_report
from app.services.market_data import (
    symbols_needing_funding_history_backfill,
    symbols_needing_history_backfill,
    symbols_needing_open_interest_history_backfill,
    sync_candle_history,
    sync_candle_windows,
    sync_candles,
    sync_funding_and_oi,
    sync_funding_history,
    sync_instruments,
    sync_open_interest_history,
    sync_orderbooks,
    sync_read_only_account,
    sync_tickers,
)
from app.services.outcomes import find_ambiguous_intrabar_windows, resolve_counterfactual_outcomes
from app.services.signals import expire_old_signals, publish_hourly_signals
from app.services.universe import (
    UniverseSelection,
    persist_universe_selection,
    resolve_universe,
)

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


def should_retry_incomplete_coverage(
    details: dict[str, object],
    *,
    total_key: str,
    covered_keys: tuple[str, ...],
    retry_count_key: str,
    max_retries: int,
) -> bool:
    """Return true when an idempotent successful job covered only part of its scope."""

    try:
        retry_count = int(details.get(retry_count_key, 0))
        items_total = int(details.get(total_key, 0))
        items_covered = sum(int(details.get(key, 0)) for key in covered_keys)
    except (TypeError, ValueError):
        return False
    return items_total > 0 and items_covered < items_total and retry_count < max_retries


def should_retry_incomplete_inference(details: dict[str, object], *, max_retries: int) -> bool:
    """Return true when an hourly inference covered only part of its universe."""

    return should_retry_incomplete_coverage(
        details,
        total_key="symbols_total",
        covered_keys=("published", "existing_current_hour"),
        retry_count_key="inference_retry_count",
        max_retries=max_retries,
    )


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
        self.model_notice: dict[str, object] | None = None
        self.model_artifact_durability: dict[str, object] | None = None
        self.last_drift_summary: dict[str, object] | None = None
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

        durability: dict[str, object] | None = None
        async with SessionFactory() as session, session.begin():
            registry = (
                await session.execute(
                    select(ModelRegistry)
                    .where(ModelRegistry.active.is_(True))
                    .order_by(ModelRegistry.updated_at.desc())
                    .limit(1)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if registry is not None and settings.active_model_path is None:
                try:
                    durability = await ensure_registry_artifact_durable(
                        session,
                        registry,
                        model_dir=settings.model_dir,
                        actor=settings.worker_id,
                    )
                except RuntimeError as exc:
                    durability = {
                        "schema": "postgresql-immutable-model-artifact-v1",
                        "available": False,
                        "action": "invalid",
                        "reason": "artifact_durability_check_failed",
                        "error": str(exc),
                    }
                    logger.exception(
                        "Active model artifact durability verification failed",
                        extra={"model_artifact_durability": durability},
                    )

        selection = select_model_runtime(
            registry=registry,
            active_model_path=settings.active_model_path,
            allow_baseline_model=settings.allow_baseline_model,
            app_mode=settings.app_mode,
            default_horizon_hours=settings.default_horizon_hours,
        )
        changed = (
            selection.runtime.metadata() != self.runtime.metadata()
            or selection.notice != self.model_notice
            or selection.registry_id != self.active_model_registry_id
        )
        self.runtime = selection.runtime
        self.active_model_registry_id = selection.registry_id
        self.model_notice = selection.notice
        self.model_artifact_durability = durability
        self.last_model_refresh = now
        if changed and self.model_notice is not None:
            logger.warning(
                "Model runtime is using deterministic baseline",
                extra={"model": self.runtime.metadata(), "model_notice": self.model_notice},
            )
        elif changed:
            logger.info("Model runtime loaded", extra={"model": self.runtime.metadata()})
        return changed

    def model_heartbeat_status(self) -> str:
        drift_status = (self.last_drift_summary or {}).get("status")
        return (
            "DEGRADED"
            if self.model_notice is not None or drift_status in {"CRITICAL", "BLOCKED"}
            else "RUNNING"
        )

    def heartbeat_details(self, **extra: object) -> dict[str, object]:
        return {
            "model": self.runtime.metadata(),
            "model_registry_id": self.active_model_registry_id,
            "model_notice": self.model_notice,
            "model_artifact_durability": getattr(self, "model_artifact_durability", None),
            "production_drift": self.last_drift_summary,
            "universe": self.universe_summary,
            **extra,
        }

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

    async def run_job(
        self,
        job_name: str,
        scheduled_for: datetime,
        coro,
        *,
        retry_incomplete_success: bool = False,
        retry_after_seconds: int = 60,
        max_inference_retries: int = 5,
        retry_total_key: str = "symbols_total",
        retry_covered_keys: tuple[str, ...] = ("published", "existing_current_hour"),
        retry_count_key: str = "inference_retry_count",
    ) -> dict:
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
                retry_count = 0
                is_incomplete_retry = False
                if existing and existing.status == "SUCCESS":
                    details = existing.details or {}
                    try:
                        retry_count = int(details.get(retry_count_key, 0))
                    except (TypeError, ValueError):
                        retry_count = 0
                    incomplete_retryable = bool(
                        retry_incomplete_success
                        and should_retry_incomplete_coverage(
                            details,
                            total_key=retry_total_key,
                            covered_keys=retry_covered_keys,
                            retry_count_key=retry_count_key,
                            max_retries=max_inference_retries,
                        )
                    )
                    cooldown_elapsed = bool(
                        existing.finished_at
                        and (datetime.now(UTC) - existing.finished_at).total_seconds() >= retry_after_seconds
                    )
                    if not (incomplete_retryable and cooldown_elapsed):
                        return {"skipped": "already_completed", "previous_details": details}
                    is_incomplete_retry = True
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
                if is_incomplete_retry:
                    result = dict(result or {})
                    result[retry_count_key] = retry_count + 1
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

    async def _refresh_tickers_for_symbols(
        self,
        session: AsyncSession,
        symbols: Iterable[str],
        *,
        purpose: str,
    ) -> dict[str, object]:
        requested_symbols = tuple(
            dict.fromkeys(
                str(symbol).strip().upper()
                for symbol in symbols
                if str(symbol).strip()
            )
        )
        if not requested_symbols:
            return {
                "purpose": purpose,
                "requested": 0,
                "payload_items": 0,
                "payload_symbols": 0,
                "stored": 0,
                "missing_from_payload": [],
                "received_at": None,
            }

        items = await self.client.get_tickers("linear")
        received_at = datetime.now(UTC)
        requested_set = set(requested_symbols)
        payload_symbols = {
            str(item.get("symbol") or "").strip().upper()
            for item in items
            if str(item.get("symbol") or "").strip().upper() in requested_set
        }
        stored = await sync_tickers(
            session,
            self.client,
            requested_set,
            items=items,
        )
        details: dict[str, object] = {
            "purpose": purpose,
            "requested": len(requested_symbols),
            "payload_items": len(items),
            "payload_symbols": len(payload_symbols),
            "stored": int(stored),
            "missing_from_payload": sorted(requested_set - payload_symbols)[:25],
            "received_at": received_at.isoformat(),
        }
        if stored <= 0:
            raise RuntimeError(f"{purpose} ticker refresh stored no active symbols")
        if stored < len(requested_symbols):
            logger.warning(
                "Ticker refresh stored only part of the active universe",
                extra={"ticker_refresh": details},
            )
        return details

    async def market_job(self, backfill: bool = False) -> dict:
        scheduled = datetime.now(UTC).replace(second=0, microsecond=0)

        async def task(session):
            now = datetime.now(UTC)
            selection: UniverseSelection | None = None
            previous_symbols = set(self.active_symbols)
            selected_symbols = self.active_symbols

            if self._universe_refresh_due(now, backfill):
                universe_ticker_items = await self.client.get_tickers("linear")
                selection = await resolve_universe(session, universe_ticker_items, settings, now=now)
                await persist_universe_selection(session, selection)
                selected_symbols = selection.symbols

            selected = set(selected_symbols)
            orderbooks = await sync_orderbooks(
                session,
                self.client,
                selected,
                depth=settings.orderbook_depth_levels,
            )

            newly_admitted = selected if backfill else selected - previous_symbols
            candles = 0
            funding = 0
            oi = 0
            if newly_admitted:
                price_types = ("last", "mark", "index") if settings.universe_sync_mark_price else ("last",)
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
                    funding, oi = await sync_funding_and_oi(session, self.client, sorted(newly_admitted))

            ticker_refresh = await self._refresh_tickers_for_symbols(
                session,
                selected,
                purpose="market_sync",
            )
            summary = selection.summary() if selection else self.universe_summary
            return {
                "tickers": ticker_refresh["stored"],
                "ticker_refresh": ticker_refresh,
                "orderbooks": orderbooks,
                "backfilled_symbols": len(newly_admitted),
                "candles": candles,
                "funding": funding,
                "open_interest": oi,
                "universe": summary,
            }

        result = await self.run_job("market_sync", scheduled, task)
        committed = result.get("previous_details") if result.get("skipped") == "already_completed" else result
        summary = committed.get("universe") if isinstance(committed, dict) else None
        if isinstance(summary, dict):
            symbols = summary.get("selected_symbols")
            if isinstance(symbols, list) and all(isinstance(symbol, str) for symbol in symbols):
                self.active_symbols = tuple(symbols)
                self.universe_summary = summary
            observed_at = summary.get("observed_at")
            if isinstance(observed_at, str):
                try:
                    self.last_universe_refresh = datetime.fromisoformat(observed_at)
                except ValueError:
                    logger.warning("Invalid persisted universe observed_at", extra={"value": observed_at})
        return result

    async def hourly_market_close_job(self, event_time: datetime) -> dict:
        async def task(session):
            symbols = self.active_symbols
            if not symbols:
                return {
                    "symbols": 0,
                    "candles": 0,
                    "symbols_total": 0,
                    "symbols_covered": 0,
                }
            price_types = ("last", "mark", "index") if settings.universe_sync_mark_price else ("last",)
            diagnostics: dict[str, object] = {}
            candles = await sync_candles(
                session,
                self.client,
                symbols,
                interval=settings.candle_interval,
                limit=3,
                price_types=price_types,
                request_batch_size=settings.universe_backfill_batch_size,
                required_close_time=event_time,
                diagnostics=diagnostics,
            )
            funding = 0
            open_interest = 0
            if settings.universe_enrich_funding_oi:
                funding, open_interest = await sync_funding_and_oi(
                    session, self.client, symbols
                )
            return {
                "symbols": len(symbols),
                "candles": candles,
                "funding": funding,
                "open_interest": open_interest,
                **diagnostics,
            }

        return await self.run_job(
            "hourly_market_close",
            event_time,
            task,
            retry_incomplete_success=True,
            retry_after_seconds=max(30, settings.market_poll_seconds),
            max_inference_retries=5,
            retry_total_key="symbols_total",
            retry_covered_keys=("symbols_covered",),
            retry_count_key="candle_sync_retry_count",
        )

    async def history_backfill_job(self) -> dict:
        scheduled = datetime.now(UTC).replace(second=0, microsecond=0)

        async def task(session):
            candle_candidates = await symbols_needing_history_backfill(
                session,
                self.active_symbols,
                interval=settings.candle_interval,
                target_days=settings.history_backfill_target_days,
                limit=settings.history_backfill_symbols_per_cycle,
                price_type="last",
            )
            mark_candidates = await symbols_needing_history_backfill(
                session,
                self.active_symbols,
                interval=settings.candle_interval,
                target_days=settings.history_backfill_target_days,
                limit=settings.history_backfill_symbols_per_cycle,
                price_type="mark",
            )
            index_candidates = await symbols_needing_history_backfill(
                session,
                self.active_symbols,
                interval=settings.candle_interval,
                target_days=settings.history_backfill_target_days,
                limit=settings.history_backfill_symbols_per_cycle,
                price_type="index",
            )
            open_interest_candidates = await symbols_needing_open_interest_history_backfill(
                session,
                self.active_symbols,
                target_days=settings.history_backfill_target_days,
                limit=settings.history_backfill_symbols_per_cycle,
            )
            funding_candidates = await symbols_needing_funding_history_backfill(
                session,
                self.active_symbols,
                target_days=settings.history_backfill_target_days,
                limit=settings.history_backfill_symbols_per_cycle,
            )
            if not any((candle_candidates, mark_candidates, index_candidates, open_interest_candidates, funding_candidates)):
                return {
                    "enabled": True,
                    "status": "COMPLETE",
                    "symbols_processed": 0,
                    "rows_received": 0,
                    "candle_history": {"symbols_processed": 0, "rows_received": 0},
                    "mark_price_history": {"symbols_processed": 0, "rows_received": 0},
                    "index_price_history": {"symbols_processed": 0, "rows_received": 0},
                    "open_interest_history": {"symbols_processed": 0, "rows_received": 0},
                    "funding_history": {"symbols_processed": 0, "rows_received": 0},
                    "target_days": settings.history_backfill_target_days,
                }
            candle_result = (
                await sync_candle_history(
                    session,
                    self.client,
                    candle_candidates,
                    interval=settings.candle_interval,
                    target_days=settings.history_backfill_target_days,
                    page_size=settings.history_backfill_page_size,
                    max_pages_per_symbol=settings.history_backfill_pages_per_symbol,
                    price_type="last",
                )
                if candle_candidates
                else {"symbols_processed": 0, "rows_received": 0, "progress": []}
            )
            mark_result = (
                await sync_candle_history(
                    session,
                    self.client,
                    mark_candidates,
                    interval=settings.candle_interval,
                    target_days=settings.history_backfill_target_days,
                    page_size=settings.history_backfill_page_size,
                    max_pages_per_symbol=settings.history_backfill_pages_per_symbol,
                    price_type="mark",
                )
                if mark_candidates
                else {"symbols_processed": 0, "rows_received": 0, "progress": []}
            )
            index_result = (
                await sync_candle_history(
                    session,
                    self.client,
                    index_candidates,
                    interval=settings.candle_interval,
                    target_days=settings.history_backfill_target_days,
                    page_size=settings.history_backfill_page_size,
                    max_pages_per_symbol=settings.history_backfill_pages_per_symbol,
                    price_type="index",
                )
                if index_candidates
                else {"symbols_processed": 0, "rows_received": 0, "progress": []}
            )
            open_interest_result = (
                await sync_open_interest_history(
                    session,
                    self.client,
                    open_interest_candidates,
                    target_days=settings.history_backfill_target_days,
                    page_size=min(settings.history_backfill_page_size, 200),
                    max_pages_per_symbol=settings.history_backfill_pages_per_symbol,
                )
                if open_interest_candidates
                else {"symbols_processed": 0, "rows_received": 0, "progress": []}
            )
            funding_result = (
                await sync_funding_history(
                    session,
                    self.client,
                    funding_candidates,
                    target_days=settings.history_backfill_target_days,
                    page_size=min(settings.history_backfill_page_size, 200),
                    max_pages_per_symbol=settings.history_backfill_pages_per_symbol,
                )
                if funding_candidates
                else {"symbols_processed": 0, "rows_received": 0, "progress": []}
            )
            return {
                "enabled": True,
                "status": "RUNNING",
                "target_days": settings.history_backfill_target_days,
                "symbols_processed": int(candle_result["symbols_processed"])
                + int(mark_result["symbols_processed"])
                + int(index_result["symbols_processed"])
                + int(open_interest_result["symbols_processed"])
                + int(funding_result["symbols_processed"]),
                "rows_received": int(candle_result["rows_received"])
                + int(mark_result["rows_received"])
                + int(index_result["rows_received"])
                + int(open_interest_result["rows_received"])
                + int(funding_result["rows_received"]),
                "candle_history": candle_result,
                "mark_price_history": mark_result,
                "index_price_history": index_result,
                "open_interest_history": open_interest_result,
                "funding_history": funding_result,
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

    async def _refresh_execution_inputs(
        self,
        session: AsyncSession,
        symbols: Iterable[str],
        *,
        purpose: str,
    ) -> dict[str, object]:
        """Refresh every mutable snapshot required by execution-plan construction.

        Market signals are account-independent, but the UI presents profile-specific
        execution plans created in the same publication transaction.  Refreshing only
        tickers allowed a long startup/backfill cycle to publish a whole universe of
        plans against missing capital or stale order books.  Keep the strict freshness
        limits and move all required reads immediately in front of publication.
        """

        account_refresh: dict[str, object] = {"enabled": False}
        if settings.bybit_read_only_account:
            account_refresh = await sync_read_only_account(session, self.client, settings)

        orderbook_refresh = await sync_orderbooks(
            session,
            self.client,
            symbols,
            depth=settings.orderbook_depth_levels,
        )
        requested = int(orderbook_refresh.get("requested", 0) or 0)
        covered = int(orderbook_refresh.get("stored", 0) or 0) + int(
            orderbook_refresh.get("duplicates", 0) or 0
        )
        if requested > 0 and covered <= 0:
            raise RuntimeError(f"{purpose} orderbook refresh stored no active symbols")

        ticker_refresh = await self._refresh_tickers_for_symbols(
            session,
            symbols,
            purpose=purpose,
        )
        return {
            "account": account_refresh,
            "orderbooks": orderbook_refresh,
            "tickers": ticker_refresh,
        }

    async def inference_job(self, event_time: datetime) -> dict:
        async def task(session):
            execution_input_refresh = await self._refresh_execution_inputs(
                session,
                self.active_symbols,
                purpose="hourly_inference",
            )
            decision_ticker_refresh = execution_input_refresh["tickers"]
            diagnostics: dict[str, object] = {}
            published = await publish_hourly_signals(
                session,
                settings=settings,
                runtime=self.runtime,
                event_time=event_time,
                symbols=self.active_symbols,
                diagnostics=diagnostics,
            )
            return {
                "universe_symbols": len(self.active_symbols),
                "published": len(published),
                "signal_ids": [str(item.id) for item in published],
                "execution_input_refresh": execution_input_refresh,
                "decision_ticker_refresh": decision_ticker_refresh,
                **diagnostics,
            }

        result = await self.run_job(
            "hourly_inference",
            event_time,
            task,
            retry_incomplete_success=True,
            retry_after_seconds=max(30, settings.market_poll_seconds),
            max_inference_retries=5,
        )
        if settings.bybit_read_only_account and not result.get("skipped"):
            self.last_account_sync = datetime.now(UTC)
        return result

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
            execution_input_refresh = await self._refresh_execution_inputs(
                session,
                self.active_symbols,
                purpose="universe_catchup_inference",
            )
            decision_ticker_refresh = execution_input_refresh["tickers"]
            diagnostics: dict[str, object] = {}
            published = await publish_hourly_signals(
                session,
                settings=settings,
                runtime=self.runtime,
                event_time=event_time,
                symbols=self.active_symbols,
                diagnostics=diagnostics,
            )
            return {
                "reason": reason,
                "event_time": event_time.isoformat(),
                "universe_symbols": len(self.active_symbols),
                "published": len(published),
                "signal_ids": [str(item.id) for item in published],
                "execution_input_refresh": execution_input_refresh,
                "decision_ticker_refresh": decision_ticker_refresh,
                **diagnostics,
            }

        result = await self.run_job("universe_catchup_inference", scheduled, task)
        if settings.bybit_read_only_account and not result.get("skipped"):
            self.last_account_sync = datetime.now(UTC)
        return result

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
            )
            resolution_cutoff = datetime.now(UTC)
            result = await resolve_counterfactual_outcomes(
                session,
                market_cutoff=event_time,
                available_cutoff=resolution_cutoff,
                intrabar_interval=settings.outcome_intrabar_interval,
                actor="worker",
            )
            return {**result, "intrabar_sync": intrabar_sync}

        return await self.run_job("counterfactual_outcomes", event_time, task)

    async def drift_monitor_job(self, event_time: datetime) -> dict:
        async def task(session):
            return await build_production_drift_report(session, settings)

        result = await self.run_job("production_drift_monitor", event_time, task)
        if result.get("skipped") == "already_completed":
            previous = result.get("previous_details")
            if isinstance(previous, dict):
                self.last_drift_summary = previous
        elif not result.get("skipped"):
            self.last_drift_summary = result
        return result

    async def hourly_decision_cycle(self, event_time: datetime) -> None:
        """Run the hourly safety checks before publishing the new decision set."""

        await self.hourly_market_close_job(event_time)
        await self.counterfactual_outcome_job(event_time)
        if settings.drift_monitor_enabled:
            await self.drift_monitor_job(event_time)
        await self.inference_job(event_time)
        await self.retention_job(event_time)

    async def retention_job(self, event_time: datetime) -> dict:
        async def task(session):
            now = datetime.now(UTC)
            ticker_cutoff = now - timedelta(hours=max(1, settings.ticker_retention_hours))
            orderbook_cutoff = now - timedelta(hours=max(1, settings.orderbook_retention_hours))
            ticker_result = await session.execute(
                delete(TickerSnapshot).where(TickerSnapshot.source_time < ticker_cutoff)
            )
            orderbook_result = await session.execute(
                delete(OrderBookSnapshot).where(OrderBookSnapshot.source_time < orderbook_cutoff)
            )
            return {
                "ticker_rows_deleted": int(ticker_result.rowcount or 0),
                "orderbook_rows_deleted": int(orderbook_result.rowcount or 0),
                "ticker_cutoff": ticker_cutoff.isoformat(),
                "orderbook_cutoff": orderbook_cutoff.isoformat(),
            }

        return await self.run_job("market_snapshot_retention", event_time, task)

    async def expiry_job(self) -> None:
        async with SessionFactory() as session:
            count = await expire_old_signals(session)
            if count:
                await session.commit()

    async def run(self) -> None:
        await self.refresh_model_runtime(force=True)
        await self.heartbeat("STARTING", self.heartbeat_details())
        try:
            await self.instrument_job()
            self.last_instrument_sync = datetime.now(UTC)
            market_result = await self.market_job(backfill=True)
            self.last_market_sync = datetime.now(UTC)
            if settings.history_backfill_enabled and self.active_symbols:
                await self.history_backfill_job()
            startup_event_time = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
            await self.counterfactual_outcome_job(startup_event_time)
            if settings.drift_monitor_enabled:
                await self.drift_monitor_job(startup_event_time)
            if self.active_symbols and not market_result.get("skipped"):
                await self.catchup_inference_job("startup_backfill")
            if settings.bybit_read_only_account and self.last_account_sync is None:
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
                if (
                    settings.history_backfill_enabled
                    and self.active_symbols
                    and (
                        self.last_history_backfill is None
                        or (now - self.last_history_backfill).total_seconds()
                        >= settings.history_backfill_interval_seconds
                    )
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
                    await self.hourly_decision_cycle(event_time)
                await self.expiry_job()
                await self.heartbeat(
                    self.model_heartbeat_status(),
                    self.heartbeat_details(
                        last_market_sync=self.last_market_sync.isoformat() if self.last_market_sync else None,
                        history_backfill=self.history_backfill_summary,
                    ),
                )
            except Exception as exc:
                logger.exception("Worker loop iteration failed")
                await self.heartbeat(
                    "DEGRADED",
                    self.heartbeat_details(
                        error=str(exc),
                        history_backfill=self.history_backfill_summary,
                    ),
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

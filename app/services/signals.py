from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

import pandas as pd
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.locks import acquire_advisory_xact_lock
from app.db.models import (
    Candle,
    CapitalProfile,
    ExecutionPlan,
    FundingRate,
    InstrumentSpecHistory,
    MarketSignal,
    OpenInterest,
    TickerSnapshot,
)
from app.ml.context import (
    MARKET_CONTEXT_COMPLETE_COLUMN,
    MARKET_CONTEXT_FEATURE_NAMES,
    build_market_context_frame,
)
from app.ml.drift import directional_prediction_snapshot
from app.ml.features import BASELINE_FEATURE_SCHEMA_VERSION, latest_feature_snapshot
from app.ml.runtime import ModelRuntime, Prediction
from app.ml.training import (
    DEFAULT_STOP_ATR_MULTIPLIER,
    DEFAULT_TP_ATR_MULTIPLIER,
    POLICY_EXPECTED_FUNDING_SOURCE,
)
from app.risk.math import (
    CostScenario,
    net_rr_and_ev,
    positive_finite_decimal,
    projected_funding_rate,
)
from app.services.attrition import INFERENCE_ATTRITION_SCHEMA
from app.services.audit import append_audit_event, publish_outbox
from app.services.drift_monitor import production_drift_publication_guard
from app.services.execution import create_execution_plan, validated_bid_ask
from app.services.market_snapshots import latest_available_ticker

logger = logging.getLogger(__name__)

PLAN_STATUSES_PRESERVED_ON_SIGNAL_REPLACEMENT = {
    "ACCEPTED",
    "ENTERED",
    "PARTIAL",
    "CLOSED",
    "REJECTED",
    "EXPIRED",
}


def decimal(value: float | str | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(frozen=True)
class SignalScenarioEconomics:
    prediction: Prediction
    reference: Decimal
    entry_low: Decimal
    entry_high: Decimal
    stop: Decimal
    take_profit_1: Decimal
    take_profit_2: Decimal | None
    net_rr: Decimal
    ev_r: Decimal
    downside: Decimal
    upside: Decimal
    timeout_return_rate: Decimal


def select_cost_aware_scenario(
    predictions: Iterable[Prediction],
    *,
    bid_price: Decimal | None,
    ask_price: Decimal | None,
    last_price: Decimal,
    atr_pct: Decimal,
    costs: CostScenario,
    stop_atr_multiplier: float = DEFAULT_STOP_ATR_MULTIPLIER,
    tp_atr_multiplier: float = DEFAULT_TP_ATR_MULTIPLIER,
    tick_size: Decimal | None = None,
    timeout_return_rate: Decimal = Decimal("-0.002"),
) -> SignalScenarioEconomics:
    """Select LONG/SHORT by the promotion-bound market-signal economics.

    The candidate promotion evidence has no historical point-in-time funding
    forecast.  Therefore expected funding must remain zero in this capital-
    independent selector.  Fresh projected funding is applied conservatively by
    the execution-plan and acceptance layers, where it can block but never flip
    the promoted market direction.
    """

    funding_rate = decimal(costs.funding_rate)
    if not funding_rate.is_finite() or funding_rate != 0:
        raise ValueError(
            "Market signal expected funding must be zero; apply current funding in the execution plan"
        )

    prediction_rows = list(predictions)
    directions = [prediction.direction for prediction in prediction_rows]
    if len(prediction_rows) != 2 or set(directions) != {"LONG", "SHORT"}:
        raise ValueError("Exactly one LONG and one SHORT directional prediction are required")

    bid, ask = validated_bid_ask(bid_price=bid_price, ask_price=ask_price)
    positive_finite_decimal(last_price, "last_price")
    atr_pct = positive_finite_decimal(atr_pct, "atr_pct")
    stop_multiplier = decimal(stop_atr_multiplier)
    tp_multiplier = decimal(tp_atr_multiplier)
    if (
        not stop_multiplier.is_finite()
        or not tp_multiplier.is_finite()
        or stop_multiplier <= 0
        or tp_multiplier <= 0
    ):
        raise ValueError("ATR barrier multipliers must be positive and finite")

    price_step = (
        positive_finite_decimal(tick_size, "tick_size") if tick_size is not None else None
    )

    def floor_to_tick(value: Decimal) -> Decimal:
        if price_step is None:
            return value
        return (value / price_step).to_integral_value(rounding=ROUND_FLOOR) * price_step

    def ceil_to_tick(value: Decimal) -> Decimal:
        if price_step is None:
            return value
        return (value / price_step).to_integral_value(rounding=ROUND_CEILING) * price_step

    candidates: list[SignalScenarioEconomics] = []
    for prediction in prediction_rows:
        reference = ask if prediction.direction == "LONG" else bid
        atr = reference * atr_pct
        zone_half = atr * Decimal("0.12")
        stop_distance = atr * stop_multiplier
        tp_distance = atr * tp_multiplier

        if price_step is not None and reference % price_step != 0:
            raise ValueError("Executable bid/ask reference is not aligned to tick_size")

        # The entry band is an admissible interval, not a risk barrier.  Keep only
        # executable ticks inside the continuous policy band; outward rounding would
        # silently approve fills that the model/policy never evaluated.
        entry_low = ceil_to_tick(reference - zone_half)
        entry_high = floor_to_tick(reference + zone_half)
        if entry_low > entry_high:
            raise ValueError("No executable tick lies inside the entry policy band")
        if prediction.direction == "LONG":
            # Conservative exchange rounding: widen the stop and pull the target
            # toward entry, so discrete ticks cannot understate loss or overstate reward.
            stop = floor_to_tick(reference - stop_distance)
            tp1 = floor_to_tick(reference + tp_distance)
        else:
            stop = ceil_to_tick(reference + stop_distance)
            tp1 = ceil_to_tick(reference - tp_distance)

        scenario_timeout_return_rate = timeout_return_rate
        if prediction.timeout_return_r is not None:
            timeout_return_r = decimal(prediction.timeout_return_r)
            if not timeout_return_r.is_finite():
                raise ValueError("Conditional TIMEOUT return R must be finite")
            gross_downside_rate = abs(reference - stop) / reference
            gross_upside_rate = abs(tp1 - reference) / reference
            if gross_downside_rate <= 0:
                raise ValueError("Conditional TIMEOUT return requires positive stop distance")
            support_upper = gross_upside_rate / gross_downside_rate
            bounded_timeout_return_r = min(
                max(timeout_return_r, Decimal("-1")),
                support_upper,
            )
            scenario_timeout_return_rate = (
                bounded_timeout_return_r * gross_downside_rate
            )

        net_rr, ev_r, downside, upside = net_rr_and_ev(
            entry=reference,
            stop=stop,
            take_profit=tp1,
            direction=prediction.direction,
            costs=costs,
            p_tp=prediction.p_tp,
            p_sl=prediction.p_sl,
            p_timeout=prediction.p_timeout,
            timeout_return_rate=scenario_timeout_return_rate,
        )
        candidates.append(
            SignalScenarioEconomics(
                prediction=prediction,
                reference=reference,
                entry_low=entry_low,
                entry_high=entry_high,
                stop=stop,
                take_profit_1=tp1,
                take_profit_2=None,
                net_rr=net_rr,
                ev_r=ev_r,
                downside=downside,
                upside=upside,
                timeout_return_rate=scenario_timeout_return_rate,
            )
        )

    if not candidates:
        raise ValueError("At least one directional prediction is required")
    return max(
        candidates,
        key=lambda item: (
            item.ev_r,
            item.net_rr,
            item.prediction.direction == "LONG",
        ),
    )


async def _candles_frame(
    session: AsyncSession,
    symbol: str,
    *,
    market_cutoff: datetime,
    available_cutoff: datetime,
    limit: int = 300,
) -> pd.DataFrame:
    rows = (
        (
            await session.execute(
                select(Candle)
                .where(
                    Candle.symbol == symbol,
                    Candle.interval == "60",
                    Candle.price_type == "last",
                    Candle.confirmed.is_(True),
                    Candle.close_time <= market_cutoff,
                    Candle.available_at <= available_cutoff,
                )
                .order_by(desc(Candle.open_time))
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    records = [
        {
            "symbol": row.symbol,
            "open_time": row.open_time,
            "close_time": row.close_time,
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": float(row.volume),
            "turnover": float(row.turnover),
        }
        for row in reversed(rows)
    ]
    return pd.DataFrame.from_records(records)


async def _market_context_values(
    session: AsyncSession,
    *,
    symbol: str,
    candles: pd.DataFrame,
    event_time: datetime,
    available_cutoff: datetime,
    funding_interval_minutes: int | None,
) -> dict[str, float]:
    if candles.empty or funding_interval_minutes is None or funding_interval_minutes <= 0:
        raise ValueError("Market context requires candles and a positive funding interval")
    history_start = event_time - timedelta(hours=24)

    async def candle_frame(price_type: str) -> pd.DataFrame:
        rows = (
            (
                await session.execute(
                    select(Candle)
                    .where(
                        Candle.symbol == symbol,
                        Candle.interval == "60",
                        Candle.price_type == price_type,
                        Candle.confirmed.is_(True),
                        Candle.close_time >= history_start,
                        Candle.close_time <= event_time,
                        Candle.available_at <= available_cutoff,
                    )
                    .order_by(Candle.open_time)
                )
            )
            .scalars()
            .all()
        )
        return pd.DataFrame.from_records(
            [
                {
                    "symbol": row.symbol,
                    "open_time": row.open_time,
                    "close_time": row.close_time,
                    "open": float(row.open),
                    "high": float(row.high),
                    "low": float(row.low),
                    "close": float(row.close),
                }
                for row in rows
            ]
        )

    mark_candles = await candle_frame("mark")
    index_candles = await candle_frame("index")
    oi_rows = (
        (
            await session.execute(
                select(OpenInterest)
                .where(
                    OpenInterest.symbol == symbol,
                    OpenInterest.interval == "1h",
                    OpenInterest.event_time >= history_start,
                    OpenInterest.event_time <= event_time,
                    OpenInterest.available_at <= available_cutoff,
                )
                .order_by(OpenInterest.event_time)
            )
        )
        .scalars()
        .all()
    )
    funding_start = event_time - timedelta(minutes=funding_interval_minutes)
    funding_rows = (
        (
            await session.execute(
                select(FundingRate)
                .where(
                    FundingRate.symbol == symbol,
                    FundingRate.funding_time >= funding_start,
                    FundingRate.funding_time <= event_time,
                    FundingRate.available_at <= available_cutoff,
                )
                .order_by(FundingRate.funding_time)
            )
        )
        .scalars()
        .all()
    )
    open_interest = pd.DataFrame.from_records(
        [
            {
                "symbol": row.symbol,
                "event_time": row.event_time,
                "available_at": row.available_at,
                "value": float(row.value),
            }
            for row in oi_rows
        ]
    )
    funding = pd.DataFrame.from_records(
        [
            {
                "symbol": row.symbol,
                "funding_time": row.funding_time,
                "available_at": row.available_at,
                "rate": float(row.rate),
            }
            for row in funding_rows
        ]
    )
    context = build_market_context_frame(
        candles[candles["close_time"] >= history_start],
        mark_candles=mark_candles,
        index_candles=index_candles,
        open_interest=open_interest,
        funding_history=funding,
        funding_interval_minutes={symbol: funding_interval_minutes},
    )
    latest = context[context["decision_time"].eq(pd.Timestamp(event_time))]
    if len(latest) != 1 or not bool(latest.iloc[0][MARKET_CONTEXT_COMPLETE_COLUMN]):
        raise ValueError("Point-in-time market context is incomplete at the decision boundary")
    return {name: float(latest.iloc[0][name]) for name in MARKET_CONTEXT_FEATURE_NAMES}


async def _latest_ticker(
    session: AsyncSession,
    symbol: str,
    *,
    cutoff: datetime,
) -> TickerSnapshot | None:
    return await latest_available_ticker(session, symbol, cutoff=cutoff)


async def _latest_spec(
    session: AsyncSession,
    symbol: str,
    *,
    available_cutoff: datetime,
) -> InstrumentSpecHistory | None:
    return (
        await session.execute(
            select(InstrumentSpecHistory)
            .where(
                InstrumentSpecHistory.symbol == symbol,
                InstrumentSpecHistory.valid_from <= available_cutoff,
                InstrumentSpecHistory.received_at <= available_cutoff,
            )
            .order_by(desc(InstrumentSpecHistory.valid_from))
            .limit(1)
        )
    ).scalar_one_or_none()


def _spread_bps(ticker: TickerSnapshot) -> float | None:
    try:
        bid, ask = validated_bid_ask(
            bid_price=ticker.bid_price,
            ask_price=ticker.ask_price,
        )
    except ValueError:
        return None
    mid = (bid + ask) / Decimal("2")
    return float((ask - bid) / mid * Decimal("10000"))


async def expire_old_signals(session: AsyncSession) -> int:
    now = datetime.now(UTC)
    result = await session.execute(
        update(MarketSignal)
        .where(MarketSignal.status == "PUBLISHED", MarketSignal.expires_at <= now)
        .values(status="EXPIRED", updated_at=now)
    )
    return int(result.rowcount or 0)


async def supersede_published_signals(
    session: AsyncSession,
    *,
    symbol: str,
    replacement_natural_key: str,
) -> list[MarketSignal]:
    """Retire older visible recommendations before publishing a replacement.

    A signal can live longer than the one-hour inference cadence.  Without an
    explicit replacement step, two consecutive hourly signals for the same
    symbol remain ``PUBLISHED`` at the same time and both are rendered by the
    operator UI.  The row lock and database uniqueness constraint make the
    replacement atomic inside the inference transaction.

    Accepted/entered plans are preserved because they belong to the trade
    lifecycle.  All still-pending plans attached to the retired recommendation
    become ``SUPERSEDED`` and can no longer be accepted from a stale browser
    dialog.
    """

    previous = (
        (
            await session.execute(
                select(MarketSignal)
                .where(MarketSignal.symbol == symbol, MarketSignal.status == "PUBLISHED")
                .order_by(desc(MarketSignal.publish_time), desc(MarketSignal.event_time))
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if not previous:
        return []

    now = datetime.now(UTC)
    previous_ids = [item.id for item in previous]
    for item in previous:
        item.status = "SUPERSEDED"
        item.invalidation_reason = f"Заменено более свежей рекомендацией {replacement_natural_key}"
        item.updated_at = now

    await session.execute(
        update(ExecutionPlan)
        .where(
            ExecutionPlan.signal_id.in_(previous_ids),
            ExecutionPlan.status.not_in(PLAN_STATUSES_PRESERVED_ON_SIGNAL_REPLACEMENT),
        )
        .values(status="SUPERSEDED", updated_at=now)
    )
    # Flush the retirement before inserting the new row.  This is required by
    # the partial unique index that permits only one PUBLISHED signal per symbol.
    await session.flush()
    return previous


async def publish_hourly_signals(
    session: AsyncSession,
    *,
    settings: Settings,
    runtime: ModelRuntime,
    event_time: datetime | None = None,
    symbols: Iterable[str] | None = None,
    diagnostics: dict[str, object] | None = None,
) -> list[MarketSignal]:
    now = datetime.now(UTC)
    event_time = event_time or now.replace(minute=0, second=0, microsecond=0)
    published: list[MarketSignal] = []
    selected_symbols = list(dict.fromkeys(symbols if symbols is not None else settings.symbols))

    def count(reason: str, amount: int = 1) -> None:
        if diagnostics is None:
            return
        skip_counts = diagnostics.setdefault("skip_counts", {})
        assert isinstance(skip_counts, dict)
        skip_counts[reason] = int(skip_counts.get(reason, 0)) + amount

    def record_symbol_outcome(
        symbol: str,
        *,
        terminal_state: str,
        reason_code: str,
        signal_id: str | None = None,
    ) -> None:
        if diagnostics is None:
            return
        if terminal_state == "SKIPPED":
            count(reason_code)
        outcomes = diagnostics.setdefault("symbol_outcomes", [])
        assert isinstance(outcomes, list)
        outcomes.append(
            {
                "symbol": symbol,
                "event_time": event_time.isoformat(),
                "terminal_state": terminal_state,
                "reason_code": reason_code,
                "signal_id": signal_id,
            }
        )

    if diagnostics is not None:
        diagnostics.update(
            {
                "event_time": event_time.isoformat(),
                "availability_cutoff": now.isoformat(),
                "symbols_total": len(selected_symbols),
                "profiles_total": 0,
                "skip_counts": {},
                "existing_current_hour": 0,
                "published": 0,
                "plan_status_counts": {},
                "attrition_schema": INFERENCE_ATTRITION_SCHEMA,
                "symbol_outcomes": [],
                "plan_outcomes": [],
            }
        )

    runtime_version = str(getattr(runtime, "version", "")).strip()
    drift_guard = await production_drift_publication_guard(
        session,
        model_version=runtime_version or "unversioned-runtime",
        monitor_enabled=(
            bool(getattr(settings, "drift_monitor_enabled", False)) and bool(runtime_version)
        ),
        runtime_is_baseline=bool(getattr(runtime, "is_baseline", True)),
    )
    if diagnostics is not None:
        diagnostics["drift_interlock"] = drift_guard
    if drift_guard["blocked"]:
        reason_code = str(drift_guard["reason_code"] or "critical_production_drift")
        for symbol in selected_symbols:
            record_symbol_outcome(
                symbol,
                terminal_state="SKIPPED",
                reason_code=reason_code,
            )
        if diagnostics is not None:
            diagnostics["skipped_total"] = len(selected_symbols)
            diagnostics["symbol_outcome_count"] = len(selected_symbols)
        logger.error(
            "Signal publication blocked by production model safety interlock",
            extra={"drift_interlock": drift_guard},
        )
        return []

    profiles = (await session.execute(select(CapitalProfile))).scalars().all()
    if diagnostics is not None:
        diagnostics["profiles_total"] = len(profiles)
    await expire_old_signals(session)

    for symbol in selected_symbols:
        ticker = await _latest_ticker(session, symbol, cutoff=now)
        if ticker is None:
            record_symbol_outcome(symbol, terminal_state="SKIPPED", reason_code="missing_ticker")
            logger.warning("Skipping symbol without ticker", extra={"symbol": symbol})
            continue
        ticker_age = (now - ticker.source_time).total_seconds()
        if ticker_age < 0 or ticker_age > settings.max_ticker_age_seconds:
            record_symbol_outcome(symbol, terminal_state="SKIPPED", reason_code="stale_ticker")
            logger.warning(
                "Skipping symbol with stale ticker",
                extra={
                    "symbol": symbol,
                    "ticker_age_seconds": ticker_age,
                    "max_ticker_age_seconds": settings.max_ticker_age_seconds,
                    "ticker_source_time": ticker.source_time.isoformat(),
                    "ticker_received_at": ticker.received_at.isoformat(),
                },
            )
            continue
        spec = await _latest_spec(session, symbol, available_cutoff=now)
        if spec is None:
            record_symbol_outcome(symbol, terminal_state="SKIPPED", reason_code="missing_instrument_spec")
            logger.warning("Skipping symbol without point-in-time instrument spec", extra={"symbol": symbol})
            continue
        frame = await _candles_frame(
            session,
            symbol,
            market_cutoff=event_time,
            available_cutoff=now,
            limit=max(100, settings.initial_backfill_bars),
        )
        if len(frame) < settings.universe_min_history_bars:
            record_symbol_outcome(symbol, terminal_state="SKIPPED", reason_code="insufficient_candle_history")
            logger.warning(
                "Skipping symbol with insufficient candle history",
                extra={"symbol": symbol, "bars": len(frame)},
            )
            continue
        snapshot = latest_feature_snapshot(frame)
        missing_flags = [flag for flag in snapshot.quality_flags if flag.startswith("MISSING_")]
        if not snapshot.values or missing_flags:
            record_symbol_outcome(symbol, terminal_state="SKIPPED", reason_code="incomplete_feature_vector")
            logger.warning(
                "Skipping symbol with incomplete or non-contiguous feature vector",
                extra={"symbol": symbol, "quality_flags": list(snapshot.quality_flags)},
            )
            continue
        latest_candle_close = frame.iloc[-1]["close_time"]
        if hasattr(latest_candle_close, "to_pydatetime"):
            latest_candle_close = latest_candle_close.to_pydatetime()
        if latest_candle_close.tzinfo is None:
            latest_candle_close = latest_candle_close.replace(tzinfo=UTC)
        data_age = (event_time - latest_candle_close).total_seconds()
        # A recommendation keyed to ``event_time`` must be built from the candle
        # that closes exactly at that decision boundary.  Allowing the preceding
        # candle (the old MAX_CANDLE_AGE_SECONDS behaviour) can publish a signal
        # one hour early; its natural key then prevents the correct retry from
        # replacing it after the decision candle becomes available.
        if latest_candle_close != event_time:
            if data_age < 0:
                reason = "future_decision_candle"
            elif data_age > settings.max_candle_age_seconds:
                reason = "stale_candle_cutoff"
            else:
                reason = "missing_decision_candle"
            record_symbol_outcome(symbol, terminal_state="SKIPPED", reason_code=reason)
            logger.warning(
                "Skipping symbol without the exact decision candle",
                extra={
                    "symbol": symbol,
                    "reason": reason,
                    "latest_candle_close": latest_candle_close.isoformat(),
                    "event_time": event_time.isoformat(),
                    "data_age_seconds": data_age,
                },
            )
            continue

        model_features = dict(snapshot.values)
        if not getattr(runtime, "is_baseline", True):
            try:
                model_features.update(
                    await _market_context_values(
                        session,
                        symbol=symbol,
                        candles=frame,
                        event_time=event_time,
                        available_cutoff=now,
                        funding_interval_minutes=spec.funding_interval_minutes,
                    )
                )
            except ValueError as exc:
                record_symbol_outcome(symbol, terminal_state="SKIPPED", reason_code="incomplete_market_context")
                logger.warning(
                    "Skipping symbol with incomplete point-in-time market context",
                    extra={"symbol": symbol, "error": str(exc)},
                )
                continue

        spread_bps = _spread_bps(ticker)
        if spread_bps is None:
            record_symbol_outcome(symbol, terminal_state="SKIPPED", reason_code="missing_executable_bid_ask")
            logger.warning("Skipping symbol without executable bid/ask", extra={"symbol": symbol})
            continue
        if spread_bps > settings.max_spread_bps:
            record_symbol_outcome(symbol, terminal_state="SKIPPED", reason_code="spread_above_execution_limit")
            logger.info(
                "Skipping symbol above executable spread limit",
                extra={"symbol": symbol, "spread_bps": spread_bps},
            )
            continue
        if ticker.funding_rate is None or ticker.next_funding_time is None:
            record_symbol_outcome(symbol, terminal_state="SKIPPED", reason_code="missing_funding_snapshot")
            logger.warning(
                "Skipping symbol because the funding snapshot is incomplete",
                extra={"symbol": symbol},
            )
            continue
        if (
            ticker.next_funding_time <= now + timedelta(hours=settings.default_horizon_hours)
            and spec.funding_interval_minutes is None
        ):
            record_symbol_outcome(symbol, terminal_state="SKIPPED", reason_code="unknown_funding_interval")
            logger.warning(
                "Skipping symbol because funding settlement is in horizon but interval is unknown",
                extra={"symbol": symbol},
            )
            continue

        try:
            atr_pct = positive_finite_decimal(
                snapshot.values.get("atr_pct_14"),
                "atr_pct_14",
            )
        except ValueError as exc:
            record_symbol_outcome(symbol, terminal_state="SKIPPED", reason_code="invalid_model_atr")
            logger.warning(
                "Skipping symbol with invalid model ATR feature",
                extra={"symbol": symbol, "error": str(exc)},
            )
            continue
        # Entry reference already uses executable ask/bid; residual slippage must not add the spread again.
        slippage_bps = settings.base_slippage_bps
        fee_round_trip = settings.fee_rate_taker * 2
        execution_funding_scenario = float(
            projected_funding_rate(
                start_time=now,
                horizon_hours=settings.default_horizon_hours,
                next_settlement=ticker.next_funding_time,
                interval_minutes=spec.funding_interval_minutes,
                current_rate=ticker.funding_rate,
            )
        )
        # Promotion/backtest evidence explicitly has no historical point-in-time
        # funding forecast.  Keep market direction and unit economics bound to
        # that evaluated policy.  create_execution_plan() independently applies
        # the fresh ticker projection as a conservative, fail-closed overlay.
        costs = CostScenario(
            fee_rate_round_trip=decimal(fee_round_trip),
            slippage_rate=decimal(slippage_bps / 10000),
            stop_gap_reserve_rate=decimal(settings.stop_gap_reserve_bps / 10000),
            funding_rate=Decimal("0"),
        )
        try:
            directional_predictions = runtime.predict_scenarios(model_features)
            scenario = select_cost_aware_scenario(
                directional_predictions,
                bid_price=ticker.bid_price,
                ask_price=ticker.ask_price,
                last_price=ticker.last_price,
                atr_pct=atr_pct,
                costs=costs,
                stop_atr_multiplier=runtime.stop_atr_multiplier,
                tp_atr_multiplier=runtime.tp_atr_multiplier,
                tick_size=spec.tick_size,
                timeout_return_rate=decimal(getattr(settings, "timeout_gross_return_rate", -0.002)),
            )
        except ValueError as exc:
            record_symbol_outcome(symbol, terminal_state="SKIPPED", reason_code="invalid_signal_economics")
            logger.warning(
                "Skipping symbol with invalid tick-aligned signal economics",
                extra={"symbol": symbol, "error": str(exc)},
            )
            continue
        prediction = scenario.prediction
        direction = prediction.direction
        reference = scenario.reference
        entry_low = scenario.entry_low
        entry_high = scenario.entry_high
        stop = scenario.stop
        tp1 = scenario.take_profit_1
        tp2 = scenario.take_profit_2
        net_rr = scenario.net_rr
        ev_r = scenario.ev_r
        downside = scenario.downside
        gross_rr = abs(tp1 - reference) / abs(reference - stop)
        natural_key = (
            f"{symbol}-{event_time:%Y%m%dT%H0000Z}-h{settings.default_horizon_hours}-"
            f"{prediction.model_version}"
        )
        # Different worker job types can overlap during startup/catch-up.  Lock
        # by symbol before the idempotency check so two transactions cannot both
        # publish a current recommendation for the same instrument.
        await acquire_advisory_xact_lock(session, "market_signal_publish", symbol)
        existing = (
            await session.execute(select(MarketSignal).where(MarketSignal.natural_key == natural_key))
        ).scalar_one_or_none()
        if existing:
            if diagnostics is not None:
                diagnostics["existing_current_hour"] = int(
                    diagnostics.get("existing_current_hour", 0)
                ) + 1
            record_symbol_outcome(
                symbol,
                terminal_state="EXISTING_CURRENT_HOUR",
                reason_code="signal_already_exists",
                signal_id=str(existing.id),
            )
            continue

        superseded = await supersede_published_signals(
            session,
            symbol=symbol,
            replacement_natural_key=natural_key,
        )

        warnings: list[str] = []
        if runtime.is_baseline:
            warnings.append("Используется некалиброванный baseline, а не обученная ML-модель")
        warnings.extend(f"Качество данных: {flag}" for flag in snapshot.quality_flags)

        signal = MarketSignal(
            natural_key=natural_key,
            symbol=symbol,
            direction=direction,
            status="PUBLISHED",
            event_time=event_time,
            publish_time=now,
            expires_at=now + timedelta(minutes=settings.signal_ttl_minutes),
            horizon_hours=settings.default_horizon_hours,
            entry_reference=reference,
            entry_low=entry_low,
            entry_high=entry_high,
            stop_loss=stop,
            take_profit_1=tp1,
            take_profit_2=tp2,
            tp1_weight=Decimal("1"),
            p_tp=prediction.p_tp,
            p_sl=prediction.p_sl,
            p_timeout=prediction.p_timeout,
            gross_rr=float(gross_rr),
            net_rr=float(net_rr),
            net_ev_r=float(ev_r),
            gross_edge_rate=float(abs(tp1 - reference) / reference),
            fee_rate_round_trip=fee_round_trip,
            slippage_rate=slippage_bps / 10000,
            funding_rate_scenario=0.0,
            stress_downside_rate=float(downside),
            model_version=prediction.model_version,
            calibration_version=prediction.calibration_version,
            feature_schema_version=(
                BASELINE_FEATURE_SCHEMA_VERSION
                if runtime.is_baseline
                else str((runtime.bundle or {}).get("feature_schema_version") or "hourly-barrier-v1")
            ),
            data_cutoff=event_time,
            reasons=list(prediction.reasons),
            warnings=warnings,
            feature_snapshot={
                **model_features,
                "score": prediction.score,
                "spread_bps": spread_bps,
                "directional_predictions": directional_prediction_snapshot(
                    directional_predictions
                ),
                "model_runtime": runtime.metadata(),
                "economics_assumptions": {
                    "timeout_gross_return_rate": str(scenario.timeout_return_rate),
                    "timeout_return_r": prediction.timeout_return_r,
                    "timeout_return_source": (
                        "artifact_training_direction_median_r"
                        if prediction.timeout_return_r is not None
                        else "configured_fallback"
                    ),
                    "expected_funding_source": POLICY_EXPECTED_FUNDING_SOURCE,
                    "market_signal_funding_rate_scenario": "0",
                    "execution_funding_projection_at_publish": str(
                        execution_funding_scenario
                    ),
                    "execution_funding_source": (
                        "ticker_current_rate_projection_revalidated_per_plan"
                    ),
                },
            },
        )
        session.add(signal)
        await session.flush()
        await append_audit_event(
            session,
            event_type="MARKET_SIGNAL_PUBLISHED",
            entity_type="market_signal",
            entity_id=str(signal.id),
            actor="worker",
            payload={
                "natural_key": natural_key,
                "symbol": symbol,
                "direction": direction,
                "p_tp": signal.p_tp,
                "p_sl": signal.p_sl,
                "p_timeout": signal.p_timeout,
                "net_rr": signal.net_rr,
                "net_ev_r": signal.net_ev_r,
                "model_version": signal.model_version,
                "data_cutoff": signal.data_cutoff.isoformat(),
            },
        )
        await publish_outbox(
            session,
            event_type="MARKET_SIGNAL_PUBLISHED",
            aggregate_type="market_signal",
            aggregate_id=str(signal.id),
            payload={"symbol": symbol, "direction": direction},
        )
        for previous in superseded:
            await append_audit_event(
                session,
                event_type="MARKET_SIGNAL_SUPERSEDED",
                entity_type="market_signal",
                entity_id=str(previous.id),
                actor="worker",
                payload={
                    "symbol": symbol,
                    "replacement_signal_id": str(signal.id),
                    "replacement_natural_key": natural_key,
                },
            )
            await publish_outbox(
                session,
                event_type="MARKET_SIGNAL_SUPERSEDED",
                aggregate_type="market_signal",
                aggregate_id=str(previous.id),
                payload={"symbol": symbol, "replacement_signal_id": str(signal.id)},
            )
        for profile in profiles:
            plan = await create_execution_plan(
                session, signal=signal, profile=profile, settings=settings
            )
            if diagnostics is not None:
                status_counts = diagnostics.setdefault("plan_status_counts", {})
                assert isinstance(status_counts, dict)
                status_counts[plan.status] = int(status_counts.get(plan.status, 0)) + 1
                plan_outcomes = diagnostics.setdefault("plan_outcomes", [])
                assert isinstance(plan_outcomes, list)
                attrition = plan.sizing_snapshot.get("attrition")
                if not isinstance(attrition, dict):
                    raise RuntimeError("Execution plan is missing attrition evidence")
                plan_outcomes.append(
                    {
                        "plan_id": str(plan.id),
                        "signal_id": str(signal.id),
                        "profile_id": str(profile.id),
                        "status": plan.status,
                        "schema": attrition.get("schema"),
                        "terminal_stage": attrition.get("terminal_stage"),
                        "primary_reason_code": attrition.get("primary_reason_code"),
                        "reason_codes": attrition.get("reason_codes"),
                        "limiting_cap": attrition.get("limiting_cap"),
                    }
                )
        published.append(signal)
        record_symbol_outcome(
            symbol,
            terminal_state="PUBLISHED",
            reason_code="signal_published",
            signal_id=str(signal.id),
        )
        if diagnostics is not None:
            diagnostics["published"] = len(published)

    if diagnostics is not None:
        skip_counts = diagnostics.get("skip_counts")
        diagnostics["skipped_total"] = (
            sum(int(value) for value in skip_counts.values())
            if isinstance(skip_counts, dict)
            else 0
        )
        symbol_outcomes = diagnostics.get("symbol_outcomes")
        if not isinstance(symbol_outcomes, list) or len(symbol_outcomes) != len(selected_symbols):
            raise RuntimeError("Inference attrition evidence does not cover every selected symbol")
        diagnostics["symbol_outcome_count"] = len(symbol_outcomes)
    return published

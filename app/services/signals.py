from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.locks import acquire_advisory_xact_lock
from app.db.models import (
    Candle,
    CapitalProfile,
    ExecutionPlan,
    InstrumentSpecHistory,
    MarketSignal,
    TickerSnapshot,
)
from app.ml.features import BASELINE_FEATURE_SCHEMA_VERSION, latest_feature_snapshot
from app.ml.runtime import ModelRuntime, Prediction
from app.ml.training import DEFAULT_STOP_ATR_MULTIPLIER, DEFAULT_TP_ATR_MULTIPLIER
from app.risk.math import CostScenario, net_rr_and_ev, projected_funding_rate
from app.services.audit import append_audit_event, publish_outbox
from app.services.execution import create_execution_plan

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
    take_profit_2: Decimal
    net_rr: Decimal
    ev_r: Decimal
    downside: Decimal
    upside: Decimal


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
) -> SignalScenarioEconomics:
    """Select LONG/SHORT by the exact economics published to the operator.

    The model runtime estimates outcome probabilities for both directions.  It
    cannot choose the economically superior direction because executable bid/ask,
    current costs and funding are only available in the signal policy layer.
    """

    stop_multiplier = decimal(stop_atr_multiplier)
    tp_multiplier = decimal(tp_atr_multiplier)
    if (
        not stop_multiplier.is_finite()
        or not tp_multiplier.is_finite()
        or stop_multiplier <= 0
        or tp_multiplier <= 0
    ):
        raise ValueError("ATR barrier multipliers must be positive and finite")

    candidates: list[SignalScenarioEconomics] = []
    for prediction in predictions:
        reference = ask_price if prediction.direction == "LONG" else bid_price
        reference = reference or last_price
        atr = reference * atr_pct
        zone_half = atr * Decimal("0.12")
        stop_distance = atr * stop_multiplier
        tp_distance = atr * tp_multiplier
        tp2_distance = atr * Decimal("3.10")

        if prediction.direction == "LONG":
            stop = reference - stop_distance
            tp1 = reference + tp_distance
            tp2 = reference + tp2_distance
        else:
            stop = reference + stop_distance
            tp1 = reference - tp_distance
            tp2 = reference - tp2_distance

        net_rr, ev_r, downside, upside = net_rr_and_ev(
            entry=reference,
            stop=stop,
            take_profit=tp1,
            direction=prediction.direction,
            costs=costs,
            p_tp=prediction.p_tp,
            p_sl=prediction.p_sl,
            p_timeout=prediction.p_timeout,
        )
        candidates.append(
            SignalScenarioEconomics(
                prediction=prediction,
                reference=reference,
                entry_low=reference - zone_half,
                entry_high=reference + zone_half,
                stop=stop,
                take_profit_1=tp1,
                take_profit_2=tp2,
                net_rr=net_rr,
                ev_r=ev_r,
                downside=downside,
                upside=upside,
            )
        )

    if not candidates:
        raise ValueError("At least one directional prediction is required")
    return max(
        candidates,
        key=lambda item: (
            item.ev_r,
            item.net_rr,
            item.prediction.score,
            item.prediction.direction == "LONG",
        ),
    )


async def _candles_frame(
    session: AsyncSession, symbol: str, *, cutoff: datetime, limit: int = 300
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
                    Candle.close_time <= cutoff,
                    Candle.available_at <= cutoff,
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


async def _latest_ticker(session: AsyncSession, symbol: str) -> TickerSnapshot | None:
    return (
        await session.execute(
            select(TickerSnapshot)
            .where(TickerSnapshot.symbol == symbol)
            .order_by(desc(TickerSnapshot.source_time))
            .limit(1)
        )
    ).scalar_one_or_none()


async def _latest_spec(
    session: AsyncSession, symbol: str, *, cutoff: datetime
) -> InstrumentSpecHistory | None:
    return (
        await session.execute(
            select(InstrumentSpecHistory)
            .where(
                InstrumentSpecHistory.symbol == symbol,
                InstrumentSpecHistory.valid_from <= cutoff,
            )
            .order_by(desc(InstrumentSpecHistory.valid_from))
            .limit(1)
        )
    ).scalar_one_or_none()


def _spread_bps(ticker: TickerSnapshot) -> float | None:
    if not ticker.bid_price or not ticker.ask_price or ticker.bid_price <= 0 or ticker.ask_price <= 0:
        return None
    mid = (ticker.bid_price + ticker.ask_price) / Decimal("2")
    return float((ticker.ask_price - ticker.bid_price) / mid * Decimal("10000"))


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
) -> list[MarketSignal]:
    now = datetime.now(UTC)
    event_time = event_time or now.replace(minute=0, second=0, microsecond=0)
    published: list[MarketSignal] = []
    profiles = (await session.execute(select(CapitalProfile))).scalars().all()

    await expire_old_signals(session)
    selected_symbols = list(symbols if symbols is not None else settings.symbols)

    for symbol in selected_symbols:
        ticker = await _latest_ticker(session, symbol)
        if ticker is None:
            logger.warning("Skipping symbol without ticker", extra={"symbol": symbol})
            continue
        ticker_age = (now - ticker.source_time).total_seconds()
        if ticker_age < 0 or ticker_age > settings.max_ticker_age_seconds:
            logger.warning(
                "Skipping symbol with stale ticker",
                extra={"symbol": symbol, "ticker_age_seconds": ticker_age},
            )
            continue
        spec = await _latest_spec(session, symbol, cutoff=event_time)
        if spec is None:
            logger.warning("Skipping symbol without point-in-time instrument spec", extra={"symbol": symbol})
            continue
        frame = await _candles_frame(
            session,
            symbol,
            cutoff=event_time,
            limit=max(100, settings.initial_backfill_bars),
        )
        if len(frame) < settings.universe_min_history_bars:
            logger.warning(
                "Skipping symbol with insufficient candle history",
                extra={"symbol": symbol, "bars": len(frame)},
            )
            continue
        snapshot = latest_feature_snapshot(frame)
        missing_flags = [flag for flag in snapshot.quality_flags if flag.startswith("MISSING_")]
        if not snapshot.values or missing_flags:
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
        if data_age < 0 or data_age > settings.max_candle_age_seconds:
            logger.warning(
                "Skipping symbol with stale candle cutoff",
                extra={"symbol": symbol, "data_age_seconds": data_age, "event_time": event_time.isoformat()},
            )
            continue

        spread_bps = _spread_bps(ticker)
        if spread_bps is None:
            logger.warning("Skipping symbol without executable bid/ask", extra={"symbol": symbol})
            continue
        if spread_bps > settings.max_spread_bps:
            logger.info(
                "Skipping symbol above executable spread limit",
                extra={"symbol": symbol, "spread_bps": spread_bps},
            )
            continue
        if (
            ticker.funding_rate
            and ticker.next_funding_time
            and ticker.next_funding_time <= now + timedelta(hours=settings.default_horizon_hours)
            and spec.funding_interval_minutes is None
        ):
            logger.warning(
                "Skipping symbol because funding settlement is in horizon but interval is unknown",
                extra={"symbol": symbol},
            )
            continue

        atr_pct = max(0.004, min(0.08, snapshot.values.get("atr_pct_14", 0.02)))
        # Entry reference already uses executable ask/bid; residual slippage must not add the spread again.
        slippage_bps = settings.base_slippage_bps
        fee_round_trip = settings.fee_rate_taker * 2
        funding_scenario = float(
            projected_funding_rate(
                start_time=now,
                horizon_hours=settings.default_horizon_hours,
                next_settlement=ticker.next_funding_time,
                interval_minutes=spec.funding_interval_minutes,
                current_rate=ticker.funding_rate or Decimal("0"),
            )
        )
        costs = CostScenario(
            fee_rate_round_trip=decimal(fee_round_trip),
            slippage_rate=decimal(slippage_bps / 10000),
            stop_gap_reserve_rate=decimal(settings.stop_gap_reserve_bps / 10000),
            funding_rate=decimal(funding_scenario),
        )
        scenario = select_cost_aware_scenario(
            runtime.predict_scenarios(snapshot.values),
            bid_price=ticker.bid_price,
            ask_price=ticker.ask_price,
            last_price=ticker.last_price,
            atr_pct=decimal(atr_pct),
            costs=costs,
            stop_atr_multiplier=runtime.stop_atr_multiplier,
            tp_atr_multiplier=runtime.tp_atr_multiplier,
        )
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
            tp1_weight=Decimal("0.7"),
            p_tp=prediction.p_tp,
            p_sl=prediction.p_sl,
            p_timeout=prediction.p_timeout,
            gross_rr=float(gross_rr),
            net_rr=float(net_rr),
            net_ev_r=float(ev_r),
            gross_edge_rate=float(abs(tp1 - reference) / reference),
            fee_rate_round_trip=fee_round_trip,
            slippage_rate=slippage_bps / 10000,
            funding_rate_scenario=funding_scenario,
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
            feature_snapshot={**snapshot.values, "score": prediction.score, "spread_bps": spread_bps},
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
            await create_execution_plan(session, signal=signal, profile=profile, settings=settings)
        published.append(signal)
    return published

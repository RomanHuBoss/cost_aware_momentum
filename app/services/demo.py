from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Candle, Instrument, InstrumentSpecHistory, TickerSnapshot
from app.ml.runtime import ModelRuntime
from app.services.signals import publish_hourly_signals

BASE_PRICES = {
    "BTCUSDT": Decimal("65000"),
    "ETHUSDT": Decimal("3500"),
    "SOLUSDT": Decimal("145"),
    "XRPUSDT": Decimal("0.62"),
    "DOGEUSDT": Decimal("0.15"),
}


async def seed_demo_market(session: AsyncSession, settings: Settings, symbols: list[str]) -> dict:
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    for symbol in symbols:
        base = BASE_PRICES.get(symbol, Decimal("100"))
        await session.execute(
            insert(Instrument)
            .values(
                symbol=symbol,
                category="linear",
                base_coin=symbol.removesuffix("USDT"),
                quote_coin="USDT",
                settle_coin="USDT",
                status="Trading",
                launch_time=now - timedelta(days=1000),
                delivery_time=None,
                is_pre_listing=False,
                raw={"demo": True},
            )
            .on_conflict_do_update(
                index_elements=[Instrument.symbol],
                set_={"status": "Trading", "raw": {"demo": True}, "updated_at": now},
            )
        )
        digest = int(hashlib.sha256(symbol.encode()).hexdigest()[:8], 16)
        step = Decimal("0.001") if base < 1000 else Decimal("0.001")
        await session.execute(
            insert(InstrumentSpecHistory)
            .values(
                symbol=symbol,
                valid_from=now,
                received_at=now,
                tick_size=Decimal("0.01") if base >= 10 else Decimal("0.0001"),
                qty_step=step,
                min_qty=step,
                max_qty=Decimal("1000000"),
                min_notional=Decimal("5"),
                max_leverage=Decimal("100"),
                funding_interval_minutes=480,
                raw={"demo": True},
            )
            .on_conflict_do_nothing(constraint="uq_spec_symbol_valid_from")
        )
        previous = base
        for offset in range(180, 0, -1):
            open_time = now - timedelta(hours=offset)
            phase = (180 - offset) / 8 + (digest % 11)
            drift = Decimal(str((180 - offset) * (0.00012 if digest % 2 == 0 else -0.00005)))
            wave = Decimal(str(math.sin(phase) * 0.006 + math.sin(phase / 3) * 0.004))
            close = base * (Decimal("1") + drift + wave)
            open_price = previous
            high = max(open_price, close) * Decimal("1.003")
            low = min(open_price, close) * Decimal("0.997")
            volume = Decimal("1000") + Decimal((digest + offset * 17) % 8000)
            turnover = volume * close
            values = {
                "symbol": symbol,
                "interval": "60",
                "open_time": open_time,
                "close_time": open_time + timedelta(hours=1),
                "available_at": open_time + timedelta(hours=1),
                "price_type": "last",
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "turnover": turnover,
                "confirmed": True,
                "source": "demo",
            }
            await session.execute(
                insert(Candle)
                .values(**values)
                .on_conflict_do_update(
                    constraint="uq_candle_natural",
                    set_={
                        k: v
                        for k, v in values.items()
                        if k not in {"symbol", "interval", "open_time", "price_type"}
                    },
                )
            )
            mark_values = {**values, "price_type": "mark", "close": close * Decimal("1.0001")}
            await session.execute(
                insert(Candle)
                .values(**mark_values)
                .on_conflict_do_update(
                    constraint="uq_candle_natural",
                    set_={
                        k: v
                        for k, v in mark_values.items()
                        if k not in {"symbol", "interval", "open_time", "price_type"}
                    },
                )
            )
            previous = close
        last = previous
        session.add(
            TickerSnapshot(
                symbol=symbol,
                source_time=datetime.now(UTC),
                received_at=datetime.now(UTC),
                last_price=last,
                mark_price=last * Decimal("1.0001"),
                index_price=last,
                bid_price=last * Decimal("0.9999"),
                ask_price=last * Decimal("1.0001"),
                turnover_24h=base * Decimal("10000000"),
                volume_24h=Decimal("10000000"),
                open_interest=Decimal("5000000"),
                funding_rate=Decimal("0.0001"),
                next_funding_time=now + timedelta(hours=8),
                raw={"demo": True},
            )
        )
    await session.flush()
    runtime = ModelRuntime(None, allow_baseline=True)
    runtime.load()
    signals = await publish_hourly_signals(session, settings=settings, runtime=runtime)
    return {"symbols": symbols, "signals_published": len(signals)}

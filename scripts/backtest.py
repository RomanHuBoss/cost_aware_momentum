from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sqlalchemy import select

from app.asyncio_compat import run_with_compatible_event_loop
from app.config import get_settings
from app.db.engine import SessionFactory, dispose_engine
from app.db.models import BacktestRun, Candle
from app.ml.training import chronological_split, evaluate_model, make_direction_dataset


async def load_frame() -> pd.DataFrame:
    settings = get_settings()
    async with SessionFactory() as session:
        query = select(Candle).where(
            Candle.interval == "60",
            Candle.price_type == "last",
            Candle.confirmed.is_(True),
        )
        if settings.universe_mode == "static":
            query = query.where(Candle.symbol.in_(settings.symbols))
        rows = (await session.execute(query.order_by(Candle.open_time))).scalars().all()
    return pd.DataFrame(
        [
            {
                "symbol": row.symbol,
                "open_time": row.open_time,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume),
                "turnover": float(row.turnover),
            }
            for row in rows
        ]
    )


async def run(args) -> None:
    started = datetime.now(UTC)
    frame = await load_frame()
    dataset = make_direction_dataset(frame, horizon=args.horizon)
    split = chronological_split(dataset, purge_rows=args.horizon)
    bundle = joblib.load(args.model)
    model = bundle["model"]
    metrics = evaluate_model(model, split)
    proba = model.predict_proba(split.x_test)[:, 1]
    direction = np.where(proba >= 0.5, 1.0, -1.0)
    gross = direction * split.test_meta["future_return"].to_numpy(float)
    costs = np.full_like(gross, args.round_trip_cost_bps / 10000.0)
    net = gross - costs
    equity = np.cumprod(1 + net)
    peaks = np.maximum.accumulate(equity)
    drawdowns = equity / peaks - 1
    trade_metrics = {
        **metrics,
        "net_return": float(equity[-1] - 1) if len(equity) else 0.0,
        "mean_net_return": float(net.mean()) if len(net) else 0.0,
        "win_rate": float((net > 0).mean()) if len(net) else 0.0,
        "max_drawdown": float(drawdowns.min()) if len(drawdowns) else 0.0,
        "cost_bps": args.round_trip_cost_bps,
        "warning": "Research baseline; not an event-driven production backtest and not evidence of profitability.",
    }
    output = Path(args.output or f"reports/backtest-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(trade_metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    async with SessionFactory() as session:
        session.add(
            BacktestRun(
                name=f"direction-baseline-h{args.horizon}",
                configuration={
                    "model": args.model,
                    "horizon": args.horizon,
                    "round_trip_cost_bps": args.round_trip_cost_bps,
                    "purge_rows": args.horizon,
                },
                started_at=started,
                finished_at=datetime.now(UTC),
                status="SUCCESS",
                metrics=trade_metrics,
                artifact_path=str(output),
            )
        )
        await session.commit()
    print(json.dumps({"output": str(output), "metrics": trade_metrics}, indent=2, ensure_ascii=False))
    await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--horizon", type=int, default=8)
    parser.add_argument("--round-trip-cost-bps", type=float, default=14.0)
    parser.add_argument("--output")
    run_with_compatible_event_loop(run(parser.parse_args()))


if __name__ == "__main__":
    main()

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
from app.ml.training import chronological_split, evaluate_model, make_barrier_dataset


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
                "close_time": row.close_time,
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


def policy_backtest(
    model,
    split,
    *,
    round_trip_cost_bps: float,
    stop_gap_reserve_bps: float,
    minimum_predicted_edge: float,
) -> dict:
    probabilities = model.predict_proba(split.x_test)
    classes = [str(item) for item in model.classes_]
    indexes = {label: classes.index(label) for label in ("TP", "SL", "TIMEOUT")}
    meta = split.test_meta.copy()
    meta["p_tp"] = probabilities[:, indexes["TP"]]
    meta["p_sl"] = probabilities[:, indexes["SL"]]
    meta["p_timeout"] = probabilities[:, indexes["TIMEOUT"]]
    cost_rate = round_trip_cost_bps / 10000.0
    gap_rate = stop_gap_reserve_bps / 10000.0
    meta["predicted_net_edge"] = (
        meta["p_tp"] * (meta["barrier_upside_rate"] - cost_rate)
        - meta["p_sl"] * (meta["barrier_downside_rate"] + cost_rate + gap_rate)
        + meta["p_timeout"] * (-cost_rate)
    )

    chosen = (
        meta.sort_values(
            ["decision_time", "symbol", "predicted_net_edge"],
            ascending=[True, True, False],
        )
        .groupby(["decision_time", "symbol"], as_index=False)
        .head(1)
        .reset_index(drop=True)
    )
    chosen["traded"] = chosen["predicted_net_edge"] >= minimum_predicted_edge
    chosen["net_return"] = np.where(
        chosen["traded"],
        chosen["realized_gross_return"]
        - cost_rate
        - np.where(chosen["target"] == "SL", gap_rate, 0.0),
        0.0,
    )
    traded = chosen[chosen["traded"]].copy()
    all_periods = pd.Index(chosen["decision_time"].drop_duplicates().sort_values())
    period_returns = (
        traded.groupby("decision_time", sort=True)["net_return"].mean().reindex(all_periods, fill_value=0.0)
    )
    concurrent_trades = (
        traded.groupby("decision_time", sort=True).size().reindex(all_periods, fill_value=0)
    )
    equity = np.concatenate(
        ([1.0], np.cumprod(1.0 + period_returns.to_numpy(float)))
    )
    peaks = np.maximum.accumulate(equity)
    drawdowns = equity / peaks - 1.0

    def stressed(multiplier: float) -> float:
        stressed_rows = chosen.loc[chosen["traded"], ["decision_time"]].copy()
        stressed_rows["net_return"] = (
            chosen.loc[chosen["traded"], "realized_gross_return"].to_numpy(float)
            - cost_rate * multiplier
            - np.where(
                chosen.loc[chosen["traded"], "target"].to_numpy() == "SL",
                gap_rate * multiplier,
                0.0,
            )
        )
        stressed_periods = (
            stressed_rows.groupby("decision_time", sort=True)["net_return"]
            .mean()
            .reindex(all_periods, fill_value=0.0)
        )
        return (
            float(np.cumprod(1.0 + stressed_periods.to_numpy(float))[-1] - 1.0)
            if len(stressed_periods)
            else 0.0
        )

    return {
        "candidate_rows": int(len(chosen)),
        "trades": int(chosen["traded"].sum()),
        "no_trade_rate": float(1.0 - chosen["traded"].mean()) if len(chosen) else 1.0,
        "net_return": float(equity[-1] - 1.0),
        "mean_net_return_per_trade": float(traded["net_return"].mean()) if len(traded) else 0.0,
        "win_rate": float((traded["net_return"] > 0).mean()) if len(traded) else 0.0,
        "max_drawdown": float(drawdowns.min()),
        "portfolio_periods": int(len(period_returns)),
        "max_concurrent_trades": int(concurrent_trades.max()) if len(concurrent_trades) else 0,
        "mean_concurrent_trades": (
            float(concurrent_trades[concurrent_trades > 0].mean())
            if (concurrent_trades > 0).any()
            else 0.0
        ),
        "cost_bps": round_trip_cost_bps,
        "stop_gap_reserve_bps": stop_gap_reserve_bps,
        "minimum_predicted_edge": minimum_predicted_edge,
        "stress_net_return_cost_x1_5": stressed(1.5),
        "stress_net_return_cost_x2": stressed(2.0),
        "warning": (
            "Barrier-policy research backtest with conservative hourly ambiguity. "
            "It still does not model historical orderbook impact, partial fills or operator latency and is not evidence of profitability."
        ),
    }


async def run(args) -> None:
    started = datetime.now(UTC)
    frame = await load_frame()
    bundle = joblib.load(args.model)
    if not isinstance(bundle, dict) or bundle.get("task") != "barrier_outcome_v1":
        raise ValueError("Model must be a version 1.3.0 barrier_outcome_v1 artifact")
    artifact_horizon = int(bundle["horizon_hours"])
    if args.horizon is not None and args.horizon != artifact_horizon:
        raise ValueError(
            f"Requested horizon {args.horizon} does not match artifact horizon {artifact_horizon}"
        )
    horizon = artifact_horizon
    dataset = make_barrier_dataset(
        frame,
        horizon=horizon,
        stop_atr_multiplier=float(bundle.get("stop_atr_multiplier", 1.15)),
        tp_atr_multiplier=float(bundle.get("tp_atr_multiplier", 2.20)),
    )
    split = chronological_split(dataset, purge_rows=horizon)
    model = bundle["model"]
    prediction_metrics = evaluate_model(model, split)
    trade_metrics = policy_backtest(
        model,
        split,
        round_trip_cost_bps=args.round_trip_cost_bps,
        stop_gap_reserve_bps=args.stop_gap_reserve_bps,
        minimum_predicted_edge=args.minimum_predicted_edge,
    )
    metrics = {
        "prediction": prediction_metrics,
        "policy": trade_metrics,
        "hourly_continuity": dataset.attrs.get("hourly_continuity") or {},
    }
    output = Path(args.output or f"reports/backtest-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    async with SessionFactory() as session:
        session.add(
            BacktestRun(
                name=f"barrier-policy-{bundle.get('model_type', 'model')}-h{horizon}",
                configuration={
                    "model": args.model,
                    "model_version": bundle.get("version"),
                    "horizon": horizon,
                    "round_trip_cost_bps": args.round_trip_cost_bps,
                    "stop_gap_reserve_bps": args.stop_gap_reserve_bps,
                    "minimum_predicted_edge": args.minimum_predicted_edge,
                    "purge_hours": horizon,
                },
                started_at=started,
                finished_at=datetime.now(UTC),
                status="SUCCESS",
                metrics=metrics,
                artifact_path=str(output),
            )
        )
        await session.commit()
    print(json.dumps({"output": str(output), "metrics": metrics}, indent=2, ensure_ascii=False))
    await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--horizon", type=int)
    parser.add_argument("--round-trip-cost-bps", type=float, default=14.0)
    parser.add_argument("--stop-gap-reserve-bps", type=float, default=10.0)
    parser.add_argument("--minimum-predicted-edge", type=float, default=0.0)
    parser.add_argument("--output")
    run_with_compatible_event_loop(run(parser.parse_args()))


if __name__ == "__main__":
    main()

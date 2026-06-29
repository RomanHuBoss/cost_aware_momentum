from __future__ import annotations

import argparse
import json
import math
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
from app.ml.training import (
    chronological_split,
    evaluate_model,
    make_barrier_dataset,
    validate_outcome_probability_matrix,
)

HOUR_NS = 3_600_000_000_000


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


def _finite_nonnegative(value: float, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return parsed


def _simulate_capital_sleeves(
    trades: pd.DataFrame,
    *,
    return_column: str,
    horizon_hours: int,
) -> tuple[float, float, int]:
    """Compound only non-overlapping hourly capital sleeves.

    A horizon-H strategy receives H equal capital sleeves.  The cohort opened at a
    given hour uses one sleeve and that sleeve cannot be reused until H hours later,
    when every barrier label in the previous cohort is already closed.  This avoids
    treating overlapping H-hour trade returns as sequential one-hour reinvestment.
    """

    if trades.empty:
        return 0.0, 0.0, 0
    if horizon_hours <= 0:
        raise ValueError("horizon_hours must be positive")

    sleeve_capital = np.full(horizon_hours, 1.0 / horizon_hours, dtype=float)
    previous_decision: dict[int, pd.Timestamp] = {}
    pnl_events: list[tuple[pd.Timestamp, float]] = []

    for decision_time, cohort in trades.groupby("decision_time", sort=True):
        decision = pd.Timestamp(decision_time)
        slot = int(decision.value // HOUR_NS) % horizon_hours
        prior = previous_decision.get(slot)
        if prior is not None and decision - prior < pd.Timedelta(horizon_hours, unit="h"):
            raise ValueError("Capital sleeve would be reused before the prior horizon closes")

        returns = cohort[return_column].to_numpy(float)
        if not np.isfinite(returns).all():
            raise ValueError(f"{return_column} contains non-finite values")
        cohort_return = float(returns.mean())
        if cohort_return <= -1.0:
            raise ValueError("A cohort return at or below -100% cannot be compounded")

        starting_capital = float(sleeve_capital[slot])
        allocation = starting_capital / len(cohort)
        for exit_time, trade_return in zip(cohort["exit_time"], returns, strict=True):
            pnl_events.append((pd.Timestamp(exit_time), allocation * float(trade_return)))

        sleeve_capital[slot] = starting_capital * (1.0 + cohort_return)
        previous_decision[slot] = decision

    event_frame = pd.DataFrame(pnl_events, columns=["exit_time", "pnl"])
    realized_pnl = event_frame.groupby("exit_time", sort=True)["pnl"].sum()
    equity = np.concatenate(([1.0], 1.0 + realized_pnl.cumsum().to_numpy(float)))
    peaks = np.maximum.accumulate(equity)
    drawdowns = equity / peaks - 1.0
    return float(sleeve_capital.sum() - 1.0), float(drawdowns.min()), int(len(realized_pnl))


def _active_trade_statistics(trades: pd.DataFrame) -> tuple[int, float]:
    if trades.empty:
        return 0, 0.0

    entries = trades.groupby("decision_time").size().to_dict()
    exits = trades.groupby("exit_time").size().to_dict()
    timestamps = sorted(set(entries) | set(exits))
    active = 0
    maximum = 0
    weighted_active = 0.0
    active_duration = 0.0

    for index, timestamp in enumerate(timestamps):
        # A position closing at a boundary releases capital before a new position
        # at that same boundary is counted.
        active -= int(exits.get(timestamp, 0))
        active += int(entries.get(timestamp, 0))
        maximum = max(maximum, active)
        if index + 1 < len(timestamps):
            duration_hours = (timestamps[index + 1] - timestamp).total_seconds() / 3600.0
            if active > 0 and duration_hours > 0:
                weighted_active += active * duration_hours
                active_duration += duration_hours

    mean_active = weighted_active / active_duration if active_duration > 0 else float(maximum)
    return maximum, float(mean_active)


def policy_backtest(
    model,
    split,
    *,
    round_trip_cost_bps: float,
    stop_gap_reserve_bps: float,
    horizon_hours: int = 1,
    slippage_bps: float = 0.0,
    funding_rate: float = 0.0,
    timeout_return_rate: float = -0.002,
    minimum_net_rr: float = 0.0,
    minimum_net_ev_r: float | None = None,
    minimum_predicted_edge: float | None = None,
) -> dict:
    """Evaluate the deployed cost-aware direction policy without overlap leverage.

    ``minimum_predicted_edge`` is retained as a compatibility alias for
    ``minimum_net_ev_r``.  New callers should use the EV/R name explicitly.
    """

    if horizon_hours <= 0:
        raise ValueError("horizon_hours must be positive")
    fee_rate_round_trip = _finite_nonnegative(round_trip_cost_bps, "round_trip_cost_bps") / 10000.0
    gap_rate = _finite_nonnegative(stop_gap_reserve_bps, "stop_gap_reserve_bps") / 10000.0
    slippage_rate = _finite_nonnegative(slippage_bps, "slippage_bps") / 10000.0
    minimum_net_rr = _finite_nonnegative(minimum_net_rr, "minimum_net_rr")
    funding_rate = float(funding_rate)
    timeout_return_rate = float(timeout_return_rate)
    if not math.isfinite(funding_rate) or not math.isfinite(timeout_return_rate):
        raise ValueError("funding_rate and timeout_return_rate must be finite")
    if minimum_net_ev_r is not None and minimum_predicted_edge is not None:
        raise ValueError("Use either minimum_net_ev_r or minimum_predicted_edge, not both")
    if minimum_net_ev_r is None:
        minimum_net_ev_r = 0.0 if minimum_predicted_edge is None else float(minimum_predicted_edge)
    if not math.isfinite(minimum_net_ev_r):
        raise ValueError("minimum_net_ev_r must be finite")

    meta = split.test_meta.copy().reset_index(drop=True)
    probabilities, indexes = validate_outcome_probability_matrix(
        model.predict_proba(split.x_test),
        model.classes_,
        expected_rows=len(meta),
    )

    required_columns = {
        "decision_time",
        "symbol",
        "direction",
        "target",
        "exit_index",
        "realized_gross_return",
        "barrier_upside_rate",
        "barrier_downside_rate",
    }
    missing_columns = sorted(required_columns - set(meta.columns))
    if missing_columns:
        raise ValueError(f"Backtest metadata is missing columns: {missing_columns}")
    if len(probabilities) != len(meta):
        raise ValueError("Prediction rows do not match backtest metadata")

    meta["decision_time"] = pd.to_datetime(meta["decision_time"], utc=True, errors="coerce")
    if meta["decision_time"].isna().any():
        raise ValueError("Backtest metadata contains invalid decision_time")
    exit_index = pd.to_numeric(meta["exit_index"], errors="coerce")
    if exit_index.isna().any() or (exit_index < 0).any() or (exit_index >= horizon_hours).any():
        raise ValueError("exit_index must be within the configured label horizon")
    if not np.allclose(exit_index, np.floor(exit_index)):
        raise ValueError("exit_index must contain integers")
    meta["exit_index"] = exit_index.astype(int)
    meta["exit_time"] = meta["decision_time"] + pd.to_timedelta(meta["exit_index"] + 1, unit="h")

    meta["p_tp"] = probabilities[:, indexes["TP"]]
    meta["p_sl"] = probabilities[:, indexes["SL"]]
    meta["p_timeout"] = probabilities[:, indexes["TIMEOUT"]]

    is_long = meta["direction"].eq("LONG")
    if (~meta["direction"].isin(["LONG", "SHORT"])).any():
        raise ValueError("Backtest metadata contains an unsupported direction")
    fee_rate_per_leg = fee_rate_round_trip / 2.0
    adverse_funding = np.where(
        is_long,
        max(0.0, funding_rate),
        max(0.0, -funding_rate),
    )
    tp_exit_ratio = np.where(
        is_long,
        1.0 + meta["barrier_upside_rate"],
        1.0 - meta["barrier_upside_rate"],
    )
    sl_exit_ratio = np.where(
        is_long,
        1.0 - meta["barrier_downside_rate"],
        1.0 + meta["barrier_downside_rate"],
    )
    timeout_exit_ratio = np.where(
        is_long,
        1.0 + timeout_return_rate,
        1.0 - timeout_return_rate,
    )
    realized_exit_ratio = np.where(
        is_long,
        1.0 + meta["realized_gross_return"],
        1.0 - meta["realized_gross_return"],
    )
    if (
        (tp_exit_ratio <= 0).any()
        or (sl_exit_ratio <= 0).any()
        or (timeout_exit_ratio <= 0).any()
        or (realized_exit_ratio <= 0).any()
    ):
        raise ValueError("Backtest produced a non-positive exit notional ratio")

    tp_fee_rate = fee_rate_per_leg * (1.0 + tp_exit_ratio)
    sl_fee_rate = fee_rate_per_leg * (1.0 + sl_exit_ratio)
    timeout_fee_rate = fee_rate_per_leg * (1.0 + timeout_exit_ratio)
    realized_fee_rate = fee_rate_per_leg * (1.0 + realized_exit_ratio)
    meta["realized_fee_rate"] = realized_fee_rate
    meta["adverse_funding_rate"] = adverse_funding
    meta["net_upside_rate"] = (
        meta["barrier_upside_rate"] - tp_fee_rate - slippage_rate - adverse_funding
    )
    meta["stress_downside_rate"] = (
        meta["barrier_downside_rate"]
        + sl_fee_rate
        + slippage_rate
        + gap_rate
        + adverse_funding
    )
    meta["timeout_net_rate"] = (
        timeout_return_rate - timeout_fee_rate - slippage_rate - adverse_funding
    )
    meta["net_rr"] = np.where(
        meta["stress_downside_rate"] > 0,
        np.maximum(meta["net_upside_rate"], 0.0) / meta["stress_downside_rate"],
        0.0,
    )
    meta["expected_net_rate"] = (
        meta["p_tp"] * meta["net_upside_rate"]
        - meta["p_sl"] * meta["stress_downside_rate"]
        + meta["p_timeout"] * meta["timeout_net_rate"]
    )
    meta["expected_ev_r"] = np.where(
        meta["stress_downside_rate"] > 0,
        meta["expected_net_rate"] / meta["stress_downside_rate"],
        0.0,
    )
    meta["direction_tiebreak"] = is_long.astype(int)

    chosen = (
        meta.sort_values(
            ["decision_time", "symbol", "expected_ev_r", "net_rr", "direction_tiebreak"],
            ascending=[True, True, False, False, False],
        )
        .groupby(["decision_time", "symbol"], as_index=False)
        .head(1)
        .sort_values(["decision_time", "symbol"])
        .reset_index(drop=True)
    )
    chosen["traded"] = (chosen["net_rr"] >= minimum_net_rr) & (
        chosen["expected_ev_r"] >= minimum_net_ev_r
    )
    chosen["net_return"] = (
        chosen["realized_gross_return"]
        - chosen["realized_fee_rate"]
        - slippage_rate
        - chosen["adverse_funding_rate"]
        - np.where(chosen["target"] == "SL", gap_rate, 0.0)
    )
    chosen["net_return_without_stop_reserve"] = chosen["net_return"] + np.where(
        chosen["target"] == "SL", gap_rate, 0.0
    )
    traded = chosen[chosen["traded"]].copy()

    net_return, max_drawdown, portfolio_periods = _simulate_capital_sleeves(
        traded,
        return_column="net_return",
        horizon_hours=horizon_hours,
    )
    reserve_free_return, _, _ = _simulate_capital_sleeves(
        traded,
        return_column="net_return_without_stop_reserve",
        horizon_hours=horizon_hours,
    )
    max_concurrent_trades, mean_concurrent_trades = _active_trade_statistics(traded)

    def stressed(multiplier: float) -> float:
        stressed_rows = traded.copy()
        stressed_rows["stressed_net_return"] = (
            stressed_rows["realized_gross_return"]
            - stressed_rows["realized_fee_rate"] * multiplier
            - slippage_rate * multiplier
            - stressed_rows["adverse_funding_rate"] * multiplier
            - np.where(stressed_rows["target"] == "SL", gap_rate * multiplier, 0.0)
        )
        result, _, _ = _simulate_capital_sleeves(
            stressed_rows,
            return_column="stressed_net_return",
            horizon_hours=horizon_hours,
        )
        return result

    return {
        "candidate_rows": int(len(chosen)),
        "trades": int(chosen["traded"].sum()),
        "no_trade_rate": float(1.0 - chosen["traded"].mean()) if len(chosen) else 1.0,
        "net_return": net_return,
        "net_return_without_stop_gap_reserve": reserve_free_return,
        "mean_net_return_per_trade": float(traded["net_return"].mean()) if len(traded) else 0.0,
        "mean_expected_ev_r": float(traded["expected_ev_r"].mean()) if len(traded) else None,
        "win_rate": float((traded["net_return"] > 0).mean()) if len(traded) else 0.0,
        "max_drawdown": max_drawdown,
        "portfolio_periods": portfolio_periods,
        "portfolio_cohorts": int(traded["decision_time"].nunique()),
        "capital_sleeves": horizon_hours,
        "max_concurrent_trades": max_concurrent_trades,
        "mean_concurrent_trades": mean_concurrent_trades,
        "cost_bps": round_trip_cost_bps,
        "round_trip_cost_bps": round_trip_cost_bps,
        "slippage_bps": slippage_bps,
        "stop_gap_reserve_bps": stop_gap_reserve_bps,
        "funding_rate": funding_rate,
        "timeout_return_rate": timeout_return_rate,
        "minimum_net_rr": minimum_net_rr,
        "minimum_net_ev_r": minimum_net_ev_r,
        "minimum_predicted_edge": minimum_net_ev_r,
        "minimum_predicted_edge_semantics": "deprecated_alias_of_minimum_net_ev_r",
        "stress_net_return_cost_x1_5": stressed(1.5),
        "stress_net_return_cost_x2": stressed(2.0),
        "warning": (
            "Barrier-policy research backtest with conservative hourly ambiguity and "
            "non-overlapping horizon capital sleeves. Equity is realized at modeled candle "
            "exit times; intrahorizon mark-to-market, historical orderbook impact, partial "
            "fills and operator latency are not modeled. This is not evidence of profitability."
        ),
    }


async def run(args) -> None:
    started = datetime.now(UTC)
    settings = get_settings()
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
    round_trip_cost_bps = (
        args.round_trip_cost_bps
        if args.round_trip_cost_bps is not None
        else settings.fee_rate_taker * 2 * 10000
    )
    slippage_bps = (
        args.slippage_bps if args.slippage_bps is not None else settings.base_slippage_bps
    )
    stop_gap_reserve_bps = (
        args.stop_gap_reserve_bps
        if args.stop_gap_reserve_bps is not None
        else settings.stop_gap_reserve_bps
    )
    minimum_net_rr = args.minimum_net_rr if args.minimum_net_rr is not None else settings.min_net_rr
    if args.minimum_net_ev_r is not None and args.minimum_predicted_edge is not None:
        raise ValueError("Use either --minimum-net-ev-r or --minimum-predicted-edge, not both")
    minimum_net_ev_r = (
        args.minimum_net_ev_r
        if args.minimum_net_ev_r is not None
        else (
            args.minimum_predicted_edge
            if args.minimum_predicted_edge is not None
            else settings.min_net_ev_r
        )
    )

    model = bundle["model"]
    prediction_metrics = evaluate_model(model, split)
    trade_metrics = policy_backtest(
        model,
        split,
        round_trip_cost_bps=round_trip_cost_bps,
        slippage_bps=slippage_bps,
        stop_gap_reserve_bps=stop_gap_reserve_bps,
        funding_rate=args.funding_rate,
        timeout_return_rate=args.timeout_return_rate,
        minimum_net_rr=minimum_net_rr,
        minimum_net_ev_r=minimum_net_ev_r,
        horizon_hours=horizon,
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
                    "round_trip_cost_bps": round_trip_cost_bps,
                    "slippage_bps": slippage_bps,
                    "stop_gap_reserve_bps": stop_gap_reserve_bps,
                    "funding_rate": args.funding_rate,
                    "timeout_return_rate": args.timeout_return_rate,
                    "minimum_net_rr": minimum_net_rr,
                    "minimum_net_ev_r": minimum_net_ev_r,
                    "purge_hours": horizon,
                    "policy_source": "cost_aware_ev_r_v1",
                    "portfolio_accounting": "non_overlapping_horizon_sleeves_v1",
                    "settings_mode": settings.app_mode,
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
    parser.add_argument("--round-trip-cost-bps", type=float)
    parser.add_argument("--slippage-bps", type=float)
    parser.add_argument("--stop-gap-reserve-bps", type=float)
    parser.add_argument("--funding-rate", type=float, default=0.0)
    parser.add_argument("--timeout-return-rate", type=float, default=-0.002)
    parser.add_argument("--minimum-net-rr", type=float)
    parser.add_argument("--minimum-net-ev-r", type=float)
    parser.add_argument(
        "--minimum-predicted-edge",
        type=float,
        help="Deprecated alias for --minimum-net-ev-r",
    )
    parser.add_argument("--output")
    run_with_compatible_event_loop(run(parser.parse_args()))


if __name__ == "__main__":
    main()

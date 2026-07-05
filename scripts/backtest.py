from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

from app import __version__
from app.asyncio_compat import run_with_compatible_event_loop
from app.config import get_settings
from app.db.engine import SessionFactory, dispose_engine
from app.db.models import BacktestRun
from app.ml.lifecycle import load_training_market_data
from app.ml.runtime import ModelRuntime
from app.ml.training import (
    apply_intrahorizon_margin_path,
    chronological_split,
    evaluate_model,
    filter_single_active_trade_per_symbol,
    historical_funding_components,
    make_barrier_dataset,
    validate_outcome_probability_matrix,
    validate_policy_evaluation_metadata,
)
from app.research.overfitting import EXPERIMENT_PERIOD_RETURN_SCHEMA_VERSION
from app.research.preregistration import build_preregistration_template
from app.services.experiment_ledger import (
    append_experiment_event,
    experiment_configuration_hash,
)

HOUR_NS = 3_600_000_000_000


def load_validated_artifact(
    model_path: str | Path,
    *,
    expected_sha256: str | None = None,
) -> ModelRuntime:
    """Load a backtest model through the same fail-closed contract as production."""

    runtime = ModelRuntime(Path(model_path).expanduser().resolve(), allow_baseline=False)
    runtime.load(expected_sha256=expected_sha256, source="backtest")
    if runtime.bundle is None or runtime.horizon_hours is None:
        raise RuntimeError("Backtest requires a validated model artifact")
    return runtime


def _finite_nonnegative(value: float, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return parsed


def _observed_policy_period_grid(
    chosen: pd.DataFrame,
    *,
    horizon_hours: int,
) -> tuple[pd.DatetimeIndex, int, int]:
    """Return only hourly periods covered by observed decision cohorts.

    Each valid decision row proves that its full label horizon was observed.
    The union of those decision-to-horizon windows therefore includes genuine
    no-trade/holding hours while excluding calendar gaps for which no decision
    cohort and no valid label path existed.
    """

    if isinstance(horizon_hours, bool) or not isinstance(horizon_hours, (int, np.integer)):
        raise TypeError("horizon_hours must be an integer")
    if int(horizon_hours) <= 0:
        raise ValueError("horizon_hours must be positive")
    resolved_horizon = int(horizon_hours)
    if chosen.empty:
        return pd.DatetimeIndex([]), 0, 0
    if "decision_time" not in chosen.columns:
        raise ValueError("Policy period grid requires decision_time")

    decisions = pd.DatetimeIndex(
        pd.to_datetime(chosen["decision_time"], utc=True, errors="coerce")
        .drop_duplicates()
        .sort_values(kind="mergesort")
    )
    if decisions.empty or decisions.isna().any():
        raise ValueError("Policy period grid requires valid observed decision times")
    if not decisions.equals(decisions.floor("h")):
        raise ValueError("Policy period grid requires hour-aligned decision times")

    covered_values: set[pd.Timestamp] = set()
    for decision in decisions:
        covered_values.update(
            pd.date_range(
                decision,
                periods=resolved_horizon + 1,
                freq="h",
            )
        )
    covered = pd.DatetimeIndex(sorted(covered_values))
    full_calendar = pd.date_range(
        decisions[0],
        decisions[-1] + pd.Timedelta(resolved_horizon, unit="h"),
        freq="h",
    )
    omitted = int(len(full_calendar) - len(covered))
    if omitted < 0:
        raise ValueError("Policy covered periods exceed the calendar span")
    return covered, int(len(decisions)), omitted


def _simulate_capital_sleeves_evidence(
    trades: pd.DataFrame,
    *,
    return_column: str,
    horizon_hours: int,
    period_grid: pd.DatetimeIndex | None = None,
) -> dict[str, object]:
    """Compound non-overlapping sleeves and expose an aligned realized return path."""

    if horizon_hours <= 0:
        raise ValueError("horizon_hours must be positive")
    if trades.empty:
        timestamps = list(period_grid) if period_grid is not None else []
        return {
            "net_return": 0.0,
            "max_drawdown": 0.0,
            "portfolio_periods": 0,
            "period_returns": [
                {"timestamp": pd.Timestamp(item).isoformat(), "return": 0.0} for item in timestamps
            ],
        }

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
    if period_grid is None:
        grid = pd.DatetimeIndex(realized_pnl.index)
    else:
        grid = pd.DatetimeIndex(period_grid)
        outside = realized_pnl.index.difference(grid)
        if len(outside):
            raise ValueError("Realized PnL events fall outside the experiment period grid")

    current_equity = 1.0
    peaks = [1.0]
    equity_path = [1.0]
    period_returns: list[dict[str, object]] = []
    for timestamp in grid:
        pnl = float(realized_pnl.get(timestamp, 0.0))
        period_return = pnl / current_equity
        if not math.isfinite(period_return) or period_return <= -1.0:
            raise ValueError("Experiment period return is invalid")
        current_equity += pnl
        equity_path.append(current_equity)
        peaks.append(max(peaks[-1], current_equity))
        period_returns.append({"timestamp": pd.Timestamp(timestamp).isoformat(), "return": period_return})

    equity = np.asarray(equity_path, dtype=float)
    peak_array = np.asarray(peaks, dtype=float)
    drawdowns = equity / peak_array - 1.0
    expected_net = float(sleeve_capital.sum() - 1.0)
    if not math.isclose(current_equity - 1.0, expected_net, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("Experiment return path does not reconcile to sleeve capital")
    return {
        "net_return": expected_net,
        "max_drawdown": float(drawdowns.min()),
        "portfolio_periods": int(len(realized_pnl)),
        "period_returns": period_returns,
    }


def _simulate_capital_sleeves(
    trades: pd.DataFrame,
    *,
    return_column: str,
    horizon_hours: int,
) -> tuple[float, float, int]:
    evidence = _simulate_capital_sleeves_evidence(
        trades,
        return_column=return_column,
        horizon_hours=horizon_hours,
    )
    return (
        float(evidence["net_return"]),
        float(evidence["max_drawdown"]),
        int(evidence["portfolio_periods"]),
    )


def _active_trade_statistics(trades: pd.DataFrame) -> tuple[int, float]:
    if trades.empty:
        return 0, 0.0

    entries = trades.groupby("decision_time").size().to_dict()
    exits = trades.groupby("exit_time").size().to_dict()
    timestamps = sorted(set(entries) | set(exits))
    active = 0
    maximum = 0
    weighted_active = 0.0
    observed_duration = 0.0

    for index, timestamp in enumerate(timestamps):
        # A position closing at a boundary releases capital before a new position
        # at that same boundary is counted.
        active -= int(exits.get(timestamp, 0))
        active += int(entries.get(timestamp, 0))
        maximum = max(maximum, active)
        if index + 1 < len(timestamps):
            duration_hours = (timestamps[index + 1] - timestamp).total_seconds() / 3600.0
            if duration_hours > 0:
                weighted_active += active * duration_hours
                observed_duration += duration_hours

    mean_active = weighted_active / observed_duration if observed_duration > 0 else float(maximum)
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
    use_model_timeout_return: bool = True,
    minimum_net_rr: float = 0.0,
    minimum_net_ev_r: float | None = None,
    minimum_predicted_edge: float | None = None,
    research_leverage: int = 3,
    liquidation_equity_reserve_fraction: float = 0.10,
    require_intrahorizon_margin: bool = False,
    include_experiment_evidence: bool = False,
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

    if len(probabilities) != len(meta):
        raise ValueError("Prediction rows do not match backtest metadata")
    meta = validate_policy_evaluation_metadata(
        meta,
        context="Backtest",
        horizon_hours=horizon_hours,
        require_barrier_return_consistency=True,
    )
    meta, intrahorizon_margin_schema = apply_intrahorizon_margin_path(
        meta,
        context="Backtest",
        require=require_intrahorizon_margin,
        expected_leverage=research_leverage,
        expected_equity_reserve_fraction=liquidation_equity_reserve_fraction,
    )

    meta["p_tp"] = probabilities[:, indexes["TP"]]
    meta["p_sl"] = probabilities[:, indexes["SL"]]
    meta["p_timeout"] = probabilities[:, indexes["TIMEOUT"]]

    timeout_predictor = getattr(model, "predict_timeout_return_r", None)
    if use_model_timeout_return and callable(timeout_predictor):
        timeout_return_r = np.asarray(timeout_predictor(split.x_test), dtype=float)
        if timeout_return_r.ndim != 1 or len(timeout_return_r) != len(meta):
            raise ValueError("Conditional TIMEOUT return estimates must align with backtest rows")
        if not np.isfinite(timeout_return_r).all():
            raise ValueError("Conditional TIMEOUT return estimates must be finite")
        support_upper = meta["barrier_upside_rate"] / meta["barrier_downside_rate"]
        bounded_timeout_return_r = np.minimum(
            np.maximum(timeout_return_r, -1.0),
            support_upper.to_numpy(float),
        )
        meta["timeout_return_r"] = bounded_timeout_return_r
        meta["timeout_gross_return_rate"] = bounded_timeout_return_r * meta["barrier_downside_rate"]
        timeout_return_source = "artifact_training_direction_median_r"
    else:
        meta["timeout_return_r"] = np.where(
            meta["barrier_downside_rate"] > 0,
            timeout_return_rate / meta["barrier_downside_rate"],
            0.0,
        )
        meta["timeout_gross_return_rate"] = timeout_return_rate
        timeout_return_source = "explicit_override" if not use_model_timeout_return else "fixed_fallback"

    is_long = meta["direction"].eq("LONG")
    fee_rate_per_leg = fee_rate_round_trip / 2.0
    (
        historical_recognized_funding,
        historical_adverse_funding,
        historical_realized_funding,
        historical_funding_schema,
    ) = historical_funding_components(meta, context="Backtest")
    override_funding_return = np.where(is_long, -funding_rate, funding_rate)
    override_recognized_funding = np.minimum(override_funding_return, 0.0)
    # Historical future settlements belong only to realized PnL. The explicit
    # CLI funding rate is an ex-ante adverse stress override and must not rewrite
    # realized historical cash flows.
    recognized_funding = override_recognized_funding
    adverse_funding = np.maximum(-override_recognized_funding, 0.0)
    realized_funding = historical_realized_funding
    meta["historical_funding_horizon_recognized_rate"] = historical_recognized_funding
    meta["historical_funding_horizon_adverse_rate"] = historical_adverse_funding
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
        1.0 + meta["timeout_gross_return_rate"],
        1.0 - meta["timeout_gross_return_rate"],
    )
    realized_exit_ratio = np.where(
        is_long,
        1.0 + meta["effective_realized_gross_return"],
        1.0 - meta["effective_realized_gross_return"],
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
    meta["funding_horizon_return_rate"] = recognized_funding
    meta["funding_return_rate"] = realized_funding
    meta["adverse_funding_rate"] = adverse_funding
    target_is_sl = meta["target"].eq("SL")
    meta["embedded_stop_gap_rate"] = np.where(
        target_is_sl,
        np.maximum(
            -meta["effective_realized_gross_return"] - meta["barrier_downside_rate"],
            0.0,
        ),
        0.0,
    )
    meta["unused_stop_gap_reserve_rate"] = np.where(
        target_is_sl,
        np.maximum(gap_rate - meta["embedded_stop_gap_rate"], 0.0),
        0.0,
    )
    meta["net_upside_rate"] = meta["barrier_upside_rate"] - tp_fee_rate - slippage_rate + recognized_funding
    meta["stress_downside_rate"] = (
        meta["barrier_downside_rate"] + sl_fee_rate + slippage_rate + gap_rate + adverse_funding
    )
    meta["timeout_net_rate"] = (
        meta["timeout_gross_return_rate"] - timeout_fee_rate - slippage_rate + recognized_funding
    )
    meta["sl_net_rate"] = (
        -(meta["barrier_downside_rate"] + sl_fee_rate + slippage_rate + gap_rate) + recognized_funding
    )
    meta["net_rr"] = np.where(
        meta["stress_downside_rate"] > 0,
        np.maximum(meta["net_upside_rate"], 0.0) / meta["stress_downside_rate"],
        0.0,
    )
    meta["expected_net_rate"] = (
        meta["p_tp"] * meta["net_upside_rate"]
        + meta["p_sl"] * meta["sl_net_rate"]
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
    chosen["traded"] = (chosen["net_rr"] >= minimum_net_rr) & (chosen["expected_ev_r"] >= minimum_net_ev_r)
    chosen["net_return"] = (
        chosen["effective_realized_gross_return"]
        - chosen["realized_fee_rate"]
        - slippage_rate
        + chosen["funding_return_rate"]
    )
    chosen["stress_net_return_with_stop_reserve"] = (
        chosen["net_return"] - chosen["unused_stop_gap_reserve_rate"]
    )
    actionable_trades = chosen[chosen["traded"]].copy()
    traded, overlap_blocked_trades = filter_single_active_trade_per_symbol(
        actionable_trades,
        context="Backtest",
    )

    (
        period_grid,
        observed_opportunity_period_count,
        omitted_unobserved_calendar_period_count,
    ) = _observed_policy_period_grid(
        chosen,
        horizon_hours=horizon_hours,
    )
    portfolio_evidence = _simulate_capital_sleeves_evidence(
        traded,
        return_column="net_return",
        horizon_hours=horizon_hours,
        period_grid=period_grid,
    )
    net_return = float(portfolio_evidence["net_return"])
    max_drawdown = float(portfolio_evidence["max_drawdown"])
    portfolio_periods = int(portfolio_evidence["portfolio_periods"])
    stress_return_with_stop_reserve, _, _ = _simulate_capital_sleeves(
        traded,
        return_column="stress_net_return_with_stop_reserve",
        horizon_hours=horizon_hours,
    )
    max_concurrent_trades, mean_concurrent_trades = _active_trade_statistics(traded)

    def stressed(multiplier: float) -> float:
        stressed_rows = traded.copy()
        stressed_gap_reserve = np.where(
            stressed_rows["target"].eq("SL"),
            np.maximum(
                gap_rate * multiplier - stressed_rows["embedded_stop_gap_rate"],
                0.0,
            ),
            0.0,
        )
        stressed_rows["stressed_net_return"] = (
            stressed_rows["effective_realized_gross_return"]
            - stressed_rows["realized_fee_rate"] * multiplier
            - slippage_rate * multiplier
            + np.where(
                stressed_rows["funding_return_rate"] < 0,
                stressed_rows["funding_return_rate"] * multiplier,
                stressed_rows["funding_return_rate"],
            )
            - stressed_gap_reserve
        )
        result, _, _ = _simulate_capital_sleeves(
            stressed_rows,
            return_column="stressed_net_return",
            horizon_hours=horizon_hours,
        )
        return result

    result = {
        "candidate_rows": int(len(chosen)),
        "actionable_candidates": int(len(actionable_trades)),
        "overlap_blocked_trades": int(overlap_blocked_trades),
        "trades": int(len(traded)),
        "no_trade_rate": float(1.0 - len(traded) / len(chosen)) if len(chosen) else 1.0,
        "net_return": net_return,
        "net_return_without_stop_gap_reserve": net_return,
        "stress_net_return_with_stop_gap_reserve": stress_return_with_stop_reserve,
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
        "stop_gap_reserve_accounting": "risk-and-stress-only-actual-gap-in-realized-v2",
        "funding_rate": funding_rate,
        "funding_rate_override": funding_rate,
        "historical_funding_schema": historical_funding_schema,
        "historical_funding_timeline_complete": historical_funding_schema is not None,
        "intrahorizon_margin_schema": intrahorizon_margin_schema,
        "intrahorizon_margin_complete": intrahorizon_margin_schema is not None,
        "research_leverage": int(research_leverage),
        "liquidation_equity_reserve_fraction": float(liquidation_equity_reserve_fraction),
        "liquidation_events": (
            int(traded["mark_liquidated"].sum()) if intrahorizon_margin_schema and len(traded) else 0
        ),
        "liquidation_rate": (
            float(traded["mark_liquidated"].mean()) if intrahorizon_margin_schema and len(traded) else 0.0
        ),
        "mark_max_adverse_excursion_mean": (
            float(traded["mark_max_adverse_excursion_rate"].mean())
            if intrahorizon_margin_schema and len(traded)
            else None
        ),
        "mark_max_favorable_excursion_mean": (
            float(traded["mark_max_favorable_excursion_rate"].mean())
            if intrahorizon_margin_schema and len(traded)
            else None
        ),
        "mark_minimum_equity_rate_min": (
            float(traded["mark_minimum_equity_rate"].min())
            if intrahorizon_margin_schema and len(traded)
            else None
        ),
        "timeout_return_rate": (
            timeout_return_rate if timeout_return_source != "artifact_training_direction_median_r" else None
        ),
        "timeout_return_source": timeout_return_source,
        "minimum_net_rr": minimum_net_rr,
        "minimum_net_ev_r": minimum_net_ev_r,
        "minimum_predicted_edge": minimum_net_ev_r,
        "minimum_predicted_edge_semantics": "deprecated_alias_of_minimum_net_ev_r",
        "stress_net_return_cost_x1_5": stressed(1.5),
        "stress_net_return_cost_x2": stressed(2.0),
        "warning": (
            "Barrier-policy research backtest with conservative hourly ambiguity and "
            "non-overlapping horizon capital sleeves and the live one-active-plan-per-symbol "
            "constraint. Realized paths include hourly Bybit mark-price OHLC under a "
            "conservative isolated-margin proxy; exact historical risk tiers, sub-hour mark "
            "paths, cross/portfolio margin, orderbook impact, partial fills and operator "
            "latency are not modeled. This is not evidence of profitability."
        ),
    }
    if include_experiment_evidence:
        result["experiment_evidence"] = {
            "schema": EXPERIMENT_PERIOD_RETURN_SCHEMA_VERSION,
            "period_returns": portfolio_evidence["period_returns"],
            "observed_opportunity_period_count": observed_opportunity_period_count,
            "covered_period_count": int(len(period_grid)),
            "omitted_unobserved_calendar_period_count": (
                omitted_unobserved_calendar_period_count
            ),
        }
    return result


async def run(args) -> None:
    started = datetime.now(UTC)
    settings = get_settings()
    trial_id = None
    experiment_family = None
    experiment_configuration: dict[str, object] | None = None
    try:
        symbols = settings.symbols if settings.universe_mode == "static" else None
        market_data = await load_training_market_data(
            symbols,
            lookback_days=None,
            max_symbols=0,
        )
        frame = market_data.candles
        runtime = load_validated_artifact(
            args.model,
            expected_sha256=getattr(args, "model_sha256", None),
        )
        assert runtime.bundle is not None
        assert runtime.horizon_hours is not None
        bundle = runtime.bundle
        artifact_horizon = runtime.horizon_hours
        if args.horizon is not None and args.horizon != artifact_horizon:
            raise ValueError(
                f"Requested horizon {args.horizon} does not match artifact horizon {artifact_horizon}"
            )
        horizon = artifact_horizon
        dataset = make_barrier_dataset(
            frame,
            horizon=horizon,
            stop_atr_multiplier=runtime.stop_atr_multiplier,
            tp_atr_multiplier=runtime.tp_atr_multiplier,
            entry_spread_bps=runtime.entry_spread_bps,
            funding_history=market_data.funding,
            funding_interval_minutes=market_data.funding_interval_minutes,
            funding_interval_history=market_data.funding_interval_history,
            require_funding_timeline=True,
            mark_candles=market_data.mark_candles,
            index_candles=market_data.index_candles,
            open_interest=market_data.open_interest,
            require_market_context=True,
            require_mark_timeline=True,
            liquidation_leverage=runtime.research_leverage,
            liquidation_equity_reserve_fraction=(runtime.liquidation_equity_reserve_fraction),
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
        timeout_return_rate = (
            args.timeout_return_rate
            if args.timeout_return_rate is not None
            else settings.timeout_gross_return_rate
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

        cohort_rows = (
            split.test_meta[["decision_time", "symbol"]]
            .drop_duplicates()
            .sort_values(["decision_time", "symbol"])
        )
        dataset_fingerprint = experiment_configuration_hash(
            {
                "schema": "backtest-test-cohort-v1",
                "horizon": horizon,
                "rows": [
                    [pd.Timestamp(row.decision_time).isoformat(), str(row.symbol)]
                    for row in cohort_rows.itertuples(index=False)
                ],
            }
        )
        experiment_family = args.experiment_family
        if not experiment_family:
            raise ValueError(
                "--experiment-family is required; prepare and register the family before its first trial"
            )
        experiment_configuration = {
            "schema": "barrier-policy-experiment-configuration-v1",
            "dataset_fingerprint": dataset_fingerprint,
            "model_version": runtime.version,
            "model_sha256": runtime.sha256,
            "feature_schema_version": bundle.get("feature_schema_version"),
            "label_path_schema_version": bundle.get("label_path_schema_version"),
            "temporal_split_schema": bundle.get("temporal_split_schema"),
            "entry_spread_bps": runtime.entry_spread_bps,
            "intrahorizon_margin_schema": bundle.get("intrahorizon_margin_schema"),
            "research_leverage": runtime.research_leverage,
            "liquidation_equity_reserve_fraction": runtime.liquidation_equity_reserve_fraction,
            "horizon": horizon,
            "round_trip_cost_bps": round_trip_cost_bps,
            "slippage_bps": slippage_bps,
            "stop_gap_reserve_bps": stop_gap_reserve_bps,
            "funding_rate_override": args.funding_rate,
            "timeout_return_rate_override": args.timeout_return_rate,
            "minimum_net_rr": minimum_net_rr,
            "minimum_net_ev_r": minimum_net_ev_r,
            "policy_source": "cost_aware_ev_r_v1",
            "portfolio_accounting": "horizon_sleeves_single_active_symbol_v2",
        }
        if args.prepare_preregistration:
            template = build_preregistration_template(
                experiment_family=experiment_family,
                configuration=experiment_configuration,
                search_parameters=tuple(args.search_parameter or ()),
                governance={
                    "pbo_segments": settings.experiment_pbo_segments,
                    "minimum_trials": settings.experiment_min_trials,
                    "minimum_periods": settings.experiment_min_periods,
                    "maximum_pbo": settings.experiment_max_pbo,
                    "minimum_dsr_probability": settings.experiment_min_dsr_probability,
                    "dependence_block_periods": settings.experiment_dependence_block_periods,
                    "minimum_independent_blocks": settings.experiment_min_independent_blocks,
                    "bootstrap_replicates": settings.research_bootstrap_replicates,
                    "confidence_level": settings.research_confidence_level,
                },
                created_at=datetime.now(UTC),
            )
            template_path = Path(args.prepare_preregistration)
            template_path.parent.mkdir(parents=True, exist_ok=True)
            template_path.write_text(
                json.dumps(template, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(
                json.dumps(
                    {
                        "status": "PREREGISTRATION_TEMPLATE_CREATED",
                        "output": str(template_path),
                        "warning": (
                            "Edit every placeholder and enumerate the complete search space, then "
                            "register the specification before running any trial."
                        ),
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return

        trial_id = uuid4()
        async with SessionFactory() as session:
            await append_experiment_event(
                session,
                trial_id=trial_id,
                experiment_family=experiment_family,
                event_type="STARTED",
                observed_at=started,
                configuration=experiment_configuration,
                evidence={"release_version": __version__},
            )
            await session.commit()

        model = bundle["model"]
        prediction_metrics = evaluate_model(model, split)
        trade_metrics = policy_backtest(
            model,
            split,
            round_trip_cost_bps=round_trip_cost_bps,
            slippage_bps=slippage_bps,
            stop_gap_reserve_bps=stop_gap_reserve_bps,
            funding_rate=args.funding_rate,
            timeout_return_rate=timeout_return_rate,
            use_model_timeout_return=args.timeout_return_rate is None,
            minimum_net_rr=minimum_net_rr,
            minimum_net_ev_r=minimum_net_ev_r,
            horizon_hours=horizon,
            research_leverage=runtime.research_leverage,
            liquidation_equity_reserve_fraction=(runtime.liquidation_equity_reserve_fraction),
            require_intrahorizon_margin=True,
            include_experiment_evidence=True,
        )
        experiment_evidence = dict(trade_metrics.pop("experiment_evidence"))
        metrics = {
            "prediction": prediction_metrics,
            "policy": trade_metrics,
            "hourly_continuity": dataset.attrs.get("hourly_continuity") or {},
            "artifact": runtime.metadata(),
            "experiment": {
                "trial_id": str(trial_id),
                "experiment_family": experiment_family,
                "configuration_hash": experiment_configuration_hash(experiment_configuration),
                "period_return_schema": experiment_evidence["schema"],
                "period_count": len(experiment_evidence["period_returns"]),
                "observed_opportunity_period_count": experiment_evidence[
                    "observed_opportunity_period_count"
                ],
                "covered_period_count": experiment_evidence["covered_period_count"],
                "omitted_unobserved_calendar_period_count": experiment_evidence[
                    "omitted_unobserved_calendar_period_count"
                ],
            },
        }
        output = Path(args.output or f"reports/backtest-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
        finished = datetime.now(UTC)
        async with SessionFactory() as session:
            session.add(
                BacktestRun(
                    name=f"barrier-policy-{bundle.get('model_type', 'model')}-h{horizon}",
                    configuration={
                        **experiment_configuration,
                        "experiment_trial_id": str(trial_id),
                        "experiment_family": experiment_family,
                        "experiment_configuration_hash": experiment_configuration_hash(
                            experiment_configuration
                        ),
                        "timeout_return_rate": timeout_return_rate,
                        "timeout_return_source": trade_metrics["timeout_return_source"],
                        "timeout_return_schema_version": bundle.get(
                            "timeout_return_schema_version"
                        ),
                        "settings_mode": settings.app_mode,
                    },
                    started_at=started,
                    finished_at=finished,
                    status="SUCCESS",
                    metrics=metrics,
                    artifact_path=str(output),
                )
            )
            await append_experiment_event(
                session,
                trial_id=trial_id,
                experiment_family=experiment_family,
                event_type="SUCCEEDED",
                observed_at=finished,
                configuration=experiment_configuration,
                evidence={
                    "period_return_schema": experiment_evidence["schema"],
                    "period_returns": experiment_evidence["period_returns"],
                    "observed_opportunity_period_count": experiment_evidence[
                        "observed_opportunity_period_count"
                    ],
                    "covered_period_count": experiment_evidence["covered_period_count"],
                    "omitted_unobserved_calendar_period_count": experiment_evidence[
                        "omitted_unobserved_calendar_period_count"
                    ],
                    "prediction_metrics": prediction_metrics,
                    "policy_metrics": trade_metrics,
                    "output_path": str(output),
                },
            )
            await session.commit()
        print(json.dumps({"output": str(output), "metrics": metrics}, indent=2, ensure_ascii=False))
    except Exception as exc:
        if trial_id is not None and experiment_family and experiment_configuration is not None:
            try:
                async with SessionFactory() as session:
                    await append_experiment_event(
                        session,
                        trial_id=trial_id,
                        experiment_family=experiment_family,
                        event_type="FAILED",
                        observed_at=datetime.now(UTC),
                        configuration=experiment_configuration,
                        evidence={
                            "error_type": type(exc).__name__,
                            "error_message": str(exc)[:500],
                        },
                    )
                    await session.commit()
            except Exception:
                pass
        raise
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--model-sha256",
        help="Optional expected SHA-256 for fail-closed artifact verification",
    )
    parser.add_argument("--horizon", type=int)
    parser.add_argument("--round-trip-cost-bps", type=float)
    parser.add_argument("--slippage-bps", type=float)
    parser.add_argument("--stop-gap-reserve-bps", type=float)
    parser.add_argument(
        "--funding-rate",
        type=float,
        default=0.0,
        help=(
            "Optional additional per-trade adverse funding stress. Historical settlement "
            "events from PostgreSQL are replayed independently."
        ),
    )
    parser.add_argument("--timeout-return-rate", type=float)
    parser.add_argument("--minimum-net-rr", type=float)
    parser.add_argument("--minimum-net-ev-r", type=float)
    parser.add_argument(
        "--minimum-predicted-edge",
        type=float,
        help="Deprecated alias for --minimum-net-ev-r",
    )
    parser.add_argument(
        "--experiment-family",
        help="Required immutable preregistered research family name.",
    )
    parser.add_argument(
        "--prepare-preregistration",
        metavar="PATH",
        help=(
            "Write an unevaluated preregistration template after deriving the exact final-test "
            "cohort and configuration, then exit before STARTED or model evaluation."
        ),
    )
    parser.add_argument(
        "--search-parameter",
        action="append",
        help=(
            "Configuration key to place in the enumerated search space of a generated template; "
            "repeat for each planned variable."
        ),
    )
    parser.add_argument("--output")
    run_with_compatible_event_loop(run(parser.parse_args()))


if __name__ == "__main__":
    main()

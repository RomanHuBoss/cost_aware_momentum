from __future__ import annotations

from app.ml.training import (
    POLICY_ACTIONABLE_CALIBRATION_SCHEMA,
    POLICY_CLUSTER_CORRELATION_THRESHOLD,
    POLICY_CLUSTER_MIN_SHARED_ACTIVE_OBSERVATIONS,
    POLICY_CLUSTER_ROBUSTNESS_SCHEMA,
    POLICY_DIRECTION_MIN_TRADES,
    POLICY_DIRECTION_ROBUSTNESS_SCHEMA,
    POLICY_INTERACTION_MIN_TRADES,
    POLICY_INTERACTION_ROBUSTNESS_SCHEMA,
    POLICY_INTERACTION_SPARSE_JACKKNIFE_SCHEMA,
    POLICY_METRIC_SCHEMA,
    POLICY_REGIME_MIN_TRADES,
    POLICY_REGIME_ROBUSTNESS_SCHEMA,
    POLICY_REGIME_TREND_SCORE_THRESHOLD,
    POLICY_REGIME_VOLATILITY_QUANTILE,
    POLICY_SYMBOL_ROBUSTNESS_SCHEMA,
)


def valid_policy_direction_robustness(
    *,
    policy_trades: int,
    policy_cohorts: int | None = None,
) -> dict[str, object]:
    if policy_trades < 0:
        raise ValueError("policy_trades must be non-negative")
    resolved_cohorts = policy_trades if policy_cohorts is None else policy_cohorts
    if resolved_cohorts < 0:
        raise ValueError("policy_cohorts must be non-negative")
    long_trades = policy_trades if policy_trades <= 1 else policy_trades // 2
    short_trades = policy_trades - long_trades
    directions: list[dict[str, object]] = []
    for direction, trades, mean_r, log_loss, brier in (
        ("LONG", long_trades, 0.03, 0.55, 0.28),
        ("SHORT", short_trades, 0.02, 0.60, 0.30),
    ):
        trade_cohorts = min(trades, resolved_cohorts)
        directions.append(
            {
                "direction": direction,
                "opportunities": resolved_cohorts,
                "trade_cohorts": trade_cohorts,
                "no_trade_cohorts": resolved_cohorts - trade_cohorts,
                "trades": trades,
                "trade_fraction": trades / policy_trades if policy_trades else 0.0,
                "realized_mean_r": mean_r if trades else 0.0,
                "calibration_rows": trades,
                "log_loss": log_loss if trades else None,
                "multiclass_brier": brier if trades else None,
            }
        )
    traded = [item for item in directions if int(item["trades"]) > 0]
    return {
        "schema": POLICY_DIRECTION_ROBUSTNESS_SCHEMA,
        "minimum_trades_per_traded_direction": POLICY_DIRECTION_MIN_TRADES,
        "opportunity_count": resolved_cohorts,
        "trade_count": policy_trades,
        "direction_count": len(directions),
        "traded_direction_count": len(traded),
        "worst_traded_direction_mean_r": (
            min(float(item["realized_mean_r"]) for item in traded) if traded else None
        ),
        "worst_traded_direction_log_loss": (
            max(float(item["log_loss"]) for item in traded) if traded else None
        ),
        "worst_traded_direction_multiclass_brier": (
            max(float(item["multiclass_brier"]) for item in traded) if traded else None
        ),
        "directions": directions,
    }

def valid_policy_symbol_robustness(*, policy_trades: int) -> dict[str, object]:
    if policy_trades < 0:
        raise ValueError("policy_trades must be non-negative")
    if policy_trades == 0:
        symbols: list[dict[str, object]] = []
    elif policy_trades == 1:
        symbols = [
            {
                "symbol": "BTCUSDT",
                "trades": 1,
                "trade_fraction": 1.0,
                "leave_one_symbol_out_policy_mean_r": 0.0,
            }
        ]
    elif policy_trades == 2:
        symbols = [
            {
                "symbol": "BTCUSDT",
                "trades": 1,
                "trade_fraction": 0.5,
                "leave_one_symbol_out_policy_mean_r": 0.02,
            },
            {
                "symbol": "ETHUSDT",
                "trades": 1,
                "trade_fraction": 0.5,
                "leave_one_symbol_out_policy_mean_r": 0.01,
            },
        ]
    else:
        first = policy_trades // 3
        second = policy_trades // 3
        third = policy_trades - first - second
        symbols = [
            {
                "symbol": "BTCUSDT",
                "trades": first,
                "trade_fraction": first / policy_trades,
                "leave_one_symbol_out_policy_mean_r": 0.03,
            },
            {
                "symbol": "ETHUSDT",
                "trades": second,
                "trade_fraction": second / policy_trades,
                "leave_one_symbol_out_policy_mean_r": 0.02,
            },
            {
                "symbol": "SOLUSDT",
                "trades": third,
                "trade_fraction": third / policy_trades,
                "leave_one_symbol_out_policy_mean_r": 0.01,
            },
        ]
    return {
        "schema": POLICY_SYMBOL_ROBUSTNESS_SCHEMA,
        "symbol_count": len(symbols),
        "trade_count": policy_trades,
        "max_symbol_trade_fraction": (
            max(float(item["trade_fraction"]) for item in symbols) if symbols else 0.0
        ),
        "leave_one_symbol_out_mean_r_min": (
            min(float(item["leave_one_symbol_out_policy_mean_r"]) for item in symbols)
            if symbols
            else None
        ),
        "symbols": symbols,
    }


def valid_policy_cluster_robustness(*, policy_trades: int) -> dict[str, object]:
    if policy_trades < 0:
        raise ValueError("policy_trades must be non-negative")
    if policy_trades == 0:
        clusters: list[dict[str, object]] = []
        symbol_count = 0
    elif policy_trades == 1:
        clusters = [
            {
                "cluster_id": "cluster-001",
                "symbols": ["BTCUSDT"],
                "trades": 1,
                "trade_fraction": 1.0,
                "leave_one_cluster_out_policy_mean_r": 0.0,
            }
        ]
        symbol_count = 1
    else:
        first = policy_trades // 2
        second = policy_trades - first
        clusters = [
            {
                "cluster_id": "cluster-001",
                "symbols": ["BTCUSDT", "ETHUSDT"],
                "trades": first,
                "trade_fraction": first / policy_trades,
                "leave_one_cluster_out_policy_mean_r": 0.02,
            },
            {
                "cluster_id": "cluster-002",
                "symbols": ["SOLUSDT"],
                "trades": second,
                "trade_fraction": second / policy_trades,
                "leave_one_cluster_out_policy_mean_r": 0.01,
            },
        ]
        symbol_count = 3
    return {
        "schema": POLICY_CLUSTER_ROBUSTNESS_SCHEMA,
        "correlation_threshold": POLICY_CLUSTER_CORRELATION_THRESHOLD,
        "minimum_shared_active_observations": (
            POLICY_CLUSTER_MIN_SHARED_ACTIVE_OBSERVATIONS
        ),
        "symbol_count": symbol_count,
        "cluster_count": len(clusters),
        "trade_count": policy_trades,
        "max_cluster_trade_fraction": (
            max(float(item["trade_fraction"]) for item in clusters) if clusters else 0.0
        ),
        "leave_one_cluster_out_mean_r_min": (
            min(float(item["leave_one_cluster_out_policy_mean_r"]) for item in clusters)
            if clusters
            else None
        ),
        "clusters": clusters,
    }



def valid_policy_regime_robustness(
    *,
    policy_trades: int,
    policy_cohorts: int | None = None,
) -> dict[str, object]:
    if policy_trades < 0:
        raise ValueError("policy_trades must be non-negative")
    resolved_cohorts = policy_trades if policy_cohorts is None else policy_cohorts
    if resolved_cohorts < 0:
        raise ValueError("policy_cohorts must be non-negative")
    regimes: list[dict[str, object]] = []
    if resolved_cohorts > 0:
        if policy_trades <= 1 or resolved_cohorts <= 1:
            definitions = [("RANGE", resolved_cohorts, policy_trades, 0.02, 0.60, 0.30)]
        else:
            first_trades = policy_trades // 2
            second_trades = policy_trades - first_trades
            first_opportunities = max(1, resolved_cohorts // 2)
            second_opportunities = resolved_cohorts - first_opportunities
            if second_opportunities == 0:
                definitions = [("RANGE", resolved_cohorts, policy_trades, 0.02, 0.60, 0.30)]
            else:
                definitions = [
                    ("RANGE", first_opportunities, first_trades, 0.02, 0.60, 0.30),
                    ("UPTREND", second_opportunities, second_trades, 0.03, 0.55, 0.28),
                ]
        for regime, opportunities, trades, mean_r, log_loss, brier in definitions:
            trade_cohorts = min(trades, opportunities)
            regimes.append(
                {
                    "regime": regime,
                    "opportunities": opportunities,
                    "trade_cohorts": trade_cohorts,
                    "no_trade_cohorts": opportunities - trade_cohorts,
                    "trades": trades,
                    "trade_fraction": trades / policy_trades if policy_trades else 0.0,
                    "realized_mean_r": mean_r if trades else 0.0,
                    "calibration_rows": trades,
                    "log_loss": log_loss if trades else None,
                    "multiclass_brier": brier if trades else None,
                }
            )
    traded = [item for item in regimes if int(item["trades"]) > 0]
    return {
        "schema": POLICY_REGIME_ROBUSTNESS_SCHEMA,
        "volatility_quantile": POLICY_REGIME_VOLATILITY_QUANTILE,
        "development_high_volatility_atr_pct_threshold": 0.03,
        "trend_score_threshold": POLICY_REGIME_TREND_SCORE_THRESHOLD,
        "minimum_trades_per_traded_regime": POLICY_REGIME_MIN_TRADES,
        "opportunity_count": resolved_cohorts,
        "trade_count": policy_trades,
        "regime_count": len(regimes),
        "traded_regime_count": len(traded),
        "worst_traded_regime_mean_r": (
            min(float(item["realized_mean_r"]) for item in traded) if traded else None
        ),
        "worst_traded_regime_log_loss": (
            max(float(item["log_loss"]) for item in traded) if traded else None
        ),
        "worst_traded_regime_multiclass_brier": (
            max(float(item["multiclass_brier"]) for item in traded) if traded else None
        ),
        "regimes": regimes,
    }


def valid_policy_interaction_robustness(*, policy_trades: int) -> dict[str, object]:
    if policy_trades < 0:
        raise ValueError("policy_trades must be non-negative")
    symbol_evidence = valid_policy_symbol_robustness(policy_trades=policy_trades)
    direction_evidence = valid_policy_direction_robustness(
        policy_trades=policy_trades,
        policy_cohorts=policy_trades,
    )
    regime_evidence = valid_policy_regime_robustness(
        policy_trades=policy_trades,
        policy_cohorts=policy_trades,
    )
    symbols = [str(item["symbol"]) for item in symbol_evidence["symbols"]]
    directions = [
        str(item["direction"])
        for item in direction_evidence["directions"]
        if int(item["trades"]) > 0
    ]
    regimes = [
        str(item["regime"])
        for item in regime_evidence["regimes"]
        if int(item["trades"]) > 0
    ]
    if policy_trades == 0:
        cells: list[dict[str, object]] = []
    else:
        cell_count = max(len(symbols), len(directions), len(regimes))
        base, remainder = divmod(policy_trades, cell_count)
        cells = []
        for index in range(cell_count):
            trades = base + (1 if index < remainder else 0)
            cells.append(
                {
                    "symbol": symbols[index % len(symbols)],
                    "direction": directions[index % len(directions)],
                    "regime": regimes[index % len(regimes)],
                    "support": (
                        "SUPPORTED"
                        if trades >= POLICY_INTERACTION_MIN_TRADES
                        else "SPARSE"
                    ),
                    "trades": trades,
                    "trade_fraction": trades / policy_trades,
                    "realized_trade_mean_r": 0.03,
                    "calibration_rows": trades,
                    "log_loss": 0.60,
                    "multiclass_brier": 0.30,
                }
            )
        direction_order = {name: index for index, name in enumerate(("LONG", "SHORT"))}
        regime_order = {
            name: index
            for index, name in enumerate(
                ("DOWNTREND", "RANGE", "UPTREND", "HIGH_VOLATILITY")
            )
        }
        cells.sort(
            key=lambda item: (
                str(item["symbol"]),
                direction_order[str(item["direction"])],
                regime_order[str(item["regime"])],
            )
        )
    supported = [item for item in cells if item["support"] == "SUPPORTED"]
    sparse = [item for item in cells if item["support"] == "SPARSE"]
    sparse_trades = sum(int(item["trades"]) for item in sparse)
    sparse_pool = None
    if sparse:
        leave_one_cell_out: list[dict[str, object]] = []
        for omitted in sparse:
            residual = [item for item in sparse if item is not omitted]
            residual_trades = sum(int(item["trades"]) for item in residual)
            leave_one_cell_out.append(
                {
                    "omitted_symbol": omitted["symbol"],
                    "omitted_direction": omitted["direction"],
                    "omitted_regime": omitted["regime"],
                    "omitted_trades": omitted["trades"],
                    "residual_trades": residual_trades,
                    "residual_trade_fraction_of_sparse_pool": (
                        residual_trades / sparse_trades
                    ),
                    "residual_realized_trade_mean_r": 0.03 if residual_trades else None,
                    "calibration_rows": residual_trades,
                    "log_loss": 0.60 if residual_trades else None,
                    "multiclass_brier": 0.30 if residual_trades else None,
                }
            )
        nonempty = [
            item for item in leave_one_cell_out if int(item["residual_trades"]) > 0
        ]
        sparse_pool = {
            "cell_count": len(sparse),
            "trades": sparse_trades,
            "trade_fraction": sparse_trades / policy_trades,
            "realized_trade_mean_r": 0.03,
            "calibration_rows": sparse_trades,
            "log_loss": 0.60,
            "multiclass_brier": 0.30,
            "jackknife_schema": POLICY_INTERACTION_SPARSE_JACKKNIFE_SCHEMA,
            "minimum_residual_trades": POLICY_INTERACTION_MIN_TRADES,
            "leave_one_cell_out_count": len(leave_one_cell_out),
            "minimum_leave_one_cell_out_residual_trades": min(
                int(item["residual_trades"]) for item in leave_one_cell_out
            ),
            "worst_leave_one_cell_out_mean_r": 0.03 if nonempty else None,
            "worst_leave_one_cell_out_log_loss": 0.60 if nonempty else None,
            "worst_leave_one_cell_out_multiclass_brier": 0.30 if nonempty else None,
            "leave_one_cell_out": leave_one_cell_out,
        }
    buckets = [*supported, *([sparse_pool] if sparse_pool else [])]
    return {
        "schema": POLICY_INTERACTION_ROBUSTNESS_SCHEMA,
        "minimum_trades_per_supported_cell": POLICY_INTERACTION_MIN_TRADES,
        "trade_count": policy_trades,
        "observed_cell_count": len(cells),
        "supported_cell_count": len(supported),
        "sparse_cell_count": len(sparse),
        "supported_trade_count": sum(int(item["trades"]) for item in supported),
        "sparse_trade_count": sparse_trades,
        "tested_bucket_count": len(buckets),
        "worst_tested_bucket_mean_r": 0.03 if buckets else None,
        "worst_tested_bucket_log_loss": 0.60 if buckets else None,
        "worst_tested_bucket_multiclass_brier": 0.30 if buckets else None,
        "cells": cells,
        "sparse_pool": sparse_pool,
    }

def valid_runtime_policy_metrics(*, policy_trades: int = 1) -> dict[str, object]:
    """Return the minimum current policy evidence required by ModelRuntime."""
    if policy_trades < 0:
        raise ValueError("policy_trades must be non-negative")
    return {
        "policy_metric_schema": POLICY_METRIC_SCHEMA,
        "policy_trades": policy_trades,
        "policy_direction_robustness": valid_policy_direction_robustness(
            policy_trades=policy_trades,
            policy_cohorts=policy_trades,
        ),
        "policy_symbol_robustness": valid_policy_symbol_robustness(
            policy_trades=policy_trades
        ),
        "policy_cluster_robustness": valid_policy_cluster_robustness(
            policy_trades=policy_trades
        ),
        "policy_cohorts": policy_trades,
        "policy_regime_robustness": valid_policy_regime_robustness(
            policy_trades=policy_trades,
            policy_cohorts=policy_trades,
        ),
        "policy_interaction_robustness": valid_policy_interaction_robustness(
            policy_trades=policy_trades
        ),
        "policy_actionable_calibration_schema": POLICY_ACTIONABLE_CALIBRATION_SCHEMA,
        "policy_actionable_calibration_rows": policy_trades,
        "policy_actionable_log_loss": 0.60 if policy_trades else None,
        "policy_actionable_multiclass_brier": 0.30 if policy_trades else None,
    }

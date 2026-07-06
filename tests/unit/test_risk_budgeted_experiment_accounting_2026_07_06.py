from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.backtest import (
    _simulate_capital_sleeves_evidence,
    _simulate_risk_budgeted_portfolio_evidence,
)


def _path(start: pd.Timestamp, end: pd.Timestamp, terminal_return: float) -> list[dict[str, object]]:
    return [
        {"timestamp": start.isoformat(), "return": 0.0},
        {"timestamp": end.isoformat(), "return": terminal_return},
    ]


def test_risk_budgeted_accounting_matches_live_risk_sizing_not_equal_notional() -> None:
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    end = start + pd.Timedelta(1, unit="h")
    trades = pd.DataFrame(
        [
            {
                "decision_time": start,
                "exit_time": end,
                "stress_downside_rate": 0.01,
                "net_return": 0.02,
                "intrahorizon_net_return_path": _path(start, end, 0.02),
            },
            {
                "decision_time": start,
                "exit_time": end,
                "stress_downside_rate": 0.10,
                "net_return": -0.05,
                "intrahorizon_net_return_path": _path(start, end, -0.05),
            },
        ]
    )
    grid = pd.date_range(start, end, freq="h")

    equal_notional = _simulate_capital_sleeves_evidence(
        trades,
        return_column="net_return",
        horizon_hours=1,
        period_grid=grid,
    )
    risk_budgeted = _simulate_risk_budgeted_portfolio_evidence(
        trades,
        return_column="net_return",
        risk_rate=0.0035,
        max_total_open_risk_rate=0.02,
        research_leverage=3,
        margin_reserve_rate=0.20,
        period_grid=grid,
    )

    # Equal-notional accounting reports a loss: (2% - 5%) / 2.
    assert equal_notional["net_return"] == pytest.approx(-0.015)
    # Live-style equal-risk sizing allocates 0.35% stress risk to each trade:
    # 0.0035 / 0.01 * 0.02 + 0.0035 / 0.10 * -0.05 = +0.00525.
    assert risk_budgeted["net_return"] == pytest.approx(0.00525)
    assert risk_budgeted["allocated_trades"] == 2
    assert risk_budgeted["risk_limited_trades"] == 0
    assert risk_budgeted["margin_limited_trades"] == 0
    values = np.asarray([row["return"] for row in risk_budgeted["period_returns"]])
    assert np.prod(1.0 + values) - 1.0 == pytest.approx(risk_budgeted["net_return"])


def test_risk_budgeted_accounting_scales_new_cohort_to_remaining_open_risk() -> None:
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    second = start + pd.Timedelta(1, unit="h")
    end = start + pd.Timedelta(2, unit="h")
    trades = pd.DataFrame(
        [
            {
                "decision_time": start,
                "exit_time": end,
                "stress_downside_rate": 0.10,
                "net_return": 0.0,
                "intrahorizon_net_return_path": [
                    {"timestamp": start.isoformat(), "return": 0.0},
                    {"timestamp": second.isoformat(), "return": 0.0},
                    {"timestamp": end.isoformat(), "return": 0.0},
                ],
            },
            {
                "decision_time": second,
                "exit_time": end,
                "stress_downside_rate": 0.10,
                "net_return": 0.10,
                "intrahorizon_net_return_path": _path(second, end, 0.10),
            },
        ]
    )
    grid = pd.date_range(start, end, freq="h")

    evidence = _simulate_risk_budgeted_portfolio_evidence(
        trades,
        return_column="net_return",
        risk_rate=0.015,
        max_total_open_risk_rate=0.02,
        research_leverage=3,
        margin_reserve_rate=0.20,
        period_grid=grid,
    )

    # First trade reserves 1.5% risk. The overlapping second trade receives only
    # the remaining 0.5%, so 0.005 / 0.10 notional earns 10% = 0.5% capital.
    assert evidence["net_return"] == pytest.approx(0.005)
    assert evidence["risk_limited_trades"] == 1
    assert evidence["max_reserved_risk_rate"] == pytest.approx(0.02)


def test_risk_budgeted_accounting_scales_cohort_to_margin_capacity() -> None:
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    end = start + pd.Timedelta(1, unit="h")
    trades = pd.DataFrame(
        [
            {
                "decision_time": start,
                "exit_time": end,
                "stress_downside_rate": 0.001,
                "net_return": 0.10,
                "intrahorizon_net_return_path": _path(start, end, 0.10),
            },
            {
                "decision_time": start,
                "exit_time": end,
                "stress_downside_rate": 0.001,
                "net_return": 0.10,
                "intrahorizon_net_return_path": _path(start, end, 0.10),
            },
        ]
    )

    evidence = _simulate_risk_budgeted_portfolio_evidence(
        trades,
        return_column="net_return",
        risk_rate=0.01,
        max_total_open_risk_rate=0.10,
        research_leverage=1,
        margin_reserve_rate=0.50,
        period_grid=pd.date_range(start, end, freq="h"),
    )

    # Desired total notional is 20x capital, but the one-times leverage account
    # with a 50% reserve can deploy only 0.5x. Both trades are scaled equally.
    assert evidence["net_return"] == pytest.approx(0.05)
    assert evidence["margin_limited_trades"] == 2
    assert evidence["risk_limited_trades"] == 0
    assert evidence["max_margin_utilization_rate"] == pytest.approx(1.0)


def test_exit_releases_risk_before_same_boundary_reentry() -> None:
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    boundary = start + pd.Timedelta(1, unit="h")
    end = start + pd.Timedelta(2, unit="h")
    trades = pd.DataFrame(
        [
            {
                "decision_time": start,
                "exit_time": boundary,
                "stress_downside_rate": 0.10,
                "net_return": 0.10,
                "intrahorizon_net_return_path": _path(start, boundary, 0.10),
            },
            {
                "decision_time": boundary,
                "exit_time": end,
                "stress_downside_rate": 0.10,
                "net_return": 0.10,
                "intrahorizon_net_return_path": _path(boundary, end, 0.10),
            },
        ]
    )

    evidence = _simulate_risk_budgeted_portfolio_evidence(
        trades,
        return_column="net_return",
        risk_rate=0.02,
        max_total_open_risk_rate=0.02,
        research_leverage=3,
        margin_reserve_rate=0.20,
        period_grid=pd.date_range(start, end, freq="h"),
    )

    # The first 2% risk reservation is released after its boundary PnL and before
    # the second entry is sized. Both cohorts therefore receive their full budget.
    assert evidence["net_return"] == pytest.approx((1.0 + 0.02) ** 2 - 1.0)
    assert evidence["risk_limited_trades"] == 0
    assert [item["scale"] for item in evidence["allocations"]] == pytest.approx([1.0, 1.0])

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from app.ml.mtm import (
    INTRAHORIZON_MARGIN_SCHEMA_VERSION,
    INTRAHORIZON_MTM_PATH_SCHEMA_VERSION,
)
from app.ml.training import (
    MODEL_FEATURE_NAMES,
    apply_intrahorizon_margin_path,
    chronological_split,
    historical_funding_components,
    validate_intrahorizon_mark_to_market_path,
    validate_policy_evaluation_metadata,
)

POLICY_PATH_COLUMNS = {
    "historical_funding_timeline_complete",
    "historical_funding_horizon_rate",
    "historical_funding_horizon_settlements",
    "historical_funding_realized_rate",
    "historical_funding_realized_settlements",
    "intrahorizon_margin_path_complete",
    "intrahorizon_margin_schema",
    "research_leverage",
    "liquidation_equity_reserve_fraction",
    "mark_max_adverse_excursion_rate",
    "mark_max_favorable_excursion_rate",
    "mark_minimum_equity_rate",
    "mark_liquidated",
    "margin_path_exit_index",
    "margin_path_exit_at_open",
    "margin_path_exit_time",
    "margin_path_realized_gross_return",
    "historical_funding_margin_path_rate",
    "historical_funding_margin_path_settlements",
    "intrahorizon_mark_to_market_path_complete",
    "intrahorizon_mark_to_market_schema",
    "intrahorizon_mark_to_market_path",
}


def _policy_dataset() -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    for hour in range(520):
        decision_time = start + timedelta(hours=hour)
        for direction, direction_code in (("LONG", 1.0), ("SHORT", -1.0)):
            row: dict[str, object] = {name: 0.1 for name in MODEL_FEATURE_NAMES}
            row["scenario_direction"] = direction_code
            row.update(
                {
                    "decision_time": decision_time,
                    "open_time": decision_time - timedelta(hours=1),
                    "label_end_time": decision_time + timedelta(hours=8),
                    "symbol": "TESTUSDT",
                    "direction": direction,
                    "target": "TIMEOUT",
                    "ambiguous": False,
                    "exit_index": 7,
                    "exit_at_open": False,
                    "realized_gross_return": 0.001 if direction == "LONG" else -0.001,
                    "barrier_upside_rate": 0.02,
                    "barrier_downside_rate": 0.01,
                    "historical_funding_timeline_complete": True,
                    "historical_funding_horizon_rate": 0.0001,
                    "historical_funding_horizon_settlements": 1,
                    "historical_funding_realized_rate": 0.0001,
                    "historical_funding_realized_settlements": 1,
                    "intrahorizon_margin_path_complete": True,
                    "intrahorizon_margin_schema": INTRAHORIZON_MARGIN_SCHEMA_VERSION,
                    "research_leverage": 3,
                    "liquidation_equity_reserve_fraction": 0.10,
                    "mark_max_adverse_excursion_rate": 0.002,
                    "mark_max_favorable_excursion_rate": 0.003,
                    "mark_minimum_equity_rate": 0.32,
                    "mark_liquidated": False,
                    "margin_path_exit_index": 7,
                    "margin_path_exit_at_open": False,
                    "margin_path_exit_time": decision_time + timedelta(hours=8),
                    "margin_path_realized_gross_return": (
                        0.001 if direction == "LONG" else -0.001
                    ),
                    "historical_funding_margin_path_rate": 0.0001,
                    "historical_funding_margin_path_settlements": 1,
                    "intrahorizon_mark_to_market_path_complete": True,
                    "intrahorizon_mark_to_market_schema": (
                        INTRAHORIZON_MTM_PATH_SCHEMA_VERSION
                    ),
                    "intrahorizon_mark_to_market_path": [
                        {
                            "timestamp": (decision_time + timedelta(hours=step)).isoformat(),
                            "gross_return_rate": (
                                (0.001 if direction == "LONG" else -0.001) * step / 8
                            ),
                            "funding_return_rate": (
                                (-0.0001 if direction == "LONG" else 0.0001) * step / 8
                            ),
                        }
                        for step in range(9)
                    ],
                }
            )
            rows.append(row)
    return pd.DataFrame.from_records(rows)


def test_chronological_split_preserves_policy_path_metadata() -> None:
    split = chronological_split(_policy_dataset(), purge_rows=8)

    assert POLICY_PATH_COLUMNS.issubset(split.test_meta.columns)
    base = validate_policy_evaluation_metadata(
        split.test_meta,
        context="Policy evaluation",
        horizon_hours=8,
        require_barrier_return_consistency=True,
    )
    validated, schema = apply_intrahorizon_margin_path(
        base,
        context="Policy evaluation",
        require=True,
        expected_leverage=3,
        expected_equity_reserve_fraction=0.10,
    )
    validated, mtm_schema = validate_intrahorizon_mark_to_market_path(
        validated,
        context="Policy evaluation",
        require=True,
    )
    _, _, _, funding_schema = historical_funding_components(
        validated,
        context="Policy evaluation",
    )

    assert schema == INTRAHORIZON_MARGIN_SCHEMA_VERSION
    assert mtm_schema == INTRAHORIZON_MTM_PATH_SCHEMA_VERSION
    assert funding_schema is not None
    assert validated["historical_funding_realized_settlements"].eq(1).all()

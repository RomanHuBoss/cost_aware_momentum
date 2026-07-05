from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import joblib
import numpy as np
import pandas as pd
import pytest

import app.risk.math as risk_math
import app.services.execution as execution
from app.config import Settings
from app.ml.data_profile import profile_from_symbol_rows
from app.ml.labels import triple_barrier_outcome
from app.ml.lifecycle import ModelCandidate, evaluate_quality_gate
from app.ml.runtime import ModelRuntime
from app.ml.training import (
    LABEL_PATH_SCHEMA_VERSION,
    MODEL_FEATURE_NAMES,
    MODEL_FEATURE_SCHEMA_VERSION,
    OUTCOME_CLASSES,
    TEMPORAL_SPLIT_SCHEMA_VERSION,
    TIMEOUT_RETURN_SCHEMA_VERSION,
    WALK_FORWARD_SCHEMA_VERSION,
    DatasetSplit,
    PolicyEvaluationConfig,
    evaluate_policy_model,
)
from scripts.backtest import _active_trade_statistics, policy_backtest
from tests.drift_reference import valid_production_drift_reference

D = Decimal


class AuditArtifactModel:
    classes_ = list(OUTCOME_CLASSES)

    def predict_proba(self, values: np.ndarray) -> np.ndarray:
        return np.repeat([[0.4, 0.3, 0.3]], len(values), axis=0)

    def predict_timeout_return_r(self, values: np.ndarray) -> np.ndarray:
        return np.zeros(len(values), dtype=float)


class RowProbabilityModel:
    classes_ = OUTCOME_CLASSES

    def __init__(self, probabilities: np.ndarray) -> None:
        self.probabilities = np.asarray(probabilities, dtype=float)

    def predict_proba(self, values: np.ndarray) -> np.ndarray:
        assert len(values) == len(self.probabilities)
        return self.probabilities.copy()


def _split(meta: pd.DataFrame, probabilities: np.ndarray) -> tuple[DatasetSplit, RowProbabilityModel]:
    meta = meta.copy()
    if "exit_at_open" not in meta.columns:
        meta["exit_at_open"] = False
    values = np.zeros((len(meta), len(MODEL_FEATURE_NAMES)), dtype=float)
    values[:, -1] = np.where(meta["direction"].eq("LONG"), 1.0, -1.0)
    targets = meta["target"].astype(str).to_numpy()
    split = DatasetSplit(values, targets, values, targets, values, targets, meta)
    return split, RowProbabilityModel(probabilities)


def _policy_config() -> PolicyEvaluationConfig:
    return PolicyEvaluationConfig(
        fee_rate_round_trip=0.0,
        slippage_rate=0.0,
        stop_gap_reserve_rate=0.0,
        min_net_rr=0.0,
        min_net_ev_r=-100.0,
        timeout_return_rate=0.0,
    )


def _pair(*, short_target: str = "SL", short_gross: float = -0.01) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return pd.DataFrame(
        [
            {
                "decision_time": start,
                "label_end_time": start + timedelta(hours=1),
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "target": "TP",
                "exit_index": 0,
                "exit_at_open": False,
                "realized_gross_return": 0.02,
                "barrier_upside_rate": 0.02,
                "barrier_downside_rate": 0.01,
            },
            {
                "decision_time": start,
                "label_end_time": start + timedelta(hours=1),
                "symbol": "BTCUSDT",
                "direction": "SHORT",
                "target": short_target,
                "exit_index": 0,
                "exit_at_open": False,
                "realized_gross_return": short_gross,
                "barrier_upside_rate": 0.01,
                "barrier_downside_rate": 0.01,
            },
        ]
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"fee_rate_taker": -0.001},
        {"fee_rate_taker": float("nan")},
        {"base_slippage_bps": -1.0},
        {"stop_gap_reserve_bps": -1.0},
        {"default_risk_rate": 0.0},
        {"default_risk_rate": float("nan")},
        {"default_risk_rate": 0.03, "max_total_open_risk_rate": 0.02},
        {"max_total_open_risk_rate": 1.01},
        {"margin_reserve_rate": 1.0},
        {"max_ticker_age_seconds": 0},
        {"max_candle_age_seconds": 0},
        {"signal_ttl_minutes": 0},
    ],
)
def test_settings_reject_quantitatively_unsafe_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        Settings(database_url="postgresql+psycopg://u:p@localhost/db", **overrides)


def test_pretrade_funding_charges_long_but_does_not_credit_short_without_exit_time() -> None:
    costs = risk_math.CostScenario(D("0"), D("0"), D("0"), D("0.01"))

    long = risk_math.net_rr_and_ev(
        entry=D("100"),
        stop=D("98"),
        take_profit=D("104"),
        direction="LONG",
        costs=costs,
        p_tp=1.0,
        p_sl=0.0,
        p_timeout=0.0,
    )
    short = risk_math.net_rr_and_ev(
        entry=D("100"),
        stop=D("102"),
        take_profit=D("96"),
        direction="SHORT",
        costs=costs,
        p_tp=1.0,
        p_sl=0.0,
        p_timeout=0.0,
    )

    assert long[3] == D("0.03")
    assert short[3] == D("0.04")


def test_favorable_funding_does_not_reduce_pretrade_sl_loss_without_exit_time() -> None:
    costs = risk_math.CostScenario(D("0"), D("0"), D("0"), D("0.01"))
    rr, ev_r, downside, upside = risk_math.net_rr_and_ev(
        entry=D("100"),
        stop=D("102"),
        take_profit=D("96"),
        direction="SHORT",
        costs=costs,
        p_tp=0.0,
        p_sl=1.0,
        p_timeout=0.0,
    )

    assert downside == D("0.02")
    assert ev_r == D("-1")
    assert rr == D("2")
    assert upside == D("0.04")


def test_backtest_does_not_credit_favorable_funding_without_settlement_timestamps() -> None:
    meta = _pair(short_target="TP", short_gross=0.02)
    meta.loc[1, "barrier_upside_rate"] = 0.02
    probabilities = np.asarray([[0.1, 0.8, 0.1], [1.0, 0.0, 0.0]])
    split, model = _split(meta, probabilities)

    result = policy_backtest(
        model,
        split,
        round_trip_cost_bps=0.0,
        stop_gap_reserve_bps=0.0,
        funding_rate=0.01,
        minimum_net_ev_r=-100.0,
    )

    assert result["mean_net_return_per_trade"] == pytest.approx(0.02)


def test_policy_evaluation_rejects_unsupported_target_before_direction_selection() -> None:
    meta = _pair(short_target="CORRUPT", short_gross=-0.01)
    probabilities = np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    split, model = _split(meta, probabilities)

    with pytest.raises(ValueError, match="target|outcome"):
        evaluate_policy_model(model, split, _policy_config())


def test_policy_evaluation_rejects_non_finite_barrier_before_direction_selection() -> None:
    meta = _pair()
    meta.loc[1, "barrier_upside_rate"] = float("nan")
    probabilities = np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    split, model = _split(meta, probabilities)

    with pytest.raises(ValueError, match="finite|barrier"):
        evaluate_policy_model(model, split, _policy_config())


def test_backtest_rejects_tp_return_inconsistent_with_barrier() -> None:
    meta = _pair()
    meta.loc[0, "realized_gross_return"] = 0.90
    probabilities = np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    split, model = _split(meta, probabilities)

    with pytest.raises(ValueError, match="inconsistent|barrier"):
        policy_backtest(
            model,
            split,
            round_trip_cost_bps=0.0,
            stop_gap_reserve_bps=0.0,
            minimum_net_ev_r=-100.0,
        )


def test_backtest_rejects_exit_beyond_label_availability() -> None:
    meta = _pair()
    meta["label_end_time"] = pd.Timestamp(meta.loc[0, "decision_time"]) + timedelta(minutes=30)
    probabilities = np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    split, model = _split(meta, probabilities)

    with pytest.raises(ValueError, match="label availability"):
        policy_backtest(
            model,
            split,
            round_trip_cost_bps=0.0,
            stop_gap_reserve_bps=0.0,
            minimum_net_ev_r=-100.0,
        )


def test_mean_concurrent_trades_includes_idle_time() -> None:
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    trades = pd.DataFrame(
        {
            "decision_time": [start, start + timedelta(hours=9)],
            "exit_time": [start + timedelta(hours=1), start + timedelta(hours=10)],
        }
    )

    maximum, mean = _active_trade_statistics(trades)

    assert maximum == 1
    assert mean == pytest.approx(0.2)


def test_triple_barrier_rejects_empty_future_window() -> None:
    with pytest.raises(ValueError, match="future|empty"):
        triple_barrier_outcome(
            pd.DataFrame(columns=["open", "high", "low", "close"]),
            direction="LONG",
            stop=98.0,
            take_profit=102.0,
        )


def test_triple_barrier_rejects_inverted_directional_barriers() -> None:
    bars = pd.DataFrame([{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}])
    with pytest.raises(ValueError, match="geometry|stop|take_profit"):
        triple_barrier_outcome(
            bars,
            direction="LONG",
            stop=105.0,
            take_profit=102.0,
        )


def _candidate(tmp_path: Path, metrics: dict[str, object]) -> ModelCandidate:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    profile = profile_from_symbol_rows(
        [("BTCUSDT", 500, now, now)],
        unique_timestamps=500,
        minimum_rows_for_coverage=300,
    )
    metrics = dict(metrics)
    metrics.setdefault("production_drift_reference", valid_production_drift_reference())
    return ModelCandidate(
        path=tmp_path / "candidate.joblib",
        version="candidate-v1",
        model_type="logistic",
        horizon=8,
        training_start=now,
        training_end=now,
        dataset_rows=1000,
        unique_timestamps=500,
        symbol_count=1,
        symbol_sample=("BTCUSDT",),
        training_data_profile=profile,
        metrics=metrics,
        incumbent_metrics=None,
        incumbent_version=None,
    )


def _passing_metrics() -> dict[str, object]:
    return {
        "rows": 300,
        "holdout_span_hours": 336.0,
        "log_loss": 0.9,
        "class_prior_log_loss": 1.05,
        "log_loss_skill_vs_prior": 0.15,
        "multiclass_brier": 0.55,
        "ece_tp": 0.05,
        "ece_sl": 0.05,
        "ece_timeout": 0.05,
        "class_distribution": {"TP": 0.35, "SL": 0.40, "TIMEOUT": 0.25},
        "policy_candidates": 1_000,
        "policy_trades": 80,
        "policy_trade_rate": 0.08,
        "policy_cohorts": 80,
        "policy_trade_cohorts": 80,
        "policy_no_trade_cohorts": 0,
        "policy_independent_cohorts": 80,
        "policy_realized_mean_r": 0.05,
        "policy_profit_factor": 1.2,
        "policy_max_drawdown_r": 5.0,
    }


@pytest.mark.parametrize(
    "distribution",
    [
        {"TP": float("nan"), "SL": 0.4, "TIMEOUT": 0.6},
        {"TP": 0.5, "SL": 0.5, "TIMEOUT": 0.5},
        {"TP": 0.5, "SL": 0.5},
    ],
)
def test_quality_gate_rejects_malformed_class_distribution(
    tmp_path: Path,
    distribution: dict[str, float],
) -> None:
    metrics = _passing_metrics()
    metrics["class_distribution"] = distribution

    result = evaluate_quality_gate(
        _candidate(tmp_path, metrics),
        Settings(database_url="postgresql+psycopg://u:p@localhost/db"),
    )

    assert result["passed"] is False
    assert "invalid_holdout_class_distribution" in result["reasons"]


def test_policy_profit_factor_uses_same_cohort_weights_as_portfolio_path() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    probabilities: list[list[float]] = []

    def add_pair(decision: datetime, symbol: str, target: str, gross: float) -> None:
        rows.extend(
            [
                {
                    "decision_time": decision,
                    "label_end_time": decision + timedelta(hours=1),
                    "symbol": symbol,
                    "direction": "LONG",
                    "target": target,
                    "exit_index": 0,
                    "realized_gross_return": gross,
                    "barrier_upside_rate": 0.01,
                    "barrier_downside_rate": 0.01,
                },
                {
                    "decision_time": decision,
                    "label_end_time": decision + timedelta(hours=1),
                    "symbol": symbol,
                    "direction": "SHORT",
                    "target": "SL",
                    "exit_index": 0,
                    "realized_gross_return": -0.01,
                    "barrier_upside_rate": 0.01,
                    "barrier_downside_rate": 0.01,
                },
            ]
        )
        probabilities.extend([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])

    add_pair(start, "WINUSDT", "TP", 0.01)
    for index in range(9):
        add_pair(start + timedelta(hours=1), f"LOSS{index}USDT", "TIMEOUT", -0.002)

    meta = pd.DataFrame(rows)
    split, model = _split(meta, np.asarray(probabilities))
    metrics = evaluate_policy_model(model, split, _policy_config())

    assert metrics["policy_profit_factor"] == pytest.approx(5.0)


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value

    def scalars(self) -> _ScalarResult:
        return self

    def all(self) -> object:
        return self.value


async def test_reconciliation_sums_multiple_manual_trades_for_same_position() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _ScalarResult(SimpleNamespace(source_time=timestamp)),
                _ScalarResult([SimpleNamespace(symbol="BTCUSDT", side="BUY", qty=D("3"))]),
                _ScalarResult(
                    [
                        SimpleNamespace(symbol="BTCUSDT", direction="LONG", remaining_qty=D("1")),
                        SimpleNamespace(symbol="BTCUSDT", direction="LONG", remaining_qty=D("2")),
                    ]
                ),
            ]
        )
    )

    assert (
        await execution.reconciliation_issues(
            session,
            profile=SimpleNamespace(id="profile-1", mode="bybit_read_only", source_account_id="account-1"),
        )
        == []
    )


async def test_reconciliation_flags_journal_position_missing_on_exchange() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _ScalarResult(SimpleNamespace(source_time=timestamp)),
                _ScalarResult([]),
                _ScalarResult([SimpleNamespace(symbol="BTCUSDT", direction="LONG", remaining_qty=D("1"))]),
            ]
        )
    )

    issues = await execution.reconciliation_issues(
        session,
        profile=SimpleNamespace(id="profile-1", mode="bybit_read_only", source_account_id="account-1"),
    )
    assert any("BTCUSDT" in issue and "журнал" in issue.lower() for issue in issues)


def test_future_ticker_is_not_fresh() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert (
        execution.ticker_snapshot_is_fresh(now + timedelta(seconds=1), now=now, max_age_seconds=120) is False
    )


@pytest.mark.parametrize(
    ("direction", "reference", "executable"),
    [
        ("LONG", D("100"), D("100.01")),
        ("SHORT", D("100"), D("99.99")),
    ],
)
def test_adverse_entry_drift_is_detected(
    direction: str,
    reference: Decimal,
    executable: Decimal,
) -> None:
    assert (
        execution.entry_price_is_adverse(direction=direction, reference=reference, executable=executable)
        is True
    )


async def test_latest_spec_excludes_future_dated_rows() -> None:
    cutoff = datetime(2026, 1, 1, tzinfo=UTC)
    session = SimpleNamespace(execute=AsyncMock(return_value=_ScalarResult(None)))

    await execution.latest_spec(session, "BTCUSDT", cutoff=cutoff)

    statement = session.execute.await_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "valid_from <=" in compiled


@pytest.mark.parametrize(
    "costs",
    [
        risk_math.CostScenario(D("0"), D("-0.001"), D("0"), D("0")),
        risk_math.CostScenario(D("0"), D("0"), D("-0.001"), D("0")),
        risk_math.CostScenario(D("0"), D("NaN"), D("0"), D("0")),
    ],
)
def test_direct_risk_math_rejects_invalid_cost_scenarios(
    costs: risk_math.CostScenario,
) -> None:
    with pytest.raises(ValueError, match="slippage|stop_gap|finite|negative"):
        risk_math.net_rr_and_ev(
            entry=D("100"),
            stop=D("98"),
            take_profit=D("104"),
            direction="LONG",
            costs=costs,
            p_tp=0.5,
            p_sl=0.4,
            p_timeout=0.1,
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"horizon_hours": 0},
        {"horizon_hours": -1},
        {"horizon_hours": 1.5},
        {"current_rate": D("NaN")},
    ],
)
def test_projected_funding_rejects_invalid_quant_inputs(kwargs: dict[str, object]) -> None:
    values: dict[str, object] = {
        "start_time": datetime(2026, 1, 1, tzinfo=UTC),
        "horizon_hours": 8,
        "next_settlement": datetime(2026, 1, 1, 1, tzinfo=UTC),
        "interval_minutes": 480,
        "current_rate": D("0.0001"),
    }
    values.update(kwargs)
    with pytest.raises(ValueError, match="horizon|current_rate|finite|integer|positive"):
        risk_math.projected_funding_rate(**values)


def test_remaining_trade_risk_is_proportional_and_never_negative() -> None:
    helper = getattr(execution, "remaining_trade_risk", None)
    assert helper is not None, "remaining_trade_risk helper is missing"
    assert helper(D("12"), D("3"), D("2")) == D("8")
    assert helper(D("12"), D("3"), D("0")) == D("0")
    with pytest.raises(ValueError):
        helper(D("12"), D("3"), D("4"))


def test_manual_trade_schema_persists_actual_remaining_risk() -> None:
    from app.db.models import ManualTrade

    assert "initial_stress_loss" in ManualTrade.__table__.columns
    assert "remaining_stress_loss" in ManualTrade.__table__.columns


def _artifact_bundle(**overrides: object) -> dict[str, object]:
    bundle: dict[str, object] = {
        "task": "barrier_outcome_v1",
        "model": AuditArtifactModel(),
        "model_type": "stub",
        "version": "audit-v1",
        "calibration_version": "cal-v1",
        "feature_names": MODEL_FEATURE_NAMES,
        "feature_schema_version": MODEL_FEATURE_SCHEMA_VERSION,
        "market_context_schema": "hourly-oi-basis-settled-funding-turnover-v2",
        "market_context_availability_schema": "exchange-event-close-live-receipt-v1",
        "market_context": {
            "schema": "hourly-oi-basis-settled-funding-turnover-v2",
                "funding_interval_schedule_schema": "instrument-spec-point-in-time-v1",
                "funding_interval_source": "instrument_spec_history_point_in_time",
            "availability_schema": "exchange-event-close-live-receipt-v1",
            "historical_receipt_time_reconstructed": False,
        },
        "market_context_ablation_schema": "same-split-zeroed-context-v1",
        "production_drift_reference": valid_production_drift_reference(),
        "label_path_schema_version": LABEL_PATH_SCHEMA_VERSION,
        "entry_spread_bps": 18.0,
        "entry_execution_model": {
            "schema": "directional-half-spread-on-next-hour-open-v1",
            "entry_spread_bps": 18.0,
        },
        "temporal_split_schema": TEMPORAL_SPLIT_SCHEMA_VERSION,
        "walk_forward_schema": WALK_FORWARD_SCHEMA_VERSION,
        "historical_funding_schema": "bybit-settlement-timestamp-replay-v2",
        "historical_funding_timeline": {
            "schema": "bybit-settlement-timestamp-replay-v2",
                "funding_interval_schedule_schema": "instrument-spec-point-in-time-v1",
                "interval_source": "instrument_spec_history_point_in_time",
                "interval_history_symbols": 3,
            "symbols": 1,
            "settlements": 10,
            "start_time": "2024-01-01T00:00:00+00:00",
            "end_time": "2025-12-31T00:00:00+00:00",
        },
        "intrahorizon_margin_path": {
            "schema": "bybit-mark-price-hourly-isolated-margin-proxy-v1",
            "required": True,
            "status": "complete",
            "mark_price_source": "bybit_hourly_mark_price_ohlc",
            "research_leverage": 3,
            "equity_reserve_fraction": 0.10,
            "same_bar_ordering": "liquidation_before_unordered_last_price_exit",
            "liquidation_loss": "full_initial_margin",
        },
        "timeout_return_schema_version": TIMEOUT_RETURN_SCHEMA_VERSION,
        "horizon_hours": 8,
        "stop_atr_multiplier": 1.5,
        "tp_atr_multiplier": 2.2,
    }
    bundle.update(overrides)
    return bundle


def test_runtime_rejects_wrong_feature_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "wrong-schema.joblib"
    joblib.dump(_artifact_bundle(feature_schema_version="stale-v1"), path)

    with pytest.raises(ValueError, match="feature schema version"):
        ModelRuntime(path, allow_baseline=False).load()


@pytest.mark.parametrize("horizon", [0, -1, 1.5, float("nan")])
def test_runtime_rejects_invalid_artifact_horizon(tmp_path: Path, horizon: float) -> None:
    path = tmp_path / "invalid-horizon.joblib"
    joblib.dump(_artifact_bundle(horizon_hours=horizon), path)

    with pytest.raises(ValueError, match="horizon_hours"):
        ModelRuntime(path, allow_baseline=False).load()


def test_artifact_prediction_rejects_missing_or_nonfinite_features() -> None:
    runtime = ModelRuntime(None, allow_baseline=False)
    runtime.bundle = _artifact_bundle()
    runtime.version = "audit-v1"
    runtime.calibration_version = "cal-v1"

    with pytest.raises(ValueError, match="missing model features"):
        runtime.predict_scenarios({})

    features = {name: 0.0 for name in MODEL_FEATURE_NAMES[:-1]}
    features[MODEL_FEATURE_NAMES[0]] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        runtime.predict_scenarios(features)


@pytest.mark.parametrize(
    "field,value",
    [
        ("log_loss", float("nan")),
        ("multiclass_brier", "corrupt"),
        ("policy_realized_mean_r", float("inf")),
        ("policy_max_drawdown_r", None),
    ],
)
def test_quality_gate_fails_closed_on_invalid_incumbent_metrics(
    tmp_path: Path, field: str, value: object
) -> None:
    candidate = _candidate(tmp_path, _passing_metrics())
    incumbent = _passing_metrics()
    incumbent[field] = value
    candidate = ModelCandidate(
        **{**candidate.__dict__, "incumbent_metrics": incumbent, "incumbent_version": "active-v1"}
    )

    result = evaluate_quality_gate(
        candidate,
        Settings(database_url="postgresql+psycopg://u:p@localhost/db"),
    )

    assert result["passed"] is False
    assert "invalid_incumbent_metrics" in result["reasons"]


async def test_open_risk_uses_accepted_plan_and_actual_remaining_trade_risk() -> None:
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(scalar_one=lambda: D("7.5")),
                SimpleNamespace(scalar_one=lambda: D("4.25")),
            ]
        )
    )

    result = await execution.open_risk_usdt(
        session,
        profile=SimpleNamespace(id="profile-1", mode="manual", source_account_id=None),
    )

    assert result == D("11.75")
    first_statement = str(session.execute.await_args_list[0].args[0])
    second_statement = str(session.execute.await_args_list[1].args[0])
    assert "execution_plans.status" in first_statement
    assert "manual_trades.remaining_stress_loss" in second_statement


def test_manual_trade_risk_constraints_match_migration_contract() -> None:
    from app.db.models import ManualTrade

    constraints = {constraint.name for constraint in ManualTrade.__table__.constraints}
    assert "ck_manual_trades_initial_stress_loss_non_negative" in constraints
    assert "ck_manual_trades_remaining_stress_loss_non_negative" in constraints
    assert "ck_manual_trades_remaining_stress_loss_lte_initial" in constraints

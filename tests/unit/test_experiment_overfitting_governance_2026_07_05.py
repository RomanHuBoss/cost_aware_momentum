from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from statistics import NormalDist

import numpy as np
import pandas as pd
import pytest

from app.config import Settings
from app.db.models import ResearchExperimentEvent
from app.research.overfitting import (
    ExperimentFamilyEvidence,
    ExperimentTrialEvidence,
    analyze_experiment_family,
    combinatorial_pbo,
    deflated_sharpe_ratio,
    effective_independent_trials,
    nonannualized_sharpe,
)
from app.services.experiment_ledger import build_experiment_event_hash
from scripts.backtest import _simulate_capital_sleeves_evidence


def _timestamps(count: int) -> tuple[datetime, ...]:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    return tuple(start + timedelta(hours=index) for index in range(count))


def _trial(name: str, returns: np.ndarray) -> ExperimentTrialEvidence:
    return ExperimentTrialEvidence(
        trial_id=f"trial-{name}",
        configuration_hash=(name * 64)[:64],
        timestamps=_timestamps(len(returns)),
        returns=tuple(float(value) for value in returns),
    )


def test_cscv_pbo_is_zero_for_stable_dominant_trial() -> None:
    periods = 48
    phase = np.arange(periods, dtype=float)
    matrix = np.column_stack(
        [
            0.010 + 0.002 * np.sin(phase),
            0.004 + 0.002 * np.cos(phase),
            -0.001 + 0.003 * np.sin(phase / 2.0),
            -0.004 + 0.002 * np.cos(phase / 3.0),
        ]
    )

    report = combinatorial_pbo(matrix, segments=4)

    assert report["status"] == "READY"
    assert report["pbo"] == pytest.approx(0.0)
    assert report["split_count"] == 6


def test_cscv_pbo_detects_regime_specific_winner_reversal() -> None:
    segments = 4
    rows_per_segment = 12
    background = -0.01 + np.linspace(-0.0005, 0.0005, segments * rows_per_segment)
    matrix = np.tile(background[:, None], (1, segments))
    for segment in range(segments):
        start = segment * rows_per_segment
        stop = start + rows_per_segment
        matrix[start:stop, segment] = 0.05 + np.linspace(-0.002, 0.002, rows_per_segment)

    report = combinatorial_pbo(matrix, segments=segments)

    assert report["status"] == "READY"
    assert report["pbo"] >= 0.5
    assert all(math.isfinite(value) for value in report["logits"])


def test_effective_independent_trials_uses_average_off_diagonal_correlation() -> None:
    base = np.asarray([0.01, -0.01, 0.02, -0.02, 0.015, -0.005], dtype=float)
    matrix = np.column_stack([base, base, -base, np.roll(base, 1)])
    correlation = np.corrcoef(matrix, rowvar=False)
    off_diagonal = correlation[np.triu_indices(4, k=1)]
    rho = max(0.0, min(1.0, float(np.mean(off_diagonal))))
    expected = rho + (1.0 - rho) * 4.0

    result = effective_independent_trials(matrix)

    assert result["average_correlation"] == pytest.approx(rho)
    assert result["effective_trials"] == pytest.approx(expected)


def test_deflated_sharpe_matches_independent_formula() -> None:
    returns = np.asarray(
        [0.012, -0.004, 0.009, 0.003, -0.002, 0.011, -0.006, 0.007, 0.004, 0.002],
        dtype=float,
    )
    trial_sharpes = np.asarray([-0.15, -0.02, 0.08, 0.20], dtype=float)
    selected_sharpe = nonannualized_sharpe(returns)
    variance = float(np.var(trial_sharpes, ddof=1))
    gamma = 0.5772156649015329
    normal = NormalDist()
    n_eff = 4.0
    benchmark = math.sqrt(variance) * (
        (1.0 - gamma) * normal.inv_cdf(1.0 - 1.0 / n_eff)
        + gamma * normal.inv_cdf(1.0 - 1.0 / (n_eff * math.e))
    )
    centered = returns - float(np.mean(returns))
    second = float(np.mean(centered**2))
    skewness = float(np.mean(centered**3) / second**1.5)
    kurtosis = float(np.mean(centered**4) / second**2)
    denominator = math.sqrt(
        1.0
        - skewness * selected_sharpe
        + ((kurtosis - 1.0) / 4.0) * selected_sharpe * selected_sharpe
    )
    z_value = (selected_sharpe - benchmark) * math.sqrt(len(returns) - 1) / denominator
    expected_probability = normal.cdf(z_value)

    report = deflated_sharpe_ratio(
        returns,
        trial_sharpes=trial_sharpes,
        effective_trials=n_eff,
    )

    assert report["status"] == "READY"
    assert report["selected_sharpe"] == pytest.approx(selected_sharpe)
    assert report["benchmark_sharpe"] == pytest.approx(benchmark)
    assert report["probability"] == pytest.approx(expected_probability)


def test_family_analysis_blocks_incomplete_trial_disclosure() -> None:
    values = np.asarray([0.01, -0.005] * 16, dtype=float)
    evidence = ExperimentFamilyEvidence(
        experiment_family="family-a",
        attempted_configuration_hashes=("a" * 64, "b" * 64, "c" * 64, "d" * 64),
        successful_trials=(_trial("a", values), _trial("b", values * 0.8)),
        failed_configuration_hashes=("c" * 64,),
        open_trial_ids=("trial-d",),
    )

    report = analyze_experiment_family(
        evidence,
        segments=4,
        minimum_trials=4,
        minimum_periods=24,
    )

    assert report["status"] == "BLOCKED_INCOMPLETE_LEDGER"
    assert report["automatic_model_action"] == "none"
    assert report["attempted_configuration_count"] == 4


def test_family_analysis_deduplicates_repeated_configuration_and_returns_governance_result() -> None:
    periods = 48
    phase = np.arange(periods, dtype=float)
    trials = (
        _trial("a", 0.010 + 0.002 * np.sin(phase)),
        _trial("b", 0.004 + 0.002 * np.cos(phase)),
        _trial("c", -0.001 + 0.003 * np.sin(phase / 2.0)),
        _trial("d", -0.004 + 0.002 * np.cos(phase / 3.0)),
        ExperimentTrialEvidence(
            trial_id="trial-a-repeat",
            configuration_hash="a" * 64,
            timestamps=_timestamps(periods),
            returns=tuple(float(value) for value in 0.010 + 0.002 * np.sin(phase)),
        ),
    )
    evidence = ExperimentFamilyEvidence(
        experiment_family="family-ready",
        attempted_configuration_hashes=("a" * 64, "b" * 64, "c" * 64, "d" * 64),
        successful_trials=trials,
        failed_configuration_hashes=(),
        open_trial_ids=(),
    )

    report = analyze_experiment_family(
        evidence,
        segments=4,
        minimum_trials=4,
        minimum_periods=24,
        maximum_pbo=0.25,
        minimum_dsr_probability=0.80,
    )

    assert report["status"] in {"READY", "REJECTED"}
    assert report["successful_unique_configuration_count"] == 4
    assert report["duplicate_success_count"] == 1
    assert report["pbo"]["status"] == "READY"
    assert report["deflated_sharpe"]["status"] == "READY"
    assert report["automatic_model_action"] == "none"


def test_experiment_event_hash_changes_when_result_is_mutated() -> None:
    base = {
        "trial_id": "11111111-1111-1111-1111-111111111111",
        "experiment_family": "family-a",
        "event_sequence": 1,
        "event_type": "SUCCEEDED",
        "observed_at": "2025-01-01T00:00:00+00:00",
        "configuration_hash": "a" * 64,
        "configuration": {"minimum_net_ev_r": 0.1},
        "evidence": {"sharpe": 1.2, "period_returns": [0.01, -0.005]},
        "previous_event_hash": "b" * 64,
    }

    original = build_experiment_event_hash(base)
    mutated = build_experiment_event_hash(
        {**base, "evidence": {"sharpe": 9.9, "period_returns": [0.01, -0.005]}}
    )

    assert len(original) == 64
    assert original != mutated



def test_capital_sleeve_evidence_exposes_zero_hours_and_reconciles_return() -> None:
    start = pd.Timestamp("2025-01-01T00:00:00Z")
    trades = pd.DataFrame(
        [
            {
                "decision_time": start,
                "exit_time": start + pd.Timedelta(2, unit="h"),
                "net_return": 0.10,
            }
        ]
    )
    grid = pd.date_range(start, start + pd.Timedelta(2, unit="h"), freq="h")

    evidence = _simulate_capital_sleeves_evidence(
        trades,
        return_column="net_return",
        horizon_hours=1,
        period_grid=grid,
    )

    values = [row["return"] for row in evidence["period_returns"]]
    assert values == pytest.approx([0.0, 0.0, 0.10])
    assert evidence["net_return"] == pytest.approx(np.prod(1.0 + np.asarray(values)) - 1.0)


def test_experiment_event_model_enforces_trial_sequence_and_record_hash_uniqueness() -> None:
    constraint_names = {item.name for item in ResearchExperimentEvent.__table__.constraints}

    assert "uq_experiment_event_trial_sequence" in constraint_names
    assert "uq_experiment_events_record_hash" in constraint_names
    assert any(name.endswith("experiment_configuration_hash_length") for name in constraint_names)
    assert any(name.endswith("experiment_record_hash_length") for name in constraint_names)



def test_experiment_governance_settings_fail_closed() -> None:
    database_url = "postgresql+psycopg://u:p@localhost/db"
    with pytest.raises(ValueError, match="EXPERIMENT_PBO_SEGMENTS"):
        Settings(_env_file=None, database_url=database_url, experiment_pbo_segments=5)
    with pytest.raises(ValueError, match="EXPERIMENT_MIN_PERIODS"):
        Settings(
            _env_file=None,
            database_url=database_url,
            experiment_pbo_segments=6,
            experiment_min_periods=10,
        )


def test_capital_sleeve_evidence_marks_intrahorizon_drawdown_before_profitable_exit() -> None:
    start = pd.Timestamp("2025-01-01T00:00:00Z")
    trades = pd.DataFrame(
        [
            {
                "decision_time": start,
                "exit_time": start + pd.Timedelta(2, unit="h"),
                "net_return": 0.01,
                "intrahorizon_net_return_path": [
                    {"timestamp": start.isoformat(), "return": 0.0},
                    {
                        "timestamp": (start + pd.Timedelta(1, unit="h")).isoformat(),
                        "return": -0.20,
                    },
                    {
                        "timestamp": (start + pd.Timedelta(2, unit="h")).isoformat(),
                        "return": 0.01,
                    },
                ],
            }
        ]
    )
    grid = pd.date_range(start, start + pd.Timedelta(2, unit="h"), freq="h")

    evidence = _simulate_capital_sleeves_evidence(
        trades,
        return_column="net_return",
        horizon_hours=2,
        period_grid=grid,
    )

    values = [row["return"] for row in evidence["period_returns"]]
    assert values == pytest.approx([0.0, -0.10, 0.105 / 0.90])
    assert evidence["max_drawdown"] == pytest.approx(-0.10)
    assert evidence["net_return"] == pytest.approx(0.005)

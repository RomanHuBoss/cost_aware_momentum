from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest

from app.config import Settings
from app.research.dependence import (
    cluster_moving_block_bootstrap,
    moving_block_bootstrap_inference,
    newey_west_mean_inference,
)
from app.research.overfitting import (
    ExperimentFamilyEvidence,
    ExperimentTrialEvidence,
    analyze_experiment_family,
)
from app.research.selection_bias import (
    SELECTION_FEATURE_NAMES,
    SelectionObservation,
    _chronological_propensity_scores,
    analyze_operator_selection,
)
from app.services import selection_experiments
from app.services.selection_experiments import build_selection_ledger_row, selection_bias_report

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _features(value: float = 0.0) -> dict[str, float]:
    result = {name: 0.0 for name in SELECTION_FEATURE_NAMES}
    result.update(
        {
            "p_tp": 0.45,
            "p_sl": 0.35,
            "p_timeout": 0.20,
            "net_rr": 1.3 + 0.05 * value,
            "net_ev_r": value,
            "gross_edge_rate": 0.01,
            "risk_rate": 0.005,
            "notional_to_capital": 0.2,
            "stress_to_budget": 0.8,
            "leverage": 3.0,
            "liquidation_buffer_rate": 0.2,
            "entry_inside_zone": 1.0,
            "seconds_to_expiry": 3600.0,
            "hour_cos": 1.0,
            "weekday_cos": 1.0,
            "direction_long": 1.0,
        }
    )
    return result


def test_newey_west_mean_matches_independent_bartlett_formula() -> None:
    values = np.asarray([0.01, 0.018, 0.014, -0.002, -0.006, 0.003, 0.011, 0.016], dtype=float)
    lag = 2
    centered = values - float(np.mean(values))
    gamma0 = float(np.dot(centered, centered) / len(values))
    long_run = gamma0
    for offset in range(1, lag + 1):
        gamma = float(np.dot(centered[offset:], centered[:-offset]) / len(values))
        long_run += 2.0 * (1.0 - offset / (lag + 1.0)) * gamma
    expected_se = math.sqrt(max(0.0, long_run) / len(values))

    report = newey_west_mean_inference(values, max_lag=lag, confidence_level=0.95)

    assert report["schema"] == "newey-west-bartlett-mean-v1"
    assert report["max_lag"] == lag
    assert report["standard_error"] == pytest.approx(expected_se)
    assert report["confidence_interval"][0] < report["mean"] < report["confidence_interval"][1]
    assert 1.0 <= report["effective_observations"] <= len(values)


def test_moving_block_bootstrap_is_deterministic_and_preserves_dependence_blocks() -> None:
    values = np.asarray([0.02, 0.018, 0.016, 0.014, -0.01, -0.008, -0.006, -0.004] * 8)

    first = moving_block_bootstrap_inference(
        values,
        block_length=4,
        replicates=300,
        confidence_level=0.90,
        seed=17,
    )
    second = moving_block_bootstrap_inference(
        values,
        block_length=4,
        replicates=300,
        confidence_level=0.90,
        seed=17,
    )

    assert first == second
    assert first["schema"] == "moving-block-bootstrap-percentile-v1"
    assert first["independent_block_count"] == len(values) // 4
    assert first["valid_replicates"] == 300
    assert first["mean_return"]["lower"] <= first["mean_return"]["estimate"] <= first["mean_return"]["upper"]
    assert first["sharpe"]["lower"] <= first["sharpe"]["estimate"] <= first["sharpe"]["upper"]


def _trial(name: str, values: np.ndarray) -> ExperimentTrialEvidence:
    timestamps = tuple(BASE + timedelta(hours=index) for index in range(len(values)))
    return ExperimentTrialEvidence(
        trial_id=f"trial-{name}",
        configuration_hash=(name * 64)[:64],
        timestamps=timestamps,
        returns=tuple(float(value) for value in values),
    )


def test_experiment_governance_uses_dependence_adjusted_dsr_and_blocks_too_few_blocks() -> None:
    periods = 72
    phase = np.arange(periods, dtype=float)
    trials = (
        _trial("a", 0.006 + 0.003 * np.sin(phase / 5.0)),
        _trial("b", 0.003 + 0.003 * np.cos(phase / 7.0)),
        _trial("c", -0.001 + 0.002 * np.sin(phase / 3.0)),
        _trial("d", -0.003 + 0.002 * np.cos(phase / 4.0)),
    )
    evidence = ExperimentFamilyEvidence(
        experiment_family="dependent-family",
        attempted_configuration_hashes=tuple(item.configuration_hash for item in trials),
        successful_trials=trials,
        failed_configuration_hashes=(),
        open_trial_ids=(),
        declared_horizons=(8,),
    )

    report = analyze_experiment_family(
        evidence,
        segments=6,
        minimum_trials=4,
        minimum_periods=60,
        dependence_block_periods=8,
        minimum_independent_blocks=6,
        bootstrap_replicates=250,
        confidence_level=0.90,
    )

    assert report["status"] in {"READY", "REJECTED"}
    dependence = report["dependence_aware_inference"]
    assert dependence["status"] == "READY"
    assert dependence["block_length"] == 8
    assert dependence["horizon_floor_periods"] == 8
    assert dependence["hac_mean"]["effective_observations"] < periods
    assert report["deflated_sharpe"]["effective_observations"] == pytest.approx(
        dependence["hac_mean"]["effective_observations"]
    )

    blocked = analyze_experiment_family(
        evidence,
        segments=6,
        minimum_trials=4,
        minimum_periods=60,
        dependence_block_periods=16,
        minimum_independent_blocks=6,
        bootstrap_replicates=250,
        confidence_level=0.90,
    )
    assert blocked["status"] == "BLOCKED_INSUFFICIENT_DEPENDENCE_EVIDENCE"


def test_experiment_family_blocks_mixed_declared_horizons() -> None:
    values = np.asarray([0.01, -0.004, 0.006, 0.002] * 18, dtype=float)
    trials = tuple(_trial(name, values * scale) for name, scale in (("a", 1.0), ("b", 0.8), ("c", 0.5), ("d", -0.2)))
    evidence = ExperimentFamilyEvidence(
        experiment_family="mixed-horizon-family",
        attempted_configuration_hashes=tuple(item.configuration_hash for item in trials),
        successful_trials=trials,
        failed_configuration_hashes=(),
        open_trial_ids=(),
        declared_horizons=(4, 8),
    )

    report = analyze_experiment_family(
        evidence,
        segments=6,
        minimum_trials=4,
        minimum_periods=60,
        bootstrap_replicates=200,
    )

    assert report["status"] == "BLOCKED_INCOMPATIBLE_HORIZONS"
    assert report["declared_horizons"] == [4, 8]


def test_propensity_scoring_never_splits_signal_cluster_between_train_and_oos() -> None:
    observations: list[SelectionObservation] = []
    for cluster_index in range(40):
        for version in range(2):
            observations.append(
                SelectionObservation(
                    plan_id=f"plan-{cluster_index}-{version}",
                    cluster_id=f"signal-{cluster_index}",
                    observed_at=BASE + timedelta(hours=cluster_index, minutes=version),
                    decision_action="ACCEPT" if cluster_index % 2 else "REJECT",
                    counterfactual_r=float(cluster_index) / 100.0,
                    features=_features(float(cluster_index % 5) / 5.0),
                )
            )

    _, _, scored_indexes = _chronological_propensity_scores(
        observations,
        warmup_observations=21,
        block_size=7,
    )
    scored = set(int(index) for index in scored_indexes)

    for cluster_index in range(40):
        cluster_rows = {2 * cluster_index, 2 * cluster_index + 1}
        assert not (cluster_rows & scored) or cluster_rows <= scored


def _clustered_observations() -> list[SelectionObservation]:
    rng = np.random.default_rng(20260705)
    rows: list[SelectionObservation] = []
    for cluster_index in range(120):
        latent = float(rng.normal())
        propensity = 1.0 / (1.0 + np.exp(-(-0.25 + 0.9 * latent)))
        accepted = bool(rng.uniform() < propensity)
        cluster_shock = float(rng.normal(scale=0.20))
        for version in range(2):
            outcome = 0.04 + 0.35 * latent + cluster_shock + float(rng.normal(scale=0.05))
            rows.append(
                SelectionObservation(
                    plan_id=f"plan-{cluster_index}-{version}",
                    cluster_id=f"signal-{cluster_index}",
                    observed_at=BASE + timedelta(hours=cluster_index, minutes=version),
                    decision_action="ACCEPT" if accepted else ("REJECT" if version else "NO_DECISION"),
                    counterfactual_r=outcome,
                    features=_features(latent),
                )
            )
    return rows


def test_operator_selection_reports_signal_cluster_block_intervals() -> None:
    report = analyze_operator_selection(
        _clustered_observations(),
        minimum_total=120,
        minimum_selected=30,
        minimum_unselected=30,
        warmup_observations=80,
        block_size=40,
        dependence_block_clusters=6,
        minimum_independent_clusters=30,
        bootstrap_replicates=250,
        confidence_level=0.90,
    )

    assert report["status"] == "READY"
    dependence = report["dependence_aware_inference"]
    assert dependence["schema"] == "signal-cluster-moving-block-bootstrap-v1"
    assert dependence["unique_cluster_count"] >= 30
    assert dependence["valid_replicates"] >= 225
    for metric in ("eligible_mean_r", "selected_mean_r", "ipsw_mean_r", "selected_subset_bias_r"):
        interval = dependence["metrics"][metric]
        assert interval["lower"] <= interval["estimate"] <= interval["upper"]

    blocked = analyze_operator_selection(
        _clustered_observations()[:40],
        minimum_total=1,
        minimum_selected=0,
        minimum_unselected=0,
        warmup_observations=20,
        block_size=10,
        dependence_block_clusters=4,
        minimum_independent_clusters=30,
        bootstrap_replicates=200,
        confidence_level=0.90,
    )
    assert blocked["status"] == "INSUFFICIENT_CLUSTER_EVIDENCE"


def test_cluster_bootstrap_rejects_cluster_fragmentation_and_is_reproducible() -> None:
    outcomes = np.asarray([1.0, 1.2, -0.5, -0.4, 0.3, 0.4, -0.1, 0.0], dtype=float)
    selected = np.asarray([1, 1, 0, 0, 1, 1, 0, 0], dtype=int)
    weights = np.asarray([1.0, 1.2, 0.0, 0.0, 0.8, 1.1, 0.0, 0.0], dtype=float)
    clusters = np.asarray(["a", "a", "b", "b", "c", "c", "d", "d"], dtype=object)
    times = [BASE + timedelta(hours=index // 2) for index in range(len(outcomes))]

    first = cluster_moving_block_bootstrap(
        outcomes,
        selected=selected,
        weights=weights,
        cluster_ids=clusters,
        observed_at=times,
        block_clusters=2,
        replicates=200,
        confidence_level=0.90,
        seed=19,
    )
    second = cluster_moving_block_bootstrap(
        outcomes,
        selected=selected,
        weights=weights,
        cluster_ids=clusters,
        observed_at=times,
        block_clusters=2,
        replicates=200,
        confidence_level=0.90,
        seed=19,
    )

    assert first == second
    assert first["unique_cluster_count"] == 4
    assert first["cluster_row_counts"] == {"a": 2, "b": 2, "c": 2, "d": 2}


class _RowsResult:
    def __init__(self, rows: list[tuple[object, object, object]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, object, object]]:
        return self._rows


class _RowsSession:
    def __init__(self, rows: list[tuple[object, object, object]]) -> None:
        self.rows = rows

    async def execute(self, _statement: object) -> _RowsResult:
        return _RowsResult(self.rows)


@pytest.mark.asyncio
async def test_selection_service_uses_signal_id_as_dependence_cluster(monkeypatch: pytest.MonkeyPatch) -> None:
    signal_id = uuid4()
    signal = SimpleNamespace(
        id=signal_id,
        direction="LONG",
        p_tp=0.45,
        p_sl=0.35,
        p_timeout=0.20,
        net_rr=1.3,
        net_ev_r=0.08,
        gross_edge_rate=0.01,
        expires_at=BASE + timedelta(hours=1),
    )
    plan = SimpleNamespace(
        id=uuid4(),
        profile_id=uuid4(),
        version=1,
        status="ACTIONABLE",
        effective_capital=10_000,
        risk_rate=0.005,
        risk_budget=50,
        actual_stress_loss=40,
        notional=2_000,
        leverage=3,
        liquidation_buffer_rate=0.2,
        warnings=[],
        sizing_snapshot={
            "entry_inside_signal_zone": True,
            "net_rr": "1.3",
            "net_ev_r": "0.08",
            "execution_quality": {"impact_bps": "2"},
            "caps": {"orderbook_depth_notional": "5000"},
        },
    )
    ledger = build_selection_ledger_row(
        signal=signal,
        plan=plan,
        observed_at=BASE,
        release_version="1.18.0",
    )
    outcome = SimpleNamespace(valuation_status="VALUED", counterfactual_r=Decimal("0.1"))
    captured: dict[str, object] = {}

    def fake_analysis(observations: list[SelectionObservation], **_kwargs: object) -> dict[str, object]:
        captured["observations"] = observations
        return {
            "schema": "operator-selection-ipsw-clustered-report-v2",
            "status": "INSUFFICIENT_CLUSTER_EVIDENCE",
            "ipsw_selected_mean_r": None,
            "causal_effect_claimed": False,
        }

    monkeypatch.setattr(selection_experiments, "analyze_operator_selection", fake_analysis)
    await selection_bias_report(
        _RowsSession([(ledger, None, outcome)]),
        since=BASE - timedelta(hours=1),
        minimum_total=1,
        minimum_selected=0,
        minimum_unselected=0,
    )

    observations = captured["observations"]
    assert isinstance(observations, list)
    assert observations[0].cluster_id == str(signal_id)


def test_dependence_settings_fail_closed() -> None:
    database_url = "postgresql+psycopg://u:p@localhost/db"
    with pytest.raises(ValueError, match="RESEARCH_BOOTSTRAP_REPLICATES"):
        Settings(_env_file=None, database_url=database_url, research_bootstrap_replicates=99)
    with pytest.raises(ValueError, match="RESEARCH_CONFIDENCE_LEVEL"):
        Settings(_env_file=None, database_url=database_url, research_confidence_level=1.0)
    with pytest.raises(ValueError, match="EXPERIMENT_DEPENDENCE_BLOCK_PERIODS"):
        Settings(_env_file=None, database_url=database_url, experiment_dependence_block_periods=1)
    with pytest.raises(ValueError, match="SELECTION_MIN_INDEPENDENT_CLUSTERS"):
        Settings(
            _env_file=None,
            database_url=database_url,
            selection_dependence_block_clusters=8,
            selection_min_independent_clusters=8,
        )

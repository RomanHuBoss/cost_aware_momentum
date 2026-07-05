from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from math import isfinite

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.research.dependence import cluster_moving_block_bootstrap

SELECTION_FEATURE_SCHEMA = "operator-selection-predecision-v1"
SELECTION_REPORT_SCHEMA = "operator-selection-ipsw-exposure-clustered-report-v3"
SELECTION_FEATURE_NAMES = (
    "p_tp",
    "p_sl",
    "p_timeout",
    "net_rr",
    "net_ev_r",
    "gross_edge_rate",
    "risk_rate",
    "notional_to_capital",
    "stress_to_budget",
    "leverage",
    "liquidation_buffer_rate",
    "warning_count",
    "limited_status",
    "entry_inside_zone",
    "vwap_impact_bps",
    "depth_utilization",
    "seconds_to_expiry",
    "hour_sin",
    "hour_cos",
    "weekday_sin",
    "weekday_cos",
    "direction_long",
)
_ALLOWED_ACTIONS = frozenset({"ACCEPT", "REJECT", "NO_DECISION"})


@dataclass(frozen=True)
class SelectionObservation:
    plan_id: str
    observed_at: datetime
    decision_action: str
    counterfactual_r: float
    features: Mapping[str, float]
    cluster_id: str | None = None

    @property
    def selected(self) -> int:
        return int(self.decision_action == "ACCEPT")

    @property
    def dependence_cluster_id(self) -> str:
        return self.cluster_id or self.plan_id


def _base_report(observations: list[SelectionObservation]) -> dict:
    actions = {action: 0 for action in sorted(_ALLOWED_ACTIONS)}
    for row in observations:
        actions[row.decision_action] += 1
    selected = [row.counterfactual_r for row in observations if row.selected]
    unselected = [row.counterfactual_r for row in observations if not row.selected]
    all_values = [row.counterfactual_r for row in observations]
    return {
        "schema": SELECTION_REPORT_SCHEMA,
        "status": "NOT_EVALUATED",
        "eligible_valued_count": len(observations),
        "decision_counts": actions,
        "acceptance_rate": (len(selected) / len(observations) if observations else None),
        "eligible_counterfactual_mean_r": (float(np.mean(all_values)) if all_values else None),
        "selected_counterfactual_mean_r": (float(np.mean(selected)) if selected else None),
        "unselected_counterfactual_mean_r": (float(np.mean(unselected)) if unselected else None),
        "selected_subset_bias_r": (
            float(np.mean(selected) - np.mean(all_values)) if selected and all_values else None
        ),
        "ipsw_selected_mean_r": None,
        "dependence_aware_inference": None,
        "propensity": {
            "method": "chronological-expanding-signal-cluster-logistic-v2",
            "feature_schema": SELECTION_FEATURE_SCHEMA,
            "feature_names": list(SELECTION_FEATURE_NAMES),
            "out_of_sample_count": 0,
            "brier_score": None,
            "log_loss": None,
            "effective_sample_size": None,
            "selected_scored_count": 0,
            "weight_clip_rate": None,
            "overlap_low": None,
            "overlap_high": None,
        },
        "causal_effect_claimed": False,
        "interpretation": (
            "Counterfactual outcomes are observed for all eligible plans. IPSW is a diagnostic "
            "reweighting of accepted plans toward the ex-ante covariate distribution of all "
            "eligible plans; it is not a causal treatment-effect estimate or proof of profitability."
        ),
    }


def _validate_observations(observations: list[SelectionObservation]) -> None:
    seen: set[str] = set()
    required = set(SELECTION_FEATURE_NAMES)
    for row in observations:
        if not row.plan_id or row.plan_id in seen:
            raise ValueError("Selection observations require unique non-empty plan_id values")
        if not row.dependence_cluster_id:
            raise ValueError("Selection observations require a non-empty dependence cluster")
        seen.add(row.plan_id)
        if row.observed_at.tzinfo is None or row.observed_at.utcoffset() is None:
            raise ValueError("Selection observed_at must be timezone-aware")
        if row.decision_action not in _ALLOWED_ACTIONS:
            raise ValueError(f"Unsupported operator decision action: {row.decision_action}")
        if not isfinite(float(row.counterfactual_r)):
            raise ValueError("Selection counterfactual_r must be finite")
        if set(row.features) != required:
            raise ValueError("Selection feature schema is incomplete or contains outcome leakage")
        for name in SELECTION_FEATURE_NAMES:
            value = float(row.features[name])
            if not isfinite(value):
                raise ValueError(f"Selection feature {name} must be finite")


def _chronological_propensity_scores(
    observations: list[SelectionObservation],
    *,
    warmup_observations: int,
    block_size: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if warmup_observations < 20:
        raise ValueError("warmup_observations must be at least 20")
    if block_size < 5:
        raise ValueError("block_size must be at least 5")
    matrix = np.asarray(
        [[float(row.features[name]) for name in SELECTION_FEATURE_NAMES] for row in observations],
        dtype=float,
    )
    labels = np.asarray([row.selected for row in observations], dtype=int)
    scores = np.full(len(observations), np.nan, dtype=float)

    grouped: dict[str, list[int]] = {}
    for index, row in enumerate(observations):
        grouped.setdefault(row.dependence_cluster_id, []).append(index)
    clusters = sorted(
        grouped,
        key=lambda cluster: (
            min(observations[index].observed_at for index in grouped[cluster]),
            cluster,
        ),
    )
    cluster_rows = [np.asarray(grouped[cluster], dtype=int) for cluster in clusters]
    cluster_min_time = [min(observations[index].observed_at for index in rows) for rows in cluster_rows]
    cluster_max_time = [max(observations[index].observed_at for index in rows) for rows in cluster_rows]

    cursor = 0
    warmup_rows = 0
    while cursor < len(cluster_rows) and warmup_rows < warmup_observations:
        warmup_rows += len(cluster_rows[cursor])
        cursor += 1
    while cursor < len(cluster_rows):
        stop = cursor
        test_row_count = 0
        while stop < len(cluster_rows) and test_row_count < block_size:
            test_row_count += len(cluster_rows[stop])
            stop += 1
        test_indexes = np.concatenate(cluster_rows[cursor:stop])
        test_start = min(cluster_min_time[cursor:stop])
        eligible_train_groups = [
            cluster_rows[index]
            for index in range(cursor)
            if cluster_max_time[index] < test_start
        ]
        if eligible_train_groups:
            train_indexes = np.concatenate(eligible_train_groups)
            train_labels = labels[train_indexes]
            if (
                np.unique(train_labels).size >= 2
                and np.sum(train_labels == 1) >= 5
                and np.sum(train_labels == 0) >= 5
            ):
                model = Pipeline(
                    [
                        ("scale", StandardScaler()),
                        (
                            "logit",
                            LogisticRegression(
                                solver="lbfgs",
                                max_iter=2000,
                                random_state=0,
                            ),
                        ),
                    ]
                )
                model.fit(matrix[train_indexes], train_labels)
                scores[test_indexes] = model.predict_proba(matrix[test_indexes])[:, 1]
        cursor = stop
    mask = np.isfinite(scores)
    return labels[mask], scores[mask], np.flatnonzero(mask)


def analyze_operator_selection(
    observations: list[SelectionObservation],
    *,
    minimum_total: int = 60,
    minimum_selected: int = 15,
    minimum_unselected: int = 15,
    warmup_observations: int = 40,
    block_size: int = 20,
    propensity_floor: float = 0.05,
    dependence_block_clusters: int = 5,
    minimum_independent_clusters: int = 30,
    bootstrap_replicates: int = 500,
    confidence_level: float = 0.95,
) -> dict:
    """Quantify operator-selection bias with honest chronological OOS propensities.

    Outcomes are counterfactual plan outcomes already resolved for accepted and
    unaccepted eligible plans. The direct all-eligible mean is therefore the primary
    benchmark. IPSW is retained as a diagnostic showing whether the accepted subset
    can be reweighted back toward the eligible ex-ante covariate distribution.
    """

    if min(minimum_total, minimum_selected, minimum_unselected) < 0:
        raise ValueError("Selection minimum sample requirements cannot be negative")
    if not 0 < propensity_floor < 0.5:
        raise ValueError("propensity_floor must be between zero and 0.5")
    if dependence_block_clusters < 2:
        raise ValueError("dependence_block_clusters must be at least two")
    if minimum_independent_clusters < 2 * dependence_block_clusters:
        raise ValueError(
            "minimum_independent_clusters must cover at least two dependence blocks"
        )
    ordered = sorted(observations, key=lambda row: (row.observed_at, row.plan_id))
    _validate_observations(ordered)
    report = _base_report(ordered)
    if len(ordered) < minimum_total:
        report["status"] = "INSUFFICIENT_SAMPLE"
        return report
    selected_count = sum(row.selected for row in ordered)
    unselected_count = len(ordered) - selected_count
    if selected_count < minimum_selected or unselected_count < minimum_unselected:
        report["status"] = "CLASS_COLLAPSE"
        return report

    labels, raw_scores, scored_indexes = _chronological_propensity_scores(
        ordered,
        warmup_observations=warmup_observations,
        block_size=block_size,
    )
    if not len(raw_scores):
        report["status"] = "NO_OUT_OF_SAMPLE_SCORES"
        return report
    clipped = np.clip(raw_scores, propensity_floor, 1.0 - propensity_floor)
    clipped_count = int(np.sum(raw_scores != clipped))
    selected_mask = labels == 1
    unselected_mask = ~selected_mask
    if not np.any(selected_mask) or not np.any(unselected_mask):
        report["status"] = "CLASS_COLLAPSE"
        return report

    selected_scores = clipped[selected_mask]
    unselected_scores = clipped[unselected_mask]
    overlap_low = float(max(np.min(selected_scores), np.min(unselected_scores)))
    overlap_high = float(min(np.max(selected_scores), np.max(unselected_scores)))
    propensity = report["propensity"]
    propensity.update(
        {
            "out_of_sample_count": int(len(clipped)),
            "brier_score": float(brier_score_loss(labels, clipped)),
            "log_loss": float(log_loss(labels, clipped, labels=[0, 1])),
            "selected_scored_count": int(np.sum(selected_mask)),
            "weight_clip_rate": float(clipped_count / len(clipped)),
            "overlap_low": overlap_low,
            "overlap_high": overlap_high,
        }
    )
    if overlap_low >= overlap_high:
        report["status"] = "POOR_OVERLAP"
        return report

    scored_outcomes = np.asarray([ordered[index].counterfactual_r for index in scored_indexes], dtype=float)
    scored_clusters = [ordered[index].dependence_cluster_id for index in scored_indexes]
    unique_cluster_count = len(set(scored_clusters))
    if unique_cluster_count < minimum_independent_clusters:
        report["status"] = "INSUFFICIENT_CLUSTER_EVIDENCE"
        report["dependence_aware_inference"] = {
            "schema": "signal-cluster-moving-block-bootstrap-v1",
            "status": "INSUFFICIENT_CLUSTERS",
            "unique_cluster_count": unique_cluster_count,
            "minimum_independent_clusters": int(minimum_independent_clusters),
            "block_clusters": int(dependence_block_clusters),
        }
        return report
    selection_rate = float(np.mean(labels))
    weights = selection_rate / selected_scores
    selected_outcomes = scored_outcomes[selected_mask]
    weight_sum = float(np.sum(weights))
    weight_square_sum = float(np.sum(np.square(weights)))
    if weight_sum <= 0 or weight_square_sum <= 0:
        report["status"] = "INVALID_WEIGHTS"
        return report
    effective_sample_size = weight_sum * weight_sum / weight_square_sum
    propensity["effective_sample_size"] = float(effective_sample_size)
    minimum_ess = max(10.0, 0.2 * float(len(selected_outcomes)))
    if effective_sample_size < minimum_ess:
        report["status"] = "LOW_EFFECTIVE_SAMPLE_SIZE"
        return report

    report["ipsw_selected_mean_r"] = float(np.sum(weights * selected_outcomes) / weight_sum)
    report["ipsw_scored_eligible_mean_r"] = float(np.mean(scored_outcomes))
    report["ipsw_scored_selected_mean_r"] = float(np.mean(selected_outcomes))

    full_weights = np.zeros(len(labels), dtype=float)
    full_weights[selected_mask] = weights
    try:
        dependence = cluster_moving_block_bootstrap(
            scored_outcomes,
            selected=labels,
            weights=full_weights,
            cluster_ids=scored_clusters,
            observed_at=[ordered[index].observed_at for index in scored_indexes],
            block_clusters=dependence_block_clusters,
            replicates=bootstrap_replicates,
            confidence_level=confidence_level,
        )
    except ValueError as exc:
        report["status"] = "INVALID_CLUSTER_DEPENDENCE_EVIDENCE"
        report["dependence_aware_inference"] = {
            "schema": "signal-cluster-moving-block-bootstrap-v1",
            "status": "INVALID",
            "reason": str(exc),
            "unique_cluster_count": unique_cluster_count,
        }
        return report
    dependence["minimum_independent_clusters"] = int(minimum_independent_clusters)
    cluster_counts = list(dependence.pop("cluster_row_counts").values())
    dependence["cluster_size_summary"] = {
        "minimum": int(min(cluster_counts)),
        "median": float(np.median(cluster_counts)),
        "maximum": int(max(cluster_counts)),
    }
    report["dependence_aware_inference"] = dependence
    report["status"] = "READY"
    return report

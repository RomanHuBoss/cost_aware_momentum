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

SELECTION_FEATURE_SCHEMA = "operator-selection-predecision-v1"
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

    @property
    def selected(self) -> int:
        return int(self.decision_action == "ACCEPT")


def _base_report(observations: list[SelectionObservation]) -> dict:
    actions = {action: 0 for action in sorted(_ALLOWED_ACTIONS)}
    for row in observations:
        actions[row.decision_action] += 1
    selected = [row.counterfactual_r for row in observations if row.selected]
    unselected = [row.counterfactual_r for row in observations if not row.selected]
    all_values = [row.counterfactual_r for row in observations]
    return {
        "schema": "operator-selection-ipsw-report-v1",
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
        "propensity": {
            "method": "chronological-expanding-logistic-v1",
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
    start = min(warmup_observations, len(observations))
    while start < len(observations):
        train_labels = labels[:start]
        if np.unique(train_labels).size < 2 or np.sum(train_labels == 1) < 5 or np.sum(train_labels == 0) < 5:
            start += 1
            continue
        stop = min(len(observations), start + block_size)
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
        model.fit(matrix[:start], train_labels)
        scores[start:stop] = model.predict_proba(matrix[start:stop])[:, 1]
        start = stop
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
    report["status"] = "READY"
    return report

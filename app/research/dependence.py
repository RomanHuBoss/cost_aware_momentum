from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Sequence
from datetime import datetime
from statistics import NormalDist
from typing import Any

import numpy as np

HAC_MEAN_SCHEMA_VERSION = "newey-west-bartlett-mean-v1"
MOVING_BLOCK_BOOTSTRAP_SCHEMA_VERSION = "moving-block-bootstrap-percentile-v1"
CLUSTER_BLOCK_BOOTSTRAP_SCHEMA_VERSION = "signal-cluster-moving-block-bootstrap-v1"
DEPENDENCE_REPORT_SCHEMA_VERSION = "time-series-dependence-aware-inference-v1"
DEFAULT_BOOTSTRAP_SEED = 20260705


def _finite_vector(values: Any, *, minimum_length: int = 2, name: str = "values") -> np.ndarray:
    vector = np.asarray(values, dtype=float)
    if vector.ndim != 1 or len(vector) < minimum_length:
        raise ValueError(f"{name} must be one-dimensional with at least {minimum_length} rows")
    if not np.isfinite(vector).all():
        raise ValueError(f"{name} must contain only finite values")
    return vector


def _validate_confidence(confidence_level: float) -> float:
    confidence = float(confidence_level)
    if not math.isfinite(confidence) or not 0.5 < confidence < 1.0:
        raise ValueError("confidence_level must be finite and between 0.5 and 1")
    return confidence


def _nonannualized_sharpe(values: np.ndarray) -> float:
    deviation = float(np.std(values, ddof=1))
    mean = float(np.mean(values))
    if deviation <= 1e-15:
        if abs(mean) <= 1e-15:
            return 0.0
        raise ValueError("Sharpe ratio is undefined for a non-zero constant return series")
    result = mean / deviation
    if not math.isfinite(result):
        raise ValueError("Sharpe ratio must be finite")
    return float(result)


def _percentile_interval(samples: np.ndarray, *, estimate: float, confidence_level: float) -> dict[str, float]:
    alpha = (1.0 - confidence_level) / 2.0
    lower, upper = np.quantile(samples, [alpha, 1.0 - alpha])
    return {
        "estimate": float(estimate),
        "lower": float(lower),
        "upper": float(upper),
        "bootstrap_standard_error": float(np.std(samples, ddof=1)),
    }


def automatic_newey_west_lag(observations: int) -> int:
    if observations < 2:
        raise ValueError("observations must be at least two")
    # Common data-driven bandwidth used for Bartlett-kernel HAC summaries.
    lag = int(math.floor(4.0 * (observations / 100.0) ** (2.0 / 9.0)))
    return max(1, min(observations - 1, lag))


def newey_west_mean_inference(
    values: Any,
    *,
    max_lag: int | None = None,
    confidence_level: float = 0.95,
) -> dict[str, Any]:
    vector = _finite_vector(values, minimum_length=3)
    confidence = _validate_confidence(confidence_level)
    observations = len(vector)
    lag = automatic_newey_west_lag(observations) if max_lag is None else int(max_lag)
    if lag < 0 or lag >= observations:
        raise ValueError("max_lag must be between zero and observations - 1")

    mean = float(np.mean(vector))
    centered = vector - mean
    gamma0 = float(np.dot(centered, centered) / observations)
    long_run_variance_raw = gamma0
    autocovariances: list[float] = []
    for offset in range(1, lag + 1):
        gamma = float(np.dot(centered[offset:], centered[:-offset]) / observations)
        autocovariances.append(gamma)
        long_run_variance_raw += 2.0 * (1.0 - offset / (lag + 1.0)) * gamma
    if not math.isfinite(long_run_variance_raw):
        raise ValueError("Newey-West long-run variance must be finite")
    if long_run_variance_raw < -1e-12:
        raise ValueError("Newey-West long-run variance is materially negative")

    # Do not claim more effective observations than the nominal sample when negative
    # autocorrelation makes the raw HAC estimate smaller than the IID variance.
    long_run_variance = max(gamma0, max(0.0, long_run_variance_raw))
    standard_error = math.sqrt(long_run_variance / observations)
    naive_standard_error = math.sqrt(gamma0 / observations)
    if long_run_variance <= 1e-30:
        effective_observations = float(observations)
    else:
        effective_observations = float(
            np.clip(observations * gamma0 / long_run_variance, 1.0, float(observations))
        )
    critical = NormalDist().inv_cdf(0.5 + confidence / 2.0)
    return {
        "schema": HAC_MEAN_SCHEMA_VERSION,
        "status": "READY",
        "observations": observations,
        "max_lag": lag,
        "confidence_level": confidence,
        "mean": mean,
        "standard_error": standard_error,
        "naive_standard_error": naive_standard_error,
        "standard_error_inflation": (
            float(standard_error / naive_standard_error) if naive_standard_error > 0 else 1.0
        ),
        "iid_variance": gamma0,
        "raw_long_run_variance": float(long_run_variance_raw),
        "long_run_variance": float(long_run_variance),
        "effective_observations": effective_observations,
        "confidence_interval": [
            float(mean - critical * standard_error),
            float(mean + critical * standard_error),
        ],
        "autocovariances": autocovariances,
    }


def _moving_block_samples(
    vector: np.ndarray,
    *,
    block_length: int,
    replicates: int,
    seed: int,
) -> list[np.ndarray]:
    observations = len(vector)
    if block_length < 2 or block_length > observations:
        raise ValueError("block_length must be between two and the sample size")
    if observations // block_length < 2:
        raise ValueError("At least two non-overlapping dependence blocks are required")
    if replicates < 100:
        raise ValueError("replicates must be at least 100")
    starts = np.arange(observations - block_length + 1, dtype=int)
    blocks_needed = math.ceil(observations / block_length)
    rng = np.random.default_rng(int(seed))
    samples: list[np.ndarray] = []
    for _ in range(replicates):
        selected_starts = rng.choice(starts, size=blocks_needed, replace=True)
        sample = np.concatenate(
            [vector[start : start + block_length] for start in selected_starts]
        )[:observations]
        samples.append(sample)
    return samples


def moving_block_bootstrap_inference(
    values: Any,
    *,
    block_length: int,
    replicates: int = 1000,
    confidence_level: float = 0.95,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> dict[str, Any]:
    vector = _finite_vector(values, minimum_length=4)
    confidence = _validate_confidence(confidence_level)
    samples = _moving_block_samples(
        vector,
        block_length=int(block_length),
        replicates=int(replicates),
        seed=int(seed),
    )
    means: list[float] = []
    sharpes: list[float] = []
    for sample in samples:
        means.append(float(np.mean(sample)))
        try:
            sharpes.append(_nonannualized_sharpe(sample))
        except ValueError:
            continue
    minimum_valid = max(100, int(math.ceil(0.90 * replicates)))
    if len(sharpes) < minimum_valid:
        raise ValueError("Too few valid moving-block bootstrap Sharpe replicates")
    mean_array = np.asarray(means, dtype=float)
    sharpe_array = np.asarray(sharpes, dtype=float)
    return {
        "schema": MOVING_BLOCK_BOOTSTRAP_SCHEMA_VERSION,
        "status": "READY",
        "observations": int(len(vector)),
        "block_length": int(block_length),
        "independent_block_count": int(len(vector) // block_length),
        "replicates": int(replicates),
        "valid_replicates": int(min(len(mean_array), len(sharpe_array))),
        "confidence_level": confidence,
        "seed": int(seed),
        "mean_return": _percentile_interval(
            mean_array,
            estimate=float(np.mean(vector)),
            confidence_level=confidence,
        ),
        "sharpe": _percentile_interval(
            sharpe_array,
            estimate=_nonannualized_sharpe(vector),
            confidence_level=confidence,
        ),
    }


def time_series_dependence_report(
    values: Any,
    *,
    block_length: int,
    minimum_independent_blocks: int,
    replicates: int = 1000,
    confidence_level: float = 0.95,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> dict[str, Any]:
    vector = _finite_vector(values, minimum_length=4)
    if minimum_independent_blocks < 2:
        raise ValueError("minimum_independent_blocks must be at least two")
    independent_blocks = len(vector) // int(block_length)
    report: dict[str, Any] = {
        "schema": DEPENDENCE_REPORT_SCHEMA_VERSION,
        "status": "NOT_EVALUATED",
        "observations": int(len(vector)),
        "block_length": int(block_length),
        "independent_block_count": int(independent_blocks),
        "minimum_independent_blocks": int(minimum_independent_blocks),
        "confidence_level": float(confidence_level),
        "hac_mean": None,
        "moving_block_bootstrap": None,
        "dependence_supported": False,
    }
    if independent_blocks < minimum_independent_blocks:
        report["status"] = "INSUFFICIENT_BLOCKS"
        return report
    hac = newey_west_mean_inference(
        vector,
        max_lag=min(int(block_length) - 1, len(vector) - 1),
        confidence_level=confidence_level,
    )
    bootstrap = moving_block_bootstrap_inference(
        vector,
        block_length=block_length,
        replicates=replicates,
        confidence_level=confidence_level,
        seed=seed,
    )
    hac_lower = float(hac["confidence_interval"][0])
    mean_lower = float(bootstrap["mean_return"]["lower"])
    sharpe_lower = float(bootstrap["sharpe"]["lower"])
    report.update(
        {
            "status": "READY",
            "hac_mean": hac,
            "moving_block_bootstrap": bootstrap,
            "dependence_supported": bool(hac_lower > 0 and mean_lower > 0 and sharpe_lower > 0),
        }
    )
    return report


def _ordered_cluster_rows(
    cluster_ids: Sequence[Any],
    observed_at: Sequence[datetime],
) -> tuple[list[str], dict[str, np.ndarray], dict[str, int]]:
    if len(cluster_ids) != len(observed_at):
        raise ValueError("cluster_ids and observed_at must align")
    grouped: OrderedDict[str, list[int]] = OrderedDict()
    cluster_first: dict[str, datetime] = {}
    for index, (raw_cluster, timestamp) in enumerate(zip(cluster_ids, observed_at, strict=True)):
        cluster = str(raw_cluster)
        if not cluster:
            raise ValueError("cluster_id cannot be empty")
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("cluster observed_at must be timezone-aware")
        grouped.setdefault(cluster, []).append(index)
        cluster_first[cluster] = min(cluster_first.get(cluster, timestamp), timestamp)
    ordered_clusters = sorted(grouped, key=lambda item: (cluster_first[item], item))
    arrays = {cluster: np.asarray(grouped[cluster], dtype=int) for cluster in ordered_clusters}
    counts = {cluster: int(len(arrays[cluster])) for cluster in ordered_clusters}
    return ordered_clusters, arrays, counts


def _metric_interval(
    samples: list[float],
    *,
    estimate: float,
    confidence_level: float,
) -> dict[str, float | int]:
    array = np.asarray(samples, dtype=float)
    if len(array) < 100 or not np.isfinite(array).all():
        raise ValueError("Too few valid cluster-bootstrap replicates")
    result = _percentile_interval(
        array,
        estimate=estimate,
        confidence_level=confidence_level,
    )
    result["valid_replicates"] = int(len(array))
    return result


def cluster_moving_block_bootstrap(
    outcomes: Any,
    *,
    selected: Any,
    weights: Any,
    cluster_ids: Sequence[Any],
    observed_at: Sequence[datetime],
    block_clusters: int,
    replicates: int = 1000,
    confidence_level: float = 0.95,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> dict[str, Any]:
    outcome_vector = _finite_vector(outcomes, minimum_length=4, name="outcomes")
    selected_vector = np.asarray(selected, dtype=int)
    weight_vector = np.asarray(weights, dtype=float)
    if selected_vector.shape != outcome_vector.shape or weight_vector.shape != outcome_vector.shape:
        raise ValueError("outcomes, selected and weights must align")
    if not np.isin(selected_vector, [0, 1]).all():
        raise ValueError("selected must contain only zero and one")
    if not np.isfinite(weight_vector).all() or np.any(weight_vector < 0):
        raise ValueError("weights must be finite and non-negative")
    confidence = _validate_confidence(confidence_level)
    if replicates < 100:
        raise ValueError("replicates must be at least 100")

    clusters, cluster_rows, cluster_counts = _ordered_cluster_rows(cluster_ids, observed_at)
    cluster_count = len(clusters)
    if block_clusters < 2 or block_clusters > cluster_count:
        raise ValueError("block_clusters must be between two and the unique cluster count")
    if cluster_count // block_clusters < 2:
        raise ValueError("At least two non-overlapping cluster blocks are required")
    selected_mask = selected_vector == 1
    if not np.any(selected_mask) or not np.any(~selected_mask):
        raise ValueError("Cluster bootstrap requires selected and unselected observations")
    selected_weight_sum = float(np.sum(weight_vector[selected_mask]))
    if selected_weight_sum <= 0:
        raise ValueError("Selected cluster-bootstrap weights must sum to a positive value")

    estimates = {
        "eligible_mean_r": float(np.mean(outcome_vector)),
        "selected_mean_r": float(np.mean(outcome_vector[selected_mask])),
        "ipsw_mean_r": float(
            np.sum(weight_vector[selected_mask] * outcome_vector[selected_mask])
            / selected_weight_sum
        ),
    }
    estimates["selected_subset_bias_r"] = (
        estimates["selected_mean_r"] - estimates["eligible_mean_r"]
    )

    starts = np.arange(cluster_count - block_clusters + 1, dtype=int)
    blocks_needed = math.ceil(cluster_count / block_clusters)
    rng = np.random.default_rng(int(seed))
    sampled_metrics: dict[str, list[float]] = {name: [] for name in estimates}
    for _ in range(int(replicates)):
        sampled_starts = rng.choice(starts, size=blocks_needed, replace=True)
        sampled_clusters: list[str] = []
        for start in sampled_starts:
            sampled_clusters.extend(clusters[start : start + block_clusters])
        sampled_clusters = sampled_clusters[:cluster_count]
        indexes = np.concatenate([cluster_rows[cluster] for cluster in sampled_clusters])
        sample_outcomes = outcome_vector[indexes]
        sample_selected = selected_vector[indexes] == 1
        sample_weights = weight_vector[indexes]
        if not np.any(sample_selected) or not np.any(~sample_selected):
            continue
        sample_selected_weights = sample_weights[sample_selected]
        weight_sum = float(np.sum(sample_selected_weights))
        if weight_sum <= 0:
            continue
        eligible_mean = float(np.mean(sample_outcomes))
        selected_mean = float(np.mean(sample_outcomes[sample_selected]))
        ipsw_mean = float(
            np.sum(sample_selected_weights * sample_outcomes[sample_selected]) / weight_sum
        )
        sampled_metrics["eligible_mean_r"].append(eligible_mean)
        sampled_metrics["selected_mean_r"].append(selected_mean)
        sampled_metrics["ipsw_mean_r"].append(ipsw_mean)
        sampled_metrics["selected_subset_bias_r"].append(selected_mean - eligible_mean)

    minimum_valid = max(100, int(math.ceil(0.90 * replicates)))
    if min(len(values) for values in sampled_metrics.values()) < minimum_valid:
        raise ValueError("Too few valid signal-cluster bootstrap replicates")
    metrics = {
        name: _metric_interval(
            values,
            estimate=estimates[name],
            confidence_level=confidence,
        )
        for name, values in sampled_metrics.items()
    }
    return {
        "schema": CLUSTER_BLOCK_BOOTSTRAP_SCHEMA_VERSION,
        "status": "READY",
        "cluster_unit": "signal_id",
        "unique_cluster_count": cluster_count,
        "cluster_row_counts": cluster_counts,
        "block_clusters": int(block_clusters),
        "independent_block_count": int(cluster_count // block_clusters),
        "replicates": int(replicates),
        "valid_replicates": int(min(len(values) for values in sampled_metrics.values())),
        "confidence_level": confidence,
        "seed": int(seed),
        "metrics": metrics,
        "propensity_refit_inside_bootstrap": False,
    }

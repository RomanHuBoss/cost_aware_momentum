from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from datetime import datetime
from statistics import NormalDist
from typing import Any

import numpy as np

from app.research.dependence import time_series_dependence_report

EULER_MASCHERONI = 0.5772156649015329
PBO_SCHEMA_VERSION = "cscv-pbo-contiguous-segments-v1"
DSR_SCHEMA_VERSION = "deflated-sharpe-bailey-lopez-de-prado-hac-effective-n-v2"
EXPERIMENT_REPORT_SCHEMA_VERSION = "experiment-selection-dependence-governance-v2"
EXPERIMENT_PERIOD_RETURN_SCHEMA_VERSION = (
    "observed-opportunity-covered-hourly-mark-to-market-capital-return-path-v3"
)


@dataclass(frozen=True)
class ExperimentTrialEvidence:
    trial_id: str
    configuration_hash: str
    timestamps: tuple[datetime, ...]
    returns: tuple[float, ...]


@dataclass(frozen=True)
class ExperimentFamilyEvidence:
    experiment_family: str
    attempted_configuration_hashes: tuple[str, ...]
    successful_trials: tuple[ExperimentTrialEvidence, ...]
    failed_configuration_hashes: tuple[str, ...]
    open_trial_ids: tuple[str, ...]
    declared_horizons: tuple[int, ...] = ()


def _return_vector(values: Any, *, minimum_length: int = 2) -> np.ndarray:
    vector = np.asarray(values, dtype=float)
    if vector.ndim != 1 or len(vector) < minimum_length:
        raise ValueError(f"Return series must be one-dimensional with at least {minimum_length} rows")
    if not np.isfinite(vector).all():
        raise ValueError("Return series must contain only finite values")
    if np.any(vector <= -1.0):
        raise ValueError("Period returns at or below -100% are invalid")
    return vector


def _finite_vector(values: Any, *, minimum_length: int = 2, name: str = "vector") -> np.ndarray:
    vector = np.asarray(values, dtype=float)
    if vector.ndim != 1 or len(vector) < minimum_length:
        raise ValueError(f"{name} must be one-dimensional with at least {minimum_length} rows")
    if not np.isfinite(vector).all():
        raise ValueError(f"{name} must contain only finite values")
    return vector


def _return_matrix(values: Any, *, minimum_rows: int = 2, minimum_trials: int = 2) -> np.ndarray:
    matrix = np.asarray(values, dtype=float)
    if matrix.ndim != 2:
        raise ValueError("Trial return matrix must be two-dimensional")
    if matrix.shape[0] < minimum_rows or matrix.shape[1] < minimum_trials:
        raise ValueError(
            f"Trial return matrix requires at least {minimum_rows} periods and {minimum_trials} trials"
        )
    if not np.isfinite(matrix).all():
        raise ValueError("Trial return matrix must contain only finite values")
    if np.any(matrix <= -1.0):
        raise ValueError("Period returns at or below -100% are invalid")
    return matrix


def nonannualized_sharpe(returns: Any) -> float:
    vector = _return_vector(returns)
    deviation = float(np.std(vector, ddof=1))
    mean = float(np.mean(vector))
    if deviation <= 1e-15:
        if abs(mean) <= 1e-15:
            return 0.0
        raise ValueError("Sharpe ratio is undefined for a non-zero constant return series")
    result = mean / deviation
    if not math.isfinite(result):
        raise ValueError("Sharpe ratio must be finite")
    return float(result)


def _trial_scores(matrix: np.ndarray) -> np.ndarray:
    return np.asarray([nonannualized_sharpe(matrix[:, index]) for index in range(matrix.shape[1])])


def effective_independent_trials(return_matrix: Any) -> dict[str, float | str | int]:
    matrix = _return_matrix(return_matrix)
    trial_count = int(matrix.shape[1])
    correlation = np.corrcoef(matrix, rowvar=False)
    if correlation.shape != (trial_count, trial_count) or not np.isfinite(correlation).all():
        raise ValueError("Trial correlation matrix is not finite")
    off_diagonal = correlation[np.triu_indices(trial_count, k=1)]
    raw_average = float(np.mean(off_diagonal))
    # Negative average dependence would imply more independent sources than submitted
    # trials under the interpolation in the DSR paper. Cap at zero so the estimate is
    # conservative and never exceeds the disclosed number of configurations.
    average = float(np.clip(raw_average, 0.0, 1.0))
    effective = average + (1.0 - average) * trial_count
    return {
        "schema": "average-correlation-implied-independent-trials-v1",
        "trial_count": trial_count,
        "raw_average_correlation": raw_average,
        "average_correlation": average,
        "effective_trials": float(np.clip(effective, 1.0, float(trial_count))),
    }


def deflated_sharpe_ratio(
    selected_returns: Any,
    *,
    trial_sharpes: Any,
    effective_trials: float,
    effective_observations: float | None = None,
) -> dict[str, float | str | int]:
    returns = _return_vector(selected_returns, minimum_length=3)
    sharpes = _finite_vector(trial_sharpes, minimum_length=2, name="trial_sharpes")
    n_eff = float(effective_trials)
    if not math.isfinite(n_eff) or n_eff < 2.0 or n_eff > len(sharpes) + 1e-9:
        raise ValueError("effective_trials must be finite, at least two, and not exceed trial count")

    selected_sharpe = nonannualized_sharpe(returns)
    n_observations = float(len(returns) if effective_observations is None else effective_observations)
    if not math.isfinite(n_observations) or not 2.0 <= n_observations <= len(returns):
        raise ValueError("effective_observations must be finite, at least two, and not exceed observations")
    sharpe_variance = float(np.var(sharpes, ddof=1))
    if not math.isfinite(sharpe_variance) or sharpe_variance < 0:
        raise ValueError("Trial Sharpe variance must be finite and non-negative")

    normal = NormalDist()
    benchmark = math.sqrt(sharpe_variance) * (
        (1.0 - EULER_MASCHERONI) * normal.inv_cdf(1.0 - 1.0 / n_eff)
        + EULER_MASCHERONI * normal.inv_cdf(1.0 - 1.0 / (n_eff * math.e))
    )
    centered = returns - float(np.mean(returns))
    second = float(np.mean(centered**2))
    if second <= 0:
        raise ValueError("Selected return variance must be positive")
    skewness = float(np.mean(centered**3) / second**1.5)
    kurtosis = float(np.mean(centered**4) / second**2)
    variance_term = (
        1.0
        - skewness * selected_sharpe
        + ((kurtosis - 1.0) / 4.0) * selected_sharpe * selected_sharpe
    )
    if not math.isfinite(variance_term) or variance_term <= 0:
        raise ValueError("Deflated Sharpe variance term must be finite and positive")
    z_value = (selected_sharpe - benchmark) * math.sqrt(n_observations - 1.0) / math.sqrt(variance_term)
    probability = normal.cdf(z_value)
    return {
        "schema": DSR_SCHEMA_VERSION,
        "status": "READY",
        "observations": int(len(returns)),
        "effective_observations": n_observations,
        "observation_adjustment_schema": (
            "newey-west-long-run-variance-effective-n-v1"
            if effective_observations is not None
            else "nominal-observation-count-v1"
        ),
        "trial_count": int(len(sharpes)),
        "effective_trials": n_eff,
        "selected_sharpe": float(selected_sharpe),
        "trial_sharpe_variance": sharpe_variance,
        "benchmark_sharpe": float(benchmark),
        "skewness": skewness,
        "kurtosis": kurtosis,
        "z_value": float(z_value),
        "probability": float(probability),
    }


def _average_rank(values: np.ndarray, selected_index: int) -> float:
    selected = float(values[selected_index])
    less = int(np.sum(values < selected))
    equal = int(np.sum(np.isclose(values, selected, rtol=1e-12, atol=1e-15)))
    return 1.0 + less + 0.5 * max(0, equal - 1)


def combinatorial_pbo(return_matrix: Any, *, segments: int = 6) -> dict[str, Any]:
    matrix = _return_matrix(return_matrix, minimum_rows=max(4, segments * 2))
    if segments < 4 or segments % 2:
        raise ValueError("PBO segments must be an even integer of at least four")
    if segments > matrix.shape[0] // 2:
        raise ValueError("Each PBO segment requires at least two observations")

    segment_indexes = tuple(np.asarray(item, dtype=int) for item in np.array_split(np.arange(len(matrix)), segments))
    if any(len(item) < 2 for item in segment_indexes):
        raise ValueError("Each PBO segment requires at least two observations")
    logits: list[float] = []
    selected_indexes: list[int] = []
    degradation: list[float] = []
    selected_oos_scores: list[float] = []
    half = segments // 2
    all_segments = set(range(segments))
    for is_segments in itertools.combinations(range(segments), half):
        oos_segments = sorted(all_segments.difference(is_segments))
        is_rows = np.concatenate([segment_indexes[index] for index in is_segments])
        oos_rows = np.concatenate([segment_indexes[index] for index in oos_segments])
        is_scores = _trial_scores(matrix[is_rows])
        oos_scores = _trial_scores(matrix[oos_rows])
        selected_index = int(np.argmax(is_scores))
        rank = _average_rank(oos_scores, selected_index)
        omega = rank / (matrix.shape[1] + 1.0)
        logit = math.log(omega / (1.0 - omega))
        logits.append(float(logit))
        selected_indexes.append(selected_index)
        selected_oos_scores.append(float(oos_scores[selected_index]))
        degradation.append(float(oos_scores[selected_index] - is_scores[selected_index]))

    pbo = float(np.mean(np.asarray(logits) <= 0.0))
    return {
        "schema": PBO_SCHEMA_VERSION,
        "status": "READY",
        "segments": segments,
        "periods": int(matrix.shape[0]),
        "trials": int(matrix.shape[1]),
        "split_count": len(logits),
        "pbo": pbo,
        "logits": logits,
        "selected_trial_indexes": selected_indexes,
        "mean_performance_degradation": float(np.mean(degradation)),
        "probability_of_oos_loss": float(np.mean(np.asarray(selected_oos_scores) < 0.0)),
    }


def _validate_trial(trial: ExperimentTrialEvidence) -> None:
    if not trial.trial_id:
        raise ValueError("Experiment trial_id cannot be empty")
    if len(trial.configuration_hash) != 64:
        raise ValueError("Experiment configuration_hash must contain 64 characters")
    if len(trial.timestamps) != len(trial.returns):
        raise ValueError("Experiment timestamps and returns must align")
    if len(set(trial.timestamps)) != len(trial.timestamps):
        raise ValueError("Experiment timestamps must be unique")
    if tuple(sorted(trial.timestamps)) != trial.timestamps:
        raise ValueError("Experiment timestamps must be strictly chronological")
    _return_vector(trial.returns)


def analyze_experiment_family(
    evidence: ExperimentFamilyEvidence,
    *,
    segments: int = 6,
    minimum_trials: int = 4,
    minimum_periods: int = 60,
    maximum_pbo: float = 0.20,
    minimum_dsr_probability: float = 0.95,
    dependence_block_periods: int = 8,
    minimum_independent_blocks: int = 6,
    bootstrap_replicates: int = 500,
    confidence_level: float = 0.95,
) -> dict[str, Any]:
    if not evidence.experiment_family:
        raise ValueError("experiment_family cannot be empty")
    if minimum_trials < 2 or minimum_periods < segments * 2:
        raise ValueError("Experiment minimums are inconsistent with PBO segmentation")
    if not 0 <= maximum_pbo <= 1 or not 0 <= minimum_dsr_probability <= 1:
        raise ValueError("Experiment governance probabilities must be between zero and one")

    attempted = tuple(dict.fromkeys(evidence.attempted_configuration_hashes))
    horizons = tuple(sorted(set(int(item) for item in evidence.declared_horizons)))
    if any(item <= 0 for item in horizons):
        raise ValueError("Experiment horizons must be positive")
    if any(len(item) != 64 for item in attempted):
        raise ValueError("Attempted configuration hashes must contain 64 characters")
    for trial in evidence.successful_trials:
        _validate_trial(trial)

    unique_success: dict[str, ExperimentTrialEvidence] = {}
    for trial in evidence.successful_trials:
        unique_success.setdefault(trial.configuration_hash, trial)
    missing = sorted(set(attempted).difference(unique_success))
    report: dict[str, Any] = {
        "schema": EXPERIMENT_REPORT_SCHEMA_VERSION,
        "experiment_family": evidence.experiment_family,
        "status": "NOT_EVALUATED",
        "attempted_configuration_count": len(attempted),
        "successful_unique_configuration_count": len(unique_success),
        "duplicate_success_count": len(evidence.successful_trials) - len(unique_success),
        "failed_configuration_count": len(set(evidence.failed_configuration_hashes)),
        "open_trial_count": len(set(evidence.open_trial_ids)),
        "declared_horizons": list(horizons),
        "missing_success_configuration_hashes": missing,
        "pbo": None,
        "deflated_sharpe": None,
        "dependence_aware_inference": None,
        "selected_configuration_hash": None,
        "thresholds": {
            "maximum_pbo": float(maximum_pbo),
            "minimum_dsr_probability": float(minimum_dsr_probability),
            "minimum_trials": int(minimum_trials),
            "minimum_periods": int(minimum_periods),
            "segments": int(segments),
            "dependence_block_periods": int(dependence_block_periods),
            "minimum_independent_blocks": int(minimum_independent_blocks),
            "bootstrap_replicates": int(bootstrap_replicates),
            "confidence_level": float(confidence_level),
        },
        "automatic_model_action": "none",
        "profitability_claimed": False,
    }
    if evidence.open_trial_ids or evidence.failed_configuration_hashes or missing:
        report["status"] = "BLOCKED_INCOMPLETE_LEDGER"
        return report
    if len(horizons) > 1:
        report["status"] = "BLOCKED_INCOMPATIBLE_HORIZONS"
        return report
    if len(unique_success) < minimum_trials:
        report["status"] = "BLOCKED_INSUFFICIENT_TRIALS"
        return report

    trials = list(unique_success.values())
    reference_timestamps = trials[0].timestamps
    if len(reference_timestamps) < minimum_periods:
        report["status"] = "BLOCKED_INSUFFICIENT_PERIODS"
        return report
    if any(trial.timestamps != reference_timestamps for trial in trials[1:]):
        report["status"] = "BLOCKED_UNALIGNED_RETURNS"
        return report

    matrix = np.column_stack([np.asarray(trial.returns, dtype=float) for trial in trials])
    try:
        sharpes = _trial_scores(matrix)
        selected_index = int(np.argmax(sharpes))
        independence = effective_independent_trials(matrix)
        if float(independence["effective_trials"]) < 2.0:
            report["status"] = "BLOCKED_REDUNDANT_TRIALS"
            report["independence"] = independence
            return report
        pbo = combinatorial_pbo(matrix, segments=segments)
        effective_block_periods = max(
            int(dependence_block_periods),
            int(horizons[0]) if horizons else 1,
        )
        dependence = time_series_dependence_report(
            matrix[:, selected_index],
            block_length=effective_block_periods,
            minimum_independent_blocks=minimum_independent_blocks,
            replicates=bootstrap_replicates,
            confidence_level=confidence_level,
        )
        dependence["requested_block_periods"] = int(dependence_block_periods)
        dependence["horizon_floor_periods"] = int(horizons[0]) if horizons else None
        if dependence["status"] != "READY":
            report.update(
                {
                    "status": "BLOCKED_INSUFFICIENT_DEPENDENCE_EVIDENCE",
                    "selected_configuration_hash": trials[selected_index].configuration_hash,
                    "selected_trial_id": trials[selected_index].trial_id,
                    "period_count": int(matrix.shape[0]),
                    "period_start": reference_timestamps[0].isoformat(),
                    "period_end": reference_timestamps[-1].isoformat(),
                    "pbo": pbo,
                    "dependence_aware_inference": dependence,
                }
            )
            return report
        dsr = deflated_sharpe_ratio(
            matrix[:, selected_index],
            trial_sharpes=sharpes,
            effective_trials=float(independence["effective_trials"]),
            effective_observations=float(
                dependence["hac_mean"]["effective_observations"]
            ),
        )
    except ValueError as exc:
        report["status"] = "BLOCKED_INVALID_RETURN_EVIDENCE"
        report["reason"] = str(exc)
        return report
    dsr["independence"] = independence
    report.update(
        {
            "selected_configuration_hash": trials[selected_index].configuration_hash,
            "selected_trial_id": trials[selected_index].trial_id,
            "period_count": int(matrix.shape[0]),
            "period_start": reference_timestamps[0].isoformat(),
            "period_end": reference_timestamps[-1].isoformat(),
            "pbo": pbo,
            "deflated_sharpe": dsr,
            "dependence_aware_inference": dependence,
        }
    )
    passed = (
        pbo["pbo"] <= maximum_pbo
        and dsr["probability"] >= minimum_dsr_probability
        and bool(dependence["dependence_supported"])
    )
    report["status"] = "READY" if passed else "REJECTED"
    return report

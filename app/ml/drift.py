from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

PRODUCTION_DRIFT_REFERENCE_SCHEMA = "final-holdout-feature-probability-selected-calibration-reference-v2"
PRODUCTION_DRIFT_REPORT_SCHEMA = "production-drift-report-v1"
DIRECTIONAL_PREDICTION_SCHEMA = "both-directional-probabilities-v1"
PRODUCTION_DRIFT_CALIBRATION_COHORT_SCHEMA = "selected-direction-final-holdout-v1"
PRODUCTION_DRIFT_UNSELECTED_CALIBRATION_COHORT_SCHEMA = "all-direction-final-holdout-v0"

_STATUS_RANK = {"OK": 0, "WARN": 1, "CRITICAL": 2, "BLOCKED": 3}


@dataclass(frozen=True)
class DriftThresholds:
    minimum_feature_observations: int = 48
    minimum_outcome_observations: int = 30
    minimum_coverage_rate: float = 0.80
    maximum_missing_rate: float = 0.02
    warning_psi: float = 0.10
    critical_psi: float = 0.25
    maximum_log_loss_delta: float = 0.10
    maximum_brier_delta: float = 0.05
    maximum_actionability_rate_delta: float = 0.20

    def __post_init__(self) -> None:
        integer_fields = {
            "minimum_feature_observations": self.minimum_feature_observations,
            "minimum_outcome_observations": self.minimum_outcome_observations,
        }
        for name, value in integer_fields.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        rate_fields = {
            "minimum_coverage_rate": self.minimum_coverage_rate,
            "maximum_missing_rate": self.maximum_missing_rate,
            "warning_psi": self.warning_psi,
            "critical_psi": self.critical_psi,
            "maximum_log_loss_delta": self.maximum_log_loss_delta,
            "maximum_brier_delta": self.maximum_brier_delta,
            "maximum_actionability_rate_delta": self.maximum_actionability_rate_delta,
        }
        for name, value in rate_fields.items():
            if isinstance(value, bool) or not math.isfinite(float(value)) or float(value) < 0:
                raise ValueError(f"{name} must be non-negative and finite")
        if not 0 < self.minimum_coverage_rate <= 1:
            raise ValueError("minimum_coverage_rate must be in (0, 1]")
        if not 0 <= self.maximum_missing_rate < 1:
            raise ValueError("maximum_missing_rate must be in [0, 1)")
        if not 0 < self.warning_psi < self.critical_psi:
            raise ValueError("warning_psi must be positive and lower than critical_psi")
        if self.maximum_actionability_rate_delta > 1:
            raise ValueError("maximum_actionability_rate_delta must be in [0, 1]")


def _finite_matrix(values: np.ndarray | Sequence[Sequence[float]], *, name: str) -> np.ndarray:
    result = np.asarray(values, dtype=float)
    if result.ndim != 2 or result.shape[0] < 1 or result.shape[1] < 1:
        raise ValueError(f"{name} must be a non-empty two-dimensional matrix")
    if not np.isfinite(result).all():
        raise ValueError(f"{name} must contain only finite values")
    return result


def _validated_classes(classes: Sequence[str]) -> list[str]:
    result = [str(item).strip().upper() for item in classes]
    if result != ["TP", "SL", "TIMEOUT"]:
        raise ValueError("classes must be ordered exactly as TP, SL, TIMEOUT")
    return result


def _validate_probability_matrix(
    values: np.ndarray | Sequence[Sequence[float]],
    *,
    expected_rows: int | None = None,
) -> np.ndarray:
    result = _finite_matrix(values, name="probabilities")
    if result.shape[1] != 3:
        raise ValueError("probabilities must contain exactly TP, SL and TIMEOUT columns")
    if expected_rows is not None and result.shape[0] != expected_rows:
        raise ValueError("probability rows do not match the expected observation count")
    if ((result < 0) | (result > 1)).any():
        raise ValueError("probabilities must be in [0, 1]")
    if not np.allclose(result.sum(axis=1), 1.0, rtol=1e-8, atol=1e-10):
        raise ValueError("probability rows must sum to one")
    return result


def _calibration_metrics(
    outcomes: Sequence[str] | np.ndarray,
    probabilities: np.ndarray,
    classes: Sequence[str],
) -> dict[str, float]:
    labels = np.asarray([str(item).strip().upper() for item in outcomes], dtype=str)
    ordered_classes = _validated_classes(classes)
    values = _validate_probability_matrix(probabilities, expected_rows=len(labels))
    class_to_index = {label: index for index, label in enumerate(ordered_classes)}
    if any(label not in class_to_index for label in labels):
        raise ValueError("outcomes contain an unsupported class")
    indexes = np.array([class_to_index[label] for label in labels], dtype=int)
    selected = np.clip(values[np.arange(len(values)), indexes], 1e-12, 1.0)
    one_hot = np.eye(len(ordered_classes), dtype=float)[indexes]
    return {
        "log_loss": float(-np.log(selected).mean()),
        "multiclass_brier": float(np.mean(np.sum((values - one_hot) ** 2, axis=1))),
    }


def _histogram_reference(values: np.ndarray, *, quantile_bins: int = 10) -> dict[str, object]:
    vector = np.asarray(values, dtype=float)
    if vector.ndim != 1 or len(vector) < 1 or not np.isfinite(vector).all():
        raise ValueError("histogram reference requires a finite one-dimensional vector")
    if quantile_bins < 2:
        raise ValueError("quantile_bins must be at least two")
    minimum = float(vector.min())
    maximum = float(vector.max())
    if math.isclose(minimum, maximum, rel_tol=0.0, abs_tol=0.0):
        scale = max(abs(minimum), 1.0) * 1e-9
        boundaries = np.array([minimum - scale, maximum + scale], dtype=float)
    else:
        quantiles = np.linspace(0.0, 1.0, quantile_bins + 1)[1:-1]
        boundaries = np.unique(np.quantile(vector, quantiles)).astype(float)
    bucket_indexes = np.searchsorted(boundaries, vector, side="right")
    counts = np.bincount(bucket_indexes, minlength=len(boundaries) + 1).astype(float)
    proportions = counts / counts.sum()
    return {
        "boundaries": [float(item) for item in boundaries],
        "proportions": [float(item) for item in proportions],
        "mean": float(vector.mean()),
        "std": float(vector.std(ddof=0)),
        "minimum": minimum,
        "maximum": maximum,
        "rows": int(len(vector)),
    }


def _validate_histogram_reference(value: object, *, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} histogram reference must be an object")
    boundaries = np.asarray(value.get("boundaries"), dtype=float)
    proportions = np.asarray(value.get("proportions"), dtype=float)
    if boundaries.ndim != 1 or proportions.ndim != 1:
        raise ValueError(f"{name} histogram arrays must be one-dimensional")
    if len(proportions) != len(boundaries) + 1:
        raise ValueError(f"{name} histogram bucket count is inconsistent")
    if not np.isfinite(boundaries).all() or not np.isfinite(proportions).all():
        raise ValueError(f"{name} histogram contains non-finite values")
    if len(boundaries) > 1 and (np.diff(boundaries) <= 0).any():
        raise ValueError(f"{name} histogram boundaries must be strictly increasing")
    if (proportions < 0).any() or not math.isclose(
        float(proportions.sum()), 1.0, rel_tol=1e-8, abs_tol=1e-8
    ):
        raise ValueError(f"{name} histogram proportions must sum to one")
    return value


def _population_stability_index(reference: Mapping[str, object], values: np.ndarray) -> float:
    validated = _validate_histogram_reference(dict(reference), name="drift")
    boundaries = np.asarray(validated["boundaries"], dtype=float)
    expected = np.asarray(validated["proportions"], dtype=float)
    vector = np.asarray(values, dtype=float)
    if vector.ndim != 1 or len(vector) < 1 or not np.isfinite(vector).all():
        raise ValueError("PSI requires a non-empty finite vector")
    indexes = np.searchsorted(boundaries, vector, side="right")
    actual = np.bincount(indexes, minlength=len(boundaries) + 1).astype(float)
    actual /= actual.sum()
    epsilon = 1e-6
    expected_safe = np.clip(expected, epsilon, None)
    actual_safe = np.clip(actual, epsilon, None)
    return float(np.sum((actual_safe - expected_safe) * np.log(actual_safe / expected_safe)))


def build_production_drift_reference(
    features: np.ndarray | Sequence[Sequence[float]],
    probabilities: np.ndarray | Sequence[Sequence[float]],
    outcomes: Sequence[str] | np.ndarray,
    *,
    feature_names: Sequence[str],
    classes: Sequence[str],
    actionability_rate: float,
    min_net_rr: float,
    min_net_ev_r: float,
    calibration_reference: Mapping[str, object] | None = None,
    calibration_cohort_schema: str = PRODUCTION_DRIFT_UNSELECTED_CALIBRATION_COHORT_SCHEMA,
) -> dict[str, object]:
    feature_matrix = _finite_matrix(features, name="features")
    names = [str(name).strip() for name in feature_names]
    if not names or any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError("feature_names must be non-empty and unique")
    if feature_matrix.shape[1] != len(names):
        raise ValueError("feature matrix width does not match feature_names")
    ordered_classes = _validated_classes(classes)
    probability_matrix = _validate_probability_matrix(probabilities, expected_rows=len(feature_matrix))
    if calibration_reference is None:
        calibration = {
            "schema": calibration_cohort_schema,
            "rows": int(len(probability_matrix)),
            **_calibration_metrics(outcomes, probability_matrix, ordered_classes),
        }
    else:
        if calibration_cohort_schema != PRODUCTION_DRIFT_CALIBRATION_COHORT_SCHEMA:
            raise ValueError("calibration cohort schema is incompatible")
        try:
            calibration_rows = int(calibration_reference["rows"])
            calibration_log_loss = float(calibration_reference["log_loss"])
            calibration_brier = float(calibration_reference["multiclass_brier"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("calibration_reference is incomplete") from exc
        if calibration_rows < 1:
            raise ValueError("calibration_reference rows must be positive")
        if (
            not math.isfinite(calibration_log_loss)
            or calibration_log_loss < 0
            or not math.isfinite(calibration_brier)
            or calibration_brier < 0
        ):
            raise ValueError("calibration_reference metrics must be finite and non-negative")
        calibration = {
            "schema": calibration_cohort_schema,
            "rows": calibration_rows,
            "log_loss": calibration_log_loss,
            "multiclass_brier": calibration_brier,
        }
    numeric_rates = {
        "actionability_rate": actionability_rate,
        "min_net_rr": min_net_rr,
        "min_net_ev_r": min_net_ev_r,
    }
    for name, value in numeric_rates.items():
        if isinstance(value, bool) or not math.isfinite(float(value)):
            raise ValueError(f"{name} must be finite")
    if not 0 <= float(actionability_rate) <= 1:
        raise ValueError("actionability_rate must be in [0, 1]")
    if float(min_net_rr) < 0:
        raise ValueError("min_net_rr must be non-negative")

    return {
        "schema": PRODUCTION_DRIFT_REFERENCE_SCHEMA,
        "rows": int(len(feature_matrix)),
        "feature_names": names,
        "classes": ordered_classes,
        "features": {
            name: _histogram_reference(feature_matrix[:, index])
            for index, name in enumerate(names)
        },
        "probabilities": {
            label: _histogram_reference(probability_matrix[:, index])
            for index, label in enumerate(ordered_classes)
        },
        "calibration": calibration,
        "actionability": {
            "rate": float(actionability_rate),
            "min_net_rr": float(min_net_rr),
            "min_net_ev_r": float(min_net_ev_r),
        },
        "missingness": {name: 0.0 for name in names},
    }


def validate_production_drift_reference(reference: object) -> dict[str, object]:
    if not isinstance(reference, dict):
        raise ValueError("Production drift reference is required")
    if reference.get("schema") != PRODUCTION_DRIFT_REFERENCE_SCHEMA:
        raise ValueError("Production drift reference schema mismatch")
    feature_names = reference.get("feature_names")
    classes = reference.get("classes")
    if not isinstance(feature_names, list) or not feature_names or len(feature_names) != len(set(feature_names)):
        raise ValueError("Production drift feature_names are invalid")
    ordered_classes = _validated_classes(classes if isinstance(classes, list) else [])
    features = reference.get("features")
    probabilities = reference.get("probabilities")
    if not isinstance(features, dict) or set(features) != set(feature_names):
        raise ValueError("Production drift feature references are incomplete")
    if not isinstance(probabilities, dict) or set(probabilities) != set(ordered_classes):
        raise ValueError("Production drift probability references are incomplete")
    for name in feature_names:
        _validate_histogram_reference(features[name], name=f"feature {name}")
    for label in ordered_classes:
        _validate_histogram_reference(probabilities[label], name=f"probability {label}")
    calibration = reference.get("calibration")
    if not isinstance(calibration, dict):
        raise ValueError("Production drift calibration reference is required")
    if calibration.get("schema") not in {
        PRODUCTION_DRIFT_CALIBRATION_COHORT_SCHEMA,
        PRODUCTION_DRIFT_UNSELECTED_CALIBRATION_COHORT_SCHEMA,
    }:
        raise ValueError("Production drift calibration cohort schema mismatch")
    rows = calibration.get("rows")
    if isinstance(rows, bool) or not isinstance(rows, int) or rows < 1:
        raise ValueError("Production drift calibration row count is invalid")
    for metric in ("log_loss", "multiclass_brier"):
        value = calibration.get(metric)
        if isinstance(value, bool) or not math.isfinite(float(value)) or float(value) < 0:
            raise ValueError(f"Production drift calibration {metric} is invalid")
    actionability = reference.get("actionability")
    if not isinstance(actionability, dict):
        raise ValueError("Production drift actionability reference is required")
    rate = actionability.get("rate")
    if isinstance(rate, bool) or not math.isfinite(float(rate)) or not 0 <= float(rate) <= 1:
        raise ValueError("Production drift actionability rate is invalid")
    return reference


def directional_prediction_snapshot(predictions: Iterable[Any]) -> dict[str, object]:
    rows = list(predictions)
    by_direction: dict[str, dict[str, float]] = {}
    versions: set[str] = set()
    calibrations: set[str] = set()
    for prediction in rows:
        direction = str(getattr(prediction, "direction", "")).upper()
        if direction not in {"LONG", "SHORT"} or direction in by_direction:
            raise ValueError("Directional prediction snapshot requires one LONG and one SHORT prediction")
        probabilities = {
            "TP": float(prediction.p_tp),
            "SL": float(prediction.p_sl),
            "TIMEOUT": float(prediction.p_timeout),
        }
        _validate_probability_matrix([list(probabilities.values())], expected_rows=1)
        by_direction[direction] = probabilities
        versions.add(str(getattr(prediction, "model_version", "")))
        calibrations.add(str(getattr(prediction, "calibration_version", "")))
    if set(by_direction) != {"LONG", "SHORT"}:
        raise ValueError("Directional prediction snapshot requires one LONG and one SHORT prediction")
    if len(versions) != 1 or "" in versions or len(calibrations) != 1 or "" in calibrations:
        raise ValueError("Directional predictions must share non-empty model and calibration versions")
    return {
        "schema": DIRECTIONAL_PREDICTION_SCHEMA,
        "model_version": next(iter(versions)),
        "calibration_version": next(iter(calibrations)),
        "predictions": {direction: by_direction[direction] for direction in ("LONG", "SHORT")},
    }


def _status_max(current: str, candidate: str) -> str:
    return candidate if _STATUS_RANK[candidate] > _STATUS_RANK[current] else current


def _status_for_psi(value: float, thresholds: DriftThresholds) -> str:
    if value >= thresholds.critical_psi:
        return "CRITICAL"
    if value >= thresholds.warning_psi:
        return "WARN"
    return "OK"


def evaluate_production_drift(
    reference: object,
    *,
    feature_rows: Sequence[Mapping[str, object]],
    probability_rows: Sequence[Mapping[str, object]],
    outcome_rows: Sequence[Mapping[str, object]],
    actionable_flags: Sequence[bool],
    expected_opportunities: int,
    published_opportunities: int,
    thresholds: DriftThresholds,
) -> dict[str, object]:
    validated_reference = validate_production_drift_reference(reference)
    if isinstance(expected_opportunities, bool) or expected_opportunities < 0:
        raise ValueError("expected_opportunities must be a non-negative integer")
    if isinstance(published_opportunities, bool) or published_opportunities < 0:
        raise ValueError("published_opportunities must be a non-negative integer")
    if published_opportunities > expected_opportunities:
        raise ValueError("published_opportunities cannot exceed expected_opportunities")
    if len(actionable_flags) != len(feature_rows):
        raise ValueError("actionable_flags must align with feature_rows")
    if any(not isinstance(value, (bool, np.bool_)) for value in actionable_flags):
        raise ValueError("actionable_flags must contain booleans")

    alerts: list[str] = []
    overall_status = "OK"
    coverage_rate = (
        float(published_opportunities / expected_opportunities) if expected_opportunities else 0.0
    )
    coverage_status = "OK"
    if expected_opportunities <= 0 or coverage_rate < thresholds.minimum_coverage_rate:
        coverage_status = "BLOCKED"
        overall_status = "BLOCKED"
        alerts.append("insufficient_inference_coverage")

    feature_names = list(validated_reference["feature_names"])
    feature_reference = validated_reference["features"]
    by_feature: dict[str, dict[str, object]] = {}
    maximum_feature_psi = 0.0
    valid_feature_rows = 0
    if len(feature_rows) < thresholds.minimum_feature_observations:
        overall_status = "BLOCKED"
        alerts.append("insufficient_feature_observations")
    for name in feature_names:
        values: list[float] = []
        missing = 0
        for row in feature_rows:
            raw = row.get(name)
            try:
                value = float(raw)
            except (TypeError, ValueError, OverflowError):
                missing += 1
                continue
            if not math.isfinite(value):
                missing += 1
                continue
            values.append(value)
        missing_rate = float(missing / len(feature_rows)) if feature_rows else 1.0
        if missing_rate > thresholds.maximum_missing_rate:
            overall_status = _status_max(overall_status, "CRITICAL")
            if "feature_missingness_above_limit" not in alerts:
                alerts.append("feature_missingness_above_limit")
        if len(values) >= thresholds.minimum_feature_observations:
            psi = _population_stability_index(feature_reference[name], np.asarray(values, dtype=float))
            status = _status_for_psi(psi, thresholds)
            overall_status = _status_max(overall_status, status)
            maximum_feature_psi = max(maximum_feature_psi, psi)
        else:
            psi = None
            status = "BLOCKED"
            overall_status = "BLOCKED"
        by_feature[name] = {
            "observations": len(values),
            "missing": missing,
            "missing_rate": missing_rate,
            "psi": psi,
            "status": status,
        }
    if feature_rows:
        valid_feature_rows = sum(
            all(
                isinstance(row.get(name), (int, float, np.integer, np.floating))
                and math.isfinite(float(row[name]))
                for name in feature_names
            )
            for row in feature_rows
        )
    if maximum_feature_psi >= thresholds.critical_psi:
        alerts.append("feature_distribution_drift")
    elif maximum_feature_psi >= thresholds.warning_psi:
        alerts.append("feature_distribution_warning")

    classes = list(validated_reference["classes"])
    probability_reference = validated_reference["probabilities"]
    probability_vectors: list[list[float]] = []
    invalid_probability_rows = 0
    for row in probability_rows:
        try:
            vector = [float(row[label]) for label in classes]
            validated = _validate_probability_matrix([vector], expected_rows=1)[0]
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid_probability_rows += 1
            continue
        probability_vectors.append([float(value) for value in validated])
    by_probability: dict[str, dict[str, object]] = {}
    maximum_probability_psi = 0.0
    if len(probability_vectors) < thresholds.minimum_feature_observations:
        overall_status = "BLOCKED"
        alerts.append("insufficient_probability_observations")
    else:
        probability_matrix = np.asarray(probability_vectors, dtype=float)
        for index, label in enumerate(classes):
            psi = _population_stability_index(probability_reference[label], probability_matrix[:, index])
            status = _status_for_psi(psi, thresholds)
            overall_status = _status_max(overall_status, status)
            maximum_probability_psi = max(maximum_probability_psi, psi)
            by_probability[label] = {
                "observations": len(probability_matrix),
                "mean": float(probability_matrix[:, index].mean()),
                "reference_mean": float(probability_reference[label]["mean"]),
                "psi": psi,
                "status": status,
            }
    if not by_probability:
        by_probability = {
            label: {
                "observations": len(probability_vectors),
                "mean": None,
                "reference_mean": float(probability_reference[label]["mean"]),
                "psi": None,
                "status": "BLOCKED",
            }
            for label in classes
        }
    if maximum_probability_psi >= thresholds.critical_psi:
        alerts.append("probability_distribution_drift")
    elif maximum_probability_psi >= thresholds.warning_psi:
        alerts.append("probability_distribution_warning")

    valid_outcomes: list[str] = []
    outcome_probabilities: list[list[float]] = []
    invalid_outcome_rows = 0
    for row in outcome_rows:
        outcome = str(row.get("outcome", "")).strip().upper()
        raw_probabilities = row.get("probabilities")
        try:
            if outcome not in classes or not isinstance(raw_probabilities, Mapping):
                raise ValueError
            vector = [float(raw_probabilities[label]) for label in classes]
            validated = _validate_probability_matrix([vector], expected_rows=1)[0]
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid_outcome_rows += 1
            continue
        valid_outcomes.append(outcome)
        outcome_probabilities.append([float(value) for value in validated])
    calibration_reference = validated_reference["calibration"]
    if len(valid_outcomes) < thresholds.minimum_outcome_observations:
        calibration: dict[str, object] = {
            "status": "INSUFFICIENT_DATA",
            "observations": len(valid_outcomes),
            "invalid_rows": invalid_outcome_rows,
            "minimum_required": thresholds.minimum_outcome_observations,
            "log_loss": None,
            "multiclass_brier": None,
            "reference_log_loss": float(calibration_reference["log_loss"]),
            "reference_multiclass_brier": float(calibration_reference["multiclass_brier"]),
            "log_loss_delta": None,
            "multiclass_brier_delta": None,
        }
    else:
        current_calibration = _calibration_metrics(
            valid_outcomes,
            np.asarray(outcome_probabilities, dtype=float),
            classes,
        )
        log_loss_delta = float(
            current_calibration["log_loss"] - float(calibration_reference["log_loss"])
        )
        brier_delta = float(
            current_calibration["multiclass_brier"]
            - float(calibration_reference["multiclass_brier"])
        )
        calibration_status = "OK"
        if (
            log_loss_delta > thresholds.maximum_log_loss_delta
            or brier_delta > thresholds.maximum_brier_delta
        ):
            calibration_status = "CRITICAL"
            overall_status = _status_max(overall_status, "CRITICAL")
            alerts.append("calibration_drift")
        elif (
            log_loss_delta > thresholds.maximum_log_loss_delta / 2
            or brier_delta > thresholds.maximum_brier_delta / 2
        ):
            calibration_status = "WARN"
            overall_status = _status_max(overall_status, "WARN")
            alerts.append("calibration_warning")
        calibration = {
            "status": calibration_status,
            "observations": len(valid_outcomes),
            "invalid_rows": invalid_outcome_rows,
            "minimum_required": thresholds.minimum_outcome_observations,
            "log_loss": current_calibration["log_loss"],
            "multiclass_brier": current_calibration["multiclass_brier"],
            "reference_log_loss": float(calibration_reference["log_loss"]),
            "reference_multiclass_brier": float(calibration_reference["multiclass_brier"]),
            "log_loss_delta": log_loss_delta,
            "multiclass_brier_delta": brier_delta,
        }

    observed_actionability_rate = (
        float(sum(bool(value) for value in actionable_flags) / len(actionable_flags))
        if actionable_flags
        else 0.0
    )
    reference_actionability_rate = float(validated_reference["actionability"]["rate"])
    actionability_delta = abs(observed_actionability_rate - reference_actionability_rate)
    actionability_status = "OK"
    if actionability_delta > thresholds.maximum_actionability_rate_delta:
        actionability_status = "CRITICAL"
        overall_status = _status_max(overall_status, "CRITICAL")
        alerts.append("actionability_density_drift")
    elif actionability_delta > thresholds.maximum_actionability_rate_delta / 2:
        actionability_status = "WARN"
        overall_status = _status_max(overall_status, "WARN")
        alerts.append("actionability_density_warning")

    return {
        "schema": PRODUCTION_DRIFT_REPORT_SCHEMA,
        "status": overall_status,
        "coverage": {
            "status": coverage_status,
            "expected_opportunities": int(expected_opportunities),
            "published_opportunities": int(published_opportunities),
            "rate": coverage_rate,
            "minimum_rate": thresholds.minimum_coverage_rate,
        },
        "features": {
            "observations": len(feature_rows),
            "fully_valid_rows": int(valid_feature_rows),
            "max_psi": maximum_feature_psi,
            "by_feature": by_feature,
        },
        "probabilities": {
            "observations": len(probability_vectors),
            "invalid_rows": invalid_probability_rows,
            "max_psi": maximum_probability_psi,
            "by_class": by_probability,
        },
        "calibration": calibration,
        "actionability": {
            "status": actionability_status,
            "observations": len(actionable_flags),
            "rate": observed_actionability_rate,
            "reference_rate": reference_actionability_rate,
            "absolute_delta": actionability_delta,
            "maximum_delta": thresholds.maximum_actionability_rate_delta,
            "min_net_rr": float(validated_reference["actionability"]["min_net_rr"]),
            "min_net_ev_r": float(validated_reference["actionability"]["min_net_ev_r"]),
        },
        "alerts": list(dict.fromkeys(alerts)),
        "thresholds": {
            "minimum_feature_observations": thresholds.minimum_feature_observations,
            "minimum_outcome_observations": thresholds.minimum_outcome_observations,
            "minimum_coverage_rate": thresholds.minimum_coverage_rate,
            "maximum_missing_rate": thresholds.maximum_missing_rate,
            "warning_psi": thresholds.warning_psi,
            "critical_psi": thresholds.critical_psi,
            "maximum_log_loss_delta": thresholds.maximum_log_loss_delta,
            "maximum_brier_delta": thresholds.maximum_brier_delta,
            "maximum_actionability_rate_delta": thresholds.maximum_actionability_rate_delta,
        },
    }

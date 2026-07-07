from __future__ import annotations

import math

import numpy as np

from app.ml.drift import (
    PRODUCTION_DRIFT_CALIBRATION_COHORT_SCHEMA,
    build_production_drift_reference,
)
from app.ml.training import MODEL_BASE_FEATURE_NAMES, OUTCOME_CLASSES


def valid_production_drift_reference(
    *,
    directional_rows: int = 12,
    selected_rows: int | None = None,
    actionability_rate: float = 0.08,
) -> dict[str, object]:
    if directional_rows < 2 or directional_rows % 2 != 0:
        raise ValueError("directional_rows must be a positive even integer")
    if selected_rows is None:
        selected_rows = directional_rows // 2
    if selected_rows < 1:
        raise ValueError("selected_rows must be positive")

    features = np.column_stack(
        [
            np.linspace(-0.03 + index * 0.001, 0.03 + index * 0.001, directional_rows)
            for index, _name in enumerate(MODEL_BASE_FEATURE_NAMES)
        ]
    )
    base_probabilities = np.asarray(
        [[0.70, 0.20, 0.10], [0.20, 0.70, 0.10], [0.10, 0.20, 0.70]],
        dtype=float,
    )
    repetitions = math.ceil(directional_rows / len(base_probabilities))
    probabilities = np.tile(base_probabilities, (repetitions, 1))[:directional_rows]
    base_outcomes = np.asarray(["TP", "SL", "TIMEOUT"])
    outcomes = np.tile(base_outcomes, repetitions)[:directional_rows]
    true_indexes = np.asarray([0, 1, 2] * repetitions, dtype=int)[:directional_rows]
    true_probabilities = probabilities[np.arange(directional_rows), true_indexes]
    one_hot = np.eye(len(OUTCOME_CLASSES), dtype=float)[true_indexes]
    calibration_log_loss = float(-np.log(true_probabilities).mean())
    calibration_brier = float(np.square(probabilities - one_hot).sum(axis=1).mean())

    return build_production_drift_reference(
        features,
        probabilities,
        outcomes,
        feature_names=MODEL_BASE_FEATURE_NAMES,
        classes=[str(item) for item in OUTCOME_CLASSES],
        actionability_rate=actionability_rate,
        min_net_rr=1.2,
        min_net_ev_r=0.05,
        calibration_reference={
            "rows": selected_rows,
            "log_loss": calibration_log_loss,
            "multiclass_brier": calibration_brier,
        },
        calibration_cohort_schema=PRODUCTION_DRIFT_CALIBRATION_COHORT_SCHEMA,
    )

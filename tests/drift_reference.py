from __future__ import annotations

import numpy as np

from app.ml.drift import (
    PRODUCTION_DRIFT_CALIBRATION_COHORT_SCHEMA,
    build_production_drift_reference,
)
from app.ml.training import MODEL_BASE_FEATURE_NAMES, OUTCOME_CLASSES


def valid_production_drift_reference() -> dict[str, object]:
    rows = 12
    features = np.column_stack(
        [
            np.linspace(-0.03 + index * 0.001, 0.03 + index * 0.001, rows)
            for index, _name in enumerate(MODEL_BASE_FEATURE_NAMES)
        ]
    )
    probabilities = np.array(
        [
            [0.70, 0.20, 0.10],
            [0.20, 0.70, 0.10],
            [0.10, 0.20, 0.70],
        ]
        * 4,
        dtype=float,
    )
    outcomes = np.array(["TP", "SL", "TIMEOUT"] * 4)
    return build_production_drift_reference(
        features,
        probabilities,
        outcomes,
        feature_names=MODEL_BASE_FEATURE_NAMES,
        classes=[str(item) for item in OUTCOME_CLASSES],
        actionability_rate=0.08,
        min_net_rr=1.2,
        min_net_ev_r=0.05,
        calibration_cohort_schema=PRODUCTION_DRIFT_CALIBRATION_COHORT_SCHEMA,
    )

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import joblib
import numpy as np

from app.ml.features import FEATURE_NAMES
from app.ml.training import (
    DEFAULT_STOP_ATR_MULTIPLIER,
    DEFAULT_TP_ATR_MULTIPLIER,
    LABEL_PATH_SCHEMA_VERSION,
    MODEL_FEATURE_NAMES,
    MODEL_FEATURE_SCHEMA_VERSION,
    OUTCOME_CLASSES,
    TEMPORAL_SPLIT_SCHEMA_VERSION,
)
from app.risk.math import validate_probability_simplex

Direction = Literal["LONG", "SHORT"]


@dataclass(frozen=True)
class Prediction:
    direction: Direction
    p_tp: float
    p_sl: float
    p_timeout: float
    score: float
    model_version: str
    calibration_version: str
    reasons: tuple[str, ...]


class ModelRuntime:
    def __init__(self, artifact_path: Path | None = None, allow_baseline: bool = True):
        self.artifact_path = artifact_path
        self.allow_baseline = allow_baseline
        self.bundle: dict[str, Any] | None = None
        self.version = "baseline-momentum-v1"
        self.calibration_version = "uncalibrated-baseline-v1"
        self.sha256: str | None = None
        self.horizon_hours: int | None = None
        self.model_type = "deterministic_baseline"
        self.source = "baseline"
        self.stop_atr_multiplier = DEFAULT_STOP_ATR_MULTIPLIER
        self.tp_atr_multiplier = DEFAULT_TP_ATR_MULTIPLIER

    @property
    def is_baseline(self) -> bool:
        return self.bundle is None

    def metadata(self) -> dict[str, object]:
        return {
            "version": self.version,
            "calibration_version": self.calibration_version,
            "model_type": self.model_type,
            "horizon_hours": self.horizon_hours,
            "artifact_path": str(self.artifact_path) if self.artifact_path else None,
            "artifact_sha256": self.sha256,
            "baseline": self.is_baseline,
            "source": self.source,
            "stop_atr_multiplier": self.stop_atr_multiplier,
            "tp_atr_multiplier": self.tp_atr_multiplier,
            "feature_schema_version": (
                self.bundle.get("feature_schema_version") if self.bundle is not None else None
            ),
            "label_path_schema_version": (
                self.bundle.get("label_path_schema_version") if self.bundle is not None else None
            ),
            "temporal_split_schema": (
                self.bundle.get("temporal_split_schema") if self.bundle is not None else None
            ),
        }

    def load(
        self,
        *,
        expected_sha256: str | None = None,
        expected_version: str | None = None,
        source: str = "artifact",
    ) -> None:
        self.bundle = None
        self.sha256 = None
        self.horizon_hours = None
        self.model_type = "deterministic_baseline"
        self.source = "baseline"
        self.stop_atr_multiplier = DEFAULT_STOP_ATR_MULTIPLIER
        self.tp_atr_multiplier = DEFAULT_TP_ATR_MULTIPLIER
        self.version = "baseline-momentum-v1"
        self.calibration_version = "uncalibrated-baseline-v1"

        if self.artifact_path:
            if not self.artifact_path.exists():
                raise RuntimeError(f"Active model artifact does not exist: {self.artifact_path}")
            raw = self.artifact_path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if expected_sha256 and digest.lower() != expected_sha256.lower():
                raise RuntimeError(
                    f"Active model SHA256 mismatch: expected {expected_sha256}, got {digest}"
                )
            bundle = joblib.load(self.artifact_path)
            if not isinstance(bundle, dict) or "model" not in bundle:
                raise ValueError("Invalid model bundle")
            if bundle.get("task") != "barrier_outcome_v1":
                raise ValueError(
                    "Unsupported or legacy model task. Retrain with version 1.3.0 or newer; "
                    "binary direction artifacts do not provide calibrated TP/SL/TIMEOUT probabilities."
                )
            artifact_features = list(bundle.get("feature_names") or [])
            if artifact_features != MODEL_FEATURE_NAMES:
                raise ValueError(
                    f"Model feature schema mismatch: expected {MODEL_FEATURE_NAMES}, got {artifact_features}"
                )
            feature_schema_version = str(bundle.get("feature_schema_version") or "")
            if feature_schema_version != MODEL_FEATURE_SCHEMA_VERSION:
                raise ValueError(
                    "Model feature schema version mismatch: "
                    f"expected {MODEL_FEATURE_SCHEMA_VERSION}, got {feature_schema_version or 'missing'}"
                )
            label_path_schema_version = str(bundle.get("label_path_schema_version") or "")
            if label_path_schema_version != LABEL_PATH_SCHEMA_VERSION:
                raise ValueError(
                    "Model label path schema mismatch: "
                    f"expected {LABEL_PATH_SCHEMA_VERSION}, "
                    f"got {label_path_schema_version or 'missing'}"
                )
            temporal_split_schema = str(bundle.get("temporal_split_schema") or "")
            if temporal_split_schema != TEMPORAL_SPLIT_SCHEMA_VERSION:
                raise ValueError(
                    "Model temporal split schema mismatch: "
                    f"expected {TEMPORAL_SPLIT_SCHEMA_VERSION}, "
                    f"got {temporal_split_schema or 'missing'}"
                )
            model = bundle["model"]
            classes = [str(item) for item in getattr(model, "classes_", [])]
            if classes != list(OUTCOME_CLASSES):
                raise ValueError(
                    f"Model outcome schema mismatch: expected {list(OUTCOME_CLASSES)}, got {classes}"
                )
            version = str(bundle.get("version", self.artifact_path.stem))
            if expected_version and version != expected_version:
                raise RuntimeError(
                    f"Active model version mismatch: registry={expected_version}, artifact={version}"
                )
            stop_atr_multiplier = self._artifact_multiplier(
                bundle, "stop_atr_multiplier", DEFAULT_STOP_ATR_MULTIPLIER
            )
            tp_atr_multiplier = self._artifact_multiplier(
                bundle, "tp_atr_multiplier", DEFAULT_TP_ATR_MULTIPLIER
            )
            raw_horizon = bundle.get("horizon_hours")
            if isinstance(raw_horizon, bool):
                raise ValueError("Model artifact horizon_hours must be a positive integer")
            try:
                horizon_hours = int(raw_horizon)
                if float(raw_horizon) != float(horizon_hours) or horizon_hours <= 0:
                    raise ValueError
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(
                    "Model artifact horizon_hours must be a positive integer"
                ) from exc
            calibration_version = str(bundle.get("calibration_version") or "").strip()
            if not calibration_version:
                raise ValueError("Model artifact calibration_version is required")
            self.bundle = bundle
            self.sha256 = digest
            self.version = version
            self.calibration_version = calibration_version
            self.horizon_hours = horizon_hours
            self.model_type = str(bundle.get("model_type", "unknown"))
            self.stop_atr_multiplier = stop_atr_multiplier
            self.tp_atr_multiplier = tp_atr_multiplier
            self.source = source
            return
        if not self.allow_baseline:
            raise RuntimeError("No active model artifact and baseline model is disabled")
        self.source = source

    @staticmethod
    def _artifact_multiplier(bundle: dict[str, Any], key: str, default: float) -> float:
        raw_value = bundle.get(key, default)
        if isinstance(raw_value, bool):
            raise ValueError(f"Model artifact {key} must be positive and finite")
        try:
            value = float(raw_value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Model artifact {key} must be positive and finite") from exc
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"Model artifact {key} must be positive and finite")
        return value

    @staticmethod
    def _validated_features(features: dict[str, float]) -> dict[str, float]:
        missing = [name for name in FEATURE_NAMES if name not in features]
        if missing:
            raise ValueError(f"missing model features: {', '.join(missing)}")
        validated: dict[str, float] = {}
        for name in FEATURE_NAMES:
            raw_value = features[name]
            if isinstance(raw_value, bool):
                raise ValueError(f"model feature {name} must be finite")
            try:
                value = float(raw_value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"model feature {name} must be finite") from exc
            if not math.isfinite(value):
                raise ValueError(f"model feature {name} must be finite")
            validated[name] = value
        return validated

    def _scenario_utility(self, p_tp: float, p_sl: float, p_timeout: float) -> float:
        # Compatibility score only. Exact direction selection is performed later by
        # the cost-aware policy, but this score must still use the artifact geometry.
        return (
            p_tp * self.tp_atr_multiplier
            - p_sl * self.stop_atr_multiplier
            - p_timeout * 0.20
        )

    def _predict_artifact_scenarios(self, features: dict[str, float]) -> tuple[Prediction, Prediction]:
        if self.bundle is None:
            raise RuntimeError("No artifact loaded")
        model = self.bundle["model"]
        vector_values_base = [features[name] for name in FEATURE_NAMES]
        scenarios: list[tuple[Direction, float, dict[str, float]]] = []
        for direction, code in (("LONG", 1.0), ("SHORT", -1.0)):
            vector_values = vector_values_base + [code]
            probabilities = model.predict_proba(np.array([vector_values], dtype=float))[0]
            mapping = dict(zip([str(item) for item in model.classes_], probabilities, strict=True))
            p_tp, p_sl, p_timeout = validate_probability_simplex(
                mapping["TP"], mapping["SL"], mapping["TIMEOUT"]
            )
            outcome = {
                "p_tp": float(p_tp),
                "p_sl": float(p_sl),
                "p_timeout": float(p_timeout),
            }
            utility = self._scenario_utility(**outcome)
            scenarios.append((direction, utility, outcome))

        predictions: list[Prediction] = []
        for index, (direction, utility, outcome) in enumerate(scenarios):
            alternative_utility = scenarios[1 - index][1]
            reasons = list(self._reasons(features, direction))
            reasons.append(
                "Модель оценила сценарий "
                f"{direction}: P(TP)={outcome['p_tp']:.1%}, P(SL)={outcome['p_sl']:.1%}, "
                f"P(timeout)={outcome['p_timeout']:.1%}"
            )
            predictions.append(
                Prediction(
                    direction=direction,
                    p_tp=outcome["p_tp"],
                    p_sl=outcome["p_sl"],
                    p_timeout=outcome["p_timeout"],
                    score=utility - alternative_utility,
                    model_version=self.version,
                    calibration_version=self.calibration_version,
                    reasons=tuple(reasons[:7]),
                )
            )
        return predictions[0], predictions[1]

    def _predict_baseline_scenarios(self, features: dict[str, float]) -> tuple[Prediction, Prediction]:
        score = (
            1.25 * features.get("ret_3h", 0.0)
            + 1.10 * features.get("ret_6h", 0.0)
            + 0.70 * features.get("ret_12h", 0.0)
            + 0.55 * features.get("ema_distance_12", 0.0)
            + 0.35 * features.get("ema_slope_12", 0.0)
            + 0.25 * features.get("breakout_24", 0.0)
            + 0.03 * max(-3.0, min(3.0, features.get("volume_z_24", 0.0)))
        )
        vol = max(0.002, min(0.10, abs(features.get("atr_pct_14", 0.02))))
        normalized = math.tanh(score / max(0.004, vol * 0.8))
        rows: list[tuple[Direction, float, dict[str, float]]] = []
        for direction, sign in (("LONG", 1.0), ("SHORT", -1.0)):
            alignment = normalized * sign
            p_tp = max(0.01, 0.34 + 0.30 * alignment)
            p_sl = max(0.01, 0.52 - 0.22 * alignment)
            p_timeout = max(0.06, 1.0 - p_tp - p_sl)
            total = p_tp + p_sl + p_timeout
            normalized_probabilities = validate_probability_simplex(
                p_tp / total,
                p_sl / total,
                p_timeout / total,
            )
            outcome = {
                "p_tp": float(normalized_probabilities[0]),
                "p_sl": float(normalized_probabilities[1]),
                "p_timeout": float(normalized_probabilities[2]),
            }
            rows.append((direction, self._scenario_utility(**outcome), outcome))

        predictions: list[Prediction] = []
        for index, (direction, utility, outcome) in enumerate(rows):
            predictions.append(
                Prediction(
                    direction=direction,
                    p_tp=outcome["p_tp"],
                    p_sl=outcome["p_sl"],
                    p_timeout=outcome["p_timeout"],
                    score=utility - rows[1 - index][1],
                    model_version=self.version,
                    calibration_version=self.calibration_version,
                    reasons=self._reasons(features, direction),
                )
            )
        return predictions[0], predictions[1]

    def predict_scenarios(self, features: dict[str, float]) -> tuple[Prediction, Prediction]:
        """Return independently calibrated LONG and SHORT outcome scenarios.

        Direction selection belongs to the cost/risk policy because current bid/ask,
        fees, funding and barrier geometry are unavailable to the model runtime.
        """

        validated = self._validated_features(features)
        if self.bundle is not None:
            return self._predict_artifact_scenarios(validated)
        return self._predict_baseline_scenarios(validated)

    def predict(self, features: dict[str, float]) -> Prediction:
        """Compatibility wrapper returning the best of the two runtime scenarios."""

        return max(self.predict_scenarios(features), key=lambda item: item.score)

    @staticmethod
    def _reasons(features: dict[str, float], direction: Direction) -> tuple[str, ...]:
        sign = 1 if direction == "LONG" else -1
        candidates = [
            (sign * features.get("ret_6h", 0), "Импульс за 6 часов поддерживает направление"),
            (sign * features.get("ret_12h", 0), "Импульс за 12 часов поддерживает направление"),
            (sign * features.get("ema_distance_12", 0), "Цена находится по направлению относительно EMA"),
            (sign * features.get("breakout_24", 0), "Наблюдается выход из локального диапазона"),
            (abs(features.get("volume_z_24", 0)), "Объем отличается от недавней нормы"),
        ]
        candidates.sort(key=lambda item: abs(item[0]), reverse=True)
        result = [text for value, text in candidates if value > 0][:4]
        if not result:
            result.append("Слабый направленный импульс; решение будет зависеть от cost/risk policy")
        return tuple(result)

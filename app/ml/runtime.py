from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import joblib
import numpy as np

from app.ml.features import FEATURE_NAMES
from app.ml.training import MODEL_FEATURE_NAMES, OUTCOME_CLASSES

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
            self.bundle = bundle
            self.sha256 = digest
            self.version = version
            self.calibration_version = str(bundle.get("calibration_version", "unknown"))
            self.horizon_hours = int(bundle["horizon_hours"])
            self.model_type = str(bundle.get("model_type", "unknown"))
            self.source = source
            return
        if not self.allow_baseline:
            raise RuntimeError("No active model artifact and baseline model is disabled")
        self.source = source

    @staticmethod
    def _scenario_utility(p_tp: float, p_sl: float, p_timeout: float) -> float:
        # Direction selection is deliberately cost-agnostic.  The policy layer later
        # calculates exact net EV using current fees, funding, spread and trade levels.
        return p_tp * 2.20 - p_sl * 1.15 - p_timeout * 0.20

    def _predict_artifact(self, features: dict[str, float]) -> Prediction:
        if self.bundle is None:
            raise RuntimeError("No artifact loaded")
        model = self.bundle["model"]
        scenarios: list[tuple[Direction, float, dict[str, float]]] = []
        for direction, code in (("LONG", 1.0), ("SHORT", -1.0)):
            vector_values = [float(features.get(name, 0.0)) for name in FEATURE_NAMES] + [code]
            probabilities = model.predict_proba(np.array([vector_values], dtype=float))[0]
            mapping = dict(zip([str(item) for item in model.classes_], probabilities, strict=True))
            outcome = {
                "p_tp": float(mapping["TP"]),
                "p_sl": float(mapping["SL"]),
                "p_timeout": float(mapping["TIMEOUT"]),
            }
            utility = self._scenario_utility(**outcome)
            scenarios.append((direction, utility, outcome))

        scenarios.sort(key=lambda item: item[1], reverse=True)
        direction, utility, outcome = scenarios[0]
        alternative_utility = scenarios[1][1]
        reasons = list(self._reasons(features, direction))
        reasons.append(
            "Модель оценила сценарий "
            f"{direction}: P(TP)={outcome['p_tp']:.1%}, P(SL)={outcome['p_sl']:.1%}, "
            f"P(timeout)={outcome['p_timeout']:.1%}"
        )
        return Prediction(
            direction=direction,
            p_tp=outcome["p_tp"],
            p_sl=outcome["p_sl"],
            p_timeout=outcome["p_timeout"],
            score=utility - alternative_utility,
            model_version=self.version,
            calibration_version=self.calibration_version,
            reasons=tuple(reasons[:7]),
        )

    def predict(self, features: dict[str, float]) -> Prediction:
        if self.bundle is not None:
            return self._predict_artifact(features)

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
        direction: Direction = "LONG" if normalized >= 0 else "SHORT"
        strength = abs(normalized)
        # These values are deterministic scaffolding, not calibrated ML output.
        p_tp = 0.34 + 0.30 * strength
        p_sl = 0.52 - 0.22 * strength
        p_timeout = max(0.06, 1.0 - p_tp - p_sl)
        total = p_tp + p_sl + p_timeout
        return Prediction(
            direction,
            p_tp / total,
            p_sl / total,
            p_timeout / total,
            normalized,
            self.version,
            self.calibration_version,
            self._reasons(features, direction),
        )

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

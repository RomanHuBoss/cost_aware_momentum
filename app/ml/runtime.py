from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import joblib
import numpy as np

from app.ml.features import FEATURE_NAMES

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
        self.calibration_version = "baseline-calibration-v1"
        self.sha256: str | None = None

    def load(self) -> None:
        if self.artifact_path and self.artifact_path.exists():
            raw = self.artifact_path.read_bytes()
            self.sha256 = hashlib.sha256(raw).hexdigest()
            bundle = joblib.load(self.artifact_path)
            if not isinstance(bundle, dict) or "model" not in bundle:
                raise ValueError("Invalid model bundle")
            artifact_features = list(bundle.get("feature_names") or [])
            if artifact_features != FEATURE_NAMES:
                raise ValueError(
                    f"Model feature schema mismatch: expected {FEATURE_NAMES}, got {artifact_features}"
                )
            self.bundle = bundle
            self.version = str(bundle.get("version", self.artifact_path.stem))
            self.calibration_version = str(bundle.get("calibration_version", "unknown"))
            return
        if not self.allow_baseline:
            raise RuntimeError("No active model artifact and baseline model is disabled")

    def predict(self, features: dict[str, float]) -> Prediction:
        vector = np.array([[float(features.get(name, 0.0)) for name in FEATURE_NAMES]], dtype=float)
        if self.bundle is not None:
            model = self.bundle["model"]
            probabilities = model.predict_proba(vector)[0]
            classes = [str(item) for item in model.classes_]
            mapping = dict(zip(classes, probabilities, strict=True))
            p_long = float(mapping.get("LONG", mapping.get("1", 0.5)))
            direction: Direction = "LONG" if p_long >= 0.5 else "SHORT"
            directional_strength = abs(p_long - 0.5) * 2
            p_tp = min(0.78, 0.34 + directional_strength * 0.34)
            p_sl = max(0.12, 0.56 - directional_strength * 0.28)
            p_timeout = max(0.05, 1.0 - p_tp - p_sl)
            total = p_tp + p_sl + p_timeout
            return Prediction(
                direction,
                p_tp / total,
                p_sl / total,
                p_timeout / total,
                directional_strength if direction == "LONG" else -directional_strength,
                self.version,
                self.calibration_version,
                self._reasons(features, direction),
            )

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
        direction = "LONG" if normalized >= 0 else "SHORT"
        strength = abs(normalized)
        p_tp = 0.34 + 0.30 * strength
        p_sl = 0.52 - 0.22 * strength
        p_timeout = 1.0 - p_tp - p_sl
        p_timeout = max(0.06, p_timeout)
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

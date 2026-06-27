from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.ml.features import FEATURE_NAMES, build_feature_frame
from app.ml.labels import triple_barrier_outcome

OUTCOME_CLASSES = np.array(["TP", "SL", "TIMEOUT"])
MODEL_FEATURE_NAMES = [*FEATURE_NAMES, "scenario_direction"]
DEFAULT_STOP_ATR_MULTIPLIER = 1.15
DEFAULT_TP_ATR_MULTIPLIER = 2.20


class TemporalCalibratedBarrierModel:
    """Direction-conditional TP/SL/TIMEOUT classifier with later-window sigmoid calibration.

    The model never emits NO TRADE.  It estimates the outcome distribution for a
    hypothetical LONG or SHORT scenario.  Cost/risk/policy code decides whether
    either scenario is tradable.
    """

    classes_ = OUTCOME_CLASSES.copy()

    def __init__(self, model_type: str = "logistic") -> None:
        if model_type == "logistic":
            self.base = Pipeline(
                [
                    ("scale", StandardScaler()),
                    (
                        "classifier",
                        LogisticRegression(
                            max_iter=3000,
                            class_weight="balanced",
                            random_state=42,
                        ),
                    ),
                ]
            )
        elif model_type == "hist_gradient_boosting":
            self.base = HistGradientBoostingClassifier(
                max_iter=300,
                learning_rate=0.05,
                max_leaf_nodes=31,
                l2_regularization=1.0,
                class_weight="balanced",
                random_state=42,
            )
        else:
            raise ValueError(f"Unsupported model_type: {model_type}")
        self.model_type = model_type
        self.calibrators: dict[str, LogisticRegression] = {}

    @staticmethod
    def _logit(probability: np.ndarray) -> np.ndarray:
        clipped = np.clip(probability, 1e-6, 1 - 1e-6)
        return np.log(clipped / (1 - clipped)).reshape(-1, 1)

    @staticmethod
    def _with_direction_interactions(x: np.ndarray) -> np.ndarray:
        """Add feature×direction terms required by a pooled LONG/SHORT linear model."""

        values = np.asarray(x, dtype=float)
        if values.ndim != 2 or values.shape[1] < 2:
            raise ValueError("Expected a 2D feature matrix ending with scenario_direction")
        direction = values[:, -1:]
        interactions = values[:, :-1] * direction
        return np.column_stack([values, interactions])

    def fit(self, x_train: np.ndarray, y_train: np.ndarray, x_cal: np.ndarray, y_cal: np.ndarray):
        train_classes = set(np.asarray(y_train, dtype=str))
        cal_classes = set(np.asarray(y_cal, dtype=str))
        required = set(self.classes_)
        if not required.issubset(train_classes) or not required.issubset(cal_classes):
            raise ValueError("Training and calibration windows must each contain TP, SL and TIMEOUT outcomes")

        self.base.fit(self._with_direction_interactions(x_train), y_train)
        raw = self._base_probabilities(x_cal)
        self.calibrators = {}
        for index, label in enumerate(self.classes_):
            binary = (np.asarray(y_cal, dtype=str) == label).astype(int)
            calibrator = LogisticRegression(max_iter=1000, random_state=42)
            calibrator.fit(self._logit(raw[:, index]), binary)
            self.calibrators[label] = calibrator
        return self

    def _base_probabilities(self, x: np.ndarray) -> np.ndarray:
        probabilities = self.base.predict_proba(self._with_direction_interactions(x))
        base_classes = [str(item) for item in self.base.classes_]
        mapping = {label: probabilities[:, index] for index, label in enumerate(base_classes)}
        missing = [label for label in self.classes_ if label not in mapping]
        if missing:
            raise ValueError(f"Model is missing required outcome classes: {missing}")
        return np.column_stack([mapping[label] for label in self.classes_])

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        raw = self._base_probabilities(x)
        if not self.calibrators:
            raise RuntimeError("Model has not been calibrated")
        calibrated = np.column_stack(
            [
                self.calibrators[label].predict_proba(self._logit(raw[:, index]))[:, 1]
                for index, label in enumerate(self.classes_)
            ]
        )
        totals = calibrated.sum(axis=1, keepdims=True)
        return calibrated / np.where(totals <= 0, 1.0, totals)

    def predict(self, x: np.ndarray) -> np.ndarray:
        probabilities = self.predict_proba(x)
        return self.classes_[np.argmax(probabilities, axis=1)]


@dataclass(frozen=True)
class DatasetSplit:
    x_train: np.ndarray
    y_train: np.ndarray
    x_cal: np.ndarray
    y_cal: np.ndarray
    x_test: np.ndarray
    y_test: np.ndarray
    test_meta: pd.DataFrame


def make_barrier_dataset(
    candles: pd.DataFrame,
    horizon: int = 8,
    *,
    stop_atr_multiplier: float = DEFAULT_STOP_ATR_MULTIPLIER,
    tp_atr_multiplier: float = DEFAULT_TP_ATR_MULTIPLIER,
) -> pd.DataFrame:
    """Build two point-in-time scenarios (LONG and SHORT) for every labeled timestamp.

    Hourly OHLC cannot reveal the order of TP/SL touches within one bar, therefore
    ambiguous bars are resolved conservatively as SL.  A future lower-timeframe
    implementation can replace this fallback without changing the model contract.
    """

    if horizon <= 0:
        raise ValueError("horizon must be positive")
    frame = build_feature_frame(candles).sort_values(["symbol", "open_time"]).reset_index(drop=True)
    rows: list[dict] = []

    for symbol, group in frame.groupby("symbol", sort=False):
        group = group.reset_index(drop=True)
        if len(group) <= horizon:
            continue
        for index in range(0, len(group) - horizon):
            current = group.iloc[index]
            values = [current.get(name) for name in FEATURE_NAMES]
            if any(value is None or not np.isfinite(float(value)) for value in values):
                continue
            entry = float(current["close"])
            atr = float(current.get("atr_14", np.nan))
            if not np.isfinite(entry) or entry <= 0 or not np.isfinite(atr) or atr <= 0:
                continue
            future = group.iloc[index + 1 : index + 1 + horizon][["high", "low", "close"]]
            if len(future) < horizon:
                continue

            for direction, direction_code in (("LONG", 1.0), ("SHORT", -1.0)):
                if direction == "LONG":
                    stop = entry - atr * stop_atr_multiplier
                    take_profit = entry + atr * tp_atr_multiplier
                    sign = 1.0
                else:
                    stop = entry + atr * stop_atr_multiplier
                    take_profit = entry - atr * tp_atr_multiplier
                    sign = -1.0
                if stop <= 0 or take_profit <= 0:
                    continue
                result = triple_barrier_outcome(
                    future,
                    direction=direction,
                    stop=stop,
                    take_profit=take_profit,
                    conservative_ambiguity=True,
                )
                realized_return = sign * (float(result.exit_price) - entry) / entry
                row = {name: float(current[name]) for name in FEATURE_NAMES}
                row.update(
                    {
                        "scenario_direction": direction_code,
                        "open_time": current["open_time"],
                        "symbol": symbol,
                        "direction": direction,
                        "target": result.outcome,
                        "ambiguous": bool(result.ambiguous),
                        "exit_index": int(result.exit_index),
                        "realized_gross_return": float(realized_return),
                        "barrier_upside_rate": float(abs(take_profit - entry) / entry),
                        "barrier_downside_rate": float(abs(entry - stop) / entry),
                    }
                )
                rows.append(row)

    return pd.DataFrame.from_records(rows)


def chronological_split(frame: pd.DataFrame, purge_rows: int = 12) -> DatasetSplit:
    """Chronological train/calibration/final-holdout split on whole timestamps with purge gaps."""

    frame = frame.sort_values(["open_time", "symbol", "direction"]).reset_index(drop=True)
    unique_times = pd.Index(frame["open_time"].drop_duplicates().sort_values())
    n_times = len(unique_times)
    if n_times < 300:
        raise ValueError("At least 300 unique labeled timestamps are required")
    train_index = int(n_times * 0.70)
    cal_index = int(n_times * 0.85)
    train_boundary = unique_times[train_index]
    cal_boundary = unique_times[cal_index]
    purge = pd.Timedelta(hours=purge_rows)

    train = frame[frame["open_time"] < train_boundary - purge]
    cal = frame[(frame["open_time"] >= train_boundary + purge) & (frame["open_time"] < cal_boundary - purge)]
    test = frame[frame["open_time"] >= cal_boundary + purge]
    if min(len(train), len(cal), len(test)) < 90:
        raise ValueError("Chronological split produced an undersized window")
    if train["open_time"].max() >= cal["open_time"].min():
        raise AssertionError("Train/calibration windows overlap")
    if cal["open_time"].max() >= test["open_time"].min():
        raise AssertionError("Calibration/final-holdout windows overlap")

    meta_columns = [
        "open_time",
        "symbol",
        "direction",
        "target",
        "ambiguous",
        "realized_gross_return",
        "barrier_upside_rate",
        "barrier_downside_rate",
    ]
    return DatasetSplit(
        train[MODEL_FEATURE_NAMES].to_numpy(float),
        train["target"].to_numpy(),
        cal[MODEL_FEATURE_NAMES].to_numpy(float),
        cal["target"].to_numpy(),
        test[MODEL_FEATURE_NAMES].to_numpy(float),
        test["target"].to_numpy(),
        test[meta_columns].reset_index(drop=True),
    )


def _expected_calibration_error(y_true: np.ndarray, probabilities: np.ndarray, bins: int = 10) -> float:
    errors: list[float] = []
    weights: list[float] = []
    edges = np.linspace(0.0, 1.0, bins + 1)
    for lower, upper in zip(edges[:-1], edges[1:], strict=True):
        mask = (probabilities >= lower) & (
            (probabilities < upper) if upper < 1.0 else (probabilities <= upper)
        )
        if not mask.any():
            continue
        errors.append(abs(float(probabilities[mask].mean()) - float(y_true[mask].mean())))
        weights.append(float(mask.mean()))
    return float(np.dot(errors, weights)) if weights else 0.0


def evaluate_model(model: TemporalCalibratedBarrierModel, split: DatasetSplit) -> dict:
    probabilities = model.predict_proba(split.x_test)
    predicted = model.predict(split.x_test)
    y = np.asarray(split.y_test, dtype=str)
    class_to_index = {label: index for index, label in enumerate(model.classes_)}
    y_index = np.array([class_to_index[label] for label in y])
    one_hot = np.eye(len(model.classes_))[y_index]

    metrics: dict[str, object] = {
        "rows": int(len(y)),
        "accuracy": float(accuracy_score(y, predicted)),
        "log_loss": float(log_loss(y, probabilities, labels=list(model.classes_))),
        "multiclass_brier": float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1))),
        "ambiguous_rate": float(split.test_meta["ambiguous"].mean()),
        "class_distribution": {label: float((y == label).mean()) for label in model.classes_},
    }
    for index, label in enumerate(model.classes_):
        binary = (y == label).astype(int)
        metrics[f"brier_{label.lower()}"] = float(brier_score_loss(binary, probabilities[:, index]))
        metrics[f"ece_{label.lower()}"] = _expected_calibration_error(binary, probabilities[:, index])
    try:
        metrics["auc_ovr_macro"] = float(
            roc_auc_score(one_hot, probabilities, multi_class="ovr", average="macro")
        )
    except ValueError:
        metrics["auc_ovr_macro"] = None
    return metrics

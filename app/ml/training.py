from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.ml.features import FEATURE_NAMES, build_feature_frame


class TemporalCalibratedDirectionModel:
    """Direction classifier with sigmoid calibration fitted on a later chronological window."""

    classes_ = np.array(["SHORT", "LONG"])

    def __init__(self) -> None:
        self.base = Pipeline(
            [
                ("scale", StandardScaler()),
                ("logit", LogisticRegression(max_iter=2000, class_weight="balanced", random_state=42)),
            ]
        )
        self.calibrator = LogisticRegression(max_iter=1000, random_state=42)

    def fit(self, x_train: np.ndarray, y_train: np.ndarray, x_cal: np.ndarray, y_cal: np.ndarray):
        y_train_binary = (np.asarray(y_train) == "LONG").astype(int)
        y_cal_binary = (np.asarray(y_cal) == "LONG").astype(int)
        if len(np.unique(y_train_binary)) < 2 or len(np.unique(y_cal_binary)) < 2:
            raise ValueError("Training and calibration windows must each contain LONG and SHORT outcomes")
        self.base.fit(x_train, y_train_binary)
        raw = self.base.decision_function(x_cal).reshape(-1, 1)
        self.calibrator.fit(raw, y_cal_binary)
        return self

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        raw = self.base.decision_function(x).reshape(-1, 1)
        p_long = self.calibrator.predict_proba(raw)[:, 1]
        return np.column_stack([1.0 - p_long, p_long])

    def predict(self, x: np.ndarray) -> np.ndarray:
        return np.where(self.predict_proba(x)[:, 1] >= 0.5, "LONG", "SHORT")


@dataclass(frozen=True)
class DatasetSplit:
    x_train: np.ndarray
    y_train: np.ndarray
    x_cal: np.ndarray
    y_cal: np.ndarray
    x_test: np.ndarray
    y_test: np.ndarray
    test_meta: pd.DataFrame


def make_direction_dataset(candles: pd.DataFrame, horizon: int = 8) -> pd.DataFrame:
    frame = build_feature_frame(candles)
    frame["future_return"] = frame.groupby("symbol")["close"].shift(-horizon) / frame["close"] - 1.0
    frame["target"] = np.where(frame["future_return"] > 0, "LONG", "SHORT")
    required = FEATURE_NAMES + ["future_return", "target", "open_time", "symbol"]
    frame = frame.dropna(subset=required).copy()
    return frame


def chronological_split(frame: pd.DataFrame, purge_rows: int = 12) -> DatasetSplit:
    """Chronological train/calibration/test split on whole timestamps with purge gaps."""
    frame = frame.sort_values(["open_time", "symbol"]).reset_index(drop=True)
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
    if min(len(train), len(cal), len(test)) < 30:
        raise ValueError("Chronological split produced an undersized window")
    if train["open_time"].max() >= cal["open_time"].min():
        raise AssertionError("Train/calibration windows overlap")
    if cal["open_time"].max() >= test["open_time"].min():
        raise AssertionError("Calibration/test windows overlap")
    return DatasetSplit(
        train[FEATURE_NAMES].to_numpy(float),
        train["target"].to_numpy(),
        cal[FEATURE_NAMES].to_numpy(float),
        cal["target"].to_numpy(),
        test[FEATURE_NAMES].to_numpy(float),
        test["target"].to_numpy(),
        test[["open_time", "symbol", "future_return"]].reset_index(drop=True),
    )


def evaluate_model(model: TemporalCalibratedDirectionModel, split: DatasetSplit) -> dict:
    proba = model.predict_proba(split.x_test)[:, 1]
    y_binary = (split.y_test == "LONG").astype(int)
    predicted = np.where(proba >= 0.5, "LONG", "SHORT")
    metrics = {
        "rows": int(len(split.y_test)),
        "accuracy": float(accuracy_score(split.y_test, predicted)),
        "brier": float(brier_score_loss(y_binary, proba)),
        "log_loss": float(log_loss(y_binary, np.column_stack([1 - proba, proba]), labels=[0, 1])),
    }
    try:
        metrics["auc"] = float(roc_auc_score(y_binary, proba))
    except ValueError:
        metrics["auc"] = None
    return metrics

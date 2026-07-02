from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import joblib
import pytest

from app.config import Settings
from app.ml.artifact_recovery import load_recovery_candidate
from app.ml.lifecycle import evaluate_quality_gate
from app.ml.training import (
    LABEL_PATH_SCHEMA_VERSION,
    MODEL_FEATURE_NAMES,
    MODEL_FEATURE_SCHEMA_VERSION,
    OUTCOME_CLASSES,
    TEMPORAL_SPLIT_SCHEMA_VERSION,
)


def _passing_metrics() -> dict[str, object]:
    return {
        "rows": 300,
        "log_loss": 0.90,
        "multiclass_brier": 0.55,
        "ece_tp": 0.05,
        "ece_sl": 0.06,
        "ece_timeout": 0.07,
        "class_distribution": {"TP": 0.35, "SL": 0.40, "TIMEOUT": 0.25},
        "policy_metric_schema": "exit-time-open-gap-single-symbol-cohort-v7",
        "policy_horizon_hours": 8,
        "policy_capital_sleeves": 8,
        "policy_trades": 80,
        "policy_cohorts": 80,
        "policy_realized_mean_r": 0.05,
        "policy_profit_factor": 1.2,
        "policy_max_drawdown_r": 5.0,
    }


def _write_artifact(path: Path, *, version: str | None = None, horizon: int = 8) -> None:
    now = datetime.now(UTC)
    resolved_version = version or path.stem
    joblib.dump(
        {
            "task": "barrier_outcome_v1",
            "model": SimpleNamespace(classes_=list(OUTCOME_CLASSES)),
            "model_type": "logistic",
            "version": resolved_version,
            "calibration_version": f"sigmoid-ovr-{resolved_version}",
            "feature_names": MODEL_FEATURE_NAMES,
            "feature_schema_version": MODEL_FEATURE_SCHEMA_VERSION,
            "label_path_schema_version": LABEL_PATH_SCHEMA_VERSION,
            "temporal_split_schema": TEMPORAL_SPLIT_SCHEMA_VERSION,
            "horizon_hours": horizon,
            "metrics": _passing_metrics(),
            "training_start": now.isoformat(),
            "training_end": now.isoformat(),
            "dataset_rows": 1000,
            "unique_timestamps": 500,
            "symbol_count": 2,
            "symbol_sample": ["BTCUSDT", "ETHUSDT"],
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "training_data_profile": {
                "candle_rows": 1800,
                "unique_timestamps": 900,
                "symbol_count": 2,
                "symbols": ["BTCUSDT", "ETHUSDT"],
                "start_time": now.isoformat(),
                "end_time": now.isoformat(),
                "min_rows_per_symbol": 900,
                "median_rows_per_symbol": 900,
                "max_rows_per_symbol": 900,
                "covered_symbols": 2,
                "coverage_ratio": 1.0,
                "minimum_rows_for_coverage": 300,
                "symbols_sha256": "symbols",
                "coverage_sha256": "coverage",
            },
            "source": "background_trainer",
            "created_at": now.isoformat(),
        },
        path,
    )


def test_recovery_loader_reconstructs_candidate_and_absolute_gate(tmp_path: Path) -> None:
    path = tmp_path / "barrier-logistic-h8-20260628T072708Z.joblib"
    _write_artifact(path)

    candidate = load_recovery_candidate(path, expected_horizon_hours=8)
    gate = evaluate_quality_gate(
        candidate,
        Settings(database_url="postgresql+psycopg://u:p@localhost/db"),
    )

    assert candidate.version == path.stem
    assert candidate.path == path.resolve()
    assert candidate.incumbent_version is None
    assert candidate.feature_schema_version == MODEL_FEATURE_SCHEMA_VERSION
    assert candidate.training_data_profile.symbols == ("BTCUSDT", "ETHUSDT")
    assert gate["passed"] is True
    assert gate["relative"] is None


def test_recovery_loader_rejects_filename_version_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "barrier-logistic-h8-new.joblib"
    _write_artifact(path, version="barrier-logistic-h8-other")

    with pytest.raises(RuntimeError, match="filename/version mismatch"):
        load_recovery_candidate(path, expected_horizon_hours=8)


def test_recovery_loader_rejects_wrong_horizon(tmp_path: Path) -> None:
    path = tmp_path / "barrier-logistic-h12-test.joblib"
    _write_artifact(path, horizon=12)

    with pytest.raises(RuntimeError, match="DEFAULT_HORIZON_HOURS=8"):
        load_recovery_candidate(path, expected_horizon_hours=8)


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value


class _FakeSession:
    def __init__(self, values: list[object]) -> None:
        self.values = iter(values)

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _statement: object) -> _ScalarResult:
        return _ScalarResult(next(self.values))


@pytest.mark.asyncio
async def test_recover_artifact_registers_and_activates_gate_passed_orphan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import model_registry

    path = tmp_path / "barrier-logistic-h8-recovery.joblib"
    path.write_bytes(b"artifact")
    active = SimpleNamespace(
        id="active-id",
        version="missing-active-v1",
        model_type="barrier_logistic",
        artifact_path=str(tmp_path / "deleted.joblib"),
    )
    candidate = SimpleNamespace(version=path.stem, path=path.resolve())
    registered = SimpleNamespace(id="candidate-id")
    activations: list[tuple[str, str | None]] = []

    monkeypatch.setattr(
        model_registry,
        "get_settings",
        lambda: Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            app_mode="paper",
            allow_baseline_model=True,
            model_dir=tmp_path,
        ),
    )
    monkeypatch.setattr(model_registry, "SessionFactory", lambda: _FakeSession([active, None]))
    monkeypatch.setattr(model_registry, "load_recovery_candidate", lambda *_args, **_kwargs: candidate)
    monkeypatch.setattr(
        model_registry,
        "evaluate_quality_gate",
        lambda *_args, **_kwargs: {"passed": True, "reasons": [], "relative": None},
    )

    async def register_and_activate(
        candidate_value: object,
        *,
        source: str,
        quality_gate: dict[str, object] | None,
        actor: str,
        expected_previous_version: str | None,
        expected_horizon_hours: int,
        incumbent_recovery: dict[str, object] | None,
    ) -> tuple[object, dict[str, object]]:
        assert source == "operator_artifact_recovery"
        assert quality_gate and quality_gate["passed"] is True
        assert expected_horizon_hours == 8
        assert incumbent_recovery is not None
        activations.append((candidate_value.version, expected_previous_version))
        return registered, {"version": candidate_value.version, "actor": actor}

    monkeypatch.setattr(
        model_registry,
        "register_and_activate_model_candidate",
        register_and_activate,
    )

    result = await model_registry.recover_artifact(path)

    assert result["activated"] is True
    assert result["reason"] == "orphan_recovery_activated"
    assert activations == [(path.stem, active.version)]


@pytest.mark.asyncio
async def test_recover_artifact_does_not_override_failed_registered_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import model_registry

    path = tmp_path / "barrier-logistic-h8-rejected.joblib"
    path.write_bytes(b"artifact")
    active = SimpleNamespace(
        id="active-id",
        version="missing-active-v1",
        model_type="barrier_logistic",
        artifact_path=str(tmp_path / "deleted.joblib"),
    )
    candidate = SimpleNamespace(version=path.stem, path=path.resolve())
    existing = SimpleNamespace(
        id="candidate-id",
        version=path.stem,
        artifact_path=str(path.resolve()),
        metrics={
            "quality_gate": {
                "passed": False,
                "reasons": ["policy_profit_factor_below_minimum"],
            }
        },
    )

    monkeypatch.setattr(
        model_registry,
        "get_settings",
        lambda: Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            app_mode="paper",
            allow_baseline_model=True,
            model_dir=tmp_path,
        ),
    )
    monkeypatch.setattr(model_registry, "SessionFactory", lambda: _FakeSession([active, existing]))
    monkeypatch.setattr(model_registry, "load_recovery_candidate", lambda *_args, **_kwargs: candidate)

    async def unexpected_activation(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("failed gate must not activate")

    monkeypatch.setattr(model_registry, "activate_registered_model", unexpected_activation)

    result = await model_registry.recover_artifact(path)

    assert result["activated"] is False
    assert result["reason"] == "registered_candidate_did_not_pass_quality_gate"

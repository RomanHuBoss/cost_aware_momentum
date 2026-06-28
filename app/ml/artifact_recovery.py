from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.ml.data_profile import TrainingDataProfile
from app.ml.lifecycle import ModelCandidate
from app.ml.runtime import ModelRuntime


def _required_datetime(bundle: Mapping[str, Any], key: str) -> datetime:
    raw = bundle.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise RuntimeError(f"Recovery artifact is missing required {key}")
    try:
        value = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"Recovery artifact has invalid {key}: {raw!r}") from exc
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _required_positive_int(bundle: Mapping[str, Any], key: str) -> int:
    try:
        value = int(bundle.get(key))
    except (TypeError, ValueError, OverflowError) as exc:
        raise RuntimeError(f"Recovery artifact has invalid {key}") from exc
    if value <= 0:
        raise RuntimeError(f"Recovery artifact has non-positive {key}")
    return value


def load_recovery_candidate(
    artifact_path: Path,
    *,
    expected_horizon_hours: int,
) -> ModelCandidate:
    """Validate an orphan artifact and reconstruct the candidate metadata.

    This does not register or activate the model.  It provides the same immutable
    candidate contract used by the normal trainer so the caller can re-run the
    absolute quality gate before any recovery action.
    """

    resolved = artifact_path.expanduser().resolve()
    if not resolved.is_file():
        raise RuntimeError(f"Recovery artifact does not exist: {resolved}")

    runtime = ModelRuntime(resolved, allow_baseline=False)
    runtime.load(source="operator_artifact_recovery")
    if runtime.version != resolved.stem:
        raise RuntimeError(
            "Recovery artifact filename/version mismatch: "
            f"filename={resolved.stem}, artifact={runtime.version}"
        )
    if runtime.horizon_hours != expected_horizon_hours:
        raise RuntimeError(
            f"Recovery artifact horizon {runtime.horizon_hours} does not match "
            f"DEFAULT_HORIZON_HOURS={expected_horizon_hours}"
        )
    bundle = runtime.bundle
    if not isinstance(bundle, dict):
        raise RuntimeError("Recovery artifact bundle is unavailable after validation")

    metrics = bundle.get("metrics")
    if not isinstance(metrics, dict):
        raise RuntimeError("Recovery artifact is missing metrics required for quality gates")
    profile = TrainingDataProfile.from_mapping(bundle.get("training_data_profile"))
    if profile is None:
        raise RuntimeError("Recovery artifact is missing a valid training_data_profile")

    model_type = str(bundle.get("model_type") or "").strip()
    if not model_type:
        raise RuntimeError("Recovery artifact is missing model_type")
    symbol_sample_raw = bundle.get("symbol_sample")
    if isinstance(symbol_sample_raw, (list, tuple)):
        symbol_sample = tuple(str(item) for item in symbol_sample_raw if item)[:25]
    else:
        symbol_sample = profile.symbols[:25]

    return ModelCandidate(
        path=resolved,
        version=runtime.version,
        model_type=model_type,
        horizon=expected_horizon_hours,
        training_start=_required_datetime(bundle, "training_start"),
        training_end=_required_datetime(bundle, "training_end"),
        dataset_rows=_required_positive_int(bundle, "dataset_rows"),
        unique_timestamps=_required_positive_int(bundle, "unique_timestamps"),
        symbol_count=_required_positive_int(bundle, "symbol_count"),
        symbol_sample=symbol_sample,
        training_data_profile=profile,
        metrics=metrics,
        incumbent_metrics=None,
        incumbent_version=None,
        feature_schema_version=str(
            bundle.get("feature_schema_version") or "hourly-barrier-v1"
        ),
    )

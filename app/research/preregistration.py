from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from app.json_utils import json_compatible

PREREGISTRATION_SPEC_SCHEMA_VERSION = "formal-experiment-family-preregistration-v1"
PREREGISTRATION_RECORD_SCHEMA_VERSION = "immutable-experiment-family-registration-v1"
PRIMARY_METRIC = {"name": "nonannualized_sharpe", "direction": "maximize"}

_REQUIRED_GOVERNANCE_KEYS = frozenset(
    {
        "pbo_segments",
        "minimum_trials",
        "minimum_periods",
        "maximum_pbo",
        "minimum_dsr_probability",
        "dependence_block_periods",
        "minimum_independent_blocks",
        "bootstrap_replicates",
        "confidence_level",
    }
)
_PLACEHOLDER_MARKERS = ("REPLACE_", "TODO", "TBD")
_EXCLUSION_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _canonical(value: Any) -> str:
    return json.dumps(
        json_compatible(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _is_placeholder(value: str) -> bool:
    upper = value.upper()
    return any(marker in upper for marker in _PLACEHOLDER_MARKERS)


def _validate_family(value: Any) -> str:
    family = str(value).strip()
    if not family or len(family) > 160:
        raise ValueError("experiment_family must contain 1..160 characters")
    return family


def _validate_sha256(value: Any, name: str) -> str:
    normalized = str(value).lower()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise ValueError(f"{name} must be a lowercase 64-character SHA-256")
    return normalized


def _finite_float(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _positive_int(value: Any, name: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    result = int(value)
    if result != value or result < minimum:
        raise ValueError(f"{name} must be an integer of at least {minimum}")
    return result


def _normalize_governance(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _REQUIRED_GOVERNANCE_KEYS:
        raise ValueError(
            "governance must contain exactly: " + ", ".join(sorted(_REQUIRED_GOVERNANCE_KEYS))
        )
    result = {
        "pbo_segments": _positive_int(value["pbo_segments"], "governance.pbo_segments", minimum=4),
        "minimum_trials": _positive_int(value["minimum_trials"], "governance.minimum_trials", minimum=2),
        "minimum_periods": _positive_int(value["minimum_periods"], "governance.minimum_periods", minimum=1),
        "maximum_pbo": _finite_float(value["maximum_pbo"], "governance.maximum_pbo"),
        "minimum_dsr_probability": _finite_float(
            value["minimum_dsr_probability"], "governance.minimum_dsr_probability"
        ),
        "dependence_block_periods": _positive_int(
            value["dependence_block_periods"],
            "governance.dependence_block_periods",
            minimum=2,
        ),
        "minimum_independent_blocks": _positive_int(
            value["minimum_independent_blocks"],
            "governance.minimum_independent_blocks",
            minimum=2,
        ),
        "bootstrap_replicates": _positive_int(
            value["bootstrap_replicates"], "governance.bootstrap_replicates", minimum=100
        ),
        "confidence_level": _finite_float(value["confidence_level"], "governance.confidence_level"),
    }
    if result["pbo_segments"] % 2:
        raise ValueError("governance.pbo_segments must be even")
    if result["minimum_periods"] < result["pbo_segments"] * 2:
        raise ValueError("governance.minimum_periods must provide two rows per PBO segment")
    if not 0.0 <= result["maximum_pbo"] <= 1.0:
        raise ValueError("governance.maximum_pbo must be in [0, 1]")
    if not 0.0 <= result["minimum_dsr_probability"] <= 1.0:
        raise ValueError("governance.minimum_dsr_probability must be in [0, 1]")
    if not 0.5 < result["confidence_level"] < 1.0:
        raise ValueError("governance.confidence_level must be in (0.5, 1)")
    return result


def _normalize_configuration_contract(value: Any) -> tuple[dict[str, Any], int]:
    if not isinstance(value, Mapping) or set(value) != {"fixed_parameters", "search_space"}:
        raise ValueError("configuration_contract must contain fixed_parameters and search_space")
    fixed = value["fixed_parameters"]
    search = value["search_space"]
    if not isinstance(fixed, Mapping) or not fixed:
        raise ValueError("configuration_contract.fixed_parameters must be a non-empty mapping")
    if not isinstance(search, Mapping) or not search:
        raise ValueError("configuration_contract.search_space must be a non-empty mapping")
    fixed_keys = {str(key) for key in fixed}
    search_keys = {str(key) for key in search}
    overlap = fixed_keys.intersection(search_keys)
    if overlap:
        raise ValueError(f"fixed and search parameters overlap: {sorted(overlap)}")
    required_fixed = {"schema", "dataset_fingerprint", "horizon", "policy_source", "portfolio_accounting"}
    missing_fixed = required_fixed.difference(fixed_keys)
    if missing_fixed:
        raise ValueError(f"fixed parameters must include {sorted(missing_fixed)}")

    normalized_fixed = json_compatible({str(key): value for key, value in fixed.items()})
    normalized_fixed["dataset_fingerprint"] = _validate_sha256(
        normalized_fixed["dataset_fingerprint"],
        "fixed parameter dataset_fingerprint",
    )
    normalized_fixed["horizon"] = _positive_int(
        normalized_fixed["horizon"],
        "fixed parameter horizon",
    )

    normalized_search: dict[str, dict[str, list[Any]]] = {}
    combination_count = 1
    for raw_name, descriptor in sorted(search.items(), key=lambda item: str(item[0])):
        name = str(raw_name)
        if not name:
            raise ValueError("search parameter names cannot be empty")
        if not isinstance(descriptor, Mapping) or set(descriptor) != {"values"}:
            raise ValueError(f"search parameter {name} must contain exactly a values list")
        raw_values = descriptor["values"]
        if not isinstance(raw_values, Sequence) or isinstance(raw_values, (str, bytes)) or not raw_values:
            raise ValueError(f"search parameter {name} values must be a non-empty list")
        values = [json_compatible(item) for item in raw_values]
        canonical_values = [_canonical(item) for item in values]
        if len(canonical_values) != len(set(canonical_values)):
            raise ValueError(f"search parameter {name} contains duplicate values")
        normalized_search[name] = {"values": values}
        combination_count *= len(values)

    return {
        "fixed_parameters": normalized_fixed,
        "search_space": normalized_search,
    }, combination_count


def normalize_preregistration_spec(
    specification: Mapping[str, Any],
    *,
    expected_family: str | None = None,
) -> dict[str, Any]:
    if not isinstance(specification, Mapping):
        raise ValueError("Preregistration specification must be a mapping")
    allowed_keys = {
        "schema",
        "experiment_family",
        "hypothesis",
        "primary_metric",
        "configuration_contract",
        "governance",
        "stopping_rule",
        "exclusion_criteria",
        "template_created_at",
    }
    unknown = set(specification).difference(allowed_keys)
    if unknown:
        raise ValueError(f"Unknown preregistration fields: {sorted(unknown)}")
    required = allowed_keys.difference({"template_created_at"})
    missing = required.difference(specification)
    if missing:
        raise ValueError(f"Missing preregistration fields: {sorted(missing)}")
    if specification["schema"] != PREREGISTRATION_SPEC_SCHEMA_VERSION:
        raise ValueError("Unsupported preregistration schema")
    family = _validate_family(specification["experiment_family"])
    if expected_family is not None and family != _validate_family(expected_family):
        raise ValueError("experiment_family does not match the requested family")

    hypothesis = str(specification["hypothesis"]).strip()
    if len(hypothesis) < 40 or len(hypothesis) > 4000 or _is_placeholder(hypothesis):
        raise ValueError("hypothesis must be a substantive pre-result statement without placeholders")
    primary_metric = json_compatible(specification["primary_metric"])
    if primary_metric != PRIMARY_METRIC:
        raise ValueError(f"primary_metric must equal {PRIMARY_METRIC}")

    contract, combination_count = _normalize_configuration_contract(
        specification["configuration_contract"]
    )
    governance = _normalize_governance(specification["governance"])

    stopping = specification["stopping_rule"]
    if not isinstance(stopping, Mapping) or set(stopping) != {
        "max_unique_configurations",
        "stop_after_utc",
    }:
        raise ValueError("stopping_rule must contain max_unique_configurations and stop_after_utc")
    max_unique = _positive_int(
        stopping["max_unique_configurations"],
        "stopping_rule.max_unique_configurations",
        minimum=governance["minimum_trials"],
    )
    if max_unique > combination_count:
        raise ValueError("stopping rule exceeds the enumerated search space")
    stop_after_raw = stopping["stop_after_utc"]
    stop_after: str | None
    if stop_after_raw is None:
        stop_after = None
    else:
        parsed = datetime.fromisoformat(str(stop_after_raw))
        stop_after = _aware(parsed, "stopping_rule.stop_after_utc").isoformat()

    exclusions = specification["exclusion_criteria"]
    if not isinstance(exclusions, Sequence) or isinstance(exclusions, (str, bytes)) or not exclusions:
        raise ValueError("exclusion_criteria must be a non-empty list")
    normalized_exclusions: list[dict[str, str]] = []
    seen_codes: set[str] = set()
    for item in exclusions:
        if not isinstance(item, Mapping) or set(item) != {"code", "description"}:
            raise ValueError("Each exclusion criterion must contain code and description")
        code = str(item["code"]).strip().upper()
        description = str(item["description"]).strip()
        if not _EXCLUSION_CODE.fullmatch(code):
            raise ValueError(f"Invalid exclusion criterion code: {code}")
        if code in seen_codes:
            raise ValueError(f"Duplicate exclusion criterion code: {code}")
        if len(description) < 20 or len(description) > 1000 or _is_placeholder(description):
            raise ValueError(f"Exclusion criterion {code} requires a substantive description")
        seen_codes.add(code)
        normalized_exclusions.append({"code": code, "description": description})

    return {
        "schema": PREREGISTRATION_SPEC_SCHEMA_VERSION,
        "experiment_family": family,
        "hypothesis": hypothesis,
        "primary_metric": dict(PRIMARY_METRIC),
        "configuration_contract": contract,
        "governance": governance,
        "stopping_rule": {
            "max_unique_configurations": max_unique,
            "stop_after_utc": stop_after,
        },
        "exclusion_criteria": normalized_exclusions,
    }


def validate_preregistered_trial(
    specification: Mapping[str, Any],
    configuration: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = normalize_preregistration_spec(
        specification,
        expected_family=str(specification.get("experiment_family", "")),
    )
    contract = normalized["configuration_contract"]
    fixed = contract["fixed_parameters"]
    search = contract["search_space"]
    actual = json_compatible(dict(configuration))
    declared = set(fixed).union(search)
    undeclared = set(actual).difference(declared)
    missing = declared.difference(actual)
    if undeclared:
        raise ValueError(f"undeclared configuration parameters: {sorted(undeclared)}")
    if missing:
        raise ValueError(f"missing preregistered configuration parameters: {sorted(missing)}")
    for name, expected in fixed.items():
        if _canonical(actual[name]) != _canonical(expected):
            raise ValueError(f"fixed parameter {name} does not match preregistration")
    selected: dict[str, Any] = {}
    for name, descriptor in search.items():
        candidate = _canonical(actual[name])
        allowed = {_canonical(item) for item in descriptor["values"]}
        if candidate not in allowed:
            raise ValueError(f"search parameter {name} is outside the preregistered values")
        selected[name] = actual[name]
    return selected


def validate_stopping_rule(
    specification: Mapping[str, Any],
    *,
    attempted_configuration_hashes: Sequence[str],
    candidate_configuration_hash: str,
    observed_at: datetime,
) -> None:
    normalized = normalize_preregistration_spec(
        specification,
        expected_family=str(specification.get("experiment_family", "")),
    )
    candidate_hash = _validate_sha256(candidate_configuration_hash, "candidate_configuration_hash")
    observed = _aware(observed_at, "observed_at")
    stop_after = normalized["stopping_rule"]["stop_after_utc"]
    if stop_after is not None and observed > datetime.fromisoformat(stop_after):
        raise ValueError("Preregistered stop_after_utc has passed")
    attempted = {
        _validate_sha256(item, "attempted_configuration_hash")
        for item in attempted_configuration_hashes
    }
    maximum = int(normalized["stopping_rule"]["max_unique_configurations"])
    if candidate_hash not in attempted and len(attempted) >= maximum:
        raise ValueError("Preregistered maximum unique configuration budget is exhausted")


def build_preregistration_template(
    *,
    experiment_family: str,
    configuration: Mapping[str, Any],
    search_parameters: Sequence[str],
    governance: Mapping[str, Any],
    created_at: datetime,
) -> dict[str, Any]:
    family = _validate_family(experiment_family)
    parameters = tuple(dict.fromkeys(str(item) for item in search_parameters))
    if not parameters:
        raise ValueError("At least one search parameter is required for a preregistration template")
    actual = json_compatible(dict(configuration))
    unknown = set(parameters).difference(actual)
    if unknown:
        raise ValueError(f"Unknown search parameters: {sorted(unknown)}")
    fixed = {key: value for key, value in actual.items() if key not in parameters}
    search = {key: {"values": [actual[key]]} for key in parameters}
    normalized_governance = _normalize_governance(governance)
    return {
        "schema": PREREGISTRATION_SPEC_SCHEMA_VERSION,
        "experiment_family": family,
        "hypothesis": "REPLACE_WITH_A_SUBSTANTIVE_DIRECTIONAL_HYPOTHESIS_BEFORE_ANY_TRIAL",
        "primary_metric": dict(PRIMARY_METRIC),
        "configuration_contract": {
            "fixed_parameters": fixed,
            "search_space": search,
        },
        "governance": normalized_governance,
        "stopping_rule": {
            "max_unique_configurations": normalized_governance["minimum_trials"],
            "stop_after_utc": None,
        },
        "exclusion_criteria": [
            {
                "code": "REPLACE_EXCLUSION_CODE",
                "description": "REPLACE_WITH_AN_OBJECTIVE_PRE_RESULT_EXCLUSION_CRITERION",
            }
        ],
        "template_created_at": _aware(created_at, "created_at").isoformat(),
    }


def build_preregistration_record_hash(
    *,
    experiment_family: str,
    registered_at: datetime,
    specification: Mapping[str, Any],
    release_version: str,
) -> str:
    payload = {
        "schema": PREREGISTRATION_RECORD_SCHEMA_VERSION,
        "experiment_family": _validate_family(experiment_family),
        "registered_at": _aware(registered_at, "registered_at").isoformat(),
        "specification": json_compatible(dict(specification)),
        "release_version": str(release_version),
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def verify_preregistration_integrity(row: Any) -> bool:
    try:
        expected = build_preregistration_record_hash(
            experiment_family=row.experiment_family,
            registered_at=row.registered_at,
            specification=row.specification,
            release_version=row.release_version,
        )
    except (AttributeError, TypeError, ValueError):
        return False
    return expected == str(row.record_hash)

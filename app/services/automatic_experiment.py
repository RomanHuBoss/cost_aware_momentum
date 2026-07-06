from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import math
import re
import sys
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

from app import __version__
from app.config import Settings
from app.db.engine import SessionFactory, engine
from app.db.locks import lock_key
from app.db.models import ModelRegistry, ResearchExperimentEvent
from app.json_utils import json_compatible
from app.research.preregistration import normalize_preregistration_spec
from app.services.audit import append_audit_event, publish_outbox
from app.services.experiment_ledger import (
    append_experiment_event,
    experiment_configuration_hash,
    experiment_governance_report,
    load_experiment_family_evidence,
    verify_experiment_event_integrity,
)
from app.services.experiment_preregistration import (
    load_experiment_preregistration,
    register_experiment_family,
)
from app.services.process_tree import (
    process_tree_spawn_kwargs,
    terminate_process_tree,
)
from app.services.trainer_control import (
    ExperimentCancelClaim,
    claim_automatic_experiment_cancel,
    finish_automatic_experiment_cancel,
)

AUTOMATIC_EXPERIMENT_SCHEMA = "automatic-preregistered-policy-experiment-v1"
AUTOMATIC_EXPERIMENT_TERMINAL_SCHEMA = "automatic-experiment-terminal-candidate-v1"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FAMILY_TOKEN = re.compile(r"[^A-Za-z0-9._-]+")
_SEARCH_PARAMETERS = ("minimum_net_rr", "minimum_net_ev_r")
_TERMINAL_REPORT_STATUSES = frozenset(
    {
        "REJECTED",
        "REJECTED_COST_STRESS",
        "BLOCKED_PREREGISTRATION_VIOLATION",
        "BLOCKED_PREREGISTRATION_POLICY_MISMATCH",
        "BLOCKED_INCOMPATIBLE_HORIZONS",
        "BLOCKED_INSUFFICIENT_PERIODS",
        "BLOCKED_INVALID_RETURN_EVIDENCE",
        "BLOCKED_REDUNDANT_TRIALS",
        "BLOCKED_UNALIGNED_RETURNS",
        "BLOCKED_INSUFFICIENT_DEPENDENCE_EVIDENCE",
    }
)

CommandRunner = Callable[[Sequence[str], Path, int], Awaitable[dict[str, Any]]]
CancellationProbe = Callable[[], Awaitable[ExperimentCancelClaim | None]]
StatusCallback = Callable[[dict[str, Any]], Awaitable[None]]


class AutomaticExperimentCancelled(RuntimeError):
    def __init__(
        self,
        claim: ExperimentCancelClaim,
        process_result: Mapping[str, Any],
    ) -> None:
        super().__init__(
            "Automatic experiment subprocess was cancelled by an authenticated operator"
        )
        self.claim = claim
        self.process_result = json_compatible(dict(process_result))


class AutomaticExperimentSubprocessFailure(RuntimeError):
    def __init__(self, message: str, process_result: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.process_result = json_compatible(dict(process_result))


def _canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        json_compatible(dict(value)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _finite_rounded(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return round(number, 12)


def automatic_experiment_plan(
    settings: Settings,
    *,
    model_version: str,
    model_sha256: str,
) -> dict[str, Any]:
    version = str(model_version).strip()
    digest = str(model_sha256).strip().lower()
    if not version:
        raise ValueError("Automatic experiment model_version is required")
    if not _SHA256.fullmatch(digest):
        raise ValueError("Automatic experiment model_sha256 must be lowercase SHA-256")

    rr_values = sorted(
        {
            _finite_rounded(settings.min_net_rr * float(multiplier), "minimum_net_rr")
            for multiplier in settings.auto_train_experiment_rr_multipliers
        }
    )
    ev_values = sorted(
        {
            _finite_rounded(settings.min_net_ev_r + float(addition), "minimum_net_ev_r")
            for addition in settings.auto_train_experiment_ev_additions
        }
    )
    if any(item < 0.0 for item in rr_values + ev_values):
        raise ValueError("Automatic experiment thresholds cannot be negative")
    deployment = {
        "minimum_net_rr": _finite_rounded(settings.min_net_rr, "MIN_NET_RR"),
        "minimum_net_ev_r": _finite_rounded(settings.min_net_ev_r, "MIN_NET_EV_R"),
    }
    configurations = [
        {"minimum_net_rr": rr, "minimum_net_ev_r": ev}
        for rr, ev in itertools.product(rr_values, ev_values)
    ]
    if deployment not in configurations:
        raise ValueError("Automatic experiment grid does not include deployment thresholds")
    if len(configurations) < settings.experiment_min_trials:
        raise ValueError("Automatic experiment grid has fewer configurations than the governance minimum")
    if len(configurations) > 16:
        raise ValueError("Automatic experiment grid exceeds the 16-configuration safety bound")

    plan_core = {
        "schema": AUTOMATIC_EXPERIMENT_SCHEMA,
        "model_version": version,
        "model_sha256": digest,
        "search_parameters": list(_SEARCH_PARAMETERS),
        "configurations": configurations,
        "deployment_configuration": deployment,
        "governance": {
            "pbo_segments": settings.experiment_pbo_segments,
            "minimum_trials": settings.experiment_min_trials,
            "minimum_periods": settings.experiment_min_periods,
            "maximum_pbo": settings.experiment_max_pbo,
            "minimum_dsr_probability": settings.experiment_min_dsr_probability,
            "dependence_block_periods": settings.experiment_dependence_block_periods,
            "minimum_independent_blocks": settings.experiment_min_independent_blocks,
            "bootstrap_replicates": settings.research_bootstrap_replicates,
            "confidence_level": settings.research_confidence_level,
        },
    }
    plan_hash = _canonical_hash(plan_core)
    version_token = _FAMILY_TOKEN.sub("-", version).strip("-._") or "candidate"
    version_token = version_token[:72]
    family = f"auto-{version_token}-{digest[:12]}-{plan_hash[:12]}"
    return json_compatible({**plan_core, "plan_hash": plan_hash, "experiment_family": family})


def finalize_automatic_preregistration(
    template: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
    model_version: str,
    model_sha256: str,
) -> dict[str, Any]:
    candidate = deepcopy(dict(template))
    family = str(plan.get("experiment_family", "")).strip()
    if candidate.get("experiment_family") != family:
        raise ValueError("Prepared preregistration family does not match the automatic plan")
    contract = candidate.get("configuration_contract")
    if not isinstance(contract, dict):
        raise ValueError("Prepared preregistration lacks a configuration contract")
    fixed = contract.get("fixed_parameters")
    search = contract.get("search_space")
    if not isinstance(fixed, dict) or not isinstance(search, dict):
        raise ValueError("Prepared preregistration contract is malformed")
    if fixed.get("model_version") != model_version:
        raise ValueError("Prepared preregistration model version mismatch")
    if str(fixed.get("model_sha256", "")).lower() != str(model_sha256).lower():
        raise ValueError("Prepared preregistration model SHA-256 mismatch")
    if set(search) != set(_SEARCH_PARAMETERS):
        raise ValueError("Prepared preregistration search parameters do not match the automatic plan")

    configurations = plan.get("configurations")
    if not isinstance(configurations, list) or not configurations:
        raise ValueError("Automatic experiment plan has no configurations")
    values_by_name = {
        name: sorted({float(item[name]) for item in configurations})
        for name in _SEARCH_PARAMETERS
    }
    contract["search_space"] = {
        name: {"values": values_by_name[name]} for name in _SEARCH_PARAMETERS
    }
    candidate["hypothesis"] = (
        "Before observing any automatic trial return, the exact deployment thresholds for "
        f"model {model_version} are hypothesized to maximize nonannualized Sharpe within the "
        "bounded preregistered stricter RR/EV grid while retaining dependence-aware and "
        "mandatory cost-stress support."
    )
    candidate["stopping_rule"] = {
        "max_unique_configurations": len(configurations),
        "stop_after_utc": None,
    }
    candidate["exclusion_criteria"] = [
        {
            "code": "EVIDENCE_INTEGRITY_FAILURE",
            "description": (
                "Exclude a trial only when point-in-time market, universe, funding, margin, "
                "artifact or return-path integrity validation fails before complete aligned "
                "evidence can be produced."
            ),
        },
        {
            "code": "RECORDED_RUNTIME_FAILURE",
            "description": (
                "Exclude a trial only for a recorded deterministic runtime or infrastructure "
                "failure; a completed trial must never be excluded because its performance is poor."
            ),
        },
    ]
    return normalize_preregistration_spec(candidate, expected_family=family)


async def _run_subprocess(
    command: Sequence[str],
    cwd: Path,
    timeout_seconds: int,
    *,
    cancellation_probe: CancellationProbe | None = None,
    cancellation_poll_seconds: float = 1.0,
    cancellation_grace_seconds: float = 10.0,
) -> dict[str, Any]:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **process_tree_spawn_kwargs(),
    )
    communicate_task = asyncio.create_task(process.communicate())
    loop = asyncio.get_running_loop()
    deadline = loop.time() + float(timeout_seconds)
    tree_cleanup_attempted = False

    async def terminate_tree(*, cancelled: bool) -> dict[str, Any]:
        nonlocal tree_cleanup_attempted
        tree_cleanup_attempted = True
        stdout, stderr, process_tree = await terminate_process_tree(
            process,
            communicate_task,
            grace_seconds=max(0.01, float(cancellation_grace_seconds)),
        )
        return {
            "returncode": process.returncode,
            "stdout": stdout.decode("utf-8", errors="replace")[-4000:],
            "stderr": stderr.decode("utf-8", errors="replace")[-4000:],
            "command": list(command),
            "cancelled": cancelled,
            "termination": process_tree["termination"],
            "process_tree": process_tree,
        }

    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                result = await terminate_tree(cancelled=False)
                raise AutomaticExperimentSubprocessFailure(
                    (
                        f"Automatic experiment command timed out after {timeout_seconds} seconds; "
                        f"termination={result['termination']}; "
                        f"tree_verified={result['process_tree']['tree_termination_verified']}"
                    ),
                    result,
                )
            done, _pending = await asyncio.wait(
                {communicate_task},
                timeout=min(max(0.01, float(cancellation_poll_seconds)), remaining),
            )
            if communicate_task in done:
                stdout, stderr = communicate_task.result()
                result = {
                    "returncode": int(process.returncode or 0),
                    "stdout": stdout.decode("utf-8", errors="replace")[-4000:],
                    "stderr": stderr.decode("utf-8", errors="replace")[-4000:],
                    "command": list(command),
                    "cancelled": False,
                    "termination": None,
                    "process_tree": {
                        "scope": "isolated_process_tree",
                        "root_pid": int(process.pid),
                        "tree_termination_verified": None,
                    },
                }
                if process.returncode != 0:
                    result = await terminate_tree(cancelled=False)
                    raise AutomaticExperimentSubprocessFailure(
                        (
                            "Automatic experiment command failed: "
                            f"returncode={process.returncode}; stderr={result['stderr']}"
                        ),
                        result,
                    )
                return result
            if cancellation_probe is not None:
                claim = await cancellation_probe()
                if claim is not None:
                    result = await terminate_tree(cancelled=True)
                    raise AutomaticExperimentCancelled(claim, result)
    except (AutomaticExperimentCancelled, AutomaticExperimentSubprocessFailure):
        raise
    except asyncio.CancelledError:
        if not tree_cleanup_attempted:
            await terminate_tree(cancelled=False)
        raise
    except BaseException as exc:
        if not tree_cleanup_attempted:
            result = await terminate_tree(cancelled=False)
            if isinstance(exc, Exception):
                raise AutomaticExperimentSubprocessFailure(
                    (
                        "Automatic experiment command aborted after an internal control failure: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                    result,
                ) from exc
        raise


def _candidate_contract(candidate: ModelRegistry, settings: Settings) -> tuple[Path, str, int]:
    artifact_path = str(candidate.artifact_path or "").strip()
    if not artifact_path:
        raise ValueError("Automatic experiment candidate has no artifact path")
    path = Path(artifact_path).expanduser()
    path = ((_PROJECT_ROOT / path) if not path.is_absolute() else path).resolve()
    if not path.is_file():
        raise ValueError(f"Automatic experiment artifact does not exist: {path}")
    digest = str(candidate.artifact_sha256 or "").strip().lower()
    if not _SHA256.fullmatch(digest):
        raise ValueError("Automatic experiment candidate artifact SHA-256 is invalid")
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("Automatic experiment candidate artifact SHA-256 mismatch")
    metrics = candidate.metrics if isinstance(candidate.metrics, dict) else {}
    raw_horizon = metrics.get("horizon_hours")
    if isinstance(raw_horizon, bool):
        raw_horizon = None
    try:
        horizon = int(raw_horizon)
    except (TypeError, ValueError) as exc:
        raise ValueError("Automatic experiment candidate horizon is invalid") from exc
    if horizon != settings.default_horizon_hours:
        raise ValueError("Automatic experiment candidate horizon does not match deployment settings")
    return path, digest, horizon


async def _load_progress(
    family: str,
    specification: Mapping[str, Any],
    preregistration_record_hash: str,
) -> dict[str, Any]:
    async with SessionFactory() as session:
        evidence, counts = await load_experiment_family_evidence(
            session,
            experiment_family=family,
            preregistration_spec=specification,
            preregistration_record_hash=preregistration_record_hash,
        )
    attempted = Counter(evidence.attempted_configuration_hashes)
    successful = {item.configuration_hash for item in evidence.successful_trials}
    failed = Counter(evidence.failed_configuration_hashes)
    return {
        "attempted": attempted,
        "successful": successful,
        "failed": failed,
        "open_trials": list(evidence.open_trial_ids),
        "event_count": counts["event_count"],
        "specification": specification,
    }


async def recover_stale_automatic_experiment_attempts(
    *,
    experiment_family: str,
    timeout_seconds: int,
    now: datetime | None = None,
) -> list[str]:
    """Close append-only STARTED trials that outlived the subprocess timeout."""

    current = (now or datetime.now(UTC)).astimezone(UTC)
    cutoff = current - timedelta(seconds=int(timeout_seconds))
    closed: list[str] = []
    async with SessionFactory() as session, session.begin():
        rows = list(
            (
                await session.execute(
                    select(ResearchExperimentEvent)
                    .where(ResearchExperimentEvent.experiment_family == experiment_family)
                    .order_by(
                        ResearchExperimentEvent.trial_id,
                        ResearchExperimentEvent.event_sequence,
                    )
                    .with_for_update()
                )
            ).scalars()
        )
        grouped: dict[object, list[ResearchExperimentEvent]] = {}
        for row in rows:
            if not verify_experiment_event_integrity(row):
                raise ValueError(
                    f"Automatic experiment ledger hash mismatch for event {row.id}"
                )
            grouped.setdefault(row.trial_id, []).append(row)
        for trial_id, events in grouped.items():
            if len(events) != 1:
                continue
            started = events[0]
            if started.event_sequence != 0 or started.event_type != "STARTED":
                raise ValueError(f"Automatic experiment trial {trial_id} has an invalid open state")
            observed_at = started.observed_at
            if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                raise ValueError(f"Automatic experiment trial {trial_id} has a naive timestamp")
            if observed_at.astimezone(UTC) > cutoff:
                continue
            await append_experiment_event(
                session,
                trial_id=started.trial_id,
                experiment_family=experiment_family,
                event_type="FAILED",
                observed_at=current,
                configuration=started.configuration,
                evidence={
                    "error_type": "AutomaticExperimentStaleTrial",
                    "error_message": (
                        "STARTED trial exceeded the configured subprocess timeout and was "
                        "closed by the automatic experiment reconciler"
                    ),
                    "automatic_recovery": True,
                    "timeout_seconds": int(timeout_seconds),
                },
            )
            closed.append(str(started.trial_id))
    return closed


async def fail_open_automatic_experiment_attempts(
    *,
    experiment_family: str,
    configuration_hash: str,
    error_type: str,
    error_message: str,
    evidence_extra: Mapping[str, Any] | None = None,
) -> list[str]:
    """Append FAILED terminals for child trials left open by an aborted process."""

    closed: list[str] = []
    async with SessionFactory() as session, session.begin():
        rows = list(
            (
                await session.execute(
                    select(ResearchExperimentEvent)
                    .where(
                        ResearchExperimentEvent.experiment_family == experiment_family,
                        ResearchExperimentEvent.configuration_hash == configuration_hash,
                    )
                    .order_by(
                        ResearchExperimentEvent.trial_id,
                        ResearchExperimentEvent.event_sequence,
                    )
                    .with_for_update()
                )
            ).scalars()
        )
        grouped: dict[object, list[ResearchExperimentEvent]] = {}
        for row in rows:
            if not verify_experiment_event_integrity(row):
                raise ValueError(
                    f"Automatic experiment ledger hash mismatch for event {row.id}"
                )
            grouped.setdefault(row.trial_id, []).append(row)
        for trial_id, events in grouped.items():
            if len(events) != 1:
                continue
            started = events[0]
            if started.event_sequence != 0 or started.event_type != "STARTED":
                raise ValueError(f"Automatic experiment trial {trial_id} has an invalid open state")
            await append_experiment_event(
                session,
                trial_id=started.trial_id,
                experiment_family=experiment_family,
                event_type="FAILED",
                observed_at=datetime.now(UTC),
                configuration=started.configuration,
                evidence={
                    "error_type": str(error_type)[:160],
                    "error_message": str(error_message)[:500],
                    "automatic_recovery": True,
                    **json_compatible(dict(evidence_extra or {})),
                },
            )
            closed.append(str(started.trial_id))
    return closed


def _configuration_from_spec(
    specification: Mapping[str, Any],
    selected: Mapping[str, Any],
) -> dict[str, Any]:
    contract = specification.get("configuration_contract")
    if not isinstance(contract, Mapping):
        raise ValueError("Automatic preregistration contract is missing")
    fixed = contract.get("fixed_parameters")
    if not isinstance(fixed, Mapping):
        raise ValueError("Automatic preregistration fixed parameters are missing")
    return json_compatible({**dict(fixed), **dict(selected)})


async def _publish_automatic_experiment_status(
    callback: StatusCallback | None,
    payload: Mapping[str, Any],
) -> None:
    if callback is not None:
        await callback(json_compatible(dict(payload)))


async def orchestrate_automatic_experiment(
    candidate: ModelRegistry,
    *,
    settings: Settings,
    actor: str,
    command_runner: CommandRunner | None = None,
    status_callback: StatusCallback | None = None,
) -> dict[str, Any]:
    if not settings.auto_train_auto_experiment:
        return {"status": "WAITING", "reason": "automatic_experiment_disabled"}
    path, digest, horizon = _candidate_contract(candidate, settings)
    plan = automatic_experiment_plan(
        settings,
        model_version=candidate.version,
        model_sha256=digest,
    )
    family = str(plan["experiment_family"])
    lock = lock_key("automatic_model_experiment", family)
    configuration_count = len(plan["configurations"])
    started_at = datetime.now(UTC).isoformat()

    async def publish(
        status: str,
        stage: str,
        *,
        subprocess_active: bool,
        **extra: Any,
    ) -> None:
        await _publish_automatic_experiment_status(
            status_callback,
            {
                "schema": AUTOMATIC_EXPERIMENT_SCHEMA,
                "status": status,
                "stage": stage,
                "subprocess_active": subprocess_active,
                "experiment_family": family,
                "candidate_version": candidate.version,
                "plan_hash": plan["plan_hash"],
                "configuration_count": configuration_count,
                "started_at": started_at,
                "updated_at": datetime.now(UTC).isoformat(),
                **extra,
            },
        )

    async def cancellation_probe() -> ExperimentCancelClaim | None:
        return await claim_automatic_experiment_cancel(
            experiment_family=family,
            candidate_version=candidate.version,
            accepted_by=actor,
        )

    if command_runner is None:
        async def runner(command: Sequence[str], cwd: Path, timeout: int) -> dict[str, Any]:
            return await _run_subprocess(
                command,
                cwd,
                timeout,
                cancellation_probe=cancellation_probe,
            )
    else:
        runner = command_runner

    async def cancelled_result(
        exc: AutomaticExperimentCancelled,
        *,
        stage: str,
        configuration_hash: str | None = None,
        configuration_index: int | None = None,
    ) -> dict[str, Any]:
        closed_trial_ids: list[str] = []
        if configuration_hash is not None:
            closed_trial_ids = await fail_open_automatic_experiment_attempts(
                experiment_family=family,
                configuration_hash=configuration_hash,
                error_type="OperatorCancelledExperiment",
                error_message=(
                    "Authenticated operator cancelled the exact running automatic experiment "
                    "subprocess; preregistration and prior trial evidence were preserved"
                ),
                evidence_extra={
                    "operator_cancelled": True,
                    "cancel_request_id": str(exc.claim.request_id),
                    "requested_by": exc.claim.requested_by,
                    "requested_at": exc.claim.requested_at,
                    "candidate_version": candidate.version,
                    "experiment_family": family,
                    "termination": exc.process_result.get("termination"),
                    "process_tree": exc.process_result.get("process_tree"),
                },
            )
        result = json_compatible(
            {
                "status": "CANCELLED",
                "reason": "automatic_experiment_cancelled_by_operator",
                "schema": AUTOMATIC_EXPERIMENT_SCHEMA,
                "experiment_family": family,
                "candidate_version": candidate.version,
                "stage": stage,
                "configuration_hash": configuration_hash,
                "configuration_index": configuration_index,
                "configuration_count": configuration_count,
                "closed_trial_ids": closed_trial_ids,
                "cancel_request_id": str(exc.claim.request_id),
                "requested_by": exc.claim.requested_by,
                "requested_at": exc.claim.requested_at,
                "cancelled_at": datetime.now(UTC).isoformat(),
                "termination": exc.process_result.get("termination"),
                "returncode": exc.process_result.get("returncode"),
                "process_tree": exc.process_result.get("process_tree"),
            }
        )
        cancellation_gate = {
            "schema": "automatic-experiment-failure-gate-v1",
            "passed": False,
            "report_status": "AUTOMATIC_EXPERIMENT_OPERATOR_CANCELLED",
            "reasons": ["automatic_experiment_cancelled_by_operator"],
            "experiment_family": family,
            "cancel_request_id": str(exc.claim.request_id),
            "requested_by": exc.claim.requested_by,
            "closed_trial_ids": closed_trial_ids,
            "process_tree": exc.process_result.get("process_tree"),
        }
        result["closure"] = await close_candidate_activation_request(
            candidate_version=candidate.version,
            experiment_family=family,
            experiment_gate=cancellation_gate,
            actor=actor,
        )
        result["control_request_completed"] = await finish_automatic_experiment_cancel(
            exc.claim,
            status="SUCCESS",
            result={
                "action": "CANCEL_EXPERIMENT",
                "cancelled": True,
                "experiment_family": family,
                "candidate_version": candidate.version,
                "stage": stage,
                "configuration_hash": configuration_hash,
                "closed_trial_ids": closed_trial_ids,
                "termination": exc.process_result.get("termination"),
                "returncode": exc.process_result.get("returncode"),
                "process_tree": exc.process_result.get("process_tree"),
            },
            actor=actor,
        )
        await publish(
            "CANCELLED",
            stage,
            subprocess_active=False,
            configuration_hash=configuration_hash,
            configuration_index=configuration_index,
            closed_trial_ids=closed_trial_ids,
            cancel_request_id=str(exc.claim.request_id),
            requested_by=exc.claim.requested_by,
            termination=exc.process_result.get("termination"),
            process_tree=exc.process_result.get("process_tree"),
        )
        return result

    await publish("PREPARING", "acquiring_lock", subprocess_active=False)
    async with engine.connect() as connection:
        acquired = bool(
            (
                await connection.execute(
                    text("SELECT pg_try_advisory_lock(:key)"),
                    {"key": lock},
                )
            ).scalar()
        )
        await connection.commit()
        if not acquired:
            result = {
                "status": "WAITING",
                "reason": "automatic_experiment_lock_held",
                "experiment_family": family,
                "candidate_version": candidate.version,
            }
            await publish("WAITING", "lock_held", subprocess_active=False)
            return result
        try:
            workdir = _PROJECT_ROOT / "reports" / "automatic-experiments" / family
            workdir.mkdir(parents=True, exist_ok=True)
            template_path = workdir / "preregistration-template.json"
            specification_path = workdir / "preregistration.json"

            async with SessionFactory() as session:
                registration = await load_experiment_preregistration(
                    session,
                    experiment_family=family,
                )
            if registration is None:
                prepare_command = [
                    sys.executable,
                    "-m",
                    "scripts.backtest",
                    "--model",
                    str(path),
                    "--model-sha256",
                    digest,
                    "--horizon",
                    str(horizon),
                    "--experiment-family",
                    family,
                    "--prepare-preregistration",
                    str(template_path),
                ]
                for parameter in _SEARCH_PARAMETERS:
                    prepare_command.extend(("--search-parameter", parameter))
                await publish(
                    "PREPARING",
                    "prepare_preregistration",
                    subprocess_active=True,
                )
                try:
                    await runner(
                        prepare_command,
                        _PROJECT_ROOT,
                        settings.auto_train_experiment_timeout_seconds,
                    )
                except AutomaticExperimentCancelled as exc:
                    return await cancelled_result(exc, stage="prepare_preregistration")
                except AutomaticExperimentSubprocessFailure as exc:
                    await publish(
                        "FAILED",
                        "prepare_preregistration",
                        subprocess_active=False,
                        error_type=type(exc).__name__,
                        termination=exc.process_result.get("termination"),
                        process_tree=exc.process_result.get("process_tree"),
                    )
                    raise
                await publish(
                    "PREPARING",
                    "register_preregistration",
                    subprocess_active=False,
                )
                raw_template = json.loads(template_path.read_text(encoding="utf-8"))
                if not isinstance(raw_template, dict):
                    raise ValueError("Automatic preregistration template must be a JSON object")
                specification = finalize_automatic_preregistration(
                    raw_template,
                    plan=plan,
                    model_version=candidate.version,
                    model_sha256=digest,
                )
                specification_path.write_text(
                    json.dumps(specification, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                async with SessionFactory() as session, session.begin():
                    registration = await register_experiment_family(
                        session,
                        experiment_family=family,
                        registered_at=datetime.now(UTC),
                        specification=specification,
                        release_version=__version__,
                    )
            else:
                specification = normalize_preregistration_spec(
                    registration.specification,
                    expected_family=family,
                )

            progress = await _load_progress(family, specification, registration.record_hash)
            recovered_stale_trial_ids: list[str] = []
            if progress["open_trials"]:
                recovered_stale_trial_ids = await recover_stale_automatic_experiment_attempts(
                    experiment_family=family,
                    timeout_seconds=settings.auto_train_experiment_timeout_seconds,
                )
                if recovered_stale_trial_ids:
                    progress = await _load_progress(
                        family,
                        specification,
                        registration.record_hash,
                    )
            if progress["open_trials"]:
                result = {
                    "status": "WAITING",
                    "reason": "automatic_experiment_open_trial",
                    "experiment_family": family,
                    "candidate_version": candidate.version,
                    "open_trial_ids": progress["open_trials"],
                    "recovered_stale_trial_ids": recovered_stale_trial_ids,
                }
                await publish(
                    "WAITING",
                    "open_trial_reconciliation",
                    subprocess_active=False,
                    open_trial_ids=progress["open_trials"],
                )
                return result

            executed = 0
            skipped = 0
            for index, selected in enumerate(plan["configurations"], start=1):
                configuration = _configuration_from_spec(specification, selected)
                configuration_hash = experiment_configuration_hash(configuration)
                if configuration_hash in progress["successful"]:
                    skipped += 1
                    continue
                attempts = int(progress["attempted"].get(configuration_hash, 0))
                if attempts >= settings.auto_train_experiment_max_attempts_per_configuration:
                    result = {
                        "status": "REJECTED",
                        "reason": "automatic_experiment_retry_exhausted",
                        "experiment_family": family,
                        "candidate_version": candidate.version,
                        "configuration_hash": configuration_hash,
                        "attempts": attempts,
                    }
                    await publish(
                        "REJECTED",
                        "retry_exhausted",
                        subprocess_active=False,
                        configuration_hash=configuration_hash,
                        configuration_index=index,
                        attempts=attempts,
                    )
                    return result
                output = workdir / f"trial-{index:02d}-{configuration_hash[:12]}.json"
                trial_command = [
                    sys.executable,
                    "-m",
                    "scripts.backtest",
                    "--model",
                    str(path),
                    "--model-sha256",
                    digest,
                    "--horizon",
                    str(horizon),
                    "--experiment-family",
                    family,
                    "--minimum-net-rr",
                    str(selected["minimum_net_rr"]),
                    "--minimum-net-ev-r",
                    str(selected["minimum_net_ev_r"]),
                    "--output",
                    str(output),
                ]
                await publish(
                    "RUNNING",
                    "formal_backtest",
                    subprocess_active=True,
                    configuration_index=index,
                    configuration_hash=configuration_hash,
                    configuration=selected,
                    attempt=attempts + 1,
                    completed_configuration_count=skipped + executed,
                )
                try:
                    await runner(
                        trial_command,
                        _PROJECT_ROOT,
                        settings.auto_train_experiment_timeout_seconds,
                    )
                except AutomaticExperimentCancelled as exc:
                    return await cancelled_result(
                        exc,
                        stage="formal_backtest",
                        configuration_hash=configuration_hash,
                        configuration_index=index,
                    )
                except Exception as exc:
                    process_result = getattr(exc, "process_result", None)
                    process_tree = (
                        process_result.get("process_tree")
                        if isinstance(process_result, Mapping)
                        else None
                    )
                    await fail_open_automatic_experiment_attempts(
                        experiment_family=family,
                        configuration_hash=configuration_hash,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                        evidence_extra={
                            "termination": (
                                process_result.get("termination")
                                if isinstance(process_result, Mapping)
                                else None
                            ),
                            "process_tree": process_tree,
                        },
                    )
                    await publish(
                        "FAILED",
                        "formal_backtest",
                        subprocess_active=False,
                        configuration_index=index,
                        configuration_hash=configuration_hash,
                        error_type=type(exc).__name__,
                        process_tree=process_tree,
                    )
                    raise
                executed += 1
                await publish(
                    "RUNNING",
                    "verify_trial_terminal",
                    subprocess_active=False,
                    configuration_index=index,
                    configuration_hash=configuration_hash,
                    completed_configuration_count=skipped + executed,
                )
                progress = await _load_progress(family, specification, registration.record_hash)
                if progress["open_trials"]:
                    closed_missing_terminal = await fail_open_automatic_experiment_attempts(
                        experiment_family=family,
                        configuration_hash=configuration_hash,
                        error_type="AutomaticExperimentMissingTerminal",
                        error_message=(
                            "Backtest subprocess exited successfully without a terminal ledger event"
                        ),
                    )
                    result = {
                        "status": "WAITING",
                        "reason": "automatic_experiment_missing_terminal_event",
                        "experiment_family": family,
                        "candidate_version": candidate.version,
                        "open_trial_ids": progress["open_trials"],
                        "closed_open_trial_ids": closed_missing_terminal,
                    }
                    await publish(
                        "WAITING",
                        "missing_terminal_event",
                        subprocess_active=False,
                        configuration_index=index,
                        configuration_hash=configuration_hash,
                        closed_open_trial_ids=closed_missing_terminal,
                    )
                    return result

            await publish(
                "FINALIZING",
                "governance_report",
                subprocess_active=False,
                completed_configuration_count=skipped + executed,
            )
            async with SessionFactory() as session:
                report = await experiment_governance_report(
                    session,
                    experiment_family=family,
                )
            result = json_compatible(
                {
                    "status": "COMPLETE",
                    "schema": AUTOMATIC_EXPERIMENT_SCHEMA,
                    "experiment_family": family,
                    "candidate_version": candidate.version,
                    "plan_hash": plan["plan_hash"],
                    "configuration_count": configuration_count,
                    "executed_configuration_count": executed,
                    "already_successful_configuration_count": skipped,
                    "recovered_stale_trial_ids": recovered_stale_trial_ids,
                    "report_status": report.get("status"),
                    "report": report,
                    "actor": actor,
                }
            )
            await publish(
                "COMPLETE",
                "governance_report_complete",
                subprocess_active=False,
                completed_configuration_count=skipped + executed,
                report_status=report.get("status"),
            )
            return result
        finally:
            await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock})
            await connection.commit()


def experiment_gate_is_terminal(gate: Mapping[str, Any]) -> bool:
    report_status = str(gate.get("report_status") or "")
    if report_status in _TERMINAL_REPORT_STATUSES:
        return True
    reasons = gate.get("reasons")
    return isinstance(reasons, list) and any(
        isinstance(item, str) and item.startswith("selected_trial_policy_mismatch:")
        for item in reasons
    )


async def close_candidate_activation_request(
    *,
    candidate_version: str,
    experiment_family: str | None,
    experiment_gate: Mapping[str, Any],
    actor: str,
) -> dict[str, Any]:
    async with SessionFactory() as session, session.begin():
        candidate = (
            await session.execute(
                select(ModelRegistry)
                .where(ModelRegistry.version == candidate_version)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if candidate is None:
            raise RuntimeError(f"Model candidate not found: {candidate_version}")
        metrics = dict(candidate.metrics) if isinstance(candidate.metrics, dict) else {}
        if candidate.active:
            return {"status": "IGNORED_ACTIVE", "candidate_version": candidate_version}
        if metrics.get("activation_requested") is not True:
            return {"status": "ALREADY_CLOSED", "candidate_version": candidate_version}
        terminal = {
            "schema": AUTOMATIC_EXPERIMENT_TERMINAL_SCHEMA,
            "experiment_family": experiment_family,
            "closed_at": datetime.now(UTC).isoformat(),
            "report_status": experiment_gate.get("report_status"),
            "reasons": json_compatible(experiment_gate.get("reasons") or []),
        }
        metrics["activation_requested"] = False
        metrics["experiment_promotion_gate"] = json_compatible(dict(experiment_gate))
        metrics["automatic_experiment_terminal"] = terminal
        candidate.metrics = json_compatible(metrics)
        await append_audit_event(
            session,
            event_type="MODEL_CANDIDATE_PROMOTION_REJECTED",
            entity_type="model_registry",
            entity_id=str(candidate.id),
            actor=actor,
            payload={"version": candidate.version, **terminal},
        )
        await publish_outbox(
            session,
            event_type="MODEL_CANDIDATE_PROMOTION_REJECTED",
            aggregate_type="model_registry",
            aggregate_id=str(candidate.id),
            payload={"version": candidate.version, "experiment_family": experiment_family},
        )
        return {"status": "CLOSED", "candidate_version": candidate_version, **terminal}

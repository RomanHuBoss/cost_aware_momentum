from __future__ import annotations

import asyncio
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.automatic_experiment import (
    AutomaticExperimentCancelled,
    AutomaticExperimentSubprocessFailure,
    _run_subprocess,
)
from app.services.process_tree import (
    PROCESS_TREE_TERMINATION_SCHEMA,
    process_tree_spawn_kwargs,
    terminate_process_tree,
    windows_taskkill_command,
)
from app.services.trainer_control import ExperimentCancelClaim


def _claim() -> ExperimentCancelClaim:
    return ExperimentCancelClaim(
        request_id=uuid4(),
        claim_token="claim-token",
        requested_by="operator",
        requested_at=datetime.now(UTC).isoformat(),
        experiment_family="auto-process-tree-family",
        candidate_version="candidate-process-tree",
    )


def _descendant_command(pid_file: Path) -> list[str]:
    child = (
        "import pathlib, subprocess, sys, time; "
        "p=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        "pathlib.Path(sys.argv[1]).write_text(str(p.pid), encoding='utf-8'); "
        "time.sleep(60)"
    )
    return [sys.executable, "-c", child, str(pid_file)]


def _effectively_alive(pid: int) -> bool:
    stat = Path(f"/proc/{pid}/stat")
    if stat.exists():
        fields = stat.read_text(encoding="utf-8", errors="replace").split()
        return len(fields) >= 3 and fields[2] != "Z"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def _wait_for_pid_file(pid_file: Path, timeout: float = 3.0) -> int:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if pid_file.exists() and pid_file.read_text(encoding="utf-8").strip():
            return int(pid_file.read_text(encoding="utf-8").strip())
        await asyncio.sleep(0.02)
    raise AssertionError("descendant pid file was not created")


async def _assert_terminated(pid: int, timeout: float = 3.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if not _effectively_alive(pid):
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"descendant process {pid} survived process-tree termination")


def _cleanup(pid: int | None) -> None:
    if pid is None or not _effectively_alive(pid):
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def test_process_tree_spawn_contract_is_cross_platform_and_fail_closed() -> None:
    assert process_tree_spawn_kwargs("posix") == {"start_new_session": True}
    windows = process_tree_spawn_kwargs("nt")
    assert int(windows["creationflags"]) & 0x00000200
    with pytest.raises(RuntimeError, match="Unsupported operating system"):
        process_tree_spawn_kwargs("unknown")


def test_windows_taskkill_contract_targets_descendant_tree() -> None:
    assert windows_taskkill_command(4321, force=False) == [
        "taskkill.exe",
        "/PID",
        "4321",
        "/T",
    ]
    assert windows_taskkill_command(4321, force=True) == [
        "taskkill.exe",
        "/PID",
        "4321",
        "/T",
        "/F",
    ]


@pytest.mark.asyncio
async def test_windows_termination_branch_uses_tree_taskkill_and_records_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import process_tree as process_tree_module

    calls: list[tuple[int, bool]] = []

    async def fake_taskkill(pid: int, *, force: bool) -> dict[str, object]:
        calls.append((pid, force))
        return {
            "command": windows_taskkill_command(pid, force=force),
            "returncode": 0,
            "stdout": "terminated",
            "stderr": "",
        }

    monkeypatch.setattr(process_tree_module, "_run_taskkill", fake_taskkill)
    communicate_task = asyncio.create_task(asyncio.sleep(0, result=(b"out", b"err")))
    process = SimpleNamespace(pid=4321, kill=lambda: None)

    stdout, stderr, evidence = await terminate_process_tree(
        process,
        communicate_task,
        grace_seconds=0.1,
        os_name="nt",
    )

    assert (stdout, stderr) == (b"out", b"err")
    assert calls == [(4321, False)]
    assert evidence["scope"] == "process_tree"
    assert evidence["termination"] == "taskkill_tree"
    assert evidence["tree_termination_verified"] is True


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux process-group proof")
@pytest.mark.asyncio
async def test_operator_cancel_terminates_the_descendant_process_group(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    descendant_pid: int | None = None

    async def cancellation_probe() -> ExperimentCancelClaim | None:
        nonlocal descendant_pid
        if not pid_file.exists():
            return None
        descendant_pid = await _wait_for_pid_file(pid_file)
        return _claim()

    try:
        with pytest.raises(AutomaticExperimentCancelled) as captured:
            await _run_subprocess(
                _descendant_command(pid_file),
                tmp_path,
                10,
                cancellation_probe=cancellation_probe,
                cancellation_poll_seconds=0.02,
                cancellation_grace_seconds=0.2,
            )
        assert descendant_pid is not None
        await _assert_terminated(descendant_pid)
        tree = captured.value.process_result["process_tree"]
        assert tree["schema"] == PROCESS_TREE_TERMINATION_SCHEMA
        assert tree["scope"] == "process_group"
        assert tree["tree_termination_verified"] is True
    finally:
        _cleanup(descendant_pid)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux process-group proof")
@pytest.mark.asyncio
async def test_timeout_terminates_the_descendant_process_group(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild-timeout.pid"
    descendant_pid: int | None = None
    try:
        task = asyncio.create_task(
            _run_subprocess(
                _descendant_command(pid_file),
                tmp_path,
                3,
                cancellation_poll_seconds=0.02,
                cancellation_grace_seconds=0.2,
            )
        )
        descendant_pid = await _wait_for_pid_file(pid_file)
        with pytest.raises(AutomaticExperimentSubprocessFailure, match="timed out") as captured:
            await task
        await _assert_terminated(descendant_pid)
        assert captured.value.process_result["process_tree"]["tree_termination_verified"] is True
    finally:
        _cleanup(descendant_pid)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux process-group proof")
@pytest.mark.asyncio
async def test_probe_failure_cleanup_terminates_the_descendant_process_group(
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "grandchild-probe-error.pid"
    descendant_pid: int | None = None

    class ProbeFailure(RuntimeError):
        pass

    async def failing_probe() -> ExperimentCancelClaim | None:
        nonlocal descendant_pid
        if not pid_file.exists():
            return None
        descendant_pid = await _wait_for_pid_file(pid_file)
        raise ProbeFailure("probe failed after descendant started")

    try:
        with pytest.raises(
            AutomaticExperimentSubprocessFailure,
            match="internal control failure",
        ) as captured:
            await _run_subprocess(
                _descendant_command(pid_file),
                tmp_path,
                10,
                cancellation_probe=failing_probe,
                cancellation_poll_seconds=0.02,
                cancellation_grace_seconds=0.2,
            )
        assert descendant_pid is not None
        assert isinstance(captured.value.__cause__, ProbeFailure)
        await _assert_terminated(descendant_pid)
    finally:
        _cleanup(descendant_pid)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux process-group proof")
@pytest.mark.asyncio
async def test_nonzero_root_exit_cleans_up_a_surviving_descendant(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild-nonzero.pid"
    descendant_pid: int | None = None
    child = (
        "import pathlib, subprocess, sys; "
        "p=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        "pathlib.Path(sys.argv[1]).write_text(str(p.pid), encoding='utf-8'); "
        "raise SystemExit(7)"
    )
    try:
        task = asyncio.create_task(
            _run_subprocess(
                [sys.executable, "-c", child, str(pid_file)],
                tmp_path,
                10,
                cancellation_poll_seconds=0.02,
                cancellation_grace_seconds=0.2,
            )
        )
        descendant_pid = await _wait_for_pid_file(pid_file)
        with pytest.raises(AutomaticExperimentSubprocessFailure, match="returncode=7") as captured:
            await task
        await _assert_terminated(descendant_pid)
        assert captured.value.process_result["process_tree"]["tree_termination_verified"] is True
    finally:
        _cleanup(descendant_pid)

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import Any

PROCESS_TREE_TERMINATION_SCHEMA = "subprocess-tree-termination-v1"
_WINDOWS_CREATE_NEW_PROCESS_GROUP = 0x00000200


def process_tree_spawn_kwargs(os_name: str | None = None) -> dict[str, Any]:
    """Return fail-closed subprocess options that isolate the spawned work tree."""

    platform = os.name if os_name is None else str(os_name)
    if platform == "posix":
        return {"start_new_session": True}
    if platform == "nt":
        return {
            "creationflags": int(
                getattr(
                    subprocess,
                    "CREATE_NEW_PROCESS_GROUP",
                    _WINDOWS_CREATE_NEW_PROCESS_GROUP,
                )
            )
        }
    raise RuntimeError(f"Unsupported operating system for process-tree containment: {platform}")


def windows_taskkill_command(pid: int, *, force: bool) -> list[str]:
    if int(pid) <= 0:
        raise ValueError("Process id must be positive")
    command = ["taskkill.exe", "/PID", str(int(pid)), "/T"]
    if force:
        command.append("/F")
    return command


def _linux_group_has_live_members(process_group_id: int) -> bool | None:
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return None
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "stat").read_text(encoding="utf-8", errors="replace")
            suffix = raw[raw.rfind(")") + 2 :].split()
            state = suffix[0]
            process_group = int(suffix[2])
        except (FileNotFoundError, IndexError, PermissionError, ValueError):
            continue
        if process_group == process_group_id and state != "Z":
            return True
    return False


def _posix_group_has_live_members(process_group_id: int) -> tuple[bool, str]:
    linux_result = _linux_group_has_live_members(process_group_id)
    if linux_result is not None:
        return linux_result, "linux_proc_process_group"
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False, "killpg_zero"
    except PermissionError:
        return True, "killpg_zero"
    return True, "killpg_zero"


async def _wait_for_communicate(
    communicate_task: asyncio.Task[tuple[bytes, bytes]],
    timeout: float,
) -> tuple[bytes, bytes] | None:
    try:
        return await asyncio.wait_for(
            asyncio.shield(communicate_task),
            timeout=max(0.01, float(timeout)),
        )
    except TimeoutError:
        return None


async def _wait_for_posix_group_exit(
    process_group_id: int,
    timeout: float,
) -> tuple[bool, str]:
    deadline = asyncio.get_running_loop().time() + max(0.01, float(timeout))
    method = "unknown"
    while True:
        alive, method = _posix_group_has_live_members(process_group_id)
        if not alive:
            return True, method
        if asyncio.get_running_loop().time() >= deadline:
            return False, method
        await asyncio.sleep(0.02)


async def _run_taskkill(pid: int, *, force: bool) -> dict[str, Any]:
    command = windows_taskkill_command(pid, force=force)
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        return {
            "command": command,
            "returncode": None,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
        }
    stdout, stderr = await process.communicate()
    return {
        "command": command,
        "returncode": process.returncode,
        "stdout": stdout.decode("utf-8", errors="replace")[-2000:],
        "stderr": stderr.decode("utf-8", errors="replace")[-2000:],
    }


async def _terminate_posix_process_group(
    process: asyncio.subprocess.Process,
    communicate_task: asyncio.Task[tuple[bytes, bytes]],
    *,
    grace_seconds: float,
) -> tuple[bytes, bytes, dict[str, Any]]:
    process_group_id = int(process.pid)
    graceful_sent = False
    force_sent = False
    try:
        os.killpg(process_group_id, signal.SIGTERM)
        graceful_sent = True
    except ProcessLookupError:
        pass

    streams = await _wait_for_communicate(communicate_task, grace_seconds)
    group_exited, verification_method = await _wait_for_posix_group_exit(
        process_group_id,
        min(max(0.05, float(grace_seconds)), 0.5),
    )
    if not group_exited:
        try:
            os.killpg(process_group_id, signal.SIGKILL)
            force_sent = True
        except ProcessLookupError:
            pass
        group_exited, verification_method = await _wait_for_posix_group_exit(
            process_group_id,
            max(1.0, float(grace_seconds)),
        )

    if streams is None:
        streams = await _wait_for_communicate(
            communicate_task,
            max(1.0, float(grace_seconds)),
        )
    if streams is None:
        raise RuntimeError("Process-group termination did not reap the direct child")
    if not group_exited:
        raise RuntimeError(
            f"Process group {process_group_id} still has live members after SIGKILL"
        )

    stdout, stderr = streams
    termination = "process_group_sigkill" if force_sent else "process_group_sigterm"
    return stdout, stderr, {
        "schema": PROCESS_TREE_TERMINATION_SCHEMA,
        "platform": "posix",
        "scope": "process_group",
        "root_pid": int(process.pid),
        "process_group_id": process_group_id,
        "spawn_isolation": "start_new_session",
        "graceful_action": "SIGTERM",
        "graceful_action_sent": graceful_sent,
        "force_action": "SIGKILL",
        "force_action_sent": force_sent,
        "termination": termination,
        "verification_method": verification_method,
        "tree_termination_verified": True,
    }


async def _terminate_windows_process_tree(
    process: asyncio.subprocess.Process,
    communicate_task: asyncio.Task[tuple[bytes, bytes]],
    *,
    grace_seconds: float,
) -> tuple[bytes, bytes, dict[str, Any]]:
    graceful = await _run_taskkill(int(process.pid), force=False)
    streams = await _wait_for_communicate(communicate_task, grace_seconds)
    force: dict[str, Any] | None = None
    if graceful.get("returncode") != 0 or streams is None:
        force = await _run_taskkill(int(process.pid), force=True)
        if streams is None:
            streams = await _wait_for_communicate(
                communicate_task,
                max(1.0, float(grace_seconds)),
            )
    verified = graceful.get("returncode") == 0 or (
        force is not None and force.get("returncode") == 0
    )
    if streams is None:
        with suppress(ProcessLookupError):
            process.kill()
        streams = await _wait_for_communicate(communicate_task, 1.0)
    if streams is None:
        raise RuntimeError("Windows process-tree termination did not reap the direct child")
    if not verified:
        raise RuntimeError(
            "Windows taskkill could not verify descendant-tree termination; "
            f"graceful={graceful}; force={force}"
        )
    stdout, stderr = streams
    return stdout, stderr, {
        "schema": PROCESS_TREE_TERMINATION_SCHEMA,
        "platform": "nt",
        "scope": "process_tree",
        "root_pid": int(process.pid),
        "process_group_id": int(process.pid),
        "spawn_isolation": "CREATE_NEW_PROCESS_GROUP",
        "graceful_action": "taskkill_/T",
        "graceful_result": graceful,
        "force_action": "taskkill_/T_/F",
        "force_result": force,
        "termination": "taskkill_tree_force" if force is not None else "taskkill_tree",
        "verification_method": "taskkill_exit_status",
        "tree_termination_verified": True,
    }


async def terminate_process_tree(
    process: asyncio.subprocess.Process,
    communicate_task: asyncio.Task[tuple[bytes, bytes]],
    *,
    grace_seconds: float,
    os_name: str | None = None,
) -> tuple[bytes, bytes, dict[str, Any]]:
    platform = os.name if os_name is None else str(os_name)
    if platform == "posix":
        return await _terminate_posix_process_group(
            process,
            communicate_task,
            grace_seconds=grace_seconds,
        )
    if platform == "nt":
        return await _terminate_windows_process_tree(
            process,
            communicate_task,
            grace_seconds=grace_seconds,
        )
    raise RuntimeError(f"Unsupported operating system for process-tree termination: {platform}")

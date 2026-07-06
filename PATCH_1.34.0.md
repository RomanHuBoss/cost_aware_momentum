# Patch 1.34.0 — Automatic-experiment process-tree containment

Date: 2026-07-06

## Problem

Release 1.33.0 allowed an authenticated operator to cancel the exact automatic experiment subprocess, but `_run_subprocess` terminated only the direct Python child. A child-created descendant with independent stdout/stderr could survive the parent's `terminate()`/`kill()` sequence and continue consuming resources or writing research evidence after the operator action had already been recorded as terminal.

The same direct-child cleanup was used for timeout and unexpected control-probe failure. A non-zero root process could also exit while leaving a sleeping descendant alive.

## Reproduction

A process regression was executed against the unmodified 1.33.0 archive:

1. The automatic experiment runner started a Python child.
2. The child started a grandchild that slept for 60 seconds and redirected its streams to `DEVNULL`.
3. An exact cancellation claim was returned.
4. The direct child exited.
5. The test verified the grandchild PID.

Result:

```text
AssertionError: grandchild 28366 survived old direct-child cancellation
1 failed
```

## Solution

- Added `app/services/process_tree.py`.
- POSIX subprocesses start with `start_new_session=True`; cleanup targets the complete process group with `SIGTERM` and bounded `SIGKILL` fallback.
- Linux verification scans `/proc` for live non-zombie members of the exact process group; other POSIX systems use `killpg(..., 0)` availability semantics.
- Windows subprocesses use `CREATE_NEW_PROCESS_GROUP`; cleanup invokes built-in `taskkill /PID <root> /T` and falls back to `/F`.
- Unknown operating systems fail before launching an uncontained formal backtest.
- Cancellation, timeout, non-zero root exit, internal cancellation-probe failure and task cancellation all use one cleanup path.
- Added `AutomaticExperimentSubprocessFailure` so timeout/runtime failures preserve structured process-tree evidence.
- Added schema `subprocess-tree-termination-v1` with platform, scope, root/group PID, graceful/force action, verification method and `tree_termination_verified`.
- Propagated evidence into append-only failed-trial evidence, cancellation control result, candidate terminal gate and trainer status.

## Compatibility

- No database migration.
- Alembic head remains `0016_universe_replay_asof`.
- No `.env` change.
- No HTTP API or frontend contract change.
- No model artifact, feature, label, risk, cost or activation-threshold change.
- No new dependency.

Existing active artifacts, preregistration records and experiment events remain valid.

## Verification

Baseline:

```text
684 passed, 7 skipped, 62 warnings
```

Targeted process-tree and operator-control tests:

```text
15 passed
```

Full post-change suite:

```text
691 passed, 7 skipped, 62 warnings
```

Static checks:

- `python -m pip check` — passed.
- `python -m compileall -q app scripts tests manage.py` — passed.
- `python -m ruff check .` — passed.
- `node --check web/js/app.js` — passed.
- `python -m alembic heads` — one head, `0016_universe_replay_asof`.

## Limitations

- The Linux runtime proof covers descendants that inherit the formal subprocess process group.
- A deliberately detached POSIX process that invokes `setsid()` or otherwise creates a different session/process group is outside this guarantee.
- The Windows branch is covered by unit contracts for `CREATE_NEW_PROCESS_GROUP`, `taskkill /T` and evidence propagation, but was not run on an actual Windows host.
- PostgreSQL integration tests remain skipped without `TEST_DATABASE_URL`.
- This patch changes operational containment only and does not establish strategy profitability.

# QA Report

Release: **1.34.0**

Date: **2026-07-06**
Scope: **automatic-experiment process-tree containment**

## Environment

- Python: 3.13.5 in an isolated virtual environment.
- Project requirement: Python >=3.12.
- Node syntax check available.
- Separate PostgreSQL integration database: not configured.
- Windows runner: not available.
- Input archive: `cost_aware_momentum-1.33.0-automatic-experiment-operator-control.zip`.
- Input archive SHA-256: `a4abefe4a3b54ebea572d8a6af70e50984f18865c60bcc9ac4c476ca0dc89266`.

## Baseline before changes

| Check | Result |
|---|---|
| source version | 1.33.0 |
| source inventory | 256 release files including manifest; 95 production Python files; 92 test Python files; 16 migration revisions; head `0016_universe_replay_asof` |
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | PASSED: no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 684 passed, 7 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | PASSED: one head, `0016_universe_replay_asof` |

## Confirmed defects/gap

1. Exact operator cancellation terminated only the direct Python child; a grandchild with detached streams survived and could continue research work after terminal cancellation evidence.
2. Timeout and internal control-probe cleanup reused the same direct-child-only logic.
3. A non-zero direct child could exit while a descendant remained alive because the old exception cleanup skipped an already-finished root process.
4. No explicit Windows descendant-tree spawn/termination contract existed.
5. Terminal cancellation/failure evidence did not disclose whether a tree-aware mechanism had been used or verified.

No model quality, PBO, DSR, dependence, cost-stress, risk, artifact or deployment-policy gate was lowered.

## Red evidence

Behavioral reproduction on the unmodified 1.33.0 archive:

```text
AssertionError: grandchild 28366 survived old direct-child cancellation
1 failed
```

Initial regression collection:

```text
ModuleNotFoundError: No module named 'app.services.process_tree'
1 collection error
```

## Added regression coverage

- POSIX subprocess isolation requires `start_new_session=True`.
- Windows subprocess isolation requires `CREATE_NEW_PROCESS_GROUP`.
- Unsupported platforms fail before spawn.
- Windows commands target descendants via `/T` and use `/F` fallback.
- Windows termination branch emits verified tree evidence under mocked host execution.
- A real Linux grandchild is absent after exact operator cancellation.
- A real Linux grandchild is absent after timeout.
- A real Linux grandchild is absent after control-probe failure.
- A real Linux grandchild is absent after non-zero root exit.
- Process-tree evidence reaches failed trial/candidate/control/status paths.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 691 passed, 7 skipped, 62 warnings |
| targeted process-tree/operator-control | PASSED: 15 passed |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | PASSED: one head, `0016_universe_replay_asof` |
| application/package version | PASSED: 1.34.0 |

## Environment-dependent checks

| Check | Result |
|---|---|
| direct PostgreSQL integration collection | SKIPPED: 7 tests; `TEST_DATABASE_URL` unavailable |
| exact cancel claim/finish against PostgreSQL | NOT RUN: no isolated PostgreSQL test database |
| concurrent API/trainer advisory-lock contention | NOT RUN |
| actual Windows `CREATE_NEW_PROCESS_GROUP` + `taskkill` | NOT RUN: no Windows host |
| intentionally detached POSIX `setsid()` descendant | NOT COVERED: outside process-group contract |
| `python manage.py doctor` | NOT RUN successfully: no project `.env`, PostgreSQL server or PostgreSQL command-line tools |
| `python manage.py test --require-integration` | NOT RUN: no isolated integration database |
| real Bybit forward cycle | NOT RUN |

## Release boundary

- Database migration: **none**; head remains `0016_universe_replay_asof`.
- New `.env` settings: **none**.
- HTTP request/status schema: **unchanged**.
- Model features, labels, artifact schema and prediction contract: unchanged.
- Risk, cost, directional, TP/SL and activation thresholds: unchanged.
- New runtime dependency: none.
- Bybit client remains read-only and advisory-only.

## Residual limitations

- POSIX protection is process-group based; a deliberately self-detaching child can escape it.
- The Windows branch is unit-tested but not run on a Windows host.
- Process-tree evidence does not prove that an external OS/container resource escaped nowhere outside the group contract.
- Cancellation remains terminal and does not delete or rewrite prior experiment evidence.
- The change does not prove profitability, improve model quality or increase recommendation frequency.

## Release archive verification

- Clean release inventory: 260 files including `SHA256SUMS`.
- SHA-256 manifest: 259/259 source entries verified after re-extraction.
- ZIP integrity: PASSED.
- Archive structure: one root directory, `cost_aware_momentum-1.34.0`.
- Release-boundary scan: no `.env`, credentials, virtual environment, caches, bytecode, egg-info, build/dist output or real model artifacts.
- Full suite from the re-extracted release: 691 passed, 7 skipped, 62 warnings.
- Re-extracted Ruff, compileall, JavaScript syntax, dependency and Alembic single-head checks: PASSED.

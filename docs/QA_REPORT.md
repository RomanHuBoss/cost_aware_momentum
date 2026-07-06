# QA Report

Release: **1.35.4**

Date: **2026-07-06**  
Scope: **exposure conflict isolation, point-in-time orderbook/account state, evidence integrity**

## Environment

- Python: 3.13.5.
- Project requirement: Python >=3.12.
- Input archive: `cost_aware_momentum-1.35.3-trainer-recovery-deadlock(1).zip`.
- Source version: 1.35.3.
- Separate PostgreSQL integration database: not configured.

## Baseline

After installing the declared PostgreSQL driver and development checks, the source tree produced `715 passed, 7 skipped, 1 failed`. The single failure was the Linux descendant-process timeout proof with a one-second subprocess timeout; the child could be terminated before writing its pid evidence in this environment. Ruff passed.

## Red evidence

- Source inspection showed that any unknown/stale/conflicting exposure raised HTTP 409 before the batch commit, while the browser restarted dwell and generated a new event id for every item.
- Point-in-time regression fakes returned the prior valid snapshot only when source and receipt cutoff predicates were present. The original orderbook and account-equity queries selected the future row.
- Exposure self-hash validation passed independently of a different opportunity ledger before the cross-ledger validator was added.
- The one-second process-tree timeout test failed repeatedly before adjustment.

## Implemented correction

- Independent outcome classification for every exposure item; no batch rollback for permanent per-item conflicts.
- Browser retries only network, 429 and 5xx failures and requeues the original event objects.
- Shared cross-ledger exposure validator.
- Shared latest-prior orderbook and account-equity queries.
- Exact decision cutoff propagated to plan creation, acceptance, reconciliation and portfolio display.
- Explicit fail-closed acceptance-validation evidence guard.
- Timeout proof retains process-tree termination verification with a less startup-sensitive three-second deadline.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | ENVIRONMENT WARNING: unrelated preinstalled `moviepy 2.2.1` requires Pillow <12 while sandbox has Pillow 12.2.0; project checks continued |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `ruff check .` | PASSED |
| `pytest -q` | PASSED: 725 passed, 7 skipped |
| focused new/affected suites | PASSED |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | PASSED: one head, `0016_universe_replay_asof` |
| release integrity | PASSED after manifest rebuild |

## Not run / residual limitations

- PostgreSQL integration tests and `manage.py test --require-integration`: not run because no isolated `TEST_DATABASE_URL` was supplied.
- `manage.py doctor` against the user's runtime: not run because the archive contains no configured PostgreSQL/Bybit environment.
- Candidate-gate diagnosis from real metric payloads and realized-loss attribution: unavailable without the operator database and artifacts.
- Windows process-tree termination runtime: not run.
- `mypy app scripts` is not clean: 306 errors remain, including missing third-party stubs and heterogeneous dynamic-data typing.
- Profitability is not proven; no quality, activation, EV/RR or risk threshold was relaxed.

# QA Report

Release: **1.34.1**

Date: **2026-07-06**  
Scope: **promotion-bound market-signal funding semantics**

## Environment

- Python: 3.13.5 in an isolated virtual environment.
- Project requirement: Python >=3.12.
- Node syntax check: available.
- Separate PostgreSQL integration database: not configured.
- Input archive: `cost_aware_momentum-main.zip`.
- Input archive SHA-256: `980df85007b83468b7b2786414b2a69f857a06f9e414d6d1c131b8d260b4d0b5`.
- Source version: 1.34.0.

## Baseline before changes

| Check | Result |
|---|---|
| clean-source inventory | 227 eligible files; 101 production files; 93 test Python files; 6 documentation/specification files; 16 migration revisions |
| input release boundary | FAILED: 19 forbidden cache/bytecode/egg-info roots; manifest listed 259 entries but only 227 eligible files existed; 32 manifest paths were absent |
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | PASSED: no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 691 passed, 7 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | PASSED: one head, `0016_universe_replay_asof` |

The seven skipped tests are PostgreSQL integration tests. `TEST_DATABASE_URL` and an isolated PostgreSQL test server were unavailable.

## Confirmed defect

The candidate evaluation/promotion path explicitly records `policy_expected_funding_source=none-no-point-in-time-forecast` and binds normal promotion to `funding_rate_override=0`. Historical point-in-time funding forecasts are absent, so the final-holdout market policy is evaluated without expected funding.

Live `publish_hourly_signals` nevertheless projected the current ticker funding rate and supplied it to `select_cost_aware_scenario`. Thus the deployed LONG/SHORT ranking used an input absent from the promotion evidence. On equal LONG/SHORT probabilities, equal executable prices and zero non-funding costs, release 1.34.0 selected LONG with funding 0 but SHORT with funding +0.005. Severity: **critical**, because activation evidence did not identify the policy actually choosing live direction.

No evidence was found that weakening quality gates is safe. One-day candidates failing minimum-history/final-holdout gates are expected fail-closed behavior and were not changed.

## Red evidence

On the unmodified 1.34.0 source:

```text
test_market_signal_policy_rejects_unvalidated_expected_funding_overlay
Failed: DID NOT RAISE ValueError

test_signal_policy_uses_the_exact_model_atr_without_hidden_clipping
AssertionError: Decimal('0.001') != Decimal('0')
```

Independent deterministic reproduction:

```text
funding=0 direction=LONG net_ev_r=0.639130434782608695652173913043478261
funding=0.005 direction=SHORT net_ev_r=0.639130434782608695652173913043478261
```

## Implemented correction

- Centralized the promotion-bound expected-funding source token.
- Made the capital-independent market selector reject non-zero expected funding fail-closed.
- Made live signal publication rank and persist unit economics with zero expected funding, matching final-holdout promotion evidence.
- Preserved the current ticker projection as explicit signal evidence.
- Kept execution-plan creation and acceptance on independently refreshed funding, so adverse funding can reduce EV/RR, shrink size, produce `NO_TRADE`, or reject acceptance, but cannot flip the promoted direction.
- Added regression coverage for both the selector contract and the publication path.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 692 passed, 7 skipped, 62 warnings |
| targeted funding/policy tests | PASSED: 2 passed |
| related policy/lifecycle/execution suite | PASSED: 106 passed, 38 warnings |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | PASSED: one head, `0016_universe_replay_asof` |
| application/package version | PASSED: 1.34.1 |
| trailing whitespace scan | PASSED: 0 findings |
| Bybit mutation endpoint/method scan | PASSED: no production order create/amend/cancel path found |

## Environment-dependent checks

| Check | Result |
|---|---|
| PostgreSQL integration collection | SKIPPED: 7 tests; `TEST_DATABASE_URL` unavailable |
| `python manage.py doctor` | NOT RUN successfully: the wrapper requires a project-local `.venv`; no project `.env`, PostgreSQL server, or PostgreSQL CLI was configured |
| `python manage.py test --require-integration` | NOT RUN: no isolated PostgreSQL integration database; wrapper also rejected the external virtual environment |
| migration upgrade/downgrade on live PostgreSQL | NOT RUN |
| real Bybit forward/shadow cycle | NOT RUN |
| economic profitability/causal loss attribution | NOT ESTABLISHED |

## Release boundary

- Database migration: **none**; head remains `0016_universe_replay_asof`.
- New `.env` settings: **none**.
- HTTP/frontend schema: **unchanged**.
- Model artifact, feature, label and class schema: **unchanged**.
- Quality, activation, risk and capital thresholds: **unchanged**.
- New dependency: **none**.
- Bybit client remains read-only and advisory-only.
- Input caches, bytecode, egg-info and stale checksum manifest are excluded from the rebuilt release.

## Residual limitations

- Historical point-in-time funding forecasts remain unavailable; market-signal expected funding is therefore zero by contract.
- Current funding is a conservative execution overlay, not a validated directional alpha feature.
- Full PostgreSQL transactional/integration behavior was not revalidated in this environment.
- The patch does not increase recommendation frequency, guarantee gate passage, prove profitability, or by itself explain all past losses.

## Release archive verification

- Clean release inventory: 232 files including `SHA256SUMS`.
- Manifest: 231/231 eligible source entries verified.
- ZIP integrity: PASSED.
- Archive structure: one root directory, `cost_aware_momentum-1.34.1`.
- Boundary scan: no `.env`, virtual environment, caches, bytecode, egg-info, build/dist output, dumps, or real model artifacts.
- Full suite from a re-extracted release: 692 passed, 7 skipped, 62 warnings.
- Re-extracted dependency, compile, Ruff, JavaScript syntax, Alembic single-head and release-integrity checks: PASSED.

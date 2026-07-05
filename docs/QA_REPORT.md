# QA Report — 1.14.0

Date: 2026-07-05

Scope: prospective point-in-time Bybit orderbook persistence, bounded-depth market-fill/VWAP simulation, depth-aware execution-plan sizing, acceptance revalidation and operator-latency evidence.

## Environment

- Python: 3.13.5
- Project requirement: Python >=3.12
- Input release: 1.13.0
- Output release: 1.14.0
- Input ZIP SHA-256: `57f990f4af40c9ea61d36652139e33f7babe1b7280f4dc94680ab6da3c0dc1da`
- Input release integrity: PASSED, 180/180 manifest entries
- Baseline tree: 84 production/maintenance files, 63 test files, 14 documentation files, 9 migrations
- Output Alembic head: `0010_orderbook_exec_evidence`

## Baseline before code changes

| Check | Status | Result |
|---|---|---|
| `python -m pip check` | FAILED | Host-level unrelated conflict: `moviepy 2.2.1` requires `pillow<12`, host has `pillow 12.2.0`. |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0. |
| `python -m ruff check .` | PASSED | Exit 0. |
| `python -m pytest -q` | PASSED | 493 passed, 4 skipped. |
| `node --check web/js/app.js` | PASSED | Exit 0. |
| Input `scripts/release_integrity.py` | PASSED | 180/180 entries. |
| `python manage.py doctor` | FAILED (environment) | Project `.venv` was not provisioned. |
| PostgreSQL integration | NOT RUN at baseline | No isolated `TEST_DATABASE_URL`; production database was not used. |

## Red → green

The new regression module was copied into an untouched 1.13.0 tree and executed:

```text
python -m pytest -q tests/unit/test_orderbook_execution_quality_red_2026_07_05.py
```

Red result: collection failed with `ModuleNotFoundError: No module named 'app.risk.liquidity'` (exit 2).

Green result on 1.14.0:

```text
python -m pytest -q tests/unit/test_orderbook_execution_quality_2026_07_05.py
```

Result: 15 passed.

The module independently covers LONG ask-depth VWAP, SHORT bid-depth impact, explicit partial fill, point-in-time normalization, idempotent persistence diagnostics, source/receipt freshness, request depth bounds, configuration fail-closed behavior and restart-safe update identity. Six additional execution-plan/acceptance tests cover depth caps, full-fill VWAP, partial-depth recalculation, exact audit evidence, legacy-plan rejection and future planning-time rejection.

## Post-change checks

| Check | Status | Result |
|---|---|---|
| `python -m pip check` | FAILED | Same external host `moviepy`/`pillow` conflict; project dependencies were not changed. |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0. |
| `python -m ruff check .` | PASSED | Exit 0. |
| `python -m pytest -q` | PASSED | 514 passed, 4 skipped. |
| `node --check web/js/app.js` | PASSED | Exit 0. |
| `python -m alembic heads` | PASSED | Single head `0010_orderbook_exec_evidence`. |
| `python -m pytest -q -rs tests/integration_postgres` | SKIPPED | 4 skipped because `TEST_DATABASE_URL` is not configured. |
| `python manage.py doctor` | FAILED (environment) | `.venv` absent; command requested `python manage.py setup`. |
| `python manage.py test --require-integration` | NOT RUN | No isolated PostgreSQL test database; production database was not used. |
| Order-mutation source scan | PASSED | No create/amend/cancel order endpoint or client method found. |
| Version consistency | PASSED | Package and `pyproject.toml` both report 1.14.0. |
| Diff whitespace check | PASSED | `git diff --no-index --check` produced no whitespace diagnostics; exit 1 reflected expected content differences. |
| Secret scan | PASSED | No private-key markers or populated Bybit secrets found. |

## Interpretation

Static and unit verification is green. The new layer is advisory-only and prospective: it validates whether a full market-style fill was available in a captured REST snapshot and repeats that check at operator acceptance. It does not prove an actual exchange fill, reconstruct orderbook history before deployment, estimate queue position or implement an OMS partial-fill lifecycle.

PostgreSQL migration execution, a live multi-symbol Bybit collection run, storage-growth observation, full paper/shadow operation and economic profitability were not tested in this environment. The official Bybit contract was checked for REST snapshot depth/timestamps and for the possibility that update ID can restart; RPI liquidity is not present in the standard snapshot.

## Release archive verification

| Check | Result |
|---|---|
| Clean staged manifest | PASSED, 185/185 files |
| Clean staged full suite | 514 passed, 4 skipped |
| Clean staged compile/Ruff/Node checks | PASSED |
| Clean staged Alembic head | `0010_orderbook_exec_evidence (head)` |
| ZIP structural test | PASSED (`unzip -t`) |
| Fresh re-extraction manifest | PASSED, 185/185 files |
| Fresh re-extraction full suite | 514 passed, 4 skipped |
| Fresh re-extraction compile/Ruff/Node checks | PASSED |
| Fresh re-extraction Alembic head | `0010_orderbook_exec_evidence (head)` |

Generated caches were removed after testing and the manifest was regenerated and verified before final packaging. The archive contains one root directory and excludes credentials, runtime `.env`, virtual environments, model artifacts, database dumps and test/build caches.

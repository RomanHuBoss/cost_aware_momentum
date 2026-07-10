# Iteration report — locked ticker validation

Date: 2026-07-10  
Release: 1.52.23  
Scope: `locked-ticker-validation`

## 1. Input archive and baseline identity

- Input archive: `cost_aware_momentum-main.zip`
- Input SHA-256: `4c744e0f0f60301d85171df148d929def1ee78bf7413b1469a3c365f114e4118`
- Source version: `1.52.22`
- Project root: `cost_aware_momentum-main/`
- Declared Python requirement: `>=3.12`
- Runtime used: Python `3.13.5`
- Alembic head: `0018_inference_observations`
- Baseline inventory: 103 production files, 128 test files, 32 documentation/release files.
- Input ZIP integrity: `unzip -t` passed; no absolute or `..` paths were present.
- Unexpected release artifacts: no `.env`, credentials, virtual environments, bytecode caches, build/dist directories, dumps, or real model artifacts were present. `models/` and `backups/` contained only `.gitkeep`. The archive contained its active `SHA256SUMS` manifest and the supplied iteration specification PDF.

## 2. Goal and acceptance criteria

Goal: after this iteration, a locked Bybit ticker quote (`bid == ask`) must not be treated as executable zero-spread evidence anywhere in the ticker-based advisory path, demonstrated by independent red→green tests and a green full non-integration suite.

Acceptance criteria:

1. Shared executable bid/ask validation rejects locked and crossed quotes with an explicit diagnostic.
2. Market-signal selection and acceptance-side entry selection both fail closed through that shared validator.
3. Dynamic-universe eligibility classifies a locked quote as invalid rather than zero-spread eligible.
4. Ticker ingestion retains a valid observational last price but stores no executable bid/ask for locked quotes.
5. No fallback to last price, risk-gate weakening, exchange write endpoint, API/schema, `.env`, or model-artifact change is introduced.
6. New tests fail on 1.52.22 for the intended reason and pass after the fix.
7. Full pytest, ruff, compileall, node syntax, Alembic-head, release-integrity, and archive checks pass where the environment permits.

## 3. Read sources and project/data-flow map

Read before the fix:

- `README.md`, `CHANGELOG.md`, `PATCH_1.52.19.md` through `PATCH_1.52.22.md`
- `pyproject.toml`, `.env.example`
- `docs/ARCHITECTURE.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`
- relevant production modules and unit tests.

Project map:

- Bybit/public read-only client: `app/bybit/client.py`
- Market ingestion and persistence: `app/services/market_data.py`
- Universe filtering and immutable eligibility evidence: `app/services/universe.py`
- Features/context: `app/ml/features.py`, `app/ml/context.py`
- Labels/targets: `app/ml/labels.py`
- Training/validation/promotion: `app/ml/training.py`, `app/ml/lifecycle.py`, `app/services/model_promotion.py`
- Artifact lifecycle/runtime: `app/ml/artifact_store.py`, `app/ml/runtime.py`, `app/services/model_activation.py`
- Market signal: `app/services/signals.py`
- Execution planning, acceptance revalidation, costs and risk: `app/services/execution.py`, `app/risk/math.py`, `app/risk/liquidity.py`, `app/risk/policy.py`
- Account/profile state: `app/api/v1/capital.py`, `app/api/v1/portfolio.py`, ORM account/profile models
- API schemas/serialization: `app/api/schemas.py`, `app/api/serializers.py`, `app/api/v1/`
- Frontend: `web/index.html`, `web/js/app.js`, `web/css/app.css`
- ORM/migrations: `app/db/models.py`, `migrations/versions/`
- Audit/idempotency/outbox: `app/services/audit.py`, `app/services/idempotency.py`, ORM models
- Tests: `tests/unit/`, `tests/integration_postgres/`.

Relevant data path for this defect:

`Bybit /v5/market/tickers` → `BybitClient.get_tickers()` → `sync_tickers()` and `select_dynamic_universe()` → persisted `TickerSnapshot` / universe eligibility → `select_cost_aware_scenario()` → execution-plan construction → acceptance revalidation via `executable_entry_price()` → API/UI entry state.

## 4. Baseline

Host environment preflight:

- `python --version`: PASSED, Python 3.13.5.
- `python -m pip check`: FAILED due unrelated global `moviepy`/`pillow` conflict.
- `python -m compileall -q app scripts tests manage.py`: PASSED.
- `python -m ruff check .`: UNAVAILABLE, host lacked ruff.
- `python -m pytest -q`: FAILED during collection with 62 errors because host lacked `psycopg`.
- `node --check web/js/app.js`: PASSED.

A clean temporary environment was installed from `.[dev]` before code changes:

- `python -m pip check`: PASSED.
- `python -m compileall -q app scripts tests manage.py`: PASSED.
- `python -m ruff check .`: PASSED.
- `python -m pytest -q`: PASSED, `905 passed, 8 skipped in 18.48s`.
- `node --check web/js/app.js`: PASSED.
- PostgreSQL integration/doctor: SKIPPED because no safe `TEST_DATABASE_URL` or local database was configured.

Baseline project-environment counts: passed 905 / failed 0 / skipped 8 / xfailed 0 / errors 0.

## 5. Confirmed defect

### Locked ticker accepted as executable evidence

- Type: CONFIRMED DEFECT
- Severity: high
- Files/functions:
  - `app/services/execution.py::validated_bid_ask`
  - `app/services/market_data.py::sync_tickers`
  - `app/services/universe.py::_spread_bps_from_prices`
  - downstream callers in `app/services/signals.py` and API serializers.
- Actual behavior:
  - only `ask < bid` was rejected;
  - `ask == bid` returned a valid executable quote;
  - dynamic universe calculated spread `0` and selected the symbol;
  - ticker ingestion persisted equal bid/ask values;
  - signal policy and acceptance returned an executable reference price.
- Expected behavior: strictly positive executable spread, `ask > bid`; locked and crossed ticker data must fail closed, matching the orderbook-depth invariant introduced in 1.52.20.
- Financial/model/operational impact: locked ticker data could understate friction, contaminate eligibility evidence, and permit signal/plan calculations from an unsafe external quote. The project remained advisory-only, so this did not directly place an order.
- Why previous tests missed it: quote-contract tests covered crossed quotes only; locked coverage existed for orderbook normalization but not ticker paths.
- Reproduction: pass `bid_price=Decimal("100")`, `ask_price=Decimal("100")` to `select_cost_aware_scenario()` or `executable_entry_price()`, or feed the same ticker into universe selection/sync.
- Future guard: the four tests added to `tests/unit/test_quote_plan_contract_2026_06_30.py`.

## 6. Plan and actual diff

Minimal systemic fix:

- Change the shared executable quote condition from `ask < bid` to `ask <= bid` and emit `locked or crossed`.
- Apply the same strict condition at dynamic-universe spread derivation.
- Null executable ticker bid/ask on ingestion when locked/crossed, while retaining a valid last price.
- Add four regressions at the external contracts.
- Replace six pre-existing locked synthetic test fixtures with valid positive, tick-aligned spreads; no production behavior was relaxed.
- Bump patch version and synchronize release documentation.

No migration, API/schema, `.env`, model-artifact, risk-threshold, or endpoint change was required.

## 7. Red → green evidence

Red command:

```bash
python -m pytest -q \
  tests/unit/test_quote_plan_contract_2026_06_30.py::test_signal_policy_rejects_locked_quote \
  tests/unit/test_quote_plan_contract_2026_06_30.py::test_acceptance_rejects_locked_quote \
  tests/unit/test_quote_plan_contract_2026_06_30.py::test_dynamic_universe_rejects_locked_quote \
  tests/unit/test_quote_plan_contract_2026_06_30.py::test_ticker_sync_drops_locked_bid_ask
```

Red result on unpatched production code:

```text
4 failed in 3.06s
```

Green result after fix:

```text
4 passed in 2.75s
```

Related subset:

```text
79 passed in 3.68s
```

Full post suite:

```text
909 passed, 8 skipped in 14.83s
```

## 8. Compatibility

- Alembic migration: none.
- Current head: `0018_inference_observations`.
- Database action: none.
- `.env` action: none.
- Public API and JSON schemas: unchanged.
- Model artifact/lifecycle contract: unchanged.
- Bybit methods/endpoints: unchanged and read-only.
- Deployment action: restart API and inference worker so all quote-validation paths use 1.52.23.

## 9. Post-check

Passed in the isolated project environment:

- `python -m pip check`
- `python -m compileall -q app scripts tests manage.py`
- `python -m ruff check .`
- `python -m pytest -q` — 909 passed, 8 skipped
- `node --check web/js/app.js`
- `python -m alembic heads` — one head, `0018_inference_observations`
- new test separately
- related 79-test subset
- forbidden exchange write endpoint grep.

Final release-integrity and archive values are appended during packaging below.

## 10. Not verified and residual risks

Not verified:

- PostgreSQL integration tests, migration upgrade/downgrade, and `manage.py doctor`: no safe test database.
- Exact Python 3.12 runtime: unavailable; Python 3.13.5 was used.
- Real Bybit paper/shadow/forward behavior, rate limits, network faults, and live locked-ticker incidence.
- Strategy profitability/live edge.

Residual risks:

- The existing orderbook database constraint still permits equality (`best_ask >= best_bid`) even though application ingestion rejects locked orderbooks. Direct/manual database writes could bypass the application invariant.
- Ticker bid/ask integrity is enforced in application paths rather than by a new database constraint; historical locked rows, if already present, are not rewritten by this patch.
- Last price is deliberately retained for observation when executable bid/ask is invalid; downstream code must continue to avoid substituting last price for executable sides.

## 11. Rollback

No database rollback is required.

1. Stop API and inference worker.
2. Restore the previously verified 1.52.22 release directory/archive.
3. Restart API and inference worker.
4. Confirm version/status and rerun release checks.

Rollback reintroduces acceptance of locked ticker quotes and should be used only for a documented regression requiring immediate restoration.

## 12. Recommended next work package

Add a new Alembic migration and integration tests that enforce strict `best_ask > best_bid` at the PostgreSQL layer for orderbook snapshots, with a pre-migration scan/remediation policy for any legacy locked rows. Evaluate an equivalent conditional constraint for nullable ticker bid/ask pairs without rewriting historical observational data.

## 13. Final packaging record

- Release-integrity manifest: PASSED — 295 eligible files checked and 295 manifest entries verified.
- Output ZIP test: PASSED — `unzip -t` reported no compressed-data errors.
- Clean re-extraction: PASSED — exactly one root directory, `cost_aware_momentum-1.52.23/`; release integrity passed again after extraction.
- Forbidden release artifacts: none detected by `scripts/release_integrity.py`; no `.env`, credentials, caches, bytecode, egg-info, build/dist output, database dumps, temporary logs, or real model artifacts were packaged.
- Output ZIP SHA-256: reported alongside the delivered archive rather than embedded here, because embedding an archive digest inside a file contained by that archive would change the digest.

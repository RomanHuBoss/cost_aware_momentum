# Iteration Report — point-in-time orderbook execution evidence

Date: 2026-07-05  
Input: `cost_aware_momentum-1.13.0-intrahorizon-mark-mtm-liquidation(1).zip`  
Input SHA-256: `57f990f4af40c9ea61d36652139e33f7babe1b7280f4dc94680ab6da3c0dc1da`  
Input version: 1.13.0  
Output version: 1.14.0

## 1. Goal and acceptance criteria

After this iteration, the advisory execution layer must use a fresh point-in-time orderbook to prove that the complete planned quantity fits inside a configured adverse-impact band, persist exact VWAP/fill evidence, and repeat the check at operator acceptance.

Acceptance criteria:

1. Public/read-only depth snapshots are validated and persisted with exchange and receipt timestamps.
2. LONG consumes asks; SHORT consumes bids.
3. Full, partial and no-fill states are explicit; partial/no-fill cannot become actionable.
4. Plan qty is capped by both turnover and bounded depth; entry/risk/EV are recomputed from full-fill VWAP.
5. Acceptance requires compatible original evidence and revalidates all qty on a fresh snapshot.
6. Operator decision stores exact second snapshot/fill evidence and latency.
7. Update-ID restart does not destroy a later valid snapshot.
8. Migration, config, tests, docs and release archive remain consistent; advisory-only is preserved.

## 2. Sources read and data flow

Read: `README.md`, `CHANGELOG.md`, `PATCH_1.10.0.md` through `PATCH_1.13.0.md`, `pyproject.toml`, `.env.example`, architecture, QA, compliance, traceability, model card, configuration, security, incident and operator documents, risk/execution/market-data/client/worker/API/ORM modules and relevant tests.

External contract checked against official Bybit V5 documentation on 2026-07-05:

- REST `GET /v5/market/orderbook` returns a snapshot; linear depth limit is 1..1000; bids descend, asks ascend; `ts`, `u`, `seq`, `cts` are exposed; RPI orders are not included.
- Public orderbook documentation states that `u=1` can occur after service restart, so `symbol + update_id` is not a safe eternal natural key.

Changed flow:

```text
Bybit public REST snapshot
  -> strict normalize/validate
  -> market.orderbook_snapshots
  -> bounded directional fill simulation
  -> depth cap + complete-fill VWAP
  -> execution-plan risk/EV/qty
  -> plan sizing_snapshot
  -> fresh acceptance revalidation
  -> operator decision audit context
```

## 3. Baseline

Input integrity: 180/180 manifest entries. Baseline tree: 84 production/maintenance files, 63 tests, 14 docs and 9 migrations.

| Command | Result |
|---|---|
| `python --version` | Python 3.13.5 |
| `python -m pip check` | FAILED: external `moviepy 2.2.1` / `pillow 12.2.0` host conflict |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | 493 passed, 4 skipped |
| `node --check web/js/app.js` | PASSED |
| `python manage.py doctor` | FAILED: project `.venv` absent |
| PostgreSQL integration | NOT RUN: no isolated `TEST_DATABASE_URL` |

## 4. Confirmed defects and gaps

### Critical — plan used top quote and turnover proxy, not executable depth

**Evidence:** `app/services/execution.py::create_execution_plan` used ticker bid/ask and `turnover_24h * 0.0001`. It did not consume multiple price levels or prove complete fill.

**Impact:** qty, entry, stop distance, stress loss, net R/R and EV could all be calculated from a price available for only a small fraction of the requested quantity.

**Why tests missed it:** fixtures contained one quote and no orderbook/path-level oracle.

### Critical — acceptance did not revalidate complete quantity

**Evidence:** acceptance checked current bid/ask and scalar turnover cap. A best ask/bid could remain inside the entry zone while the rest of the book implied a materially worse VWAP or partial fill.

**Impact:** an apparently safe plan could be accepted after its executable depth disappeared.

### High — no point-in-time audit evidence or operator latency

No persisted snapshot linked plan sizing to `source_time`, `received_at`, update/sequence, levels, VWAP and impact. Operator decisions could not quantify the delay between plan construction and revalidation.

### High — unsafe natural identity for update IDs

An early implementation used `(symbol, update_id)`. Official exchange semantics allow the update ID to restart. The final key is `(symbol, source_time, update_id)`.

### Confirmed gap — historical reconstruction remains unavailable

The exchange endpoint provides current snapshots, not pre-deployment historical depth. This release accumulates forward evidence only. Queue, RPI, limit-order fill probability and actual partial-fill lifecycle remain outside scope.

## 5. Change plan and actual diff

Production/config/migration:

- `app/risk/liquidity.py`
- `app/bybit/client.py`
- `app/services/market_data.py`
- `app/services/execution.py`
- `app/api/v1/recommendations.py`
- `app/workers/runner.py`
- `app/db/models.py`
- `app/config.py`
- `migrations/versions/0010_orderbook_exec_evidence.py`
- `.env.example`
- `app/__init__.py`, `pyproject.toml`

Tests:

- new `tests/unit/test_orderbook_execution_quality_2026_07_05.py`
- updated `tests/unit/test_execution_acceptance_safety.py`
- updated `tests/unit/test_migration_revision_contract.py`

Documentation:

- `README.md`, `CHANGELOG.md`, `PATCH_1.14.0.md`
- architecture, configuration, operator, security, incident, model card, compliance, traceability and QA documents
- this iteration report

## 6. Implementation details

- `simulate_market_fill` uses Decimal and validates nonempty positive sorted uncrossed levels.
- LONG boundary is `best_ask * (1 + impact_bps/10000)`; SHORT boundary is `best_bid * (1 - impact_bps/10000)`.
- Fill evidence contains requested/filled/unfilled qty, available qty/notional, best, VWAP, worst, impact and levels used.
- Plan depth cap is combined with the existing turnover cap using the smaller positive value.
- Sizing iterates risk geometry and VWAP up to five times; no convergence is blocked, not approximated silently.
- Source and receipt timestamps both must be nonfuture and within `MAX_ORDERBOOK_AGE_SECONDS`.
- Acceptance rejects an old or tampered plan if schema, full-fill status, qty, VWAP, entry or timezone-aware planning time is inconsistent.
- The operator decision captures the new snapshot and `operator_latency_seconds`.
- Persistence uses `ON CONFLICT DO NOTHING`; duplicate and inserted counts are distinguished.

## 7. Red → green evidence

Red command on untouched 1.13.0 after adding the regression file:

```text
python -m pytest -q tests/unit/test_orderbook_execution_quality_red_2026_07_05.py
```

Result: collection error `ModuleNotFoundError: No module named 'app.risk.liquidity'`.

Green targeted result on 1.14.0:

```text
15 passed
```

The complete suite rose from 493 to 514 passing tests with the same four PostgreSQL skips.

## 8. Migration, API, config and compatibility

- New Alembic revision/head: `0010_orderbook_exec_evidence`.
- New table: `market.orderbook_snapshots`.
- New `.env` fields: `ORDERBOOK_DEPTH_LEVELS`, `MAX_ORDERBOOK_AGE_SECONDS`, `MAX_VWAP_IMPACT_BPS`, `ORDERBOOK_RETENTION_HOURS`.
- No order-placement API or Bybit mutation method was added.
- Public recommendation endpoint shape remains compatible; stored plan/decision evidence is extended.
- Model artifact schema remains 1.13-compatible; retraining is not required for this work package.
- Existing execution plans must be recalculated because they lack the new evidence contract.

## 9. Post-change verification

| Command | Result |
|---|---|
| `python -m pip check` | FAILED: same external host conflict |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | 514 passed, 4 skipped |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | `0010_orderbook_exec_evidence (head)` |
| PostgreSQL integration module | 4 skipped: `TEST_DATABASE_URL` absent |
| `python manage.py doctor` | FAILED: `.venv` absent |
| Order mutation scan | PASSED |
| Secret scan | PASSED |
| Version consistency | PASSED: 1.14.0 |

Final staged/re-extracted archive verification is appended in section 14 after packaging.

## 10. Unverified items

- Migration upgrade/downgrade against a real isolated PostgreSQL instance.
- Real multi-symbol Bybit collection, rate-limit behavior and storage growth.
- Exact behavior during network stalls or exchange service restart in a live run.
- Forward paper/shadow evidence and actual operator latency distribution.
- Economic benefit or profitability.

## 11. Residual risks and limitations

- REST is a snapshot; depth can change between receipt and manual order submission.
- Standard snapshot omits RPI liquidity.
- A full market-style snapshot fill is not a limit-order/queue model.
- No historical depth exists before deployment; training/backtest still use the 1.10 spread entry proxy.
- Partial/no-fill is a blocking advisory state, not a real exchange order lifecycle.
- Large uncapped universes can increase serial request duration and PostgreSQL volume.

## 12. Rollback

1. Stop API/worker/trainer.
2. Preserve depth rows if needed for incident audit.
3. Revert source to 1.13.0.
4. Downgrade Alembic one revision only if the table can be discarded.
5. Restore previous `.env` or leave unused new variables.
6. Restart and run doctor. Model artifact rollback is unnecessary because ML schemas did not change.

## 13. Recommended next work package

Build a forward execution experiment ledger from the newly persisted snapshots and operator decisions: eligibility of every recommendation, plan/accept/reject latency, counterfactual bounded-depth outcomes and selection-bias correction. Do not call this historical fill validation until enough prospective evidence has accumulated.

## 14. Final release archive verification

The clean staged release and a fresh re-extraction of the packaged tree were checked independently:

| Check | Staged tree | Freshly re-extracted ZIP |
|---|---|---|
| Release manifest | PASSED, 185/185 files | PASSED, 185/185 files |
| `python -m compileall -q app scripts tests manage.py` | PASSED | PASSED |
| `python -m ruff check .` | PASSED | PASSED |
| `python -m pytest -q` | 514 passed, 4 skipped | 514 passed, 4 skipped |
| `node --check web/js/app.js` | PASSED | PASSED |
| `python -m alembic heads` | `0010_orderbook_exec_evidence (head)` | `0010_orderbook_exec_evidence (head)` |
| ZIP structural test | not applicable | PASSED (`unzip -t`) |

Generated bytecode and test caches were removed after verification. The release manifest was then regenerated and rechecked before final packaging. The archive contains one root directory, `cost_aware_momentum-1.14.0`, and no `.env`, credentials, model artifacts, database dumps, virtual environments or test/build caches.

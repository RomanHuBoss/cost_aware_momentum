# Iteration report — 2026-06-30 — acceptance/spec integrity

## 1. Input archive and baseline identity

- Input: `cost_aware_momentum-main.zip`
- Input SHA-256: `59cef1a7fb996f9c29fa9f48df7c8d4b19683383fa77b2d94fca1e6d5f5d2694`
- Source version: `1.8.15`
- Target version: `1.8.16`
- Python requirement: `>=3.12`; checks used Python `3.13.5`
- Alembic revisions: `0001`–`0006`; head `0006_manual_trade_remaining_risk`
- Input layout: one project root, 182 archive entries, 156 regular project files; no `.env`, virtual environment, caches, bytecode, database dump or real model artifact.

The external statements that other reviewers found dozens of unnamed errors could not be verified because they contained no module, reproducer or expected/actual behavior. They were treated as untrusted leads, not as defect evidence.

## 2. Iteration goal and acceptance criteria

**Goal:** after this iteration, an execution plan can be accepted only when its fresh capital-dependent economics and current exchange constraints remain valid, and every newly published manual price level is valid for the current exchange tick.

Acceptance criteria:

1. Capital deterioration that breaks the configured per-trade risk limit returns HTTP 409 and does not accept the old plan.
2. Insufficient fresh available margin after reserve returns HTTP 409.
3. Changed `qtyStep`, min order, max qty/leverage or tick constraints invalidate the old plan.
4. Newly adverse projected funding or failed current net-policy gates force recalculation.
5. Published LONG/SHORT entry-zone, SL and TP levels are tick-aligned with conservative rounding.
6. The serialized total portfolio-risk gate uses freshly recomputed stress loss.
7. Advisory-only, PostgreSQL-only, API contracts and schema head remain unchanged.
8. Existing and new unit/static checks remain green.

## 3. Sources read and affected data flow

Read: `README.md`, `CHANGELOG.md`, `PATCH_1.8.12.md`–`PATCH_1.8.15.md`, `pyproject.toml`, `.env.example`, architecture, QA, compliance, traceability, model card, configuration, security, operator manual, embedded DOCX specification, relevant production modules and tests. `docs/INCIDENT_RUNBOOK.md` requested by the generic iteration prompt is absent from this archive.

Affected flow:

`Bybit ticker + point-in-time InstrumentSpec + model probabilities` → validation → tick-aligned directional geometry → cost-aware signal selection → PostgreSQL `MarketSignal` → profile/account snapshot → `ExecutionPlan` → fresh accept-time revalidation → serialized portfolio-risk check → `ACCEPTED` decision/audit or superseding plan.

## 4. Baseline before source changes

Initial host-environment attempt identified missing project dependencies (`psycopg`) and an unrelated global `moviepy`/`Pillow` conflict. An isolated project `.venv` was then created and `.[dev]` installed; the authoritative baseline was run before production source changes:

| Command | Result |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `.venv/bin/python -m pip check` | PASSED |
| `.venv/bin/python -m compileall -q app scripts tests manage.py` | PASSED |
| `.venv/bin/python -m ruff check .` | PASSED |
| `.venv/bin/python -m pytest -q` | PASSED — 288 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `.venv/bin/python manage.py release-check` | PASSED — 155/155 |
| `python manage.py doctor` | NOT RUN — no application `.env` or disposable PostgreSQL |
| `python manage.py test --require-integration` | NOT RUN — no safe `TEST_DATABASE_URL` |

## 5. Confirmed defects and evidence

### D1 — stale per-trade risk and margin at acceptance — CRITICAL

- Files: `app/api/v1/recommendations.py`, `app/services/execution.py`.
- Previous behavior: acceptance loaded fresh capital but only compared stale `plan.actual_stress_loss` with the broad total-risk cap. It did not reapply `profile.risk_rate`, and `available_margin` was loaded but unused.
- Reproducer: a 50 USDT stress-loss plan created for 10,000 USDT capital was accepted after effective capital fell to 1,000 USDT, although a 1% per-trade limit allowed only 10 USDT. A separate case accepted margin 100 USDT even when reserve policy left less capacity.
- Expected: HTTP 409 and a new/recalculated plan. Actual: HTTP 200 and `ACCEPTED`.
- Impact: operator could approve risk materially above the configured individual budget or beyond fresh margin.
- Why tests missed it: existing acceptance tests covered stale snapshots and total portfolio risk, not fresh per-trade/margin recomputation.

### D2 — current instrument constraints were not revalidated — CRITICAL

- Files: `app/api/v1/recommendations.py`, `app/services/execution.py`.
- Previous behavior: acceptance did not repeat `qtyStep`, `minQty`, `minNotional`, `maxQty`, `maxLeverage` and tick checks against the current point-in-time specification.
- Reproducer: an old qty `0.01` was accepted after current `qtyStep/minQty` became `0.1`.
- Impact: technically invalid manual order guidance and stale leverage/size assumptions.

### D3 — newly adverse funding/economics could remain stale — HIGH

- Files: `app/api/v1/recommendations.py`, `app/services/execution.py`.
- Previous behavior: funding scenario was recalculated during plan creation but not immediately before acceptance. A newly crossed adverse settlement could reduce current R/R and EV without invalidating the old plan.
- Reproducer: stored funding zero, fresh projected LONG funding `0.01`; unchanged code returned HTTP 200.
- Impact: stale positive policy decision after material cost deterioration.

### D4 — signal price levels were not constrained by `tickSize` — HIGH

- File: `app/services/signals.py`.
- Previous behavior: ATR-derived zone/SL/TP values were stored at arbitrary Decimal precision. `tickSize` was available but not passed into scenario construction.
- Reproducer: entry 100, ATR 1.3, multipliers 1.7/2.3, tick 0.5 produced raw SL 97.79 and TP 102.99.
- Impact: operator could receive price levels the exchange does not accept; unrounded economics were optimistic relative to executable discrete prices.

### D5 — legacy off-tick geometry was not blocked — HIGH

- File: `app/services/execution.py`.
- Previous behavior: execution-plan construction could continue from an old signal whose price geometry no longer matched the current tick.
- Impact: compatibility records could bypass the new publication boundary.

## 6. Plan and actual diff

Production:

- `app/services/signals.py`: optional/current tick contract, conservative directional rounding, post-rounding economics, fail-closed publication diagnostic.
- `app/services/execution.py`: reusable acceptance validator; current qty/min-order/leverage/tick/funding/risk/margin/economics checks; off-tick plan block; tick evidence in sizing snapshot.
- `app/api/v1/recommendations.py`: current spec/funding lookup, fresh acceptance validation, recomputed total-risk reservation and expanded decision context.

Tests:

- `tests/unit/test_execution_acceptance_safety.py`
- `tests/unit/test_cost_aware_direction_selection.py`

Release/docs:

- `pyproject.toml`, `app/__init__.py`, `README.md`, `CHANGELOG.md`, `PATCH_1.8.16.md`
- `docs/ARCHITECTURE.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/MODEL_CARD.md`, `docs/OPERATOR_MANUAL.md`
- this report and regenerated `SHA256SUMS`.

No migration, config variable, dependency or public API schema was added.

## 7. Red → green evidence

Command on unchanged production code with four acceptance regressions:

```text
pytest -q <four named acceptance tests>
4 failed in 2.24s
expected HTTP 409; actual HTTP 200 in every case
```

Command on unchanged production code with tick regression:

```text
pytest -q tests/unit/test_cost_aware_direction_selection.py::test_signal_geometry_is_conservatively_aligned_to_exchange_tick
1 failed in 4.39s
TypeError: select_cost_aware_scenario() got an unexpected keyword argument 'tick_size'
```

After implementation:

```text
pytest -q <same five tests>
5 passed in 5.34s
```

Three additional tests verify successful acceptance after all fresh checks, fail-closed legacy off-tick plan creation and conservative SHORT rounding.

## 8. Migration, API, configuration and compatibility

- Migration: none; head remains `0006_manual_trade_remaining_risk`.
- `.env`: no new or changed variable.
- API: existing endpoints/status model retained. Invalidated mutable plans continue to produce HTTP 409 and a new version through the established lifecycle.
- Database: no schema change.
- Models: no artifact contract or retraining requirement.
- Roll-forward behavior: restart API and worker so all processes load 1.8.16 code.

## 9. Post-change checks

| Command | Result |
|---|---|
| `.venv/bin/python -m pip check` | PASSED |
| `.venv/bin/python -m compileall -q app scripts tests manage.py` | PASSED |
| `.venv/bin/python -m ruff check .` | PASSED |
| `.venv/bin/python -m pytest -q` | PASSED — 296 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `.venv/bin/alembic heads` | PASSED — one head: `0006_manual_trade_remaining_risk` |
| independent randomized LONG/SHORT math checks | PASSED — 1,000 cases |
| release manifest/tree check | PASSED — 157/157 after clean staging and regeneration |
| ZIP integrity and clean re-extraction | PASSED |

No previously green unit test regressed. No Bybit order-create/amend/cancel method was added.

## 10. Not verified

- PostgreSQL integration tests and live migration smoke: NOT RUN because there was no disposable PostgreSQL/test URL. Unit coverage mocks the transactional boundary but does not replace real lock/transaction evidence.
- `manage.py doctor`: NOT RUN because no safe application `.env`/PostgreSQL service was configured.
- Bybit live/read-only smoke, paper/shadow forward performance and actual manual-order acceptance: NOT RUN.
- Browser interaction/accessibility smoke beyond JavaScript syntax: NOT RUN.

## 11. Residual risks and limitations

- Historical research labels and backtests do not reconstruct point-in-time `tickSize` histories, so exact train/live discrete-price parity is still incomplete.
- Instrument specification can change between successful acceptance and the operator's later manual order entry; the project does not place or reserve exchange orders.
- Margin check is conservative but does not model every exchange maintenance-margin tier, fee-tier, queue/no-fill or partial-fill behavior.
- Single chronological holdout is not full multi-fold walk-forward validation; historical orderbook impact and dynamic-universe membership history remain absent.
- Passing technical checks does not establish profitability, robustness across regimes or suitability for live capital.

## 12. Rollback

1. Stop API and worker.
2. Restore the 1.8.15 application files; no database downgrade is needed.
3. Restart services and run `python manage.py release-check`, unit tests and `manage.py doctor` in the operator environment.
4. Plans created under 1.8.16 remain schema-compatible. Do not bypass 1.8.16 HTTP 409 responses by manually editing their status.

## 13. Recommended next work package

Implement point-in-time instrument-spec history in research labels and backtest geometry: reconstruct historical `tickSize`/`qtyStep` at every decision timestamp, quantize barriers with the same conservative contract, version the label/policy schema, and compare candidate/incumbent only on identically quantized holdouts. This should be a separate econometric iteration with PostgreSQL-backed tests.

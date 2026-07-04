# Iteration Report — 2026-07-04 — hourly decision-candle integrity

## 1. Input archive, SHA-256 and source version

- Input: `cost_aware_momentum-main.zip`.
- SHA-256: `276e17e3f527cfe1a228f9030ab25ba00cc63056ff71c64d49adfa819d5894ce`.
- Source version: `1.9.1`.
- Source Alembic head: `0009_candle_receipt_availability`.
- Target version: `1.9.2`.
- Input composition: 70 production/maintenance Python files, 52 test modules, 20 Markdown docs, 9 migrations, 169 ZIP files.

## 2. Goal and acceptance criteria

After this iteration an hourly recommendation must be generated only from the confirmed candle that closes exactly at its `event_time`; a previous-hour feature window must fail closed and must not occupy the current-hour natural key.

Acceptance criteria:

1. Latest candle `close_time` must equal `event_time` before signal economics runs.
2. A previous-hour candle produces diagnostic `missing_decision_candle` and no signal.
3. No natural key, audit/outbox event or execution plan is created on the mismatched window.
4. Exact current-hour behavior and existing retry/idempotency tests do not regress.
5. ML/risk/economic thresholds and artifact contracts remain unchanged.
6. Regression test is demonstrably red on 1.9.1 and green after the fix.
7. Full available unit/static/frontend suite passes.
8. Output release passes manifest and clean-archive verification.

## 3. Sources read and affected data flow

Read: `README.md`, `pyproject.toml`, `.env.example`, architecture, QA, compliance, traceability, model card, configuration, security, incident runbook, operator manual, all current iteration reports, production signal/market-data/ML/risk paths, related tests and relevant temporal sections of `docs/source/Cost_aware_hourly_ML_momentum_specification.docx`.

The input archive did not contain `CHANGELOG.md` or any `PATCH_*.md`; this contradiction with the prior report was recorded rather than silently reconstructing history.

Affected flow:

```text
Bybit confirmed hourly candles
→ market_cutoff=event_time + availability_cutoff=publish time
→ contiguous feature frame
→ exact latest close_time/event_time anchor
→ directional scenario economics
→ natural-key/idempotency check
→ MarketSignal / ExecutionPlan / API / UI
```

## 4. Baseline

The shared system Python was not a valid project environment: missing `ruff`/`psycopg` caused unavailable lint and 23 pytest collection errors; global `pip check` reported an unrelated MoviePy/Pillow conflict. An isolated virtualenv outside the project tree was installed with `pip install -e '.[dev]'`.

| Command | Result |
|---|---|
| `python --version` | Python 3.13.5; requirement satisfied |
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | 434 passed, 4 skipped, 55 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | one head `0009_candle_receipt_availability` |
| `python manage.py release-check` on clean input | FAILED: manifest missing; 169 files, 0 entries |
| `python manage.py doctor` | NOT RUN: no configured `.env`/PostgreSQL |
| PostgreSQL integration | NOT RUN: no isolated `TEST_DATABASE_URL`/server |

## 5. Confirmed defects/gaps and evidence

### HIGH — previous-hour data could publish a current-hour signal

File/function: `app/services/signals.py::publish_hourly_signals`.

Minimal state:

```text
event_time              = 10:00
latest candle close     = 09:00
MAX_CANDLE_AGE_SECONDS  = 4200
computed data age       = 3600
```

Actual 1.9.1 behavior: the candle passed freshness, reached `select_cost_aware_scenario`, and could publish a natural key containing `10:00`.

Expected behavior: no signal until confirmed candle `close_time=10:00` is available.

Operational consequence: after the correct 10:00 candle arrived, the natural-key check treated the hour as already published. This creates a mismatch among feature window, signal `event_time`, `data_cutoff` and eventual outcome attribution.

Severity is HIGH, not CRITICAL: the project is advisory-only and does not place orders automatically. The defect can expose an operator to a bad recommendation, but the archive alone does not prove a particular realized loss.

Existing tests missed it because freshness, point-in-time query and natural-key retry were verified separately; no test bound the selected feature close to the publication anchor.

### MEDIUM — release provenance files were absent

A clean extraction failed its own `manage.py release-check`: `SHA256SUMS` was missing and all 169 eligible files were unlisted. `CHANGELOG.md` and prior patch notes mentioned by the 1.9.1 report were also absent. Current release provenance is restored; unverifiable previous content is not invented.

### Documented limitation, not weakened

Rare model activation after one day is not evidence of a code defect by itself. Current defaults require at least 1206 unique hourly timestamps before the configured purged split and minimum holdout can fit. This iteration does not lower holdout, profitability, risk or policy gates merely to increase recommendation count.

## 6. Plan and actual diff

Production/version:

- `app/services/signals.py`: exact decision-candle guard before market economics.
- `app/__init__.py`, `pyproject.toml`: patch version 1.9.2.

Tests:

- `tests/unit/test_hourly_decision_candle_integrity_2026_07_04.py`: previous-hour substitution regression.

Docs/release:

- `README.md`, `CHANGELOG.md`, `PATCH_1.9.2.md`.
- `docs/ARCHITECTURE.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `OPERATOR_MANUAL.md`, `INCIDENT_RUNBOOK.md`.
- `docs/SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `QA_REPORT.md`, this report.
- generated `SHA256SUMS` after final cleanup.

No migration, environment variable, public API, DB model, model artifact, barrier multiplier, fee/slippage/funding formula or execution sizing change.

## 7. Red → green evidence

RED against untouched source 1.9.1:

```text
PYTHONPATH=. python -m pytest -q /tmp/test_hourly_decision_candle_integrity_2026_07_04.py
1 failed in 2.41s
AssertionError: a prior-hour feature window reached current-hour signal economics
```

The failure proves the previous-hour frame passed the old age gate and reached signal economics.

GREEN after the fix:

```text
python -m pytest -q \
  tests/unit/test_hourly_decision_candle_integrity_2026_07_04.py \
  tests/unit/test_quant_integrity_2026_07_02.py \
  tests/unit/test_inference_retry.py
13 passed in 2.91s
```

The regression oracle supplies `event_time`, previous `close_time` and a sentinel economics function independently from production output.

## 8. Migration, API/config/env and compatibility

- Alembic head remains `0009_candle_receipt_availability`; migration not required.
- No new/renamed `.env` variables.
- `MAX_CANDLE_AGE_SECONDS` remains accepted for backward compatibility and diagnostic stale classification, but no longer authorizes a previous-hour substitute.
- API JSON schemas, DB schema and model artifact schemas are unchanged.
- Retraining is not required solely by the patch.
- Existing records are not rewritten automatically. Suspect pre-1.9.2 recommendations require forensic comparison with stored candle/signal snapshots.

## 9. Post-check

| Command | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | 435 passed, 4 skipped, 55 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | one head `0009_candle_receipt_availability` |
| `python -m alembic upgrade head --sql` | PASSED; 853-line offline SQL generated |
| Static Bybit mutation scan | PASSED; create/amend/cancel flow not found |
| Secret filename scan | PASSED |
| `python manage.py release-check` | PASSED after final cleanup: 173 files checked, 173 manifest entries |

No previously green test became red. Full suite increased by one passing regression.

## 10. Not verified and why

- Real PostgreSQL migration/integration and transactional behavior: no isolated PostgreSQL server or `TEST_DATABASE_URL`.
- `manage.py doctor`: no operator `.env` or configured application database.
- Running candidate/incumbent metrics, rejection reasons, recommendations, accepted plans and fills: absent from source archive.
- Live Bybit smoke: not required to verify this deterministic time-anchor rule and would not substitute for database evidence.

## 11. Residual risks and limitations

- This fix prevents temporally early signals; it does not guarantee more recommendations and can correctly suppress the first retry until current candle ingestion completes.
- Other reasons for rare recommendations may be valid gates: insufficient 1206-timestamp history, class collapse, weak class-prior skill, policy EV/RR, spread, liquidity, margin or stale account data.
- Particular losing trades cannot be attributed without the running PostgreSQL state and operator fill journal.
- Historical order book/fills/operator latency/exact funding replay, complete rolling walk-forward, drift governance and PBO/DSR remain incomplete.
- Technical correctness and green tests are not evidence of profitable edge.

## 12. Rollback procedure

1. Stop API/worker/trainer.
2. Restore the 1.9.1 code tree; no DB downgrade or `.env` change is required.
3. Re-run release/doctor checks and restart.
4. Rollback is not recommended because it reopens previous-hour substitution. Do not emulate rollback by increasing `MAX_CANDLE_AGE_SECONDS`.

## 13. Recommended next work package

Export an operator-facing rejection and realized-loss dossier from the actual PostgreSQL database: per-hour worker skip counts, candidate absolute/relative gates, active artifact metadata, signal/plan immutable economics, accept/reject state, manual fills and outcome attribution. This is the minimum evidence needed to distinguish legitimate scarcity from another implementation defect without weakening safety thresholds.

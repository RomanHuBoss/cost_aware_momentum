# Iteration Report — 2026-07-03 — candle availability integrity

## 1. Input archive, SHA-256 and source version

- Input: `cost_aware_momentum-main.zip`.
- SHA-256: `0817de47461ad67551cab98a85216148bc3f5c71a34f3ad725e1125fec38f566`.
- Source version: `1.9.0`.
- Source Alembic head: `0008_outcome_path_unavailable`.
- Target version: `1.9.1`.

## 2. Goal and acceptance criteria

After this iteration late-fetched candles must be unavailable to point-in-time consumers until the actual Bybit response is received, and legacy rows must be corrected conservatively without inventing historical receipt timestamps.

Acceptance criteria:

1. `available_at` equals post-response receipt time for new candle snapshots.
2. `confirmed` remains based on market close versus receipt time.
3. Confirmed-candle immutability is preserved.
4. Legacy confirmed candles cannot appear available before migration time.
5. Alembic has exactly one revision head fitting the 32-character contract.
6. A regression test fails before and passes after the production change.
7. Existing unit/static/frontend checks do not regress.

## 3. Sources read and data flow

Read: README, CHANGELOG, patch notes, `pyproject.toml`, `.env.example`, architecture, QA, compliance, traceability, model card, configuration, security, incident runbook, operator manual and the relevant point-in-time sections of the bundled DOCX specification.

Affected flow:

```text
Bybit get_kline response
→ post-response receipt timestamp
→ _candle_values normalization
→ PostgreSQL Candle.available_at
→ market_cutoff + availability_cutoff queries
→ live inference / replay / outcome reconstruction
```

## 4. Baseline

The first run in the shared system Python was unusable because project dependencies were absent. An isolated virtualenv was created outside the release boundary and installed with `pip install -e '.[dev]'`.

| Command | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | 432 passed, 4 skipped, 55 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | one head `0008_outcome_path_unavailable` |
| `manage.py doctor` | NOT RUN: no operator config/database |
| PostgreSQL integration | NOT RUN: no isolated PostgreSQL available |

## 5. Confirmed defect

### HIGH — candle availability was backdated to market close

File/function: `app/services/market_data.py::_candle_values`.

Minimal reproduction: a candle closes at 09:00 and is first fetched at 12:00. Before the fix the insert parameters were `confirmed=True` and `available_at=09:00`. Expected `available_at=12:00`.

This allowed `Candle.available_at <= availability_cutoff` to pass for replay decisions between 09:00 and 12:00 even though the process had not received the row. Existing test coverage checked response-time confirmation but asserted the wrong availability value.

Impact: temporal leakage, non-reproducible replay and potentially overstated model/policy evidence. It does not by itself prove that any particular live loss was caused by this defect.

## 6. Plan and actual diff

Production:

- `app/services/market_data.py`: receipt-time availability.
- `migrations/versions/0009_candle_receipt_availability.py`: conservative data correction.
- version sources: `pyproject.toml`, `app/__init__.py`.

Tests:

- new `tests/unit/test_candle_availability_integrity_2026_07_03.py`;
- corrected receipt-time oracle in `test_point_in_time_candle_integrity_2026_07_01.py`;
- updated Alembic head contracts in unit/integration tests.

Docs/release:

- README, CHANGELOG, PATCH_1.9.1, QA, architecture, configuration, model card, operator manual, compliance, traceability and this report.

No risk thresholds, model gates, label geometry, execution-plan math, API schema or `.env` variables were changed.

## 7. Red → green evidence

RED:

```text
python -m pytest -q tests/unit/test_candle_availability_integrity_2026_07_03.py
2 failed
```

- observed `available_at=09:00` versus expected response receipt `12:00:07`;
- migration file missing.

GREEN:

```text
python -m pytest -q \
  tests/unit/test_candle_availability_integrity_2026_07_03.py \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py \
  tests/unit/test_migration_revision_contract.py
12 passed
```

The oracle uses an independently controlled response clock; it does not call the tested function to derive the expected timestamp.

## 8. Migration, API/config and compatibility

- New head: `0009_candle_receipt_availability`.
- Upgrade moves confirmed candle availability forward with `GREATEST(available_at, CURRENT_TIMESTAMP)`.
- No schema columns or public API fields change.
- No new environment variables.
- Downgrade is intentionally data-no-op because the original receipt timestamp never existed; restoring close-time values would reopen look-ahead.
- Existing 1.9.0 code can read the conservatively updated timestamps.

## 9. Post-check

| Command | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED after one import-order correction |
| `python -m pytest -q` | 434 passed, 4 skipped, 55 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | one head `0009_candle_receipt_availability` |
| `python -m alembic upgrade head --sql` | PASSED; migration SQL generated |

## 10. Not verified

- Real PostgreSQL upgrade and row-level data result: PostgreSQL client/server and isolated `TEST_DATABASE_URL` were unavailable.
- `manage.py doctor`: no configured local installation.
- Running-database candidate metrics, recommendations, accepted plans and fill journal were not in the archive.
- Bybit network smoke was not required for this deterministic timestamp fix.

## 11. Residual risks and limitations

- Legacy receipt time is unknowable; migration time is intentionally conservative.
- Replays before migration may now have less available history. They must be rerun rather than compared directly with old contaminated results.
- Exact executable-entry order book, no-fill, partial fill, operator delay and funding settlement replay remain incomplete.
- The low recommendation frequency may be correct under current fee/risk/model gates. Source code alone cannot justify lowering them.
- Technical correctness is not evidence of profitable edge.

## 12. Rollback

1. Stop processes and restore the pre-upgrade PostgreSQL backup if full state rollback is required.
2. Code-only rollback to 1.9.0 is compatible with the later `available_at` values, but it reintroduces incorrect timestamps for newly fetched candles and is not recommended.
3. Do not manually reset legacy rows to `close_time`; that recreates the confirmed temporal defect.

## 13. Recommended next work package

Build an operator-facing rejection/loss dossier from the real PostgreSQL state: candidate absolute/relative gate values, class and regime slices, signal/plan assumptions, accepted/manual fills and outcome attribution. This is necessary to determine why actual recommendations are rare and losing; it cannot be fabricated from the source archive.

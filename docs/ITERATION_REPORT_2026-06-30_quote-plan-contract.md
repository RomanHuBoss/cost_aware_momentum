# Iteration report — executable quote and plan contract

## 1. Input and baseline identity

- Input archive: `cost_aware_momentum-main.zip`.
- Input SHA-256: `540854cfbc878d4c838fd0866fb3eaf104f6ff4fb9f1fce6cef6b5c1a129c557`.
- Source version: `1.8.14`.
- Python requirement: `>=3.12`; verification runtime: Python `3.13.5`.
- Alembic head: `0006_manual_trade_remaining_risk`.
- Initial inventory: 68 production Python files, 34 test Python files, 21 documentation files and 6 migrations.
- Input release integrity: passed, 152 files and 152 manifest entries.
- No production `.env`, credentials, virtual environment, model artifact, cache or bytecode was present in the input archive. The old `SHA256SUMS` was valid for the input and is regenerated for the output.

## 2. Iteration goal and acceptance criteria

After this iteration, every user-visible or executable quote decision must use a finite, positive, non-crossed top-of-book pair, malformed ticker items must not abort a batch, and the published target list must exactly match the one-TP outcome/economics model.

Acceptance criteria:

1. `ask < bid`, missing sides and non-finite sides fail closed before signal ranking and acceptance.
2. Dynamic-universe selection handles `NaN`/`Infinity` as invalid data, not an exception.
3. A malformed ticker primary price is skipped without preventing valid rows in the same batch.
4. Entry-state uses ask for LONG and bid for SHORT.
5. New signals do not publish TP2 and use TP1 weight 100%.
6. API details do not advertise a legacy TP2 as executable guidance.
7. Existing tests remain green; no migration or environment change is introduced.

## 3. Sources and data flow reviewed

Reviewed: `README.md`, `CHANGELOG.md`, `PATCH_1.8.12.md`–`PATCH_1.8.14.md`, `pyproject.toml`, `.env.example`, architecture, QA, compliance, traceability, model card, configuration, security, incident runbook and operator manual; the supplied iterative prompt; and the embedded DOCX specification sections on top-of-book costs, fail-closed behavior, partial exits, labels and weighted plan economics.

Changed flow:

`Bybit ticker payload → finite parsing → universe/ticker snapshot → bid/ask validator → spread and LONG/SHORT economics → MarketSignal → profile ExecutionPlan → API entry-state/detail → accept-time revalidation`.

## 4. Baseline before edits

The host Python environment was not a valid project environment: host `pip check` reported an unrelated `moviepy`/`pillow` conflict, Ruff was absent and pytest could not import `psycopg`. A clean virtual environment was therefore created and the project installed with `.[dev]`; the reproducible baseline below is the project baseline.

| Command | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 282 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python manage.py release-check` on input | PASSED — 152/152 |
| `python manage.py test --require-integration` | NOT RUN — no safe disposable PostgreSQL URL |
| `python manage.py doctor` | NOT RUN — no application `.env`/PostgreSQL runtime configuration |

An exploratory, non-gating mypy run reported 143 typing errors across 29 files. Mypy is not configured as a release gate in this project; this broader typing debt was not mixed into the quantitative safety patch.

## 5. Confirmed defects

### QPC-01 — crossed quote accepted as negative spread

- Severity: **critical**.
- Evidence: `app/services/signals.py::_spread_bps` only checked positivity and calculated `(ask-bid)/mid`; `ask < bid` therefore produced a negative spread, bypassed the maximum-spread gate and entered scenario ranking.
- Acceptance path: `app/services/execution.py::executable_entry_price` validated only the selected side and did not validate the pair.
- Impact: impossible/corrupt market state could improve apparent costs, change direction selection and be accepted.
- Missing test: only missing/zero/NaN selected-side cases were covered, not crossed pairs.

### QPC-02 — advertised TP2 did not exist in the economic model

- Severity: **critical**.
- Evidence: `select_cost_aware_scenario` generated TP2 at `3.10 × ATR` and `publish_hourly_signals` stored a 70/30 split, while `net_rr_and_ev`, execution sizing, labels and outcome evaluation used only TP1.
- Impact: the operator was instructed to execute a partial-exit path whose EV, R/R, risk and model probabilities were never calculated.
- Specification conflict: partial exits require a real weighted path; a decorative second target is not compliant.
- Missing test: geometry tests asserted only TP1 and never checked target-contract parity.

### QPC-03 — non-finite ticker numerics aborted batches

- Severity: **high**.
- Evidence: `Decimal("NaN")` was accepted by parsers and later compared with zero in universe and ticker synchronization, raising `decimal.InvalidOperation`.
- Impact: one malformed instrument could interrupt the complete universe or ticker update and age otherwise valid data.
- Missing test: no mixed malformed/valid ticker batch existed.

### QPC-04 — UI entry-state used last instead of executable side

- Severity: **high**.
- Evidence: `app/api/serializers.py::entry_state` used `ticker.last_price`; accept-time validation used ask for LONG and bid for SHORT.
- Impact: the UI could show `IN_ENTRY_ZONE` while the actual marketable entry was outside the zone and acceptance would reject/recalculate.
- Missing test: no last-inside/ask-outside or last-inside/bid-outside case.

## 6. Plan and actual diff

Production:

- `app/services/execution.py`: shared bid/ask validator; acceptance uses validated pair.
- `app/services/signals.py`: finite quote/last/ATR validation; invalid spread blocked; TP2 deactivated and TP1 weight set to one.
- `app/services/market_data.py`: finite optional parser and malformed-row isolation.
- `app/services/universe.py`: non-finite decimals rejected before comparison.
- `app/api/serializers.py`: executable-side entry-state and one-target API contract.

Tests:

- `tests/unit/test_quote_plan_contract_2026_06_30.py`: six independent regression tests.

Version/docs:

- `app/__init__.py`, `pyproject.toml`, `README.md`, `CHANGELOG.md`;
- `PATCH_1.8.15.md`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/ARCHITECTURE.md`, `docs/MODEL_CARD.md`, `docs/OPERATOR_MANUAL.md`;
- this report and regenerated `SHA256SUMS`.

No migration, API endpoint, dependency or environment variable was added.

## 7. Red → green evidence

| Regression | Red evidence | Green evidence |
|---|---|---|
| crossed quote in signal policy | did not raise | raises fail-closed |
| crossed quote at acceptance boundary | did not raise | raises fail-closed |
| unmodeled TP2 | returned numeric TP2 | returns `None` |
| non-finite universe ticker | `decimal.InvalidOperation` | instrument excluded as invalid bid/ask |
| malformed ticker batch | `decimal.InvalidOperation` | malformed row skipped, valid row inserted |
| executable-side entry-state | returned `IN_ENTRY_ZONE` from last | returns `MISSED_ENTRY` from ask |

Commands and logs:

- first red run: `pytest -q tests/unit/test_quote_plan_contract_2026_06_30.py` → 5 failed;
- second red run: focused entry-state test → 1 failed;
- green focused run → 6 passed;
- full post-change unit suite → 288 passed, 4 skipped, 19 warnings.

## 8. Migration, API, configuration and compatibility

- Migration: none; head remains `0006_manual_trade_remaining_risk`.
- `.env`: no changes.
- API endpoints and JSON structure remain compatible; `take_profits` now contains only the target supported by current economics.
- Database TP2 columns remain nullable to avoid rewriting released migrations or breaking existing installations.
- Existing artifacts and policy metrics remain compatible; no retraining is required.

## 9. Post-check

Final post-check and release-integrity results:

- compileall: PASSED;
- Ruff: PASSED;
- pytest: PASSED — 288 passed, 4 skipped, 19 warnings;
- Node syntax: PASSED;
- release integrity: PASSED — 155 files checked, 155 manifest entries.

## 10. Not verified

- PostgreSQL integration tests, migration smoke on a clean DB and `manage.py doctor`: no safe disposable PostgreSQL/application configuration.
- Live Bybit network behavior: tests use deterministic local objects and no order-capable endpoint exists.
- Economic profitability, forward performance and live slippage: outside technical verification.

## 11. Residual risks and limitations

- A real weighted TP1/TP2 or trailing partial-exit policy remains absent. It requires path-dependent labels, probabilities or conditional policy assumptions, fee/funding timing, remaining-position risk and outcome valuation.
- Point-in-time historical universe membership, historical orderbook impact, multi-fold walk-forward, drift monitoring and production forward evidence remain documented gaps.
- The broad mypy debt remains; it should be handled as a separate maintainability package, not by weakening runtime gates.

## 12. Rollback

1. Stop API/worker/trainer.
2. Restore the 1.8.14 source archive; no database downgrade is needed.
3. Restart services.
4. Treat any restored TP2 display as unmodeled guidance; do not execute it as a weighted plan.

## 13. Recommended next work package

Implement account-scoped portfolio/reconciliation semantics: associate exchange position snapshots and manual-journal risk with an explicit account/profile scope, then prove that one hypothetical/manual profile cannot contaminate another profile’s risk or reconciliation state.

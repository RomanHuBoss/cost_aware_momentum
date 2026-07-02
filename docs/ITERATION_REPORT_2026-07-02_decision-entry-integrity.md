# Iteration report — 2026-07-02 — decision entry integrity

## 1. Вход, hash и версия

- Input archive: `cost_aware_momentum-main.zip`.
- SHA-256: `df82eab5721cf1922170594a20aef114eb6b8049a3387eef16696a33e7d23ec7`.
- Source version: `1.8.35`; result version: `1.8.36`.
- Python requirement: `>=3.12`; test runtime: Python 3.13.5.
- Alembic: revisions `0001`–`0008`, one head `0008_outcome_path_unavailable`.

## 2. Цель и критерии приемки

После итерации ни training label, ни holdout/promotion evidence не должны учитывать ценовое движение, произошедшее между close feature-свечи и первым observable entry в `decision_time`.

Критерии:

1. Entry proxy равен `open` первой непрерывной валидной label-свечи.
2. LONG up-gap и SHORT down-gap до entry не превращаются в мгновенный TP.
3. Barrier relative rates совпадают с live формулой `atr_pct_14 × multiplier`.
4. Entry audit field сохраняется в dataset/final-holdout metadata и валидируется.
5. Artifacts/evidence со старой семантикой fail-closed несовместимы.
6. Risk gates, advisory-only, PostgreSQL-only и process separation не ослаблены.
7. Full available static/unit suite не регрессирует.

## 3. Прочитанные источники и data flow

Прочитаны README, pyproject, `.env.example`, QA/compliance/traceability, architecture, model card, configuration, security, incident/operator docs, предыдущие iteration reports, source specification внутри проекта, ML features/labels/training/runtime/lifecycle, trainer, signals, execution/risk, backtest и tests.

Изменённый flow:

`confirmed hourly candles → feature row available at source close (`decision_time`) → first future bar open as entry proxy → ATR-percentage LONG/SHORT barriers → TP/SL/TIMEOUT path → realized return → purged split → policy metrics → guarded model activation`.

## 4. Baseline

В изолированном virtualenv:

- `python --version`: PASSED — 3.13.5.
- `python -m pip check`: PASSED.
- `python -m compileall -q app scripts tests manage.py`: PASSED.
- `python -m ruff check .`: PASSED.
- `python -m pytest -q`: **422 passed, 4 skipped, 19 warnings**.
- `node --check web/js/app.js`: PASSED.
- `python -m alembic heads`: PASSED — `0008_outcome_path_unavailable`.

System environment had unrelated dependency/tooling deficiencies and was not used as project baseline. PostgreSQL integration and doctor were not run without an isolated DB/runtime configuration.

## 5. Подтверждённые defects/gaps

### D1 — CONFIRMED DEFECT / HIGH / temporal + econometric + trading-policy parity

- File/function: `app/ml/training.py::make_barrier_dataset`.
- Old path: `current close → barriers centered on close → first future bar open checked for gap → realized return from close`.
- Reproduction: source close about 100, first post-decision open 110, subsequent path 109.5–111.1.
- Old result: LONG TP at open with `+0.01804`; SHORT SL at open with `-0.10`.
- Correct result: entry proxy 110; LONG TIMEOUT with `+0.004545`; no P&L exists before entry.
- Impact: label contamination, false direction/outcome evidence, distorted calibration and promotion economics.
- Missing test: existing tests validated gap handling after a modeled entry but did not validate when the entry itself becomes observable.

### D2 — CONFIRMED GAP / MEDIUM / auditability

Dataset did not persist the price used as entry, so downstream reviewers could not directly verify return/barrier alignment.

### D3 — CONFIRMED DEFECT / MEDIUM / release integrity

Input release lacked changelog, patch note and checksum manifest despite QA/traceability claims.

No evidence was supplied for the alleged exact counts of critical/medium defects. No additional issue was labeled fixed without reproduction.

## 6. План и фактический diff

Production:

- `app/ml/training.py`: decision-open entry, relative ATR barrier geometry, `entry_price`, metadata validation, schema bumps.
- `app/__init__.py`, `pyproject.toml`: version 1.8.36.

Tests:

- new `tests/unit/test_decision_time_entry_integrity_2026_07_02.py`.
- exact old label schema rejection in runtime test.
- policy schema fixtures updated to v9.

Docs/release:

- README, architecture, model card, configuration, operator manual, security, compliance, traceability and QA.
- new `CHANGELOG.md`, `PATCH_1.8.36.md`, this report and `SHA256SUMS`.

Migrations/API/env: none.

## 7. Red → green evidence

Command:

`python -m pytest -q tests/unit/test_decision_time_entry_integrity_2026_07_02.py`

Red on source behavior:

- first failure: `KeyError: 'entry_price'`;
- after exposing entry, barrier parity assertion failed: obtained `0.01640`, expected `0.01804`.

Green after complete fix: `2 passed`.

Targeted ML/lifecycle suite: `131 passed, 19 warnings` before the second symmetric test was added; final full suite is below.

## 8. Compatibility, migration and rollback risk

- No Alembic migration.
- No `.env` change.
- Public HTTP/API schema unchanged.
- Old model artifacts are intentionally incompatible by label-path schema; retraining is required.
- Old policy evidence v8 is intentionally incompatible; recalculation is required.
- Rollback source-only to 1.8.35 is technically possible, but re-enables pre-entry-gap contamination and is not recommended.

## 9. Post-check

- `python -m pip check`: PASSED.
- `python -m compileall -q app scripts tests manage.py`: PASSED.
- `python -m ruff check .`: PASSED.
- `python -m pytest -q`: **425 passed, 4 skipped, 19 warnings**.
- `node --check web/js/app.js`: PASSED.
- `python -m alembic heads`: PASSED — one head.
- release manifest/check: PASSED — 166 eligible files and 166 manifest entries.
- repacked ZIP integrity/rehydration: PASSED after packaging; archive SHA-256 reported to the user.

## 10. Непроверенное

- PostgreSQL integration/migration execution against a real isolated test DB.
- `manage.py doctor` against the user's `.env`, PostgreSQL, backup tools and Bybit connectivity.
- Actual candidate metrics, live signal snapshots and fills from the user's running database.
- Historical bid/ask/orderbook, operator latency, no-fill/partial-fill and exact funding path remain research limitations.

## 11. Остаточные риски

Hourly `open` is the best available decision-time proxy in the current dataset, not a guarantee of an executable bid/ask fill after network/operator delay. Profitability requires new OOS/forward evidence after retraining; old reported performance is not comparable.

## 12. Rollback

1. Stop API, worker and trainer.
2. Restore the 1.8.35 source tree; DB downgrade is unnecessary.
3. Restore only an artifact compatible with that code and verify hash/metadata.
4. Do not mix 1.8.36 model/evidence metadata with 1.8.35 runtime.

## 13. Рекомендуемый следующий work package

Build an entry-latency-aware research layer using point-in-time bid/ask or bounded slippage scenarios, then compare it with actual manual fills. This requires real operational data and was not implemented in this iteration.

# Iteration Report — 2026-07-02 — quantitative integrity

## 1. Входной архив, hash и исходная версия

- Input: `cost_aware_momentum-main.zip`
- SHA-256: `a9be1f4321153df46b716ab7c2df547aadd1db4a1e227b75819690551744d67b`
- Source version: `1.8.28`
- Python requirement: `>=3.12`
- Alembic head: `0007_position_account_scope`
- Input composition: 70 production Python files, 45 test Python files, 12 documentation/source-specification files, 8 migration Python files, 149 clean files total.
- Input boundary: no `.env`, credentials, venv, caches, bytecode, build/dist, dumps or real model artifacts.
- Release inconsistency: `CHANGELOG.md`, `PATCH_*.md` and `SHA256SUMS` were missing although the prior QA/report stated that they had been restored and verified.

## 2. Цель и критерии приемки

Цель: после итерации model probabilities, barrier geometry, auto-activation comparison and research backtest must refer to one explicit, validated quantitative task; incompatible or incomplete semantics must fail closed.

Acceptance criteria:

1. Signal policy uses the exact positive finite model ATR without undocumented floors/caps.
2. Runtime rejects missing or incompatible label-path and temporal-split schemas.
3. Candidate/incumbent relative evaluation occurs only for matching horizon and ATR barrier geometry.
4. Positive no-loss holdouts are distinguishable from missing/no-trade metrics.
5. Backtest uses the production artifact validator and can verify an expected SHA-256.
6. Advisory-only, PostgreSQL-only, process boundaries, API and DB schema remain unchanged.
7. Regression tests demonstrate red → green and the full suite remains green.
8. Release provenance files and manifest match the final archive.

## 3. Прочитанные источники и data flow

Read: `README.md`, `pyproject.toml`, `.env.example`, all current `docs/*.md`, prior iteration report, source DOCX specification sections on direction-specific labels, probability/barrier identity, temporal validation, costs, backtest and econometric threats; relevant production and test modules for features, labels, training, runtime, lifecycle, signals, risk math, execution, workers, backtest, release integrity and frontend boundary.

Changed data flows:

- confirmed hourly candles → contiguous features/ATR → model probabilities → exact ATR barrier geometry → current bid/ask economics → signal/plan;
- training labels + feature/label/temporal schema metadata → immutable artifact → hash/schema/classes/horizon/geometry validation → inference;
- candidate dataset/holdout → candidate model → incumbent load → horizon/geometry compatibility gate → same-task relative metrics → activation gate;
- policy exit-period outcomes → gross gain/loss → finite or explicitly unbounded profit factor → absolute quality gate;
- CLI model path + optional expected SHA → shared runtime validator → research dataset/backtest/report.

## 4. Baseline до правок

The system Python environment was not a valid project baseline: unrelated MoviePy/Pillow dependency conflict, missing Ruff and missing `psycopg` caused 21 pytest collection errors. A clean `.audit-venv` was created with `-e .[dev]` and excluded from release.

| Command | Result |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 393 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — one head `0007_position_account_scope` |
| `python manage.py doctor` | NOT RUN — no project-local `.venv`, `.env` or safe DB configuration |
| PostgreSQL integration | NOT RUN — no isolated test/admin URL |
| Input release integrity | FAILED — `SHA256SUMS` missing; 149 files, 0 manifest entries |

A green baseline did not prove quantitative correctness; the defects below were found with independent invariants and counterexamples.

## 5. Подтверждённые defects/gaps

### HIGH — hidden ATR task change at inference

- Path: `app/services/signals.py::publish_hourly_signals`.
- Before: `atr_pct = max(0.004, min(0.08, model_atr))`.
- Reproduction: model ATR `0.001` became `0.004`.
- Expected: probabilities and SL/TP geometry use the same ATR definition as the labels.
- Actual: live barriers could be four times farther while probabilities remained calibrated to the original task.
- Impact: wrong EV/RR and direction selection; monetary risk sizing still bounded the changed stop, so severity is HIGH rather than proven P0.
- Test gap: existing tests checked geometry and risk after a supplied ATR, not the hidden caller transformation.

### HIGH — artifact semantic schemas were not enforced

- Path: `app/ml/runtime.py::ModelRuntime.load`.
- Before: task, features/classes/horizon/multipliers were checked, but `label_path_schema_version` and `temporal_split_schema` were ignored.
- Reproduction: missing and legacy/random values loaded without error in four cases.
- Impact: an artifact trained with different intrabar path or leaky/random split semantics could reach inference under a compatible feature list.
- Test gap: fixtures asserted feature-schema and horizon failures only.

### HIGH — invalid candidate/incumbent apples-to-oranges comparison

- Path: `app/ml/lifecycle.py::build_model_candidate`.
- Reproduction: incumbent with stop/TP multipliers `1.50/3.00` was evaluated against candidate labels built at `1.15/2.20` and returned ordinary metrics.
- Expected: probabilities must be scored only against their own barrier task, or comparison must be unavailable.
- Impact: relative gate could promote/reject on mathematically invalid evidence.
- Fix: mismatch returns `comparison_skipped=incumbent_barrier_geometry_mismatch`; the quality gate blocks auto-activation.

### MEDIUM — no-loss profit factor conflated with missing data

- Paths: `app/ml/training.py::evaluate_policy_model`, `app/ml/lifecycle.py::evaluate_quality_gate`.
- Before: zero gross loss produced `profit_factor=None`; gate mapped all `None` to negative infinity.
- Impact: positive all-win holdout was rejected like no-trade/malformed data.
- Fix: explicit gross gain/loss and a validated unbounded flag; only `gain > 0` and `loss == 0` qualifies.

### HIGH (research integrity) — backtest bypassed artifact contract

- Path: `scripts/backtest.py::run`.
- Before: direct `joblib.load`, task-only check and silent default barrier multipliers.
- Impact: research metrics could be generated from an incompatible or partially specified artifact, undermining econometric evidence and reproducibility.
- Fix: shared `ModelRuntime`, optional expected hash and recorded artifact schemas/hash.

### MEDIUM — release evidence contradicted archive contents

- Paths: supplied root, prior `docs/QA_REPORT.md` and prior iteration report.
- Evidence: release checker failed with missing manifest; changelog and patch files were absent despite contrary claims.
- Impact: source/archive provenance was not reproducible.

### Unsupported reviewer counts

The claims of approximately 20 critical + 7 medium findings from unnamed experts and 18 critical findings from Claude Opus supplied no module, line, reproducer, report or test. This audit neither confirms nor disproves those counts. It found five quantitative defects and one release-provenance gap. No evidence-backed P0/critical defect was confirmed in the available environment.

## 6. План и фактический diff

Production:

- `app/services/signals.py` — remove hidden ATR clipping; invalid ATR blocks.
- `app/ml/training.py` — temporal schema constant and explicit profit-factor components.
- `app/ml/runtime.py` — semantic schema validation and metadata exposure.
- `app/ml/lifecycle.py` — label schema metrics and same-geometry incumbent comparison.
- `scripts/backtest.py` — shared validated artifact loader, optional hash and artifact metadata.
- `app/__init__.py`, `pyproject.toml` — version 1.8.29.

Tests:

- `tests/unit/test_quant_integrity_2026_07_02.py` — eight new regression/acceptance tests.
- Existing synthetic artifact fixtures updated to declare the now-required semantic schemas.

Docs/release:

- `README.md`, `CHANGELOG.md`, `PATCH_1.8.29.md`, `SHA256SUMS`.
- `docs/ARCHITECTURE.md`, `CONFIGURATION.md`, `INCIDENT_RUNBOOK.md`, `MODEL_CARD.md`, `OPERATOR_MANUAL.md`, `QA_REPORT.md`, `SECURITY.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md` and this report.

No migration, dependency, API or env change.

## 7. Red → green evidence

Command:

```text
python -m pytest -q tests/unit/test_quant_integrity_2026_07_02.py
```

Observed red stages before production fixes:

1. Six failures: exact ATR expected `0.001` but got `0.004`; four incompatible schema cases did not raise; no-loss quality gate returned `passed=False`.
2. Backtest acceptance test failed with `ImportError: cannot import name 'load_validated_artifact'`.
3. Barrier-geometry comparison returned incumbent metrics `{'rows': 1}` instead of a fail-closed skip.

Green after fixes: 8 passed. Tests use independent constants/counterexamples and do not use the tested functions as their own oracle.

## 8. Migration, API, config and compatibility

- Alembic: none; head remains `0007_position_account_scope`.
- API/JSON: unchanged.
- `.env`: no action and no new variables.
- Dependencies: unchanged.
- Behavioral compatibility: current trainer artifacts are compatible. Legacy artifacts lacking required label/temporal schemas are intentionally rejected; retrain rather than weakening validation.
- Rollout: restart API/worker/trainer and verify active model status. If blocked on schema metadata, keep incumbent disabled/unchanged as appropriate and train a current artifact.

## 9. Post-check

| Command/check | Result |
|---|---|
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED — all checks passed |
| `python -m pytest -q` | PASSED — 401 passed, 4 skipped, 19 warnings |
| dedicated regressions | PASSED — 8 passed |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — single head `0007_position_account_scope` |
| randomized independent quant audit | PASSED — 20,000 deterministic cases |
| advisory-only mutation scan | PASSED — no order/withdraw methods or endpoint literals |
| release integrity | PASSED — 153 source files checked, 153 manifest entries |

## 10. Не удалось проверить

- PostgreSQL integration and migration behavior on a real isolated PostgreSQL instance.
- Live/current Bybit public and read-only private API behavior.
- Browser E2E and operator workflow.
- Production model performance, profitability or robustness under forward conditions.

## 11. Остаточные риски и ограничения

- Live entry uses current executable bid/ask, while labels are anchored to historical hourly close because point-in-time historical executable quotes are incomplete. Large close-to-entry gaps remain a model-target distribution risk requiring historical quotes/order book or explicit entry-gap features.
- Backtest still lacks exact historical order book, no-fill/partial-fill, per-outcome funding settlement timeline and operator latency.
- Full expanding/rolling walk-forward, drift/regime monitoring, PBO/DSR and multiple-testing governance remain incomplete.
- Unit coverage is strong in quantitative core but does not replace PostgreSQL concurrency, external API and browser evidence.
- Green technical checks do not imply economic edge.

## 12. Rollback

1. Stop API, worker and trainer.
2. Restore the previous source archive and its matching model artifacts; no database downgrade is required.
3. Restart processes and verify active model registry/runtime consistency.
4. Do not cherry-pick only the version/docs files. The runtime, lifecycle, signals, training, backtest and tests form one integrity patch.

## 13. Следующий рекомендуемый work package

Implement point-in-time executable-entry research data: historical bid/ask or order-book snapshots, explicit close-to-entry gap/no-fill logic and exact settlement-crossing funding by outcome. Validate it in one purged walk-forward protocol before adding PBO/DSR or broader model complexity.

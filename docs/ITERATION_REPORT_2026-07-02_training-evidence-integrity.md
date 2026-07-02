# Iteration report — 2026-07-02 — training evidence integrity

## 1. Входной архив

- File: `cost_aware_momentum-main.zip`.
- SHA-256: `5fb73ee5eb5014960d317539b507374e4776edc1203dfb09cd1c1c851b8cdf91`.
- Source version: `1.8.33`; result version: `1.8.34`.
- Python requirement: `>=3.12`.
- Migrations: 8, single Alembic head `0008_outcome_path_unavailable`.
- Initial tree: 69 production/source Python files, 49 test Python files, 16 documentation files; no `.env`, secrets, model artifacts or database dumps. The input release omitted `PATCH_*.md` and `SHA256SUMS` despite repository documentation referring to them.

## 2. Цель и критерии приёмки

После итерации trainer не должен повторно строить детерминированный candidate после quality-gate rejection без нового data evidence, а model-promotion gate должен оценивать временную глубину по неперекрывающимся label windows и календарному span holdout.

Критерии:

1. Соседние hourly labels на horizon H не считаются независимыми до расстояния H.
2. Raw cohort count сохраняется как diagnostic, отдельный independent count используется gate.
3. Holdout короче 168 часов блокирует promotion независимо от cross-sectional rows.
4. Rejected bootstrap на том же profile после cooldown не запускается.
5. Retry разрешается после 168 новых timestamps либо material profile change.
6. Existing active model не деактивируется; advisory-only/PostgreSQL-only/process boundaries сохраняются.
7. Full unit suite, static checks и release integrity проходят.

## 3. Прочитанные источники и data flow

Прочитаны `README.md`, `CHANGELOG.md`, `pyproject.toml`, `.env.example`, architecture/QA/compliance/traceability/model-card/configuration/security/operator/runbook docs, все предыдущие iteration reports, релевантная DOCX specification, production ML/trainer/status modules и tests.

Изменяемый flow:

`confirmed hourly candles → training_data_profile / barrier dataset → purged train/calibration/final holdout → ML metrics + live-policy simulation → quality gate → immutable candidate registration/activation → trainer scheduling diagnostics/status`.

## 4. Baseline

Изолированный venv:

- `python --version`: PASSED — 3.13.5.
- `python -m pip check`: PASSED.
- `python -m compileall -q app scripts tests manage.py`: PASSED.
- `python -m ruff check .`: PASSED.
- `python -m pytest -q`: PASSED — 416 passed, 4 skipped, 19 warnings.
- `node --check web/js/app.js`: PASSED.
- `python -m alembic heads`: PASSED — `0008_outcome_path_unavailable`.

Global environment before isolated install could not collect tests because `psycopg`/ruff were absent and had an unrelated package conflict; these were classified as environment issues, not project defects.

## 5. Подтверждённые defects

### D1 — unchanged-data quality-gate retry loop — high

- Path: `app/workers/trainer.py::BackgroundTrainer.due_reason`.
- Actual: successful job with `activation_skipped=quality_gate_failed` used a 6h cooldown and then returned `due=True` for the same bootstrap episode without comparing the rejected attempt's data profile.
- Expected: deterministic re-fit requires new timestamps/material data change; explicit operator recovery may override scheduling but not gates.
- Impact: repeated identical failed candidates, compute waste, noisy registry and false appearance that “daily training” is learning from new evidence.
- Existing tests covered cooldown but not the post-cooldown unchanged-data state.

### D2 — raw hourly cohorts mislabelled as independent — high

- Paths: `app/ml/training.py::evaluate_policy_model`, `app/ml/lifecycle.py::evaluate_quality_gate`.
- Actual: `policy_cohorts = len(unique decision_time)` and gate used it as independent evidence.
- Reproducer: 20 consecutive hourly decisions with horizon 8 produced 20 counted cohorts although only timestamps 0h, 8h and 16h have non-overlapping label windows.
- Impact: inflated temporal sample size and unsafe confidence in promotion economics.
- Existing test only separated cross-sectional trades from timestamps; it did not test label overlap between timestamps.

### D3 — no minimum holdout calendar span — high

- Paths: `app/ml/training.py::evaluate_model`, `app/ml/lifecycle.py::evaluate_quality_gate`.
- Actual: 300 rows could pass through many symbols over 47 hours.
- Expected: row count and calendar coverage are separate gates.
- Impact: candidate may be judged on a narrow regime despite apparently large row count.

### G1 — release provenance missing — medium gap

Input tree omitted patch note and manifest referenced by release process. `PATCH_1.8.34.md` and regenerated `SHA256SUMS` restore the release boundary for this output.

## 6. План и фактический diff

Production:

- `app/ml/training.py` — holdout bounds, horizon-separated cohort count, schema v8.
- `app/ml/lifecycle.py` — span and independent-cohort absolute/relative gate validation.
- `app/workers/trainer.py` — compare rejected attempt profile before automatic retry.
- `app/config.py` — new validated holdout-span setting.
- `app/api/v1/status.py` — expose new thresholds.

Tests:

- New `tests/unit/test_training_evidence_integrity_2026_07_02.py`.
- Extended trainer scheduling tests.
- Updated current-schema fixtures and `evaluate_model` metadata fixtures.

Configuration/docs/release:

- `.env.example`, README, CHANGELOG, configuration/operator/model/security/compliance/traceability/QA docs, patch note and this report.
- No migration and no public order/trading API changes.

## 7. Red → green evidence

Command before production fix:

`python -m pytest -q tests/unit/test_training_evidence_integrity_2026_07_02.py tests/unit/test_trainer_recovery_scheduling.py::test_rejected_bootstrap_waits_for_new_training_data_after_cooldown`

Red result: 3 failed — missing `policy_independent_cohorts`, short holdout accepted, unchanged bootstrap returned `due=True`.

Green focused result after fix: 3 passed. Additional retry-resume contract passes after 168 new timestamps. Full suite: 420 passed, 4 skipped.

## 8. Migration/API/config compatibility

- Migration: none; Alembic head unchanged.
- API: additive diagnostics only; `minimum_policy_cohorts` is retained for compatibility and the semantically explicit `minimum_policy_independent_cohorts` alias is added.
- Env: additive `AUTO_TRAIN_MIN_HOLDOUT_SPAN_HOURS=168` with validation.
- Artifact/policy evidence: v7 evidence intentionally fails schema check and must be recomputed. Active incumbent remains active on candidate failure.
- Rollback compatibility: code rollback to 1.8.33 does not require DB rollback; v8 candidate evidence will not be understood by the old promotion gate and should not be manually activated there.

## 9. Post-check

- `python -m pip check`: PASSED.
- `python -m compileall -q app scripts tests manage.py migrations`: PASSED.
- `python -m ruff check .`: PASSED.
- `python -m pytest -q`: PASSED — 420 passed, 4 skipped, 19 warnings.
- `node --check web/js/app.js`: PASSED.
- `python -m alembic heads`: PASSED — one head.
- `python manage.py doctor`: FAILED ENVIRONMENT — missing `.env`, non-default secrets, PostgreSQL CLI/server.
- `python manage.py test --require-integration`: NOT RUN — no safe isolated PostgreSQL URL.

## 10. Не проверено

- Real PostgreSQL integration and migrations against a live test DB.
- User-specific candidate gate reasons, signal frequency and losses because runtime DB/artifacts/fills were not supplied.
- Real Bybit forward execution, order-book slippage, no-fill/latency and exact historical funding path.
- Economic profitability.

## 11. Остаточные риски

- One-week holdout minimum is a safety floor, not sufficient proof across regimes.
- Greedy horizon separation removes direct label overlap but does not prove statistical independence under autocorrelation/common market factors.
- Current model evaluation remains a single final holdout rather than full rolling walk-forward governance.
- More rigorous gates may reduce activations until sufficient history is accumulated.

## 12. Rollback

1. Stop API/worker/trainer.
2. Restore 1.8.33 source tree; no DB downgrade is required.
3. Restore prior `.env` if the new variable was added (old Settings ignores unknown env fields, so removal is optional).
4. Do not manually activate v8-only candidate evidence under 1.8.33.
5. Restart services and verify active incumbent checksum/status.

## 13. Рекомендуемый следующий work package

Implement rolling walk-forward evaluation with fixed untouched terminal holdout, regime/time-slice diagnostics and artifact-persisted fold evidence. This should be a separate iteration and requires enough historical data; it must not be approximated by repeatedly reusing the same final holdout.

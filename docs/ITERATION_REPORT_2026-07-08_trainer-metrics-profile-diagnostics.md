# Iteration report — 2026-07-08 — trainer metrics profile diagnostics

Дата: 2026-07-08. Целевая версия: 1.52.5.

## 1. Входной архив

- Входной ZIP: `cost_aware_momentum-main.zip`.
- SHA-256 входного ZIP: `1e3e0c117e3c47c616c113adbcc061c7f003dd9972217a55c1ba2ef69a99cbf4`.
- Исходная версия: 1.52.4.
- Python requirement: `>=3.12`.
- Alembic head: `0018_inference_observations`.
- Фактический root: `cost_aware_momentum-main`.
- До локальных проверок найдено 281 файлов; migrations: 18; production Python modules: app/scripts; tests: unit + PostgreSQL integration; documentation: README, changelog, docs, patch reports.
- В исходном ZIP не обнаружены `.env`, `.venv`, build/dist, `*.egg-info`, real model artifacts или dumps. `__pycache__`/`.pytest_cache` появились после локальных проверок и исключены из release archive.

## 2. Цель итерации и критерии приемки

После этой итерации trainer должен классифицировать rejected bootstrap/recovery candidate как data-dependent wait, если persisted previous training profile доступен не только в `trigger`, но и в candidate `metrics`; это подтверждается regression test и targeted trainer/UI suite.

Критерии приемки:

1. Previous profile извлекается из `trigger.training_data_profile`, как раньше.
2. Previous profile также извлекается из `metrics.training_data_profile`, если trigger profile отсутствует.
3. При unchanged profile и недостатке новых timestamps wait reason остаётся `quality_gate_failed_waiting_for_new_data` / `training_deferred_waiting_for_new_data`, а не generic cooldown.
4. Wait reason показывает `previous_profile_source`.
5. При отсутствии валидного profile в обоих местах generic fail-closed cooldown не ослабляется.
6. DB/API/env/model artifact contracts не меняются.

## 3. Прочитанные источники и data flow

Прочитаны: `README.md`, `CHANGELOG.md`, `PATCH_1.52.4.md`, `pyproject.toml`, `.env.example`, `docs/ARCHITECTURE.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/MODEL_CARD.md`, `docs/CONFIGURATION.md`, `docs/SECURITY.md`, `docs/INCIDENT_RUNBOOK.md`, `docs/OPERATOR_MANUAL.md`, `docs/source/Cost_aware_hourly_ML_momentum_specification.docx`, `app/workers/trainer.py`, `web/js/app.js`, trainer tests.

Затронутый flow:

`JobRun.details from previous model_retraining -> persisted previous profile evidence -> due_reason bootstrap retry classification -> ServiceHeartbeat.wait_reason -> status API/UI trainer dialog -> operator diagnostics`.

## 4. Baseline до правок

| Команда | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED / environment limitation | external `moviepy`/`pillow` conflict in shared environment |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | NOT COMPLETED | full suite process did not finish within available timeout; no passed claim made |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | FAILED / environment limitation | project-local `.venv`, `.env` and PostgreSQL unavailable |
| `python manage.py test --require-integration` | NOT RUN / environment limitation | no safe isolated PostgreSQL `TEST_DATABASE_URL` |

## 5. Подтвержденный defect/gap

### CONFIRMED DEFECT — data-dependent bootstrap skip ignored persisted profile in candidate metrics

- Severity: medium.
- Files: `app/workers/trainer.py::due_reason`.
- Expected: if latest successful bootstrap/recovery job has `activation_skipped=quality_gate_failed` and a persisted profile proving no new labeled timestamps, the scheduler reports `quality_gate_failed_waiting_for_new_data`.
- Actual before fix: when the previous profile existed only under `JobRun.details.metrics.training_data_profile`, scheduler ignored it and returned generic `training_cooldown_not_elapsed`.
- Impact: operator sees less actionable reason; after cooldown, trainer can retry the same bootstrap episode without evidence of new data instead of clearly waiting for new labeled timestamps.
- Why existing tests missed it: coverage only checked trigger-embedded profile and missing-profile generic fallback, not metrics-only legacy/candidate evidence.

## 6. План и фактический diff

Production:

- `app/workers/trainer.py` — added `_job_training_profile()` and used it in data-dependent bootstrap skip handling; wait reason now includes `previous_profile_source`.

Tests:

- `tests/unit/test_trainer_recovery_scheduling.py` — extended test helper and added metrics-only profile regression.

Docs/version:

- `pyproject.toml`, `app/__init__.py`, `README.md`, `CHANGELOG.md`, `PATCH_1.52.5.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/OPERATOR_MANUAL.md`, this report, `SHA256SUMS`.

Migrations/API/config/model schema: unchanged.

## 7. Red → green evidence

Red on 1.52.4 production code with new regression test:

```bash
python -m pytest -q tests/unit/test_trainer_recovery_scheduling.py::test_rejected_bootstrap_recovers_profile_from_candidate_metrics
```

Result: `1 failed`.

Key failure:

```text
AssertionError: assert 'training_cooldown_not_elapsed' == 'quality_gate_failed_waiting_for_new_data'
```

Green after fix:

```bash
python -m pytest -q tests/unit/test_trainer_recovery_scheduling.py tests/unit/test_trainer_operator_ui.py
```

Result: `16 passed`.

## 8. Migration/API/config compatibility

- Alembic migration: not required.
- API contract: unchanged.
- `.env`: unchanged.
- Model artifact schema: unchanged.
- Rollback risk: low; previous release can be restored without DB downgrade.

## 9. Post-check

| Команда | Статус | Результат |
|---|---|---|
| `python -m pip check` | FAILED / environment limitation | external `moviepy`/`pillow` conflict |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q tests/unit/test_trainer_recovery_scheduling.py tests/unit/test_trainer_operator_ui.py` | PASSED | 16 passed |
| `python -m pytest -q` | NOT COMPLETED | full suite did not finish within available timeout in shared environment; no passed claim made |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | FAILED / environment limitation | project-local `.venv`/PostgreSQL/.env absent |
| `python manage.py test --require-integration` | NOT RUN / environment limitation | safe PostgreSQL test DB absent |
| `python -B manage.py release-check --write` | PASSED after cleanup | clean manifest written |
| `python -B manage.py release-check` | PASSED after cleanup | release contract and checksums confirmed |

## 10. Что не удалось проверить

- Full `pytest -q` to normal process exit in this shared environment.
- PostgreSQL integration suite.
- `manage.py doctor` against a configured local installation.
- Live Bybit read-only smoke.
- Actual trainer run against the user's database.
- Economic profitability / forward performance.

## 11. Остаточные риски

- If prior job lacks valid `TrainingDataProfile` in both trigger and metrics, scheduler keeps generic cooldown by design.
- This patch improves scheduler evidence resolution; it does not lower quality gate thresholds or make rejected models pass.
- Shared-environment dependency/plugin state prevented a clean full-suite exit here.

## 12. Rollback procedure

Stop trainer/API, deploy 1.52.4 archive, reinstall dependencies by its `pyproject.toml`, restart trainer/API. No DB downgrade is required.

## 13. Recommended next work package

Investigate why the full pytest process does not reliably exit in this shared environment after unit completion, then add a test-environment teardown guard if the root cause is project-owned async/DB resource lifecycle rather than external pytest plugins.

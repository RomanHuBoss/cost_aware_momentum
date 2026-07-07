# Iteration report — 2026-07-08 — walk-forward deferral and contract diagnostics

## 1. Входной архив и исходная версия

- Входной архив: `cost_aware_momentum.zip`.
- SHA-256: `8cc184e5024ad18fd6dbf16ddfa9a6dfa26f79bf0fe661e4672d50258c810d95`.
- Исходная версия: `1.52.0`.
- Python requirement: `>=3.12`.
- Alembic head: `0018_inference_observations`.
- Inventory: 270 файлов; 98 production/script Python-файлов; 120 test Python-файлов; 13 documentation-файлов; 18 migrations.
- Во входном ZIP не обнаружены `.env`, secrets, virtual environments, caches, bytecode, `*.egg-info`, build/dist и реальные model artifacts.

## 2. Цель итерации и критерии приемки

Цель: после этой итерации ожидаемый дефицит post-feature/post-label development history должен оставаться fail-closed, но завершаться как диагностируемый `DEFERRED`, а не аварийный `FAILED/ERROR`; предупреждение decision-time execution contract должно сохранять безопасную структурированную причину блокировки.

Критерии приемки:

1. Теоретический history preflight и фактический expanding splitter используют единый capacity contract.
2. Недостаток timestamps после filtering поднимает отдельное исключение с actual/required capacity и machine-readable reason code.
3. Background job завершается технически `SUCCESS` с внутренним `DEFERRED`, trainer остаётся healthy/`WAITING`, incumbent не меняется.
4. Scheduler не повторяет тот же bootstrap в tight loop без новых timestamps или material profile change.
5. Decision-time contract warning включает безопасные reason/error/time/lag/limit поля.
6. Walk-forward folds, purge, holdout и quality/promotion gates не ослабляются.
7. Все исходно зелёные unit/static проверки остаются зелёными.
8. Release archive проходит manifest и clean re-extract verification.

## 3. Прочитанные источники и data flow

Прочитаны `README.md`, `CHANGELOG.md`, `PATCH_1.51.1.md`, `PATCH_1.52.0.md`, `pyproject.toml`, `.env.example`, `docs/ARCHITECTURE.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/MODEL_CARD.md`, `docs/CONFIGURATION.md`, `docs/SECURITY.md`, `docs/INCIDENT_RUNBOOK.md`, `docs/OPERATOR_MANUAL.md`, предыдущие iteration/audit reports, релевантная DOCX-спецификация, production modules и tests.

Изменяемый training flow:

```text
hourly PostgreSQL history
→ raw dataset profile / bootstrap preflight
→ point-in-time features, context and labels
→ chronological final holdout
→ purged expanding walk-forward development folds
→ candidate quality/policy gates
→ immutable artifact / optional activation
→ training job state and operator diagnostics
```

Изменяемый signal diagnostics flow:

```text
active artifact decision-time contract + runtime settings + event timestamp
→ fail-closed contract validation
→ publication blocked
→ structured JSON warning
```

## 4. Baseline до правок

Окружение: Python 3.13.5, external venv `/mnt/data/cam_work/testenv`.

| Команда | Результат |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | 846 passed, 8 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | `0018_inference_observations (head)` |
| `python manage.py doctor` | FAILED: project-local `.venv` отсутствует |
| `python manage.py test --require-integration` | NOT RUN: wrapper требует project-local `.venv`; отдельная safe PostgreSQL test DB отсутствует |

## 5. Подтверждённые defects

### DEFECT-1 — expected post-filter shortage classified as infrastructure failure

- Severity: high operational/ML lifecycle correctness.
- Files: `app/ml/training.py`, `app/ml/lifecycle.py`, `app/workers/trainer.py`.
- Фактический путь: raw profile может удовлетворить bootstrap minimum, но feature/context/label attrition и final-holdout boundary уменьшают development timestamps. `expanding_walk_forward_splits()` поднимал generic `ValueError`; общий handler записывал job `FAILED`, trainer `ERROR` и traceback.
- Ожидаемое поведение: candidate не строится и gates не ослабляются, но это retryable data-dependent `DEFERRED`, а incumbent остаётся активным.
- Почему существующие tests не поймали: splitter тестировал отказ отдельно, а trainer tests не связывали этот отказ с job-state semantics.

### DEFECT-2 — duplicated capacity formula could drift

- Severity: medium, temporal validation/maintenance.
- Files: `app/ml/training.py`.
- Фактическое поведение: raw minimum-history helper и splitter независимо повторяли block/initial-train formula. Они не предоставляли общий structured result и не могли объяснить разницу между raw preflight и post-filter capacity.
- Влияние: повторная рассинхронизация и непрозрачная операторская диагностика.

### DEFECT-3 — JSON formatter discarded contract diagnostics

- Severity: medium operational diagnostics.
- Files: `app/logging.py`, `app/services/signals.py`.
- Фактическое поведение: signal service передавал reason/error/time через `extra`, но whitelist formatter не включал эти поля; оператор видел только `Signal publication blocked by decision-time execution contract`.
- Ожидаемое поведение: fail-closed блокировка сохраняется, лог содержит reason code, sanitized mismatch, event/publish time, lag и configured limit.
- Почему tests не поймали: не было formatter-level contract test для этих fields.

События из пользовательского лога не образуют доказанную причинную цепочку: warning signal publication был зарегистрирован раньше training failure. Исправления объединены только как один incident-diagnostics package, а не как предположение, что trainer вызвал signal block.

## 6. План и фактический diff

### Production

- `app/ml/training.py` — единый `WalkForwardCapacity`, specialized exception, common minimum/capacity functions, splitter integration.
- `app/ml/lifecycle.py` — единое построение development frame и ранняя post-filter capacity check до основного final fit.
- `app/workers/trainer.py` — structured `DEFERRED`, healthy `WAITING`, data-dependent cooldown/retry semantics.
- `app/logging.py` — allowlist безопасных incident fields.
- `app/services/signals.py` — sanitized contract comparison details и lag metadata.
- `app/__init__.py`, `pyproject.toml` — версия 1.52.1.

### Tests

- `tests/unit/test_fail_closed_incident_diagnostics_2026_07_08.py` — capacity, trainer state и formatter regressions.
- `tests/unit/test_trainer_recovery_scheduling.py` — deferral retry scheduling.

### Docs/release

- `README.md`, `CHANGELOG.md`, `PATCH_1.52.1.md`.
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`.
- `docs/INCIDENT_RUNBOOK.md`, `docs/OPERATOR_MANUAL.md`.
- этот iteration report и пересчитанный `SHA256SUMS`.

Migrations, API schemas и `.env.example` не изменялись.

## 7. Red → green evidence

Red-команда на исходном production code:

```bash
python -m pytest -q tests/unit/test_fail_closed_incident_diagnostics_2026_07_08.py
```

Red: `3 failed` по правильным причинам:

1. generic exception не имел `.capacity`;
2. trainer возвращал `FAILED` вместо `DEFERRED`;
3. JSON formatter не сохранял `reason_code`.

Green после исправления: `3 passed`.

Новый scheduler test отдельно и в full suite подтверждает controlled wait after deferral.

## 8. Migration, API, config и compatibility

- Alembic migration: не требуется; head остаётся `0018_inference_observations`.
- Новые `.env` variables: отсутствуют.
- API contract: не изменён.
- Existing active artifact/incumbent: не деактивируется и не перезаписывается.
- Advisory-only и PostgreSQL-only boundaries сохранены.
- Deployment action: заменить файлы release и перезапустить inference worker и trainer.
- Roll-forward не требует DB migration.

## 9. Post-check

| Команда | Результат |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | 850 passed, 8 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | `0018_inference_observations (head)` |
| `python manage.py doctor` | FAILED / environment limitation: external venv не признаётся project-local `.venv` |
| `python manage.py test --require-integration` | NOT RUN: safe PostgreSQL test DB не настроена |
| `python -B manage.py release-check --write` / `release-check` | PASSED; 272 release files/manifest entries до packaging root rename, затем manifest пересчитан после финальных docs |
| ZIP integrity / clean re-extract | PASSED; один root directory, `unzip -t` без ошибок, forbidden artifacts отсутствуют |

Full unit suite увеличился с 846 до 850 passed: три incident regression tests и один scheduler regression test. Ни один прежний тест не стал красным.

## 10. Что не удалось проверить

- PostgreSQL integration suite — отсутствовала отдельная безопасная test database и project-local runtime wrapper остановил команду до tests.
- `manage.py doctor` в нативной project-local `.venv` — external audit venv намеренно не копировался в release tree.
- Windows service restart и реальный long-running trainer/worker smoke — недоступны в текущем Linux sandbox.
- Live Bybit/network behavior — credentials и сеть не использовались; изменённый scope не требует order/private API.
- Экономическая прибыльность и promotion outcome на реальных данных — не выводятся из unit tests.

## 11. Остаточные риски и ограничения

- `DEFERRED` может сохраняться дольше номинального числа часов из-за gaps и отсутствующего point-in-time context/spec/funding/mark evidence.
- Row-level undersize внутри отдельного fold также остаётся fail-closed и использует отдельный reason code.
- 62 dependency deprecation warnings требуют самостоятельной cleanup-итерации.
- Structured logging не заменяет durable DB/audit evidence; оно только возвращает потерянную operator diagnostics.
- Изменение не доказывает, что существующий active artifact экономически качественен.

## 12. Rollback procedure

1. Остановить worker и trainer.
2. Восстановить release 1.52.0 целиком, а не смешивать отдельные Python-файлы.
3. DB rollback не требуется: migrations отсутствуют.
4. Перезапустить процессы.
5. Учесть, что 1.52.0 снова классифицирует post-filter walk-forward shortage как `FAILED/ERROR` и теряет contract diagnostics; incumbent при самом исключении не должен удаляться.

## 13. Следующий рекомендуемый work package

Отдельно устранить 62 NumPy/pandas/joblib deprecation warnings с version-bounded regression tests, не смешивая dependency compatibility с торговой или ML-математикой.

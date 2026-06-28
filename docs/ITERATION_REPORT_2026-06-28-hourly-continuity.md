# Iteration report — strict hourly feature and label continuity

Дата: 2026-06-28

Версия после итерации: **1.7.11**
Scope: **hourly continuity for live features and training/backtest labels**

## 1. Входной архив, SHA-256 и исходная версия

- Входной архив: `cost_aware_momentum-main(2).zip`.
- SHA-256 входного ZIP: `c9f4d1a5ee22950781f70fb5b7fc271ae9845b7d5a70902db809c9eaa393e924`.
- Фактический корень: `cost_aware_momentum-main/`.
- Исходная версия: `1.7.10` в `app/__init__.py` и `pyproject.toml`.
- Python requirement: `>=3.12`.
- Alembic migrations: 5; единственный head — `0005_plan_outcome_invalid_input`.
- Исходные counts: 66 production Python files (`app/`, `scripts/`), 18 test files, 23 files under `docs/`, 5 migration files.

Release boundary входного архива не был чистым: присутствовали `.pytest_cache/`, `.ruff_cache/`, многочисленные `__pycache__/` и `*.pyc`, `cost_aware_momentum.egg-info/` с устаревшей metadata-версией `1.2.2`, а также старый `SHA256SUMS`. Корневые `CHANGELOG.md` и `PATCH_*.md` отсутствовали, хотя история предыдущих iteration reports ссылалась на release-процесс с такими файлами. Это зафиксировано как packaging/documentation inconsistency; функциональный scope итерации не расширялся на изменение application architecture.

## 2. Цель итерации и критерии приемки

**Цель:** после этой итерации live inference, training и backtest должны использовать признаки и barrier labels только из строго непрерывных часовых окон, что подтверждается независимыми regression tests, schema/diagnostic metadata и полным доступным test suite.

Критерии приемки:

1. Последний live feature snapshot не содержит значений, если в требуемом 24-часовом lookback есть пропущенная свеча.
2. Последний live feature snapshot не содержит значений, если в требуемом lookback есть дубликат timestamp.
3. Training label использует ровно timestamps `t+1h ... t+Nh`; окно с gap/duplicate исключается, а не растягивается до следующих N наблюдаемых строк.
4. После восстановления 24 последовательных переходов последующие валидные timestamps снова допускаются; весь symbol/history целиком не отбрасывается.
5. Training/backtest и новые model artifacts содержат явные continuity diagnostics и новый feature schema marker; recovery старого artifact сохраняет его прежний marker.
6. Advisory-only, PostgreSQL-only, разделение API/worker/trainer, DB schema, API JSON contract и `.env` contract не меняются.
7. Все доступные static/unit checks остаются зелеными; PostgreSQL integration не объявляется пройденной без отдельной test database.

## 3. Прочитанные источники и затронутый data flow

Прочитаны и сопоставлены:

- `README.md`, `pyproject.toml`, `.env.example`;
- `docs/ARCHITECTURE.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/MODEL_CARD.md`, `docs/CONFIGURATION.md`, `docs/SECURITY.md`, `docs/INCIDENT_RUNBOOK.md`, `docs/OPERATOR_MANUAL.md`;
- последние iteration reports для 1.7.7–1.7.10;
- `docs/source/Cost_aware_hourly_ML_momentum_specification.docx` в части point-in-time features, temporal validation и model lifecycle;
- production modules features/training/lifecycle/runtime/signals/backtest, ORM/model registry и связанные unit/PostgreSQL tests;
- входной мастер-промпт итеративной доработки.

До итерации корневые `CHANGELOG.md` и `PATCH_*.md` отсутствовали, поэтому фактическая последовательность изменений восстанавливалась по `docs/QA_REPORT.md` и versioned `docs/ITERATION_REPORT_*.md`.

Затронутые потоки:

### Live inference

`PostgreSQL confirmed Candle rows` → `app.services.signals._candles_frame()` → `app.ml.features.latest_feature_snapshot()` → data-quality gate → `ModelRuntime.predict()` → cost/risk policy → `MarketSignal` → API/UI.

Изменение находится до prediction/publication: non-contiguous feature history возвращает пустой vector и существующий signal service пропускает symbol с диагностикой.

### Training / activation

`PostgreSQL confirmed hourly candles` → `train_candidate()` → `make_barrier_dataset()` → `chronological_split()` → calibration/holdout evaluation → immutable `.joblib` artifact → quality gate → model registry/activation.

Изменение находится на dataset boundary: каждый feature timestamp и его будущий label-window проверяются по timestamps до split и fit. Candidate/incumbent lifecycle, quality gates и atomic activation не ослаблены.

### Research backtest

`confirmed hourly candles` → `make_barrier_dataset()` → model fit/evaluation → policy simulation → JSON report. Report дополнен теми же continuity counts, которые использует trainer.

## 4. Baseline до правок

Baseline запускался до изменения production code.

### Host environment

| Команда | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED (external environment) | установленный вне проекта `moviepy 2.2.1` требует `pillow<12`, host содержит Pillow 12.2.0 |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | UNAVAILABLE | host Python не содержал Ruff |
| `python -m pytest -q` | FAILED (environment/collection) | 8 collection errors: отсутствовал `psycopg` |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python manage.py doctor` | NOT RUN by manager | manager остановился: нет project-local `.venv` |
| `python manage.py test --require-integration` | NOT RUN by manager | manager остановился: нет project-local `.venv` |
| `python -m alembic heads` | PASSED | `0005_plan_outcome_invalid_input (head)` |

### Изолированное окружение из declared dependencies

Создан отдельный venv вне release tree; SQLite и production database не использовались.

| Команда | Статус | Результат |
|---|---|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| `python -m pytest -q` | PASSED | **133 passed, 3 skipped, 19 warnings** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | `0005_plan_outcome_invalid_input (head)` |

Три skipped tests — PostgreSQL integration tests без `TEST_DATABASE_URL`. 19 warnings исходят из совместимости joblib с NumPy 2.5 в существующем runtime artifact test и не созданы этим patch.

## 5. Подтвержденный defect

### CONFIRMED DEFECT — row-count windows изменяли временную семантику

- **Severity:** high.
- **Файлы:** `app/ml/features.py::build_feature_frame`, `app/ml/features.py::latest_feature_snapshot`, `app/ml/training.py::make_barrier_dataset`; live consumer — `app/services/signals.py::publish_hourly_signals`.
- **Фактическое поведение:** feature returns вычислялись через `groupby.diff(24)`, rolling indicators — по 24 наблюдаемым строкам, а label — по следующим N наблюдаемым строкам. Timestamp continuity не проверялась.
- **Минимальное воспроизведение:** 90 часовых timestamps с отсутствующим hour 75. На 1.7.10 `latest_feature_snapshot()` вернул все 10 finite features, включая `ret_24h`, хотя фактический интервал между текущей и 24-й предыдущей строкой был длиннее 24 часов. Аналогично дубликат timestamp не блокировал vector. В training history с отсутствующим hour 60 dataset сохранял labels для timestamps 56–59, чьи следующие четыре наблюдаемые строки пересекали gap.
- **Ожидаемое поведение:** full 24-hour feature contract требует 24 последовательных перехода ровно по одному часу; N-hour label требует timestamps `t+1h ... t+Nh`.
- **Влияние:** live signal мог быть опубликован с feature semantics, отличающейся от заявленной; training/backtest могли присваивать N-hour label событию, наступившему позже N часов. Это влияет на model fit, holdout metrics, policy gate и сопоставимость live/research.
- **Почему тесты не поймали:** существующие fixtures содержали регулярные hourly timestamps и проверяли schema/temporal split, но не gap/duplicate внутри feature lookback и label window.

Это не external API issue и не гипотетический рыночный риск: исходное поведение воспроизведено unit tests на неизмененном 1.7.10 production code.

## 6. План и фактический diff

Планировалось локальное изменение ML data boundary без DB/API/config refactor:

1. вычислить continuity metadata рядом с feature calculations;
2. fail closed в live snapshot до model runtime;
3. проверить exact future timestamps при построении labels;
4. сохранить aggregate diagnostics в training/backtest/artifact;
5. version new feature schema, не переписывая старые artifacts;
6. добавить regression tests и синхронизировать release docs.

Фактически изменены production/version files:

- `app/ml/features.py`;
- `app/ml/training.py`;
- `app/ml/lifecycle.py`;
- `app/ml/artifact_recovery.py`;
- `app/services/signals.py`;
- `scripts/backtest.py`;
- `app/__init__.py`;
- `pyproject.toml`.

Tests:

- `tests/unit/test_labels_features.py`;
- `tests/unit/test_training.py`;
- `tests/unit/test_model_artifact_recovery.py`.

Documentation/release:

- `README.md`;
- `CHANGELOG.md` (создан);
- `PATCH_1.7.11.md` (создан);
- `docs/ARCHITECTURE.md`;
- `docs/MODEL_CARD.md`;
- `docs/QA_REPORT.md`;
- `docs/SPEC_COMPLIANCE.md`;
- `docs/TRACEABILITY.md`;
- `docs/INCIDENT_RUNBOOK.md`;
- `docs/OPERATOR_MANUAL.md`;
- этот iteration report.

Migration/config/API files не изменялись. Packaging cleanup удаляет только generated/stale release artifacts и пересоздает `SHA256SUMS`.

## 7. Red → green evidence

Regression tests сначала были добавлены поверх копии исходного 1.7.10, без production fix.

Команда RED:

```bash
python -m pytest -q \
  tests/unit/test_labels_features.py::test_feature_snapshot_fails_closed_on_gap_in_required_hourly_lookback \
  tests/unit/test_labels_features.py::test_feature_snapshot_fails_closed_on_duplicate_in_required_hourly_lookback \
  tests/unit/test_training.py::test_barrier_dataset_excludes_non_contiguous_feature_and_label_windows
```

RED result на 1.7.10: **3 failed**.

Существенные причины:

- gap case: ожидалось `{}`, фактически возвращены 10 features;
- duplicate case: ожидалось `{}`, фактически возвращены 10 features;
- label case: timestamps 56–59 присутствовали в dataset, хотя future N-hour sequence пересекала отсутствующий hour 60.

GREEN result после исправления той же команды: **3 passed**. Расширенный targeted suite features/training/recovery: **19 passed**.

Тесты используют независимый oracle — конкретные UTC timestamps и требование ровно одного часа между соседними свечами; результат проверяемой функции не используется для построения ожидаемого значения.

## 8. Migration, API, config и compatibility

- Alembic migration: **не требуется**; schema head остается `0005_plan_outcome_invalid_input`.
- `.env`: новых переменных нет.
- REST/API schema: не изменена.
- Existing DB rows: не мигрируются и не переписываются.
- Existing model artifacts: остаются читаемыми; recovery сохраняет artifact `feature_schema_version`, а при отсутствии marker использует legacy fallback `hourly-barrier-v1`.
- New artifacts: `feature_schema_version=hourly-barrier-contiguous-v2`, continuity metadata `schema=strict-hourly-v1`.
- Baseline runtime signal marker: `hourly-core-contiguous-v2`.
- При непрерывной истории численные formulas и feature order не меняются; меняется admissibility затронутых timestamps.
- Advisory-only и read-only Bybit boundary сохранены.

Операторское действие после обновления: перезапустить API/worker/trainer. Для получения нового artifact schema выполнить обычное переобучение; действующий legacy artifact не требуется удалять вручную.

## 9. Post-check

Финальные результаты записываются после проверки release tree и повторной распаковки ZIP. Итоговые authoritative counts:

| Команда | Статус | Результат |
|---|---|---|
| isolated `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| targeted continuity tests | PASSED | 3 passed |
| targeted features/training/recovery | PASSED | 19 passed |
| `python -m pytest -q` | PASSED | **136 passed, 3 skipped, 19 warnings** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | `0005_plan_outcome_invalid_input (head)` |
| PostgreSQL integration test module | SKIPPED | 3 skipped: `TEST_DATABASE_URL` отсутствует |
| `python manage.py doctor` | NOT RUN by manager | project-local `.venv`/native PostgreSQL environment не настроены |
| `python manage.py test --require-integration` | NOT RUN by manager | project-local `.venv` отсутствует; отдельная test DB не настроена |
| release archive test / re-extract | PASSED | one root, clean artifact scan, checksum verification |

## 10. Что не удалось проверить

- Реальная PostgreSQL migration/integration suite не запускалась: отсутствуют отдельная безопасная test database и `TEST_DATABASE_URL`. Три integration tests корректно skipped; production DB не использовалась.
- `manage.py doctor` не прошел до application checks, поскольку проект специально не содержит release `.venv` и локальную native configuration в sandbox.
- Не выполнялся network smoke с Bybit и не использовались реальные API credentials.
- Не выполнялось фактическое обучение на пользовательской полной истории, auto-activation либо forward/paper evidence. Unit correctness не является доказательством прибыльности.
- Windows-native startup не запускался в Linux sandbox.

## 11. Остаточные риски и ограничения

- Gap не синтезируется и не ремонтируется автоматически; затронутые timestamps блокируются/исключаются до восстановления непрерывного окна.
- Diagnostics агрегируются по training run, но отдельный persistent data-quality incident для каждого gap не создается.
- Hourly training labels по-прежнему используют conservative SL при неоднозначном одновременном касании TP/SL внутри одной hourly candle; доступная lower-timeframe path semantics пока не перенесена в training/backtest.
- Полный multi-fold walk-forward, drift monitoring, point-in-time historical universe membership, historical orderbook impact и forward profitability evidence остаются незакрытыми требованиями.
- Legacy artifact schema marker честно сохраняется; это не означает, что исторический artifact был обучен на strict-continuity dataset.

## 12. Rollback procedure

1. Остановить API, inference worker и trainer.
2. Восстановить файлы версии 1.7.10 или предыдущий release ZIP.
3. Не выполнять Alembic downgrade: migration в этой итерации отсутствует.
4. Не удалять registry rows/artifacts, созданные 1.7.11, автоматически. Если новый candidate был активирован, использовать существующий reviewed model rollback/activation CLI для возврата на выбранный immutable artifact.
5. Перезапустить процессы и проверить status/readiness/model version.

Rollback возвращает прежнее row-based admissibility и потому повторно открывает описанный temporal correctness defect.

## 13. Рекомендуемый следующий work package

**Перенести exact lower-timeframe intrabar resolution в training/backtest labels.** Сейчас точный 1/3/5-minute path уже используется для post-event outcomes, но model dataset при одновременном hourly TP/SL touch остается conservative-SL. Следующая отдельная итерация должна определить point-in-time coverage contract, доказать fallback behavior и сравнить label/policy metrics без смешивания scope с walk-forward или live execution.

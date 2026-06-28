# QA report

Дата проверки версии 1.7.12: 28 июня 2026 г.

## Итерация 1.7.12 — monotonic manual fill chronology

Подтвержден data-integrity defect: `POST /api/v1/trades/{id}/close` проверял status и remaining qty, но не сравнивал `fill_time` с entry и предыдущими fills. Поэтому partial/full close мог быть записан раньше открытия либо более ранним временем после уже сохраненного partial close.

| Проверка | Baseline 1.7.11 | Post-check 1.7.12 |
|---|---|---|
| isolated `python -m pip check` | PASSED | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED | PASSED |
| `python -m ruff check .` | PASSED | PASSED |
| `python -m pytest -q` | PASSED — 136 passed, 3 skipped, 19 warnings | PASSED — 139 passed, 3 skipped, 19 warnings |
| manual chronology regression tests | RED — 2 failed, 1 passed на исходном production code | GREEN — 3 passed |
| `node --check web/js/app.js` | PASSED | PASSED |
| `alembic heads` | `0005_plan_outcome_invalid_input` | `0005_plan_outcome_invalid_input` |
| PostgreSQL integration | NOT RUN — нет отдельной test database | NOT RUN — нет отдельной test database |

Close flow теперь блокирует `ManualTrade` через `FOR UPDATE`, читает последний `Fill.fill_time` и отклоняет время раньше entry/latest fill с HTTP 422 до изменения remaining qty, P&L, audit/outbox и idempotency result. Одинаковый timestamp разрешен для нескольких фактических fills. Migration и `.env`-изменения не требуются.

Полный отчет: `docs/ITERATION_REPORT_2026-06-28-manual-fill-chronology.md`.

Дата проверки версии 1.7.11: 28 июня 2026 г.

## Итерация 1.7.11 — strict hourly feature/label continuity

Подтвержден high-severity ML/live correctness defect: rolling features и barrier labels использовали количество наблюдаемых строк. При пропущенной часовой свече `ret_24h` фактически охватывал более 24 часов, а N-bar label — более N часов; live worker мог опубликовать signal по такому вектору.

| Проверка | Baseline 1.7.10 | Post-check 1.7.11 |
|---|---|---|
| isolated `python -m pip check` | PASSED | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED | PASSED |
| `python -m ruff check .` | PASSED | PASSED |
| `python -m pytest -q` | PASSED — 133 passed, 3 skipped, 19 warnings | PASSED — 136 passed, 3 skipped, 19 warnings |
| continuity regression tests | RED — 3 failed на исходном production code | GREEN — 3 passed |
| `node --check web/js/app.js` | PASSED | PASSED |
| `alembic heads` | `0005_plan_outcome_invalid_input` | `0005_plan_outcome_invalid_input` |
| PostgreSQL integration | NOT RUN — нет отдельной test database | NOT RUN — нет отдельной test database |

Новый contract требует 24 последовательных одночасовых перехода для полного feature-lookback и ровно N следующих hourly candles для label. Live snapshot при gap возвращает пустой vector с `NON_CONTIGUOUS_HOURLY_HISTORY`; training/backtest исключают только затронутые timestamps и сохраняют counts в `hourly_continuity`. Новые artifacts имеют `feature_schema_version=hourly-barrier-contiguous-v2`; старые artifacts не переписываются.

Дата проверки версии 1.7.10: 28 июня 2026 г.

## Итерация 1.7.10 — label-end-aware temporal purge

Подтвержден high-severity ML temporal defect: barrier label строился по следующим N наблюдаемым свечам, а purge между train/calibration/final-holdout задавался как N wall-clock часов. При пропусках свечей train-label мог использовать OHLC уже из calibration window, и same-holdout quality gate получал оптимистично загрязненную оценку.

| Проверка | Результат |
|---|---|
| Input ZIP SHA-256 | `d68133e676485d2597a96bffd6e2388a9f4677f0be19be6587ba98b0581bbdf1` |
| Initial host baseline | FAILED/UNAVAILABLE — отсутствовали `ruff` и `psycopg`; внешний `moviepy/pillow` conflict; зафиксировано до создания isolated environment |
| Baseline isolated `python -m pytest -q` | PASSED — 131 passed, 3 skipped, 20 warnings |
| RED temporal regression | PASSED как доказательство дефекта — 2 failed; train label ended `2025-02-19T20:00Z`, calibration began `2025-02-19T08:00Z` |
| `python -m pip check` | PASSED — No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 133 passed, 3 skipped, 19 warnings |
| targeted training tests | PASSED — 8 passed |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | PASSED — `0005_plan_outcome_invalid_input` |
| `python manage.py doctor` | FAILED (environment) — project-local `.venv`, `.env` and PostgreSQL native setup are not configured |
| PostgreSQL integration | SKIPPED — 3 tests; `TEST_DATABASE_URL` is not configured |
| Migration / `.env` | не требуется |

Новые training rows содержат `label_end_time`. Split отклоняет отсутствующие/невалидные timestamps и проверяет, что train label ends строго раньше calibration features, а calibration label ends — раньше final holdout. Horizon-hour embargo после границы сохранен. Новые artifacts получают `temporal_split_schema=label-end-purged-v2` и отдельный `label_data_end`; существующие artifacts не переписываются.

Полный отчет: `docs/ITERATION_REPORT_2026-06-28-label-end-temporal-purge.md`.

Дата проверки версии 1.7.9: 28 июня 2026 г.

## Итерация 1.7.9 — class-order-safe multiclass log loss

Подтвержден high-severity ML metric defect: model probability columns имели artifact-порядок `TP / SL / TIMEOUT`, но `sklearn.metrics.log_loss` интерпретировал строковые labels лексикографически как `SL / TIMEOUT / TP`. Из-за этого quality gate мог сохранять `log_loss_above_limit` при нормальных Brier/ECE и не активировать подходящий candidate.

| Проверка | Результат |
|---|---|
| Input ZIP SHA-256 | `27742e2e3b4649e0161015e4b7dfc4c9813afbcda2a92b72b82b92b761028fc0` |
| Baseline isolated `python -m pytest -q` | PASSED — 129 passed, 3 skipped, 20 warnings |
| Baseline training tests | PASSED — 4 passed |
| RED class-order regression | PASSED как доказательство дефекта — expected `0.1053605`, получено `2.9957323` |
| `python -m pip check` | PASSED — No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 131 passed, 3 skipped, 20 warnings |
| targeted training tests | PASSED — 6 passed |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | PASSED — `0005_plan_outcome_invalid_input` |
| PostgreSQL integration | NOT RUN — отдельная test database и `TEST_DATABASE_URL` отсутствуют |
| Migration / `.env` | не требуется |

Новый расчет выбирает вероятность истинного класса по явному `model.classes_`, проверяет форму/finite/range/row sum и сохраняет `classification_metric_schema=ordered-probability-v2`. Metrics также содержат raw/calibrated log loss, calibration improvement и training class-prior/uniform benchmarks. Исторические registry rows не переписываются.

Полный отчет: `docs/ITERATION_REPORT_2026-06-28-log-loss-class-order.md`.

Дата проверки версии 1.7.8: 28 июня 2026 г.

## Итерация 1.7.8 — atomic model candidate promotion

Подтвержден high-severity lifecycle defect: новый candidate сначала коммитился как inactive с `activation_requested=true`, а затем активировался во второй транзакции. Сбой процесса, БД, audit или outbox между этими операциями оставлял промежуточное registry-состояние и требовал отдельного восстановления.

| Проверка | Результат |
|---|---|
| Input ZIP SHA-256 | `df0cbffd190fd0d7575aab141c848b1c1bdfede03998ecd060d422c382bf02d5` |
| Baseline isolated `python -m pytest -q` | PASSED — 126 passed, 3 skipped, 20 warnings |
| RED atomic-promotion test | PASSED как доказательство gap — collection error: отсутствовал `register_and_activate_model_candidate` |
| `python -m pip check` | PASSED — No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 129 passed, 3 skipped, 20 warnings |
| targeted atomic/lifecycle/recovery tests | PASSED — 14 passed |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | PASSED — `0005_plan_outcome_invalid_input` |
| release ZIP / re-extracted full suite | PASSED — one root, clean artifact scan, 129 passed, 3 skipped |
| `python manage.py doctor` | FAILED (environment) — project-local `.venv`/application environment not configured |
| PostgreSQL integration | NOT RUN — отдельная test database и `TEST_DATABASE_URL` отсутствуют |
| Migration / `.env` | не требуется |

Новый atomic service валидирует artifact до mutation, блокирует active-row, проверяет expected incumbent и в одной транзакции выполняет candidate insertion, candidate audit/outbox, incumbent deactivation, activation и activation audit/outbox. Background trainer, manual `train --activate` и новый gate-passed orphan recovery используют этот путь; failed/manual-review candidates остаются inactive.

Host baseline отдельно зафиксирован: внешний MoviePy/Pillow conflict, отсутствующие Ruff/psycopg и 7 collection errors. Production code проверяется в isolated environment из `.[dev]`; SQLite/fake application database не применялась.

Полный отчет: `docs/ITERATION_REPORT_2026-06-28-atomic-model-promotion.md`.

Дата проверки версии 1.7.7: 28 июня 2026 г.

## Итерация 1.7.7 — controlled orphan model recovery and diagnostics

Подтвержден operational gap: наличие нового `.joblib` в `MODEL_DIR` не означало active model, однако status/UI не различали inactive candidate, failed gate и orphan artifact. Безопасного CLI для повторной регистрации уже созданного artifact при отсутствующей usable active-модели не было.

| Проверка | Результат |
|---|---|
| Input ZIP SHA-256 | `dc7caaf4bd0f733ad92d7b3426bced5770eefe7dedb96b516b0fb55f8887bd4a` |
| Baseline isolated `python -m pytest -q` | PASSED — 120 passed, 3 skipped, 20 warnings |
| Red recovery tests | PASSED как доказательство gap — collection error: отсутствовал `app.ml.artifact_recovery` |
| `python -m pip check` | PASSED — No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 126 passed, 3 skipped, 20 warnings |
| targeted recovery/diagnostics tests | PASSED — 17 passed |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | PASSED — `0005_plan_outcome_invalid_input` |
| `model_registry --help` | PASSED — `recover-artifact` присутствует |
| `python -m scripts.doctor` | FAILED (environment) — 6 ошибок: `.env`, secrets, PostgreSQL tools/service |
| PostgreSQL integration | NOT RUN — отдельная test database отсутствует; 3 integration tests skipped |
| Migration / `.env` | не требуется |

Host baseline также зафиксирован: внешний MoviePy/Pillow conflict, отсутствующие Ruff/psycopg. Production code проверен в isolated environment из `.[dev]`. Реальная пользовательская model/DB не были доступны, поэтому фактический gate result файла `barrier-logistic-h8-20260628T072708Z.joblib` не заявляется.

Полный отчет: `docs/ITERATION_REPORT_2026-06-28-model-artifact-reconciliation.md`.

## Итерация 1.7.6 — fail-closed counterfactual plan valuation

Подтвержден defect post-event financial boundary: `estimate_plan_outcome()` не проверял finite Decimal values. `NaN` вызывал `decimal.InvalidOperation` либо попадал в P&L, бесконечные stress/reserve значения ошибочно получали `VALUED`, а поврежденная plan version могла прервать обработку последующих outcomes.

| Проверка | Результат |
|---|---|
| Input ZIP SHA-256 | `d86b3ca56d134b1ecf528398df2adf5e70812a26b85778d7bad3b871678790f7` |
| Baseline isolated `python -m pytest -q` | PASSED — 111 passed, 3 skipped, 20 warnings |
| Red counterfactual tests | PASSED как доказательство дефекта — 8 failed, 12 passed |
| `python -m pip check` | PASSED — No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 120 passed, 3 skipped, 20 warnings |
| targeted counterfactual tests | PASSED — 21 passed |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | PASSED — `0005_plan_outcome_invalid_input` |
| `python manage.py doctor` | FAILED (environment) — project-local `.venv`/`.env` и PostgreSQL tools/service отсутствуют |
| PostgreSQL integration | NOT RUN — `TEST_DATABASE_URL` и отдельная PostgreSQL test database отсутствуют; 3 integration tests корректно skipped в full suite |
| Migration / `.env` | требуется `python manage.py migrate`; новые `.env` переменные не требуются |

Host environment до isolated setup также зафиксирован: `pip check` выявил внешний MoviePy/Pillow conflict, Ruff и psycopg отсутствовали, из-за чего host pytest завершился collection errors. Production fix проверен в isolated environment из `.[dev]`; SQLite/fake application database не применялась.

Полный отчет: `docs/ITERATION_REPORT_2026-06-28-plan-outcome-input-validation.md`.

## Итерация 1.7.5 — fail-closed numeric sizing inputs

Подтвержден defect финансовой boundary: `calculate_position_plan()` доверял non-price Decimal inputs. `NaN` в capital/margin/caps и zero `qty_step` приводили к необработанным исключениям, infinite risk rate мог вернуть non-blocked plan, а отрицательная fee уменьшала downside и формировала `ACTIONABLE` sizing.

| Проверка | Результат |
|---|---|
| Input ZIP SHA-256 | `fe1f05616b7099c384d865d6eb25e95b9aab5da27b511cb1d0d5214487e3ce4c` |
| Baseline isolated `python -m pytest -q` | PASSED — 103 passed, 3 skipped, 20 warnings |
| Red risk-input tests | PASSED как доказательство дефекта — 7 failed, 19 passed |
| `python -m pip check` | PASSED — No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 111 passed, 3 skipped, 20 warnings |
| targeted risk tests | PASSED — 26 passed |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | PASSED — `0004_counterfactual_outcomes` |
| `python manage.py doctor` | FAILED (environment) — 6 failures: `.env`, default secrets, PostgreSQL tools/service |
| PostgreSQL integration | NOT RUN — `POSTGRES_ADMIN_URL`/`TEST_DATABASE_URL` и отдельная test database отсутствуют |
| Migration / `.env` | не требуется |

Host Python environment до isolated setup также зафиксирован: `pip check` выявил внешний MoviePy/Pillow conflict, Ruff и psycopg отсутствовали. Production fix проверен в isolated environment из `.[dev]`; SQLite/fake application database не применялась.

Полный отчет: `docs/ITERATION_REPORT_2026-06-28-risk-input-validation.md`.

## Итерация 1.7.4 — fail-closed directional geometry

Подтвержден дефект risk boundary: `stress_downside_rate()` и `upside_rate()` использовали абсолютную разницу цен и принимали инвертированные LONG/SHORT stop/TP как положительные расстояния. В результате corrupted/legacy/imported signal мог получить ненулевой sizing, а ручной fill за stop-границей приводил к необработанной ошибке после введения строгой проверки.

| Проверка | Результат |
|---|---|
| Input ZIP SHA-256 | `7a6149eb3e5a3a61350836bbe50717edadea9fbeaf75257a77d654050c6fca54` |
| Baseline isolated `python -m pytest -q` | PASSED — 96 passed, 3 skipped, 20 warnings |
| Red risk tests | PASSED как доказательство дефекта — 5 failed: 4 inverted geometries не вызывали ошибку, sizing не принимал `take_profit` и не мог проверить полный контракт |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 103 passed, 3 skipped, 20 warnings |
| directional risk/outcome targeted tests | PASSED — 37 passed |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | PASSED — `0004_counterfactual_outcomes` |
| `python manage.py doctor` | FAILED (environment) — `.env`, безопасные secrets, PostgreSQL tools/service отсутствуют |
| PostgreSQL integration | NOT RUN — `POSTGRES_ADMIN_URL`/`TEST_DATABASE_URL` и отдельная test database отсутствуют |
| Migration / `.env` | не требуется |

Host Python environment до создания изолированного окружения не использовался как проектный oracle: `pip check` выявил внешний конфликт MoviePy/Pillow, Ruff и psycopg отсутствовали. В isolated environment, установленном из `.[dev]`, `pip check` прошел.

Полный отчет: `docs/ITERATION_REPORT_2026-06-28-directional-geometry.md`.

## Итерация 1.7.3 — немедленное bootstrap/recovery training

Подтвержден scheduler gap версии 1.7.2: worker переходил на deterministic baseline при удаленном active artifact, но trainer продолжал применять обычные dataset-change/scheduled triggers и мог наследовать шестичасовой cooldown от несвязанного failure. Исправление выделяет отсутствие пригодной ML-модели в отдельный bootstrap episode.

| Проверка | Результат |
|---|---|
| Input ZIP SHA-256 | `3495386c9ed9f056641b1d6a39c2fff7aee7bc02e23b23d08a9ec93481b94852` |
| Baseline `python -m pytest -q` | PASSED — 88 passed, 3 skipped |
| Red scheduler tests | PASSED как доказательство gap — 4 failed: отсутствовал `bootstrap_recovery`, применялся `not_enough_new_or_changed_training_data`/общий cooldown |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 96 passed, 3 skipped |
| recovery scheduler targeted tests | PASSED — 7 passed |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | PASSED — `0004_counterfactual_outcomes` |
| PostgreSQL integration | NOT RUN — отдельная test database отсутствует |
| Migration | не требуется |

`python -m pip check` в host environment остается FAILED из-за внешнего конфликта `moviepy 2.2.1`/`pillow 12.2.0`, не объявленного данным проектом. Scheduler проверен unit-level с deterministic profiles и mock async DB methods; SQLite/fake application database не применялась.

Полный отчет: `docs/ITERATION_REPORT_2026-06-28-model-bootstrap-recovery.md`.

## Итерация 1.7.2 — recovery после удаления active model artifact

Подтвержден пользовательский startup failure: registry-active модель оставалась в PostgreSQL, но удаленный `.joblib` приводил к завершению inference worker до heartbeat. Исправление добавляет controlled baseline fallback и bootstrap recovery trainer без ослабления production/integrity boundary.

| Проверка | Результат |
|---|---|
| Input ZIP SHA-256 | `75740b1e1a908e4a7040ee5bbaa6f9d8b2876e253d5e5eaa3d82b3d2c158788b` |
| Baseline `python -m pytest -q` | PASSED — 77 passed, 3 skipped |
| Red regression test | PASSED как доказательство gap — collection failed: `ModuleNotFoundError: app.ml.runtime_selection` |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 88 passed, 3 skipped |
| model fallback targeted tests | PASSED — 11 passed |
| `node --check web/js/app.js` | PASSED |
| PostgreSQL integration | NOT RUN — отдельная test database отсутствует |
| Migration | не требуется; head остается `0004_counterfactual_outcomes` |

`python -m pip check` в host environment остается FAILED из-за внешнего конфликта `moviepy 2.2.1`/`pillow 12.2.0`, не объявленного данным проектом. Missing artifact recovery проверен unit-level через фактический `Worker.refresh_model_runtime()` с mock PostgreSQL session; SQLite/fake application database не применялась.

Полный отчет: `docs/ITERATION_REPORT_2026-06-28-model-artifact-recovery.md`.

## Историческая проверка версии 1.7.1

## Итерация 1.7.1 — JSON-safe model lifecycle

Подтвержден пользовательский PostgreSQL failure при регистрации candidate: JSONB отвергал `-Infinity` в `quality_gate.relative.incumbent_policy_realized_mean_r`. Исправление отделяет внутренние fail-closed sentinels от сериализуемых значений и нормализует model/trainer/audit JSON payload.

| Проверка | Результат |
|---|---|
| Input ZIP SHA-256 | `58e1270f61c0d6efc8e731790e8a5cbe673278d021fe61e7b2d3db9bd80732b6` |
| Red regression tests | PASSED как доказательство дефекта — 2 tests failed с strict-JSON `-inf` |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 77 passed, 3 skipped |
| lifecycle/json targeted tests | PASSED — 7 passed |
| `node --check web/js/app.js` | PASSED |
| PostgreSQL integration | NOT RUN — отдельная test database отсутствует |
| Migration | не требуется; head остается `0004_counterfactual_outcomes` |

`python -m pip check` в host environment остается FAILED из-за внешнего конфликта `moviepy 2.2.1`/`pillow 12.2.0`, не объявленного данным проектом. Полный отчет: `docs/ITERATION_REPORT_2026-06-28-model-registry-json-safety.md`.

## Историческая проверка версии 1.7.0

## Baseline до изменений

Входной архив: `cost_aware_momentum-main(4).zip`, SHA-256 `4653f12d4d99311a3303797535d541b696610e3118b9a677fdb08666c337bac7`.

Проверки исходной версии 1.6.0 выполнены в изолированном Python environment после установки declared dependencies:

| Проверка | Результат |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED — broken requirements не обнаружены |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 67 passed, 3 skipped, 20 warnings |
| `node --check web/js/app.js` | PASSED |
| `python manage.py doctor` | FAILED (environment) — нет `.env`, native PostgreSQL tools/service и безопасных credentials |
| `python manage.py test --require-integration` | NOT RUN — отсутствуют `POSTGRES_ADMIN_URL`/`TEST_DATABASE_URL` и отдельная PostgreSQL test database |

Первый запуск в host environment без declared dev/runtime dependencies был также зафиксирован: Ruff и psycopg отсутствовали, поэтому он не использовался как доказательство качества проекта.

## Post-check версии 1.7.0

| Проверка | Результат |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 74 passed, 3 skipped, 20 warnings |
| `python -m pytest -q tests/unit/test_intrabar_outcomes.py` | PASSED — 7 passed |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | PASSED — единственный head `0004_counterfactual_outcomes` |
| Версия пакета / приложения | `1.7.0` / `1.7.0` |
| `python manage.py doctor` | FAILED (environment) — нет `.env`, замененных secrets, PostgreSQL service и `psql`/`pg_dump`/`pg_restore` |
| `python manage.py test --require-integration` | UNAVAILABLE — отдельная PostgreSQL test database не настроена |

3 skipped tests являются PostgreSQL integration tests и не заменены SQLite/fake database.

## Red → green evidence

До production implementation создан и запущен новый module:

```text
python -m pytest -q tests/unit/test_intrabar_outcomes.py
```

RED: collection завершилась `ImportError: cannot import name 'CandleWindow' from 'app.services.market_data'`.

GREEN: тот же module прошел — `7 passed`.

## Проверенный контракт intrabar outcome

Unit tests и static analysis подтверждают:

1. hourly non-ambiguous TP/SL/TIMEOUT behavior сохранено;
2. LONG и SHORT используют правильную directional geometry;
3. hourly TP+SL разрешается по первому касанию в complete 1/3/5-minute path;
4. source candle и exit time получают intrabar precision;
5. missing intermediate intrabar оставляет outcome pending;
6. TP+SL внутри одного finest bar дает conservative SL и `ambiguous=true`;
7. точечный fetch использует только public/read-only kline window с exact `start`, `end`, `interval`, `limit`;
8. запросы дедуплицируются по symbol/start/end и ограничиваются конфигурацией;
9. fetch error не создает выдуманный outcome;
10. existing immutable outcome, plan valuation, audit/outbox и advisory-only границы не изменены.

## Проверка внешнего контракта Bybit

28 июня 2026 г. проверена официальная документация Bybit V5 `Get Kline`: endpoint является `GET /v5/market/kline`, принимает `start`, `end`, `limit` и интервалы `1`, `3`, `5` среди поддерживаемых. Production tests используют mock/fake client и не выполняют торговых операций.

## PostgreSQL integration tests

В среде сборки отсутствовали PostgreSQL server/native utilities и отдельная test database. Миграция не менялась, но DB flow с existing `market.candles` и `advisory.signal_outcomes` не проверялся фактической concurrent integration с PostgreSQL.

Перед эксплуатацией выполнить:

```powershell
$env:POSTGRES_ADMIN_URL="postgresql+psycopg://postgres:ПАРОЛЬ@localhost:5432/postgres"
py -3.12 manage.py test --require-integration
Remove-Item Env:POSTGRES_ADMIN_URL
```

Дополнительно проверить worker smoke-test на paper/shadow:

1. hourly bar с TP1+SL;
2. загрузку 12 пяти-минутных candles для одного часа;
3. pending при неполном path;
4. повторный cycle после восстановления API;
5. audit/outbox/API detail для intrabar-resolved outcome.

## Release boundary

Проверяется перед упаковкой:

- Bybit client содержит только GET/public/read-only methods;
- PostgreSQL-only и advisory-only границы сохранены;
- release исключает `.env`, credentials, `.venv`, caches, `*.egg-info`, dumps и real model artifacts;
- `SHA256SUMS` пересчитывается после финального состава release.

## Не покрыто данной проверкой

- фактический PostgreSQL integration/concurrency run;
- длительный worker smoke-test на реальном потоке Bybit;
- intrabar reconstruction в training labels и backtest;
- TP2/partial exits, no-fill, operator latency и historical orderbook impact;
- comparison counterfactual estimate с manual fills;
- paper/shadow forward evidence и экономическое преимущество стратегии.

Финальные release hash и повторная распаковка фиксируются в `docs/ITERATION_REPORT_2026-06-28_intrabar-outcomes.md`.

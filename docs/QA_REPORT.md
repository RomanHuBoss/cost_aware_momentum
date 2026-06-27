# QA report

Дата проверки версии 1.5.0: 28 июня 2026 г.

## Выполненные проверки

| Проверка | Результат |
|---|---|
| `python -m ruff check .` | пройдена |
| `python -m compileall -q app scripts tests` | пройдена |
| полный `python -m pytest -q` | 54 теста пройдено, 2 PostgreSQL integration-теста пропущены |
| `node --check web/js/app.js` | пройдена |
| Версия пакета / приложения | `1.5.0` / `1.5.0` |
| Проверка запрещенных order endpoints | методов создания/изменения/отмены ордеров не обнаружено |
| Проверка мусора релиза | `*.egg-info`, cache-каталоги и `SHA256SUMS` в итоговый архив не включаются |

## Проверка dataset-aware trainer

Проверено unit-тестами и статическим анализом:

1. background trainer является отдельным процессом и не выполняет fitting внутри FastAPI или inference worker;
2. supervisor запускает trainer вместе с API/worker при `AUTO_TRAIN_ENABLED=true`;
3. каждый цикл создает новый immutable artifact и сохраняет его атомарно;
4. active artifact и candidate сохраняют полный `training_data_profile`: строки свечей, timestamps, полный состав символов, временные границы, coverage и SHA256-подписи;
5. trainer использует тот же детерминированный top-N scope, что и ручное обучение;
6. переобучение запускается не только по новым timestamps, но и после существенного historical row growth, появления новых покрытых символов, изменения top-N universe либо отсутствия profile у legacy-модели;
7. небольшое несущественное расширение датасета не вызывает лишний цикл обучения;
8. dataset-change trigger имеет отдельный cooldown и не отменяет обычное недельное расписание;
9. bootstrap/candidate блокируется, если недостаточная доля символов имеет минимальную глубину истории;
10. candidate оценивается абсолютным quality gate по holdout size, class balance, log loss, multiclass Brier и ECE;
11. candidate и incumbent дополнительно сравниваются на одной cost-aware holdout policy по числу сделок, realized mean R, profit factor и drawdown;
12. материальная ML- или policy-регрессия блокирует автоматическую активацию;
13. при `AUTO_TRAIN_REQUIRE_IMPROVEMENT=true` отсутствие достаточного улучшения блокирует автоматическую активацию;
14. activation защищена ожидаемой предыдущей active-version;
15. session advisory lock предотвращает конкурентный fitting несколькими trainer instances;
16. ошибка обучения или провал gate не деактивируют текущую модель;
17. `ACTIVE_MODEL_PATH` отключает registry auto-activation;
18. trainer heartbeat, phase, wait reason и data profile включены в status/readiness.

## Проверка progressive history backfill

Проверено, что:

- быстрый стартовый backfill не блокирует запуск на полную глубину;
- отдельный job `history_backfill` расширяет историю активного universe назад малыми пакетами;
- глубина ограничивается `HISTORY_BACKFILL_TARGET_DAYS` и launch time инструмента;
- число символов и REST-страниц на цикл ограничивается конфигурацией;
- ошибка отдельного символа не прерывает весь цикл;
- прогресс и ошибки сохраняются в `job_runs` и worker heartbeat;
- trainer оценивает уже фактически сохраненные в PostgreSQL данные, а не предполагаемую глубину lookback.

## Проверка ML-контракта

Проверено, что:

- модель возвращает нормированное распределение `TP`, `SL`, `TIMEOUT`;
- pooled модель учитывает взаимодействия признаков с LONG/SHORT direction;
- barrier dataset создает оба сценария на symbol/time;
- chronological split не разделяет один timestamp между окнами и сохраняет purge gap;
- runtime отвергает legacy binary-direction artifact;
- runtime проверяет task, feature list, classes, version и SHA256;
- unsafe production defaults отклоняются конфигурацией;
- baseline явно помечается как некалиброванная заглушка;
- trained model и registry version должны совпадать в readiness;
- policy evaluation применяет те же пороги net R/R, net EV и базовые cost assumptions, что и live policy;
- текущие рекомендации API фильтруются по актуальному worker universe;
- UI обновляет system status, universe и trainer state каждые 30 секунд.

## PostgreSQL integration tests

В текущей среде отдельная PostgreSQL test database не была настроена, поэтому 2 integration-теста пропущены. Перед эксплуатацией выполните:

```powershell
$env:POSTGRES_ADMIN_URL="postgresql+psycopg://postgres:ПАРОЛЬ@localhost:5432/postgres"
py -3.12 manage.py test --require-integration
Remove-Item Env:POSTGRES_ADMIN_URL
```

Дополнительно требуется эксплуатационный smoke-test на отдельной тестовой базе:

1. дождаться нескольких `history_backfill` jobs;
2. убедиться, что `candle_rows`, `symbol_count` и coverage в status растут;
3. дождаться dataset-change trigger и события `MODEL_CANDIDATE_TRAINED`;
4. проверить `ops.job_runs`, heartbeat `trainer`, artifact SHA256 и `training_data_profile`;
5. при прохождении gate проверить атомарную auto-activation и загрузку новой active-version worker;
6. подтвердить, что провал gate оставляет прежнюю модель активной.

## Не покрыто данной проверкой

- качество модели на реальной накопленной истории конкретной установки;
- profitability/OOS stability и paper/shadow forward evidence;
- многократный walk-forward и OOF aggregation;
- исторический orderbook, partial fills и operator latency;
- PSI/live calibration drift и realized-performance auto-rollback;
- нагрузочное обучение на полном динамическом universe;
- backup/restore на инфраструктуре пользователя.

## Обязательная приемка

1. `python manage.py migrate` — новых миграций в 1.5.0 нет, но head должен быть актуален.
2. `python manage.py doctor`.
3. PostgreSQL integration tests с отдельной базой.
4. `/health/ready` после появления heartbeat worker и trainer.
5. Проверка прогресса `history_backfill` и профиля доступного датасета.
6. Проверка первого автоматически созданного background candidate в `model-registry list`.
7. Проверка auto-activation только после прохождения ML- и policy-gates.
8. Backup + restore-check.
9. Paper/shadow forward period до любого production advisory использования.

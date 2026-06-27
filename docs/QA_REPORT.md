# QA report

Дата проверки версии 1.4.0: 27 июня 2026 г.

## Выполненные проверки

| Проверка | Результат |
|---|---|
| `ruff check app scripts tests migrations manage.py` | пройдена |
| `python -m compileall -q app scripts migrations tests manage.py` | пройдена |
| `pytest tests/unit -q` | 47 unit-тестов пройдено |
| полный `pytest -q` | 47 пройдено, 2 PostgreSQL integration-теста пропущены |
| `node --check web/js/app.js` | пройдена |
| Версия пакета / приложения | `1.4.0` / `1.4.0` |
| Проверка запрещенных order endpoints | методов создания/изменения/отмены ордеров не обнаружено |
| Проверка мусора релиза | `*.egg-info` и `SHA256SUMS` в проект не включены |

## Проверка фонового trainer

Проверено unit-тестами и статическим анализом:

1. background trainer является отдельным процессом и не выполняет fitting внутри FastAPI или inference worker;
2. supervisor запускает trainer вместе с API/worker при `AUTO_TRAIN_ENABLED=true`;
3. каждый цикл создает новый immutable artifact и сохраняет его атомарно;
4. candidate оценивается абсолютным quality gate по holdout size, class balance, log loss, multiclass Brier и ECE;
5. candidate сравнивается с incumbent на одном holdout;
6. материальная регрессия блокирует автоматическую активацию;
7. при `AUTO_TRAIN_REQUIRE_IMPROVEMENT=true` отсутствие улучшения блокирует автоматическую активацию;
8. activation защищена ожидаемой предыдущей active-version;
9. session advisory lock предотвращает конкурентный fitting несколькими trainer instances;
10. ошибка обучения или провал gate не деактивируют текущую модель;
11. `ACTIVE_MODEL_PATH` отключает registry auto-activation;
12. trainer heartbeat и phase включены в status/readiness.

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
- trained model и registry version должны совпадать в readiness.

## PostgreSQL integration tests

В текущей среде отдельная PostgreSQL test database не была настроена, поэтому 2 integration-теста пропущены. Перед эксплуатацией выполните:

```powershell
$env:POSTGRES_ADMIN_URL="postgresql+psycopg://postgres:ПАРОЛЬ@localhost:5432/postgres"
py -3.12 manage.py test --require-integration
Remove-Item Env:POSTGRES_ADMIN_URL
```

Дополнительно требуется эксплуатационный smoke-test trainer на реальной тестовой базе: дождаться `MODEL_CANDIDATE_TRAINED`, проверить `ops.job_runs`, heartbeat `trainer`, artifact SHA256 и загрузку новой active-version worker.

## Не покрыто данной проверкой

- качество модели на реальной накопленной истории конкретной установки;
- profitability/OOS stability и paper/shadow forward evidence;
- многократный walk-forward и OOF aggregation;
- historical orderbook, partial fills и operator latency;
- PSI/live calibration drift и realized-performance auto-rollback;
- нагрузочное обучение на полном динамическом universe;
- backup/restore на инфраструктуре пользователя.

## Обязательная приемка

1. `python manage.py migrate` — новых миграций в 1.4.0 нет, но head должен быть актуален.
2. `python manage.py doctor`.
3. PostgreSQL integration tests с отдельной базой.
4. `/health/ready` после появления heartbeat worker и trainer.
5. Проверка первого background candidate в `model-registry list`.
6. Backup + restore-check.
7. Paper/shadow forward period до любого production advisory использования.

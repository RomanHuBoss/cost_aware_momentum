# QA report

Дата проверки версии 1.3.0: 27 июня 2026 г.

## Выполненные проверки

| Проверка | Результат |
|---|---|
| `ruff check app scripts tests migrations manage.py` | пройдена |
| `python -m compileall -q app scripts migrations tests manage.py` | пройдена |
| `pytest tests/unit -q` | 43 unit-теста пройдены |
| `node --check web/js/app.js` | пройдена |
| Версия пакета / приложения | `1.3.0` / `1.3.0` |
| Проверка запрещенных order endpoints | методов создания/изменения/отмены ордеров не обнаружено |
| Проверка мусора релиза | `*.egg-info` и `SHA256SUMS` в проект не включены |

## Проверка ML-контракта 1.3.0

Проверено unit-тестами и статическим анализом:

1. модель возвращает нормированное распределение `TP`, `SL`, `TIMEOUT`;
2. pooled модель учитывает взаимодействия признаков с LONG/SHORT direction;
3. barrier dataset создает оба сценария на symbol/time;
4. chronological split не разделяет один timestamp между окнами и сохраняет purge gap;
5. runtime отвергает legacy binary-direction artifact;
6. runtime проверяет task, feature list, classes, version и SHA256;
7. unsafe production defaults отклоняются конфигурацией;
8. baseline явно помечается как некалиброванная заглушка;
9. trained model и registry version должны совпадать в readiness.

## Проверка данных и публикации

Проверено, что live inference:

- выбирает только confirmed candles с `close_time <= event_time` и `available_at <= event_time`;
- использует instrument spec, действовавший на cutoff;
- не публикует сигнал при stale candle/ticker;
- не подставляет нулевой spread при отсутствующих bid/ask;
- блокирует missing features, missing spec, excessive spread и неизвестный funding interval при пересечении settlement;
- атомарно заменяет предыдущий `PUBLISHED` signal того же символа;
- сохраняет audit/outbox events и versioned execution plans.

## Миграции

- `0002_one_signal_per_symbol` очищает дубли активных рекомендаций и вводит частичный уникальный индекс.
- `0003_single_active_model` устраняет возможные множественные active model rows и вводит частичный уникальный индекс `model.uq_model_registry_single_active`.

## PostgreSQL integration tests

В текущем контейнере отдельная PostgreSQL test database не была доступна, поэтому integration tests не запускались. Они обновлены для migration head `0003_single_active_model` и должны быть выполнены перед эксплуатацией:

```powershell
$env:POSTGRES_ADMIN_URL="postgresql+psycopg://postgres:ПАРОЛЬ@localhost:5432/postgres"
py -3.12 manage.py test --require-integration
Remove-Item Env:POSTGRES_ADMIN_URL
```

## Не покрыто данной проверкой

- качество модели на реальной накопленной истории конкретной установки;
- profitability/OOS stability и paper/shadow forward evidence;
- полный event-driven execution с historical orderbook, partial fills и operator latency;
- drift monitoring и автоматический fallback;
- нагрузочное тестирование полного динамического universe;
- backup/restore на инфраструктуре пользователя.

## Обязательная приемка

1. `python manage.py migrate`.
2. `python manage.py doctor`.
3. PostgreSQL integration tests с отдельной базой.
4. `/health/ready` после успешного market sync.
5. Обучение, review holdout/backtest и явная activation модели.
6. Backup + restore-check.
7. Paper/shadow forward period до любого production advisory использования.

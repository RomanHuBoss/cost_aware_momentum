# Patch 1.4.0 — safe background model retraining

## Цель

Добавить автономное фоновое переобучение модели без выполнения тяжелого fitting внутри FastAPI или часового inference worker.

## Архитектура

- новый процесс `app.workers.trainer`;
- отдельный heartbeat `service_name=trainer`;
- периодический job `model_retraining` в PostgreSQL;
- session-level advisory lock не допускает одновременное обучение несколькими trainer instances;
- все artifacts immutable и сохраняются атомарной заменой временного файла;
- активная модель продолжает обслуживать inference во время обучения.

## Цикл

1. Проверить интервал и число новых подтвержденных часовых timestamps.
2. Загрузить rolling-окно данных из PostgreSQL.
3. Построить direction-specific TP/SL/TIMEOUT dataset.
4. Обучить и откалибровать новый candidate.
5. Оценить candidate и incumbent на одном final holdout.
6. Применить absolute/relative quality gate.
7. Зарегистрировать artifact, SHA256, метрики и gate decision.
8. Активировать candidate только при успешном gate и неизменной incumbent version.
9. Worker подхватит новую active-модель при очередном `MODEL_REFRESH_SECONDS`.

## Безопасность

Это переобучение, а не изменение существующего sklearn-объекта через `partial_fit`. Предыдущая версия не перезаписывается и остается доступной для rollback. Провал обучения, quality gate или конкурентная смена active-модели не останавливают текущий inference.

## Запуск

```powershell
py -3.12 manage.py run
```

По умолчанию supervisor запускает API, inference worker и trainer. Отдельный запуск:

```powershell
py -3.12 manage.py trainer
```

Отключение:

```env
AUTO_TRAIN_ENABLED=false
```

Оставить фоновое обучение, но активировать кандидатов вручную:

```env
AUTO_TRAIN_ENABLED=true
AUTO_TRAIN_AUTO_ACTIVATE=false
```

## Обновление

Миграция схемы не требуется. После замены файлов:

```powershell
py -3.12 manage.py setup
py -3.12 manage.py doctor
py -3.12 manage.py run
```

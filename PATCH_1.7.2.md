# Patch 1.7.2 — controlled baseline recovery after model artifact loss

Дата: 28 июня 2026 г.

## Проблема

`model.model_registry` мог продолжать указывать на active ML-модель после случайного удаления ее `.joblib`. При запуске worker строго загружал registry artifact и завершался с `RuntimeError: Active model artifact does not exist`. API и trainer оставались запущены, но inference останавливался, хотя в non-production конфигурации уже было задано `ALLOW_BASELINE_MODEL=true`.

Дополнительная проблема состояла в том, что trainer видел отсутствующий artifact как недоступный incumbent comparison. Quality gate добавлял `incumbent_comparison_unavailable`, поэтому новый кандидат не мог автоматически восстановить систему даже при прохождении абсолютных проверок.

## Исправление

- Выбор runtime вынесен в `app/ml/runtime_selection.py`.
- При отсутствии active artifact worker использует deterministic baseline только когда:
  - `ALLOW_BASELINE_MODEL=true`;
  - `APP_MODE` не равен `production`;
  - отсутствует именно файл/path, а не выявлена ошибка целостности существующего artifact.
- `ACTIVE_MODEL_PATH` остается строгим override: его отсутствие не приводит к fallback.
- SHA256 mismatch, поврежденный bundle, несовместимые task/schema/classes/version/horizon остаются fail-closed.
- Worker heartbeat содержит `model_notice`, работает в статусе `DEGRADED` и продолжает market sync/inference на baseline.
- `/health/ready` считает такую конфигурацию операционной только при свежем heartbeat/market data и отсутствии другой worker error; ответ явно содержит `fallback_active=true` и `degraded=true`.
- UI показывает фактически используемый runtime и причину fallback, а не только stale registry version.
- Trainer в том же разрешенном recovery-mode рассматривает физически утраченный incumbent как bootstrap baseline. Candidate не получает фиктивные incumbent metrics и может активироваться только после абсолютных ML/policy gates и optimistic check прежней active-version.
- Recovery context сохраняется в trainer heartbeat/job result, candidate registry metrics и audit event.

## Безопасностные границы

- Production продолжает требовать `ALLOW_BASELINE_MODEL=false` и остается fail-closed.
- Registry row не удаляется и не деактивируется автоматически при обнаружении отсутствующего файла.
- Baseline не выдается за обученную модель; каждая рекомендация уже получает предупреждение о некалиброванном baseline.
- Новый candidate не активируется без прохождения действующих абсолютных gates.
- Никаких торговых методов или автоматической отправки ордеров не добавлено.

## Совместимость

- Alembic migration не требуется.
- Новые environment variables не требуются.
- Обновление совместимо с существующим `.env` версии 1.7.1.

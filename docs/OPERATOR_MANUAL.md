# Operator Manual

## Безопасный запуск

1. Создайте Python environment по требованию `pyproject.toml`.
2. Заполните локальный `.env` по `.env.example`; не помещайте его в архив.
3. Настройте отдельную PostgreSQL database и выполните Alembic migrations.
4. Запустите `python manage.py doctor`.
5. Запускайте API, inference worker и trainer отдельными процессами через предусмотренные команды `manage.py`.

## Работа с рекомендациями

- Проверяйте freshness, direction, entry zone, execution status, costs, funding и warnings.
- `ACCEPTED` означает только решение оператора; ордер на биржу не создаётся.
- Реальный вход и выход регистрируются вручную в fills/trades journal.
- Не обходите `NO_TRADE`, stale, risk, margin, liquidity, reconciliation или model quarantine блокировки.

## Обновление 1.52.1

Миграций и новых `.env` variables нет. После обновления перезапустите worker и trainer.

Если raw history прошла preflight, но после feature/context/label filtering её недостаточно для purged walk-forward, trainer теперь показывает healthy `WAITING` и результат `DEFERRED`, а не `ERROR`. Поле `walk_forward_capacity` показывает фактические и минимально необходимые development timestamps. Не снижайте folds/purge/holdout: дождитесь новых данных и устраните gaps/missing point-in-time evidence.

Warning `Signal publication blocked by decision-time execution contract` теперь обязан содержать `reason_code`, `contract_error`, event/publish timestamps, lag и configured limit. При mismatch сравните artifact/runtime entry-zone и publication-delay values; при lag устраните задержку decision pipeline. Публикация остаётся заблокированной до совпадения контракта.

## Обновление 1.52.0

Миграций нет. Новые bootstrap-параметры уже имеют безопасные defaults в `.env.example`. После обновления перезапустите worker и trainer. В окне trainer ожидайте режим `historical_frozen_dynamic_bootstrap`; счётчик истории должен начать отражать загруженные historical hours, а не только часы после установки. После накопления полной prospective history режим автоматически сменится на `prospective_dynamic_replay`.

До запуска выполните:

```bash
python manage.py release-check
python -m pip check
python -m pytest -q
```

Для сборки нового release сначала удалите caches/build artifacts, затем выполните `release-check --write` и повторную verification.

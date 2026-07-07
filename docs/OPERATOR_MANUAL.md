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

## Обновление 1.52.0

Миграций нет. Новые bootstrap-параметры уже имеют безопасные defaults в `.env.example`. После обновления перезапустите worker и trainer. В окне trainer ожидайте режим `historical_frozen_dynamic_bootstrap`; счётчик истории должен начать отражать загруженные historical hours, а не только часы после установки. После накопления полной prospective history режим автоматически сменится на `prospective_dynamic_replay`.

До запуска выполните:

```bash
python manage.py release-check
python -m pip check
python -m pytest -q
```

Для сборки нового release сначала удалите caches/build artifacts, затем выполните `release-check --write` и повторную verification.

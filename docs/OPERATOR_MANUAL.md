# Operator Manual

## Upgrade to 1.10.0

1. Сохраните backup PostgreSQL и текущего model registry/artifact.
2. Обновите исходники. Alembic migration не требуется.
3. Добавьте в `.env` или подтвердите:

```env
MODEL_ENTRY_SPREAD_BPS=18
```

4. Запустите `python manage.py doctor` в локальном настроенном окружении.
5. Переобучите candidate. Старый artifact с прежней label schema не должен загружаться.
6. Проверьте gate diagnostics. Не активируйте candidate с mismatch execution metadata.
7. Выполните paper/shadow validation до любого ручного использования рекомендаций.

## Интерпретация

`18` означает полный 18 bps spread stress, то есть 9 bps adverse offset от next-hour open для каждой стороны. Это не оценка конкретного инструмента и не historical orderbook reconstruction. Для консервативного исследования значение должно определяться до OOS evaluation и фиксироваться в experiment record.

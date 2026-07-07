# Patch 1.51.1 — fail-closed release contract

## Проблема

`verify_release_tree()` проверял только отсутствие запрещённых файлов и взаимное соответствие дерева с `SHA256SUMS`. Архив из двух произвольных файлов с корректно пересчитанным manifest получал `ok=True`, даже если в нём отсутствовали QA, security, architecture, compliance и rollback-документы. Версии в `pyproject.toml`, `app/__init__.py` и README также не сравнивались.

Это fail-open в supply/release boundary: checksum доказывал неизменность неполного набора, но не его полноту и не идентичность заявленной версии.

## Исправление

- `scripts/release_integrity.py` требует статический набор release-файлов.
- Текущая версия извлекается независимо из TOML, Python-модуля и README; несовпадение блокирует релиз.
- Для версии обязателен `PATCH_<version>.md`.
- Обязателен хотя бы один `docs/ITERATION_REPORT_*.md`.
- Добавлены red → green regression tests.
- Создан минимально достаточный комплект эксплуатационной и трассировочной документации.

## Миграции и конфигурация

- Alembic migration: нет.
- `.env`: новых переменных нет.
- API/JSON schema: без изменений.

## Проверка

Полные результаты находятся в `docs/QA_REPORT.md` и `docs/ITERATION_REPORT_2026-07-07_release-integrity.md`.

## Ограничения

Изменение подтверждает состав и идентичность release-архива, но не доказывает экономическую прибыльность модели и не заменяет PostgreSQL integration/forward evidence.

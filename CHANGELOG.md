# Changelog

Все существенные изменения текущей линии фиксируются здесь начиная с версии 1.51.1. История до 1.51.1 отсутствовала во входном release-архиве и не реконструируется задним числом без доказательств.

## 1.51.1 — 2026-07-07

### Fixed

- Release verification больше не принимает самосогласованный, но неполный `SHA256SUMS` как достаточное доказательство готовности архива.
- Добавлена fail-closed проверка обязательных governance, security, operations и QA документов.
- Добавлена проверка совпадения версии в `pyproject.toml`, `app/__init__.py` и README.
- Добавлены обязательные version-specific patch notes и iteration report.

### Added

- Восстановлены `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md` и базовый комплект эксплуатационной документации.
- Добавлены regression tests для неполного release tree и version drift.

### Compatibility

- Миграций БД, новых переменных окружения и изменений API нет.
- Торговая, ML и risk-математика не изменялась.

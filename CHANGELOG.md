# Changelog

Все существенные изменения проекта фиксируются в этом файле. Версии до 1.8.7 частично восстанавливаются по сохраненным iteration reports и release-документам; для точной истории прежних релизов используйте соответствующие `docs/ITERATION_REPORT_*`.

## 1.8.7 — 2026-06-29

### Fixed

- Проверка entry-zone при принятии использует текущий ask для LONG и bid для SHORT вместо `last_price`.
- Read-only account equity/margin snapshot получает fail-closed age gate; missing, stale, future-dated и timezone-invalid snapshot блокирует execution plan и accept.
- Общий open-risk check при принятии выполняется после глобального transaction-scoped PostgreSQL advisory lock, исключая oversubscription двумя параллельными accept-запросами.
- Stop-loss за консервативно оцененной liquidation boundary всегда дает `BLOCKED_LIQUIDATION`, включая плечо 1–3x.
- Синхронизированы версия, QA/compliance/traceability и release notes; восстановлены отсутствовавшие `CHANGELOG.md` и patch note текущего релиза.

### Configuration

- Добавлен `MAX_ACCOUNT_SNAPSHOT_AGE_SECONDS=180`; допустимое значение не меньше 30 секунд.
- Миграция БД не требуется.

### Verification

- 184 unit/integration-discovery tests passed; 4 PostgreSQL integration tests skipped из-за отсутствующего `TEST_DATABASE_URL`.
- Ruff, compileall, Node syntax check и Alembic single-head check passed.

## 1.8.6 — 2026-06-29

- Добавлена агрегированная диагностика hourly inference, ограниченные повторы неполного часа и operator-visible распределение execution-plan statuses. Подробности: `docs/ITERATION_REPORT_2026-06-29_inference-diagnostics.md`.

## 1.8.5 — 2026-06-29

- Исправлены cost-aware direction parity research/production, exit-notional fee normalization, overlap capital sleeves, concurrency accounting и funding start boundary. Подробности: `docs/ITERATION_REPORT_2026-06-29_econometrics-audit.md`.

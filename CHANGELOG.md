# Changelog

Все существенные изменения текущей линии фиксируются здесь начиная с версии 1.51.1. История до 1.51.1 отсутствовала во входном release-архиве и не реконструируется задним числом без доказательств.

## 1.52.7 — 2026-07-08

### Fixed

- Open-interest history backfill now has a separate default depth: `HISTORY_BACKFILL_OPEN_INTEREST_PAGES_PER_SYMBOL=7`, covering the current 1206-hour training-readiness precondition at Bybit's 200-row hourly OI page size.
- Startup trainer defer `insufficient_walk_forward_history_after_filtering` with observed `actual_timestamps=326 < required_timestamps=366` is no longer caused by the old 2-page OI cap when candle/mark/index history is otherwise available.
- The worker suppresses repeated stale hourly decision attempts for the same event hour after a terminal `decision_publication_lag_exceeded` result; the next hour remains eligible.
- `/api/v1/status` exposes `history_backfill.open_interest_pages_per_symbol` for operator diagnostics.

### Compatibility

- No database migration, API-breaking change, order execution capability, model-artifact schema change or gate weakening.
- Existing `.env` files can add `HISTORY_BACKFILL_OPEN_INTEREST_PAGES_PER_SYMBOL=7`; absent values use the new safe default.
- Restart worker and trainer after update.

## 1.52.6 — 2026-07-08

### Fixed

- Startup market backfill depth now matches the default training quality-gate precondition: `INITIAL_BACKFILL_BARS` default increased from 1000 to 1500, above the current 1206-hour default minimum.
- `sync_candles()` now paginates Bybit kline requests when the caller requests more than the exchange single-page limit, so `INITIAL_BACKFILL_BARS>1000` actually stores the requested depth instead of silently receiving only one page.
- Added regression coverage proving that the default backfill can cover the training preflight minimum and that a 1206-bar startup request produces two kline pages and 1206 distinct hourly rows.

### Compatibility

- Миграций БД, новых `.env` variables, API-breaking changes и model-artifact schema changes нет.
- Existing `.env` files with `INITIAL_BACKFILL_BARS=1000` remain accepted, but they can delay first training readiness; set it to at least `1500` for the new startup behavior.
- Quality, walk-forward, holdout, policy, promotion and risk gates are unchanged.


## 1.52.5 — 2026-07-08

### Fixed

- Trainer scheduler теперь восстанавливает previous `TrainingDataProfile` из `JobRun.details.metrics.training_data_profile`, если legacy/successful candidate job не содержит профиль в `trigger`.
- Data-dependent bootstrap/recovery skip после `quality_gate_failed` или walk-forward deferral больше не откатывается к generic `training_cooldown_not_elapsed`, когда persisted candidate metrics уже доказывают тот же training profile и отсутствие новых размеченных часов.
- Wait reason получил поле `previous_profile_source`, чтобы оператор и QA видели, из какого persisted evidence взят профиль предыдущей попытки.

### Compatibility

- Миграций БД, новых `.env` variables, API-breaking changes и model-artifact schema changes нет.
- Trainer gates, thresholds, cooldown durations и activation semantics не ослаблены; меняется только извлечение уже сохранённого evidence для диагностики/планирования повтора.
- После обновления требуется перезапуск trainer и API/UI process.


## 1.52.4 — 2026-07-08

### Fixed

- Trainer scheduling больше не маскирует rejected bootstrap/recovery candidate с `quality_gate_failed` или data-dependent walk-forward deferral общим `training_cooldown_not_elapsed`, когда повтор всё равно требует новых данных.
- Heartbeat/UI wait reason теперь сразу сообщает `quality_gate_failed_waiting_for_new_data` или `training_deferred_waiting_for_new_data`, предыдущий skip reason, прогресс новых размеченных часов и, если применимо, оставшееся cooldown window.
- UI добавил человекочитаемые сообщения для data-dependent trainer waits и показывает progress bar по новым размеченным часам.
- Dependency contract ограничивает NumPy `<2.5`; fresh QA install с NumPy 2.5.1 ломал существующие funding replay и policy phase contracts, тогда как NumPy 2.3.5 проходит suite.

### Compatibility

- Миграций БД, новых `.env` variables, API-breaking changes и model-artifact changes нет.
- Trainer gates, quality thresholds и cooldown limits не ослаблены; меняется только ранняя классификация причины ожидания и reproducible dependency bound.
- После обновления требуется перезапуск trainer и API/UI process.


## 1.52.3 — 2026-07-08

### Fixed

- Worker больше не запускает hourly decision cycle, если текущий event hour уже вышел за `MAX_SIGNAL_PUBLICATION_DELAY_SECONDS` до начала цикла.
- Catch-up inference больше не пытается публиковать current-hour сигнал после истечения decision-time publication window; вместо этого сохраняется terminal skip `decision_publication_lag_exceeded` с lag/limit diagnostics.
- Hourly inference повторно проверяет publication window непосредственно перед execution input refresh/publication, если предшествующие jobs заняли слишком много времени.
- Retry accounting теперь использует terminal `symbol_outcome_count` для inference jobs и не делает повторные попытки только из-за sparse actionability.

### Compatibility

- Миграций БД, новых `.env` variables, API-breaking changes и model-artifact changes нет.
- `MAX_SIGNAL_PUBLICATION_DELAY_SECONDS` намеренно не увеличен; stale recommendations остаются blocked.
- После обновления требуется перезапуск inference worker.

## 1.52.2 — 2026-07-08

### Fixed

- Многоуровневый orderbook sizing больше не переводит суммарный quote notional обратно в завышенное base quantity по best/reference price.
- Quantity-safe depth cap гарантирует, что плановый размер не превышает доступный base quantity внутри impact limit для LONG и SHORT.
- Acceptance больше не требует tick alignment от агрегированного VWAP нескольких валидных уровней.
- Fresh acceptance использует фактический available depth notional после точной FULL-fill симуляции, а не консервативный planning cap.

### Compatibility

- Миграций БД, новых `.env` variables, API-breaking changes и model-artifact changes нет.
- Tick validation уровней стакана и signal geometry, FULL-fill, freshness, risk, funding, margin и reconciliation gates сохранены.
- После обновления требуется перезапуск API и inference worker.

## 1.52.1 — 2026-07-08

### Fixed

- Недостаток post-feature/post-label history для purged expanding walk-forward больше не считается аварийным падением background trainer.
- Walk-forward capacity теперь рассчитывается одним общим контрактом и сообщает actual/required timestamps, block size, initial train и purge requirements.
- Candidate build проверяет capacity до основного model fit, когда final holdout metadata доступна.
- Expected data shortage завершается как `SUCCESS` job с внутренним статусом `DEFERRED`, сохраняет incumbent и переводит trainer в healthy `WAITING`.
- Повторная bootstrap-попытка после deferral ждёт новых timestamps или material dataset change вместо tight error loop.
- JSON formatter больше не отбрасывает безопасные decision-time contract diagnostics; warning содержит reason code, lag, limit и sanitized contract mismatch values.

### Compatibility

- Миграций БД, новых переменных окружения и API-breaking changes нет.
- Walk-forward, purge, holdout, quality, policy и promotion thresholds не снижены.
- После обновления требуется перезапуск worker и trainer.

## 1.52.0 — 2026-07-07

### Fixed

- Устранено обязательное ожидание примерно 50 суток перед первой dynamic training attempt на чистой базе.
- Historical backfill теперь используется только внутри свежего hash-bound frozen execution cohort и не выдаётся за historical dynamic replay.
- Добавлен ограниченный conservative tick-size fallback для часов до первой локальной instrument-spec записи.
- Exact prospective replay больше не применяет full-sample candle-coverage symbol preselection.
- Training trigger/profile/evidence получили fail-closed identity, hash, timestamp и cohort validation.
- Scheduled retraining считает новые часы только внутри exact fitted symbol scope.
- Stale universe snapshot не может стать bootstrap cohort.

### Added

- Режимы `historical_frozen_dynamic_bootstrap` и `prospective_dynamic_replay` с автоматическим upgrade retraining.
- Три bootstrap configuration variables и regression tests cold-start path.
- Отдельный audit/iteration evidence по econometric и operational ограничениям.

### Compatibility

- Миграций БД и API-breaking changes нет.
- Existing active artifacts продолжают работать.
- После обновления требуется перезапуск worker и trainer.
- Quality, policy, experiment, cost-stress и risk thresholds не снижены.

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

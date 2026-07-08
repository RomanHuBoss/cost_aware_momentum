# Patch 1.52.3 — stale decision publication scheduling

Дата: 2026-07-08.

## Симптом

Worker мог вызывать публикацию сигнала за hourly event time после истечения immutable decision-time execution contract. Типичный лог:

```json
{
  "message": "Signal publication blocked by decision-time execution contract",
  "reason_code": "decision_publication_lag_exceeded",
  "publication_lag_seconds": 1886.062415,
  "maximum_delay_seconds": 600
}
```

Само блокирование было правильным fail-closed поведением, но scheduler/catch-up layer не должен был доводить stale current-hour цикл до execution refresh и publication attempt.

## Исправления

- Добавлен `DecisionPublicationWindow` и общий `resolve_decision_publication_window` для проверки publication lag до запуска тяжёлых hourly/catch-up операций.
- `hourly_decision_cycle` теперь, когда вызывается из worker loop с фактическим `cycle_started_at`, пропускает уже stale event hour до `market_close/outcomes/drift/inference`.
- `inference_job` повторно проверяет окно непосредственно перед execution input refresh/publication, если предшествующие hourly jobs заняли слишком много времени.
- `catchup_inference_job` записывает terminal skip `decision_publication_lag_exceeded` с `publication_boundary`, `skip_counts`, `symbol_outcome_count` и per-symbol terminal outcomes, а не вызывает stale publication.
- Retry accounting для inference jobs теперь использует существующий terminal coverage helper `should_retry_incomplete_inference`, чтобы sparse-but-complete outcomes не запускали лишние retries.

## Совместимость

- Миграций БД нет.
- Новых или изменённых `.env` variables нет.
- API schema, model artifact contracts, risk/math gates и Bybit client не изменены.
- `MAX_SIGNAL_PUBLICATION_DELAY_SECONDS` не увеличен и не ослаблен.
- Advisory-only, PostgreSQL-only и fail-closed boundaries сохранены.
- После обновления перезапустите inference worker.

## Ограничения

Если worker стартует или освобождается уже после publication window, текущий hourly signal намеренно не публикуется. Это снижает ложные stale opportunities, но не устраняет первопричину задержки: тяжёлый startup/backfill, медленную сеть, долгие DB locks или слишком частые maintenance jobs нужно диагностировать отдельно по `JobRun.details` и heartbeat.

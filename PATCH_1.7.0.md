# Patch 1.7.0 — intrabar resolution of hourly TP/SL ambiguity

## Проблема

Версия 1.6.0 автоматически сохраняла counterfactual outcome, но если hourly candle одновременно пересекала TP1 и SL, порядок касаний был неизвестен и результат всегда записывался как консервативный `SL` с `ambiguous=true`. Это безопасный fallback, но грубая post-event оценка: сигнал с фактическим TP-first мог быть классифицирован как SL.

Техническая спецификация требует использовать 1–5-минутные данные для восстановления пути, а консервативное правило оставлять только резервом. В предыдущей реализации finer-grained candles не запрашивались и не участвовали в outcome resolver.

## Решение

- worker сначала находит только те нерешенные signal windows, где confirmed hourly bar содержит одновременно TP1 и SL;
- для каждого уникального symbol/hour выполняется ограниченный public/read-only `GET /v5/market/kline` с точными `start`, `end`, `interval` и `limit`;
- поддерживаются интервалы `1`, `3` и `5` минут, default `5`;
- intrabar path обязан непрерывно покрывать весь неоднозначный час;
- первое касание TP1 или SL определяет outcome и 1/3/5-минутный source candle;
- неполный path оставляет outcome pending;
- если TP1 и SL остаются внутри одного самого мелкого бара, применяется консервативный `SL` с `ambiguous=true`;
- existing signal/plan outcome uniqueness, transaction lock, audit и outbox сохраняются.

## Конфигурация

```env
OUTCOME_INTRABAR_INTERVAL=5
OUTCOME_INTRABAR_MAX_WINDOWS_PER_CYCLE=100
```

`OUTCOME_INTRABAR_INTERVAL` допускает `1`, `3` или `5`. Лимит windows на cycle ограничивает burst при backlog. 1/3/5-minute history не загружается для всего universe: используются только точные окна неоднозначных сигналов.

## Миграции и API

- новая Alembic migration не требуется;
- текущий head остается `0004_counterfactual_outcomes`;
- публичная API schema не изменена;
- `SignalOutcome.details` получает дополнительные диагностические поля: `hourly_ambiguous`, `interval`, `intrabar_bars_evaluated` и уточненное `same_bar_rule`;
- уже сохраненные outcomes версии 1.6.0 не переписываются.

## Проверки

```text
python -m pip check                                      PASSED
python -m compileall -q app scripts tests manage.py     PASSED
python -m ruff check .                                   PASSED
python -m pytest -q                                      PASSED — 74 passed, 3 skipped
python -m pytest -q tests/unit/test_intrabar_outcomes.py PASSED — 7 passed
node --check web/js/app.js                               PASSED
alembic heads                                            PASSED — 0004_counterfactual_outcomes
```

Новый acceptance module до implementation завершался ошибкой импорта отсутствующих `CandleWindow`/`sync_candle_windows`; после реализации прошел полностью.

## Ограничения

- training labels и текущий backtest по-прежнему используют hourly OHLC и консервативное same-bar правило; intrabar refinement пока относится только к post-event journal;
- TP2, partial exits, trailing stop, entry-zone/no-fill и operator latency не моделируются;
- PostgreSQL integration tests и длительный live Bybit worker smoke-test в среде сборки не выполнялись;
- техническая корректность outcome journal не доказывает прибыльность стратегии.

# Patch 1.12.0 — historical funding settlement replay

## Problem

До 1.12.0 PostgreSQL хранил отдельные funding observations, но research training и backtest не строили полную event-by-event settlement timeline. Policy economics использовала скалярный funding scenario без доказательства, что позиция фактически пересекла settlement. Это искажало realized PnL и могло одинаково списывать funding с раннего выхода и позиции, действительно удержанной через выплату.

## Solution

- Добавлен progressive read-only backfill `/v5/market/funding/history` с обратной пагинацией по `endTime`.
- Фактические `fundingRateTimestamp` сохраняются в существующую таблицу `market.funding` идемпотентно.
- Research loader передаёт candles, funding events и funding interval в training/backtest одним bundle.
- Для каждого LONG/SHORT label рассчитываются horizon и actual-exit funding aggregates по окну `(entry_time, exit_time]`.
- Пропущенный ожидаемый settlement, отсутствие anchor или interval metadata блокируют соответствующий cohort; пустой пригодный dataset блокирует training.
- Realized PnL использует фактический signed cash flow: положительный rate списывается с LONG и начисляется SHORT.
- Будущие фактические rates не участвуют в ex-ante direction selection, RR, EV или actionability, устраняя funding look-ahead.
- Artifact/runtime/activation gate требуют `bybit-settlement-timestamp-replay-v1` и непустое timeline evidence.

## Compatibility

- Database migration: нет; используется существующая таблица `market.funding`.
- `.env`: новых переменных нет; funding backfill использует текущие `HISTORY_BACKFILL_*` настройки, page size ограничивается 200 для endpoint funding history.
- Public API/UI: без изменений.
- Artifact 1.11.0: несовместим с новым runtime contract; требуется funding backfill и retraining.
- Rollback: вернуть код и artifact 1.11.0. Artifact 1.12.0 не считать совместимым со старым runtime.

## Verification

- Red: новый regression module на исходном 1.11.0 падал при collection с `ModuleNotFoundError: No module named 'app.ml.funding'`.
- Green: 7 funding-specific tests passed.
- Full suite: 483 passed, 4 skipped.
- Ruff, compileall и Node syntax: passed.
- PostgreSQL integration: не выполнялась без отдельной test database.

## Limitations

- Completeness использует последний известный funding interval инструмента; point-in-time history смены interval не реконструируется.
- Нет исторических forecast/indicative funding snapshots, поэтому ex-ante policy funding cost не восстанавливается из будущего actual rate.
- Funding не является model feature.
- Реализация не моделирует historical depth, no-fill, partial-fill, liquidation или operator latency и не доказывает прибыльность.

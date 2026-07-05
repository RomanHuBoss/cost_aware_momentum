# Patch 1.14.0 — point-in-time orderbook execution evidence

## Problem

До 1.14.0 execution plan ограничивал размер позиции скалярной долей 24-часового turnover и использовал только best bid/ask. Глубина по нескольким уровням, полный VWAP, no-fill и partial-fill не входили в sizing. При принятии плана оператор мог получить свежую лучшую котировку, но система не доказывала, что весь рассчитанный объём исполним в допустимом ценовом воздействии. Point-in-time evidence и задержка между расчётом и решением не сохранялись.

## Solution

- Worker получает public/read-only REST orderbook snapshot для активных символов и сохраняет matching-engine time, system time, local receipt time, update/cross sequence и канонические bid/ask levels.
- Natural key включает `symbol + source_time + update_id`; один `update_id` не считается вечным идентификатором биржевого сервиса.
- LONG market-fill simulation потребляет asks по возрастанию, SHORT — bids по убыванию.
- Симулятор возвращает `FULL / PARTIAL / NO_FILL`, requested/filled/unfilled qty, available depth/notional, VWAP, worst price, impact bps и число использованных уровней.
- Допустимая глубина ограничена `MAX_VWAP_IMPACT_BPS` относительно best executable quote.
- Plan sizing использует минимум turnover cap и bounded-depth cap, затем пересчитывает stop distance, risk, qty и VWAP до устойчивого результата. Неполное исполнение и отсутствие сходимости блокируются fail-closed.
- Acceptance требует совместимый исходный depth contract, повторяет полный fill simulation по свежему snapshot и создаёт новую версию плана при stale/partial/no-fill, ухудшении цены или несовместимом legacy evidence.
- Operator decision сохраняет точный повторный snapshot/fill evidence и plan-to-decision latency.
- Retention удаляет старые ticker/orderbook snapshots независимо.

## Database and configuration

Migration `0010_orderbook_exec_evidence` добавляет `market.orderbook_snapshots` и индекс `(symbol, source_time)`. Upgrade поддерживает как существующую схему, так и fresh install, где migration `0001` создаёт текущую metadata. Downgrade удаляет только новую таблицу.

Новые параметры:

- `ORDERBOOK_DEPTH_LEVELS=200`, допустимо 1..1000;
- `MAX_ORDERBOOK_AGE_SECONDS=90`;
- `MAX_VWAP_IMPACT_BPS=12`;
- `ORDERBOOK_RETENTION_HOURS=48`.

Изменение depth/impact policy не требует retraining market model, но меняет execution-plan semantics; активные legacy plans должны быть пересчитаны.

## Compatibility

- Advisory-only boundary сохранена: order create/amend/cancel не добавлены.
- Public recommendation schema не меняется; `sizing_snapshot` и operator decision context получают дополнительное evidence.
- Existing model artifacts 1.13.0 совместимы: feature/label/training schemas не изменены.
- Existing database requires `python manage.py migrate` before worker/API startup.
- Rollback: остановить API/worker, вернуть код 1.13.0 и выполнить downgrade только если сохранённые depth snapshots больше не нужны. Model artifact откатывать не требуется.

## Verification

- Red: новый regression module на untouched 1.13.0 падал при collection с `ModuleNotFoundError: No module named 'app.risk.liquidity'`.
- Green targeted suite: 15 orderbook-specific tests plus execution-plan/acceptance regressions.
- Full unit/static results are recorded in `docs/QA_REPORT.md` and the iteration report.

## Limitations

- REST snapshot является моментальным prospective evidence, а не реконструкцией исторического orderbook до 1.14.0.
- RPI orders не представлены в стандартном REST snapshot.
- Queue position, limit-order probability, cancel/replace race, network/operator latency distribution и exchange partial-fill lifecycle не моделируются.
- Advisory system блокирует partial/no-fill вместо создания реального OMS fill lifecycle.
- Forward snapshots ещё не накопили достаточную историю для использования в model training или causal evaluation.
- Техническая корректность не доказывает прибыльность.

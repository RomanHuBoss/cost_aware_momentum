# Patch 1.52.2 — orderbook VWAP sizing and acceptance correctness

Дата: 2026-07-08.

## Цель

Устранить два связанных дефекта в account-dependent execution layer:

1. plan sizing использовал суммарный quote notional всех допустимых уровней стакана как cap, а затем переводил его обратно в base quantity по одной reference price; на многоуровневом стакане это могло запросить больше base quantity, чем реально доступно, и превратить полностью исполнимый план в ложный `PARTIAL`/blocked;
2. acceptance требовал tick alignment от агрегированного VWAP, хотя средневзвешенная цена нескольких валидных tick-aligned уровней закономерно может лежать между тиками.

## Исправления

- `orderbook_depth_notional_cap` теперь возвращает quantity-safe conservative sizing cap: доступный base quantity оценивается по минимальной executable price внутри допустимой глубины. Последующее деление на best/reference price не может породить quantity больше доступной.
- Для LONG и SHORT добавлены независимые regression cases с многоуровневым стаканом и ручными ожидаемыми cap.
- Acceptance больше не применяет price-tick constraint к агрегированному VWAP. Tick constraints остаются обязательными для отдельных уровней стакана и immutable signal geometry.
- После точной FULL-fill симуляции acceptance использует фактический `available_notional` текущей допустимой глубины. Консервативный sizing cap намеренно не переиспользуется как acceptance cap.
- Добавлен endpoint regression test, в котором два tick-aligned уровня дают VWAP `100.05` при tick `0.1`; рекомендация принимается только после всех fresh-state checks.

## Совместимость

- Миграций БД нет.
- Новых или изменённых `.env` variables нет.
- API schema и model artifact contracts не изменены.
- Advisory-only и PostgreSQL-only boundaries сохранены.
- Risk, EV/RR, funding, margin, reconciliation, freshness и FULL-fill gates не ослаблены.
- После обновления перезапустите API и inference worker, чтобы новые sizing/acceptance semantics применились к вновь создаваемым и принимаемым планам.

## Ограничения

Depth/VWAP simulation остаётся bounded market-fill proxy. Она не моделирует queue position, latency between snapshot and manual order, hidden liquidity, exchange matching priority или фактический partial fill после решения оператора. Техническая корректность sizing не является доказательством прибыльности стратегии.

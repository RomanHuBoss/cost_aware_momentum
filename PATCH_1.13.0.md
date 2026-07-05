# Patch 1.13.0 — intrahorizon mark-to-market and liquidation proxy

## Problem

До 1.13.0 research labels и policy backtest знали только конечный `TP / SL / TIMEOUT` исход по last-price OHLC. Они не восстанавливали внутригoризонтную mark-to-market траекторию, не измеряли MAE/MFE/minimum equity и не проверяли, могла ли позиция быть ликвидирована по mark price раньше последующего last-price выхода. Поэтому realized OOS evidence мог сохранять прибыльный исход для траектории, которая при заданном плече уже потеряла бы isolated margin.

## Solution

- Progressive history backfill теперь отдельно запрашивает и сохраняет hourly Bybit mark-price candles с `price_type=mark`.
- Training требует точную непрерывную mark timeline от entry bar до modeled last-price exit; пропущенный bar исключает весь LONG/SHORT cohort fail-closed.
- Добавлен `simulate_intrahorizon_margin_path()` с directional mark returns, MAE/MFE, minimum equity, фактическим timing funding settlement и консервативным isolated-margin reserve.
- Mark liquidation может сократить только realized exit/PnL. Она не меняет исходный class target `TP / SL / TIMEOUT` и не участвует в ex-ante direction ranking, RR, EV или actionability.
- В одном hourly bar liquidation touch консервативно считается более ранним, чем неупорядоченный последующий last-price TP/SL touch. Выход на open не использует экстремумы после выхода.
- Artifact/runtime/activation gate требуют `bybit-mark-price-hourly-isolated-margin-proxy-v1`, полную path metadata, одинаковые leverage и reserve assumptions.
- Candidate/incumbent comparison выполняется только при совместимых intrahorizon assumptions.

## Mathematical scope

Для направления `d` mark return считается на notional:

- LONG: `mark / entry - 1`;
- SHORT: `1 - mark / entry`.

Начальная isolated-margin rate равна `1 / leverage`. Ликвидационный proxy срабатывает, когда `initial_margin_rate + adverse_mark_return + adverse_realized_funding` не превышает фиксированный reserve `10%` начальной маржи. При срабатывании conservative gross loss равен полной начальной марже `-1 / leverage`; fees, funding и slippage затем учитываются обычной policy-экономикой. Благоприятный будущий funding не используется для предотвращения ликвидации.

Это не точная формула биржи: исторические risk tiers/MMR, liquidation fee, cross/portfolio margin, sub-hour event ordering и exchange execution mechanics не реконструируются.

## Compatibility

- Database migration: нет; используется существующая таблица свечей с `price_type`.
- `.env`: новых переменных нет. Progressive mark backfill использует существующие `HISTORY_BACKFILL_*`; research leverage берётся из `DEFAULT_LEVERAGE`.
- Public API/UI: без изменений.
- Artifact 1.12.0: несовместим с новым runtime contract; требуется mark-price backfill и retraining.
- Rollback: вернуть код и artifact 1.12.0. Artifact 1.13.0 не считать совместимым со старым runtime.

## Verification

- Red: новый regression module на исходном 1.12.0 падал при collection с `ModuleNotFoundError: No module named 'app.ml.mtm'`.
- Green: 9 intrahorizon-specific tests passed.
- Full suite: 493 passed, 4 skipped.
- Ruff, compileall и Node syntax: passed.
- PostgreSQL integration: не выполнялась без отдельной test database.

## Limitations

- Hourly OHLC не задаёт точный sub-hour порядок mark-price экстремумов; ambiguous same-bar path трактуется консервативно.
- Используется fixed isolated-margin reserve, а не point-in-time Bybit maintenance-margin/risk-tier history.
- Нет liquidation fee, cross/portfolio margin, ADL, insurance-fund или bankruptcy-price simulation.
- Mark path не заменяет historical orderbook/VWAP/no-fill/partial-fill и operator latency.
- Реализация не доказывает прибыльность стратегии.

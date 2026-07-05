# Traceability

Состояние: release 1.26.6, 2026-07-05. Таблица связывает hourly mark-to-market experiment path с production-кодом, тестами и эксплуатационной документацией.

| ID | Требование / инвариант | Реализация | Проверка | Статус |
|---|---|---|---|---|
| EXP-MTM-01 | Внутрисделочная просадка должна отражаться до exit, даже если terminal trade прибыльный | `scripts/backtest.py::_simulate_capital_sleeves_evidence` применяет increments cumulative net path | `test_capital_sleeve_evidence_marks_intrahorizon_drawdown_before_profitable_exit` | Проверено red → green unit |
| EXP-MTM-02 | MTM path должен покрывать каждый час от decision до effective exit и точно сверяться с realized gross/funding | `app/ml/mtm.py::build_intrahorizon_mark_to_market_path`; `app/ml/training.py::validate_intrahorizon_mark_to_market_path` | dataset/path assertions и metadata split validation | Проверено unit |
| EXP-MTM-03 | Future mark path не может менять ex-ante LONG/SHORT ranking | path добавлен только в policy metadata; model features и expected EV inputs не изменены | existing `test_future_mark_liquidation_cannot_change_ex_ante_direction_selection` | Проверено unit |
| EXP-MTM-04 | Net capital path признаёт entry fee/slippage при decision, funding по settlement path и terminal exit fee/outcome при exit | `scripts/backtest.py::policy_backtest.cumulative_net_path` | reconciliation regression + full suite | Проверено unit |
| EXP-MTM-05 | Missing/malformed MTM evidence блокирует experiment return emission | `validate_intrahorizon_mark_to_market_path(..., require=True)` при `include_experiment_evidence` | `test_experiment_evidence_fails_closed_without_hourly_mark_to_market_path` | Проверено unit |
| EXP-MTM-06 | Exit-realized predecessor evidence не может авторизовать normal promotion | `EXPERIMENT_PERIOD_RETURN_SCHEMA_VERSION` v3 exact match | `test_exit_realized_v2_experiment_return_schema_is_rejected` | Проверено unit |
| EXP-PATH-01 | Недоступные календарные часы не становятся zero-return observations | `_observed_policy_period_grid` сохраняет union observed decision-to-horizon windows | `test_experiment_return_path_omits_unobserved_calendar_gap` | Проверено unit |
| EXP-PATH-02 | Genuine no-trade/holding hours внутри observed coverage остаются в return path | covered grid + MTM event aggregation | observed-period regression and full suite | Проверено unit |
| COMPAT-01 | Active artifacts, model feature/runtime schema, DB/API/env и risk thresholds не изменены | research metadata/backtest-only extension; no migration | static diff, version/docs checks | Реализовано |
| BOUNDARY-01 | Advisory-only и read-only Bybit boundary не ослаблены | order mutation code не добавлен | static grep + full suite | Проверено static/unit |

## Непроверенная трассировка

- Реальная PostgreSQL integration/concurrency проверка не выполнялась: отдельные `TEST_DATABASE_URL`/`POSTGRES_ADMIN_URL` не настроены, PostgreSQL tools отсутствуют в sandbox.
- Forward/live прибыльность, достаточная частота сигналов и устойчивость edge не доказаны unit tests.
- Hourly mark-close MTM не восстанавливает sub-hour barrier/liquidation order, exact historical orderbook, queue position, operator latency, exchange risk-tier changes, cross/portfolio margin или ADL.
- Текущий work package исправляет experiment-selection capital path; отдельная policy-quality return-in-R methodology не была переработана в этой итерации.

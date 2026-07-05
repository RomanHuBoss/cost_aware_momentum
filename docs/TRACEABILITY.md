# Traceability

Состояние: release 1.26.5, 2026-07-05. Таблица связывает observed experiment-period support с production-кодом, тестами и эксплуатационной документацией.

| ID | Требование / инвариант | Реализация | Проверка | Статус |
|---|---|---|---|---|
| EXP-PATH-01 | Недоступные календарные часы не могут становиться zero-return observations | `scripts/backtest.py::_observed_policy_period_grid` | `test_experiment_return_path_omits_unobserved_calendar_gap` | Проверено red → green unit |
| EXP-PATH-02 | Genuine decision/no-trade/holding periods внутри каждого валидного label horizon остаются в return path | union decision-to-horizon windows + `_simulate_capital_sleeves_evidence` | regression test verifies two disjoint 1h windows yield four covered periods, not 102 calendar periods | Проверено unit |
| EXP-PATH-03 | Evidence раскрывает observed, covered и omitted counts | `policy_backtest(..., include_experiment_evidence=True)` and `scripts.backtest.run` | regression assertions and full suite | Проверено unit |
| EXP-PATH-04 | Counts, timestamps and calendar-span arithmetic проверяются до PBO/DSR | `app/services/experiment_ledger.py::_trial_evidence_from_success` | `test_legacy_synthetic_calendar_return_schema_is_rejected` | Проверено red → green unit |
| EXP-PATH-05 | Legacy synthetic-calendar evidence не может авторизовать normal promotion | `EXPERIMENT_PERIOD_RETURN_SCHEMA_VERSION` v2 exact match | legacy v1 rejection test | Проверено unit |
| EXP-PATH-06 | Invalid experiment evidence даёт diagnostic failed gate, а не необработанное исключение | `app/services/model_promotion.py::evaluate_experiment_promotion_gate` | `test_promotion_gate_blocks_invalid_period_return_evidence` | Проверено red → green unit |
| EXP-PATH-07 | Existing policy, risk, artifact and advisory-only gates не ослаблены | unchanged lifecycle/risk/Bybit boundaries | full suite: 618 passed, 4 skipped | Проверено unit/static |
| OPS-01 | Active model не деактивируется; legacy experiment family требует rerun | compatibility policy in `README.md`, `PATCH_1.26.5.md` | static review | Реализовано |

## Непроверенная трассировка

- Реальная PostgreSQL integration/concurrency проверка не выполнялась: отдельные `TEST_DATABASE_URL`/`POSTGRES_ADMIN_URL` не настроены.
- Forward/live прибыльность, достаточная частота сигналов и устойчивость edge не доказаны unit tests.
- Return path является exit-realized, а не полноценным hourly mark-to-market portfolio series.
- Exact historical orderbook, point-in-time funding forecasts, sub-hour barrier ordering и exchange-accurate liquidation mechanics остаются ограничениями `docs/SPEC_COMPLIANCE.md`.

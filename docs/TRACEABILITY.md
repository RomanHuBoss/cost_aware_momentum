# Traceability

Состояние: release 1.28.0, 2026-07-06. Таблица связывает risk-budgeted experiment portfolio accounting с production/research-кодом, тестами и release evidence.

| ID | Требование / инвариант | Реализация | Проверка | Статус |
|---|---|---|---|---|
| RISK-ACCT-01 | Experiment path должен взвешивать сделки по stress risk, а не по равному notional | `scripts/backtest.py::_simulate_risk_budgeted_portfolio_evidence` | `test_risk_budgeted_accounting_matches_live_risk_sizing_not_equal_notional` | Проверено red → green unit |
| RISK-ACCT-02 | Одновременный cohort должен получать одинаковый per-trade risk budget без произвольного operator ordering | proportional cohort scale over desired equal-risk notionals | synthetic two-trade sign-reversal test | Проверено unit/independent arithmetic |
| RISK-ACCT-03 | Open risk должен сохраняться до modeled exit и ограничивать overlapping entries | active absolute `risk_reserve`; release before same-boundary entries | `test_risk_budgeted_accounting_scales_new_cohort_to_remaining_open_risk` | Проверено unit |
| RISK-ACCT-04 | Margin reserve и leverage должны ограничивать суммарный research notional | remaining margin-notional capacity in risk-budgeted replay | `test_risk_budgeted_accounting_scales_cohort_to_margin_capacity` | Проверено unit |
| RISK-ACCT-05 | Nominal и mandatory cost-stress paths должны использовать одну sizing semantics | `policy_backtest` uses risk-budgeted helper for nominal, stop reserve and ×1.5/×2 paths | experiment-path and cost-stress regression suites | Проверено unit |
| RISK-ACCT-06 | Hourly MTM path должен продолжать reconciliate terminal portfolio equity | cumulative return deltas × allocated notional; period compounding reconciliation | existing MTM tests + new portfolio reconciliation assertion | Проверено unit |
| RISK-ACCT-07 | Experiment evidence должно раскрывать limiting caps | `risk_allocated_trades`, `risk_limited_trades`, `margin_limited_trades`, `risk_blocked_trades`, utilization metrics | new helper tests + backtest result checks | Проверено unit/static |
| RISK-ACCT-08 | Evidence для другой risk policy не может авторизовать activation | policy binding v2 adds risk/max-open-risk/margin-reserve | `test_activation_rejects_gate_after_risk_budget_policy_changes` | Проверено unit |
| RISK-ACCT-09 | Legacy equal-notional evidence должно fail closed | return schema v4, cost-stress v2, policy binding v2 | legacy schema rejection and promotion tests | Проверено unit |
| COMPAT-01 | DB/API/env/model runtime contracts не изменены | migration отсутствует; HTTP и artifact schemas не затронуты | static diff, full suite, version checks | Реализовано |
| BOUNDARY-01 | Advisory-only/read-only Bybit boundary не ослаблен | order mutation code не добавлен | static grep + full suite | Проверено static/unit |

## Непроверенная трассировка

- PostgreSQL integration tests не выполнялись: отдельная test database и PostgreSQL tooling не настроены.
- Historical instrument minQty/minNotional, risk tiers, exact orderbook depth/partial fills и operator ordering не доступны в final-holdout replay.
- Research allocation использует process-wide default risk policy; фактические profile-specific capital/risk settings и ручной выбор подмножества рекомендаций требуют prospective exposure/decision/outcome evidence.
- Исправление устраняет accounting mismatch, но не доказывает positive forward edge и само по себе не увеличивает частоту рекомендаций.

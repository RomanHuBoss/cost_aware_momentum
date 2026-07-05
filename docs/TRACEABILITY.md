# Traceability

Состояние: release 1.26.7, 2026-07-06. Таблица связывает cost-stress experiment promotion gate с production-кодом, тестами и release evidence.

| ID | Требование / инвариант | Реализация | Проверка | Статус |
|---|---|---|---|---|
| EXP-COST-01 | Обязательные cost stress ×1,5/×2 должны иметь полный hourly capital path, а не только terminal total | `scripts/backtest.py::policy_backtest`; `_simulate_capital_sleeves_evidence` | `test_experiment_evidence_carries_aligned_cost_stress_paths` | Проверено red → green unit |
| EXP-COST-02 | Stress paths должны использовать exact nominal timestamps и сверяться с terminal return/max drawdown | `app/services/experiment_ledger.py::_trial_evidence_from_success` | missing-evidence regression + full suite | Проверено unit |
| EXP-COST-03 | Statistically selected trial с отрицательным terminal stress return не получает `READY` | `app/research/overfitting.py::analyze_experiment_family` | `test_family_analysis_rejects_selected_trial_with_negative_cost_stress` | Проверено unit |
| EXP-COST-04 | READY report без passed cost-stress evidence блокируется до selected-trial lookup | `app/services/model_promotion.py::evaluate_experiment_promotion_gate` | `test_ready_report_without_cost_stress_fails_closed` | Проверено unit |
| EXP-COST-05 | Persisted legacy gate v2 не авторизует normal activation | promotion gate schema v3 + `require_passed_experiment_promotion_gate` | `test_legacy_promotion_gate_schema_cannot_authorize_activation` | Проверено unit |
| EXP-MTM-01 | Entry costs, funding и terminal outcome остаются cumulative hourly MTM и reconcile to terminal capital | existing nominal path + scenario-specific stressed paths | observed-path regressions | Проверено unit |
| COMPAT-01 | DB/API/env/model artifact schemas и recommendation thresholds не изменены | migration отсутствует; isolated research/governance change | static diff, version/docs checks | Реализовано |
| BOUNDARY-01 | Advisory-only/read-only Bybit boundary не ослаблен | order mutation code не добавлен | static grep + full suite | Проверено static/unit |

## Непроверенная трассировка

- PostgreSQL integration/concurrency не выполнялись: отдельная test DB и PostgreSQL tools отсутствуют.
- Forward/live прибыльность, достаточная частота сигналов и реальная точность stress assumptions не доказаны unit tests.
- ×1,5/×2 не моделируют historical orderbook impact, partial fills, queue position, operator latency, dynamic fee tiers или cross/portfolio margin.
- Существующие successful experiment events без cost-stress v1 не реконструируются автоматически и требуют preregistered rerun.

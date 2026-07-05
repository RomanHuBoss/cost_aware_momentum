# Traceability

Состояние: release 1.26.4, 2026-07-05. Таблица связывает observed-opportunity policy inference с production-кодом, тестами и эксплуатационной документацией.

| ID | Требование / инвариант | Реализация | Проверка | Статус |
|---|---|---|---|---|
| ML-OPP-01 | Denominator экономической policy evaluation включает каждый фактически наблюдавшийся hourly decision cohort | `app/ml/training.py::evaluate_policy_model` (`opportunity_times`) | `test_policy_uncertainty_uses_zero_return_for_observed_no_trade_cohorts` | Проверено red → green unit |
| ML-OPP-02 | Реальный `NO TRADE` cohort имеет strategy return 0; отсутствующие market hours не синтезируются | reindex trade cohorts на observed opportunity index with zero fill | тот же regression test: 16 total = 8 trade + 8 no-trade | Проверено unit |
| ML-OPP-03 | Mean return, expected contribution, horizon phases и bootstrap LCB используют один unconditional opportunity path | `cohort_metrics`, `_horizon_separated_phase_series`, `_policy_mean_r_bootstrap` | regression + policy uncertainty/evidence suites | Проверено unit |
| ML-OPP-04 | Candidate evidence раскрывает trade/no-trade cohorts и арифметически согласовано | `policy_trade_cohorts`, `policy_no_trade_cohorts`; `evaluate_quality_gate` | lifecycle fixtures and full suite | Проверено unit |
| ML-OPP-05 | Incumbent-relative comparison не принимает missing/inconsistent opportunity accounting | incumbent metric validation in `app/ml/lifecycle.py` | `test_quality_gate_rejects_inconsistent_incumbent_opportunity_counts` | Проверено unit |
| ML-OPP-06 | Старое trade-conditional evidence не используется normal promotion | policy metric v17 and uncertainty v3 schema checks | `test_quality_gate_requires_observed_opportunity_policy_metric_schema` | Проверено unit |
| ML-LC-01 | Absolute gates, candidate/incumbent comparison, artifact activation and advisory-only boundaries не ослаблены | existing lifecycle/activation services | full unit suite | Проверено unit |
| OPS-01 | Active artifact не деактивируется; inactive legacy candidate требует retraining/new governed evidence | schema compatibility policy in `README.md`, `PATCH_1.26.4.md` | static review | Реализовано |

## Непроверенная трассировка

- Реальная PostgreSQL integration/concurrency проверка не выполнялась: отдельные `TEST_DATABASE_URL`/`POSTGRES_ADMIN_URL` не настроены.
- Forward/live прибыльность, достаточная частота сигналов и устойчивость edge не доказаны unit tests.
- Exact historical orderbook, point-in-time funding forecasts, sub-hour barrier ordering и exchange-accurate liquidation mechanics остаются ограничениями, перечисленными в `docs/SPEC_COMPLIANCE.md`.

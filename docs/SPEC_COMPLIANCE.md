# Specification Compliance

Источник: `docs/source/Cost_aware_hourly_ML_momentum_specification.docx`, версия 1.3.

| Требование | Статус | Доказательство/ограничение |
|---|---|---|
| Advisory-only, без order mutations | IMPLEMENTED / STATICALLY CHECKED | README, Bybit client и API audit; create/amend/cancel flow не обнаружен |
| PostgreSQL-only | IMPLEMENTED / UNIT CHECKED | `app.config.Settings`, migrations; integration DB в этой итерации не запускалась |
| Alembic revision IDs fit standard version table and graph has one head | IMPLEMENTED / UNIT + OFFLINE SQL CHECKED in 1.8.32 | duplicate 0008 branch removed; all revision IDs are limited to 32 characters; single head `0008_outcome_path_unavailable`; real PostgreSQL upgrade not executed in this environment |
| API / worker / trainer separation | IMPLEMENTED | process entry points и README |
| LONG/SHORT directional geometry | IMPLEMENTED / UNIT CHECKED | risk/labels/outcomes tests и independent randomized P&L audit |
| TP/SL/TIMEOUT, NO TRADE в policy | IMPLEMENTED | runtime/training/research audit |
| Point-in-time event/availability separation | IMPLEMENTED / UNIT CHECKED | market-data and signal tests |
| Fill/plan entry uses executable ask/bid | IMPLEMENTED / UNIT CHECKED in 1.8.26 | `create_execution_plan`; current quote, missing quote and zone regression tests |
| Entry-zone содержит только исполнимые тики внутри policy band | IMPLEMENTED / UNIT CHECKED in 1.8.28 | inward tick rounding; coarse-tick regression test |
| Entry outside zone requires new calculation / no entry | IMPLEMENTED / UNIT CHECKED | plan returns `NO_TRADE`; acceptance remains fail-closed |
| Exact read-only Bybit private GET signing | IMPLEMENTED / UNIT CHECKED in 1.8.28 | HMAC verified against exact query received by `httpx.MockTransport` |
| Dynamic crypto universe excludes known TradFi product families | IMPLEMENTED / UNIT CHECKED in 1.8.28 | exact normalized `stock/forex/commodity/xstocks/xstock` filter; explicit opt-in tested |
| Positive economic floor for automatic promotion | IMPLEMENTED / UNIT CHECKED in 1.8.26 | non-negative realized mean R and PF >= 1 when auto-activation is enabled |
| Account/profile-scoped margin capacity | IMPLEMENTED / UNIT CHECKED in 1.8.27 | allocated-capital basis, accepted-plan/open-trade reservations, sizing and acceptance regressions |
| Actual manual fill preserves accepted risk/margin reservations | IMPLEMENTED / UNIT CHECKED in 1.8.27 | actual entry fee substitution; stress-loss and margin rejection tests |
| Exact ATR barrier parity between labels and inference | IMPLEMENTED / UNIT CHECKED in 1.8.29 | `atr_pct_14` is validated and used without hidden clipping |
| Artifact label/temporal semantics fail-closed | IMPLEMENTED / UNIT CHECKED in 1.8.29 | runtime requires exact feature, label-path and temporal-split schemas |
| Candidate/incumbent comparison uses one barrier task | IMPLEMENTED / UNIT CHECKED in 1.8.29 | horizon and ATR multipliers must match; otherwise comparison is skipped and activation blocks |
| No-loss profit factor is distinct from missing/no-trade data | IMPLEMENTED / UNIT CHECKED in 1.8.29 | explicit gross gain/loss and validated unbounded flag |
| Backtest uses production artifact contract | IMPLEMENTED / UNIT CHECKED in 1.8.29 | shared `ModelRuntime`, optional expected SHA-256, no silent multiplier fallback |
| Research/promotion policy matches live one-active-symbol constraint | IMPLEMENTED / UNIT CHECKED in 1.8.32 | overlapping candidate for the same symbol is blocked until modeled exit; boundary re-entry and metric counters tested; policy schema v7 |
| Late execution-plan counterfactual path integrity | IMPLEMENTED / UNIT CHECKED in 1.8.30; MIGRATION NOT DB-TESTED | later `planning_time` cannot reuse movement before plan creation; status `PATH_UNAVAILABLE`; migration 0008 backfills existing rows |
| Profit factor preserves simultaneous gross gains/losses | IMPLEMENTED / UNIT CHECKED in 1.8.30 | gross gain/loss use individual weighted trade contributions; exit-time netting remains only for equity/drawdown |
| Execution instrument specs respect receipt cutoff | IMPLEMENTED / UNIT CHECKED in 1.8.30 | `valid_from` and `received_at` are both bounded by cutoff |
| Funding timeline advancement is bounded | IMPLEMENTED / UNIT CHECKED in 1.8.30 | stale anchor advances arithmetically rather than settlement-by-settlement |
| Purged temporal validation | IMPLEMENTED / UNIT CHECKED | split uses decision time and label end time |
| Immutable guarded model lifecycle | IMPLEMENTED / UNIT CHECKED | artifact/runtime/trainer tests; live promotion evidence not checked |
| Actual historical order book/fills/funding timeline in research | PARTIAL | documented research limitation |
| Full walk-forward, drift/regime governance, PBO/DSR | NOT FULLY IMPLEMENTED | requires a separate work package and data |
| Technical correctness ≠ profitability | DOCUMENTED | README and model card |

Формулировка «полностью соответствует спецификации» не применяется: существенные research/forward-evidence пункты остаются частичными.

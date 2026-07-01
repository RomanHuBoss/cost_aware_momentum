# Specification Compliance

Источник: `docs/source/Cost_aware_hourly_ML_momentum_specification.docx`, версия 1.3.

| Требование | Статус | Доказательство/ограничение |
|---|---|---|
| Advisory-only, без order mutations | IMPLEMENTED / STATICALLY CHECKED | README, Bybit client и API audit; create/amend/cancel flow не обнаружен |
| PostgreSQL-only | IMPLEMENTED / UNIT CHECKED | `app.config.Settings`, migrations; integration DB в этой итерации не запускалась |
| API / worker / trainer separation | IMPLEMENTED | process entry points и README |
| LONG/SHORT directional geometry | IMPLEMENTED / UNIT CHECKED | risk/labels/outcomes tests |
| TP/SL/TIMEOUT, NO TRADE в policy | IMPLEMENTED | runtime/training/research audit |
| Point-in-time event/availability separation | IMPLEMENTED / UNIT CHECKED | market-data and signal tests |
| Fill/plan entry uses executable ask/bid | IMPLEMENTED / UNIT CHECKED in 1.8.26 | `create_execution_plan`; current quote, missing quote and zone regression tests |
| Entry outside zone requires new calculation / no entry | IMPLEMENTED / UNIT CHECKED in 1.8.26 | plan returns `NO_TRADE`; acceptance remains fail-closed |
| Positive economic floor for automatic promotion | IMPLEMENTED / UNIT CHECKED in 1.8.26 | non-negative realized mean R and PF >= 1 when auto-activation is enabled |
| Purged temporal validation | IMPLEMENTED / UNIT CHECKED | split uses decision time and label end time |
| Immutable guarded model lifecycle | IMPLEMENTED / UNIT CHECKED | artifact/runtime/trainer tests; live promotion evidence not checked |
| Actual historical order book/fills/funding timeline in research | PARTIAL | documented research limitation |
| Full walk-forward, drift/regime governance, PBO/DSR | NOT FULLY IMPLEMENTED | requires a separate work package and data |
| Technical correctness ≠ profitability | DOCUMENTED | README and model card |

Формулировка «полностью соответствует спецификации» не применяется: существенные research/forward-evidence пункты остаются частичными.

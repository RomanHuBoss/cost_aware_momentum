# Specification Compliance

Источник: `docs/source/Cost_aware_hourly_ML_momentum_specification.docx`, версия 1.3.

| Требование | Статус | Доказательство/ограничение |
|---|---|---|
| Advisory-only, без order mutations | IMPLEMENTED / STATICALLY CHECKED | README, Bybit client и API audit; create/amend/cancel flow не обнаружен |
| PostgreSQL-only | IMPLEMENTED / UNIT CHECKED | `app.config.Settings`, migrations; integration DB в этой итерации не запускалась |
| API / worker / trainer separation | IMPLEMENTED | process entry points и README |
| LONG/SHORT directional geometry | IMPLEMENTED / UNIT + INDEPENDENT CHECKED | полный suite; 10 000 economics cases |
| TP/SL/TIMEOUT, NO TRADE в policy | IMPLEMENTED | runtime/training/research audit |
| Point-in-time event/availability separation | IMPLEMENTED / UNIT CHECKED in 1.8.25 | market-data, signals, 8 regression tests |
| Purged temporal validation | IMPLEMENTED / UNIT CHECKED | split использует decision time и label end time |
| Immutable guarded model lifecycle | IMPLEMENTED / UNIT CHECKED | artifact/runtime/trainer tests; live promotion evidence не проверено |
| Actual historical order book/fills/funding timeline in research | PARTIAL | documented research limitation |
| Full walk-forward, drift/regime governance, PBO/DSR | NOT FULLY IMPLEMENTED | требует отдельного work package и данных |
| Technical correctness ≠ profitability | DOCUMENTED | README и model card |

Формулировка «полностью соответствует спецификации» не применяется: существенные research/forward-evidence пункты остаются частичными.

# Specification Compliance

Источник: `docs/source/Cost_aware_hourly_ML_momentum_specification.docx`, версия 1.3.

| Требование | Статус | Доказательство/ограничение |
|---|---|---|
| Advisory-only, без order mutations | IMPLEMENTED / STATICALLY CHECKED | README, Bybit client и API audit; create/amend/cancel flow не обнаружен |
| PostgreSQL-only | IMPLEMENTED / UNIT CHECKED | `app.config.Settings`, migrations; integration DB в этой итерации не запускалась |
| Alembic revision IDs fit standard version table and graph has one head | IMPLEMENTED / UNIT + OFFLINE SQL CHECKED in 1.8.32 | duplicate 0008 branch removed; all revision IDs are limited to 32 characters; single head `0009_candle_receipt_availability`; real PostgreSQL upgrade not executed in this environment |
| API / worker / trainer separation | IMPLEMENTED | process entry points и README |
| LONG/SHORT directional geometry | IMPLEMENTED / UNIT CHECKED | risk/labels/outcomes tests и independent randomized P&L audit |
| TP/SL/TIMEOUT, NO TRADE в policy | IMPLEMENTED | runtime/training/research audit |
| Global capital risk/leverage ceilings cannot be weakened by a profile | IMPLEMENTED / UNIT CHECKED in 1.9.3 | centralized policy validates create/patch/activate/planning/acceptance; unsafe legacy row blocks; PostgreSQL integration not run |
| Некалиброванный baseline не становится исполнимой рекомендацией | IMPLEMENTED / UNIT CHECKED in 1.8.33 | diagnostic market signal allowed; plan forced to `NO_TRADE`; legacy acceptance blocked; production override rejected |
| TIMEOUT economics is estimated without holdout leakage and persisted end-to-end | IMPLEMENTED / UNIT CHECKED in 1.9.0 | train-only direction-specific median TIMEOUT return in stop-risk units; scaled to current barriers; exact signal value reused by plan/acceptance; baseline keeps explicit fallback |
| Raw trade and horizon-independent cohort promotion minima are separate | IMPLEMENTED / UNIT CHECKED in 1.8.34 | `policy_cohorts` remains descriptive; gate uses `policy_independent_cohorts` separated by full label horizon |
| Promotion requires non-microscopic policy actionability density | IMPLEMENTED / UNIT CHECKED in 1.9.5 | gate validates `policy_candidates`, `policy_trades`, and `policy_trade_rate`; default minimum is 1% in addition to absolute trade/cohort minima |
| Final holdout has minimum calendar coverage | IMPLEMENTED / UNIT CHECKED in 1.8.34 | `AUTO_TRAIN_MIN_HOLDOUT_SPAN_HOURS=168`; cross-sectional row count cannot replace temporal span |
| Trainer does not fit before configured holdout is feasible | IMPLEMENTED / UNIT CHECKED in 1.8.35 | preflight mirrors feature warm-up, 70/15/15 split, horizon embargo and holdout gates; defaults require 1206 hourly timestamps |
| Candidate must beat class-prior log-loss baseline | IMPLEMENTED / UNIT CHECKED in 1.8.35 | `log_loss_skill_vs_prior > 0`; missing/non-finite/inconsistent evidence fails closed |
| Rejected deterministic bootstrap waits for new evidence | IMPLEMENTED / UNIT CHECKED in 1.8.34 | same-profile quality-gate rejection returns `quality_gate_failed_waiting_for_new_data`; retry resumes after new timestamps/material change |
| Point-in-time event/availability separation | IMPLEMENTED / UNIT + OFFLINE SQL CHECKED in 1.9.1 | candle `available_at` uses post-response receipt time; migration 0009 moves legacy confirmed rows forward fail-closed; ticker/spec/account receipt timestamps and separate market/availability cutoffs remain enforced; real PostgreSQL migration not run in this environment |
| Hourly signal is anchored to the exact decision candle | IMPLEMENTED / UNIT CHECKED in 1.9.2 | `publish_hourly_signals` requires latest confirmed `close_time == event_time`; previous-hour data returns `missing_decision_candle` before scenario economics/natural-key publication |
| Partial hourly candle fetch is retried with exact coverage evidence | IMPLEMENTED / UNIT CHECKED in 1.9.4 | `sync_candles` reports exact last-price coverage; `hourly_market_close` performs bounded idempotent refetch after cooldown; inference gate remains fail-closed |
| Fill/plan entry uses executable ask/bid | IMPLEMENTED / UNIT CHECKED in 1.8.26 | `create_execution_plan`; current quote, missing quote and zone regression tests |
| Entry-zone содержит только исполнимые тики внутри policy band | IMPLEMENTED / UNIT CHECKED in 1.8.28 | inward tick rounding; coarse-tick regression test |
| Entry outside zone requires new calculation / no entry | IMPLEMENTED / UNIT CHECKED | plan returns `NO_TRADE`; acceptance remains fail-closed |
| Exact read-only Bybit private GET signing | IMPLEMENTED / UNIT CHECKED in 1.8.28 | HMAC verified against exact query received by `httpx.MockTransport` |
| Dynamic crypto universe excludes known TradFi product families | IMPLEMENTED / UNIT CHECKED in 1.8.28 | exact normalized `stock/forex/commodity/xstocks/xstock` filter; explicit opt-in tested |
| Positive economic floor for automatic promotion | IMPLEMENTED / UNIT CHECKED in 1.8.26 | non-negative realized mean R and PF >= 1 when auto-activation is enabled |
| Account/profile-scoped margin capacity | IMPLEMENTED / UNIT CHECKED in 1.8.27 | allocated-capital basis, accepted-plan/open-trade reservations, sizing and acceptance regressions |
| Actual manual fill preserves accepted risk/margin reservations | IMPLEMENTED / UNIT CHECKED in 1.8.27 | actual entry fee substitution; stress-loss and margin rejection tests |
| Executable decision-time entry semantics in labels | IMPLEMENTED / UNIT CHECKED in 1.8.36 | label entry is first future bar `open` at `decision_time`; feature-candle close-to-entry gap is excluded from P&L; `entry_price` persisted |
| Exact ATR barrier parity between labels and inference | IMPLEMENTED / UNIT CHECKED in 1.8.36 | both paths use `entry × atr_pct_14 × multiplier`; no hidden clipping or stale absolute ATR after an opening gap |
| Artifact label/temporal/economic semantics fail-closed | IMPLEMENTED / UNIT CHECKED through 1.9.0 | runtime requires exact feature, label-path, temporal-split and TIMEOUT-return schemas |
| Candidate/incumbent comparison uses one barrier task | IMPLEMENTED / UNIT CHECKED in 1.8.29 | horizon and ATR multipliers must match; otherwise comparison is skipped and activation blocks |
| No-loss profit factor is distinct from missing/no-trade data | IMPLEMENTED / UNIT CHECKED in 1.8.29 | explicit gross gain/loss and validated unbounded flag |
| Backtest uses production artifact contract | IMPLEMENTED / UNIT CHECKED in 1.8.29 | shared `ModelRuntime`, optional expected SHA-256, no silent multiplier fallback |
| Research/promotion policy matches live one-active-symbol constraint | IMPLEMENTED / UNIT CHECKED in 1.8.32 | overlapping candidate for the same symbol is blocked until modeled exit; boundary re-entry and metric counters tested; current policy schema v10 |
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

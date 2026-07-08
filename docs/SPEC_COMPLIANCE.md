# Specification Compliance

Источник концепции: `docs/source/Cost_aware_hourly_ML_momentum_specification.docx`. Статусы ниже основаны на коде и доступных unit/static checks версии 1.52.7; они не означают полную production/economic validation.

| Требование | Статус | Evidence / ограничение |
|---|---|---|
| Advisory-only, без отправки ордеров | Implemented, statically reviewed | Bybit client и API не содержат order create/amend/cancel paths |
| PostgreSQL-only | Implemented, unit/static checked | SQLAlchemy/Alembic; integration DB в этой итерации не запускалась |
| Разделение API / inference / trainer | Implemented | `app/main.py`, `app/workers/runner.py`, `app/workers/trainer.py` |
| Market signal отделён от capital-dependent plan | Implemented, unit tested | `app/services/signals.py`, `app/services/execution.py` |
| Directional LONG/SHORT geometry | Implemented, unit tested | `app/risk/math.py`, barrier/tick tests |
| Cost-aware fee/slippage/funding math | Implemented, unit tested | Decimal risk math и policy/backtest tests |
| Bounded-depth VWAP sizing и fresh acceptance | Implemented, unit tested | quantity-safe base-depth cap; aggregate VWAP may be between ticks; FULL-fill and tick-aligned source levels remain mandatory |
| Safe qty rounding и min order blocking | Implemented, unit tested | floor-to-step и post-round checks |
| Point-in-time features/specs | Implemented, unit tested | training/context/spec timeline tests |
| Clean-install dynamic historical bootstrap | Implemented, unit tested | frozen hash-validated cohort, immutable preflight scope, conservative tick fallback, automatic prospective upgrade |
| Startup backfill depth covers default training minimum | Implemented, unit tested | `INITIAL_BACKFILL_BARS=1500`; `sync_candles()` paginates >1000 kline requests; does not lower quality gates |
| Purged temporal split/final holdout | Implemented, unit tested | shared capacity contract, structured post-filter deferral, `chronological_split`, walk-forward tests |
| Immutable artifact + guarded activation | Implemented, unit tested | lifecycle/artifact/promotion tests |
| Drift/attrition/selection governance | Implemented, unit tested | соответствующие services и tests |
| Full PostgreSQL integration evidence | Not verified this iteration | отдельная TEST_DATABASE_URL не была настроена |
| Live Bybit/network smoke evidence | Not verified this iteration | внешняя сеть/credentials не использовались |
| Economic profitability | Not claimed | требуется paper/shadow/forward evidence |
| Fail-closed operator diagnostics | Implemented, unit tested | structured walk-forward capacity, safe decision-time contract JSON fields, and pre-publication stale skip diagnostics |
| Worker stale decision scheduling | Implemented, unit tested | stale hourly/catch-up inference records `decision_publication_lag_exceeded` before publication attempt |
| Trainer data-dependent wait diagnostics | Implemented, unit tested | rejected bootstrap/recovery candidates report `quality_gate_failed_waiting_for_new_data` or `training_deferred_waiting_for_new_data` with new-labeled-hour progress; previous profile evidence is recovered from trigger or candidate metrics |
| Dependency QA reproducibility | Implemented, static/unit checked | NumPy constrained to `<2.5`; NumPy 2.5.1 fresh install was confirmed incompatible with existing funding/policy tests |
| Complete release attestation | Implemented since 1.51.1 | required docs, version agreement, patch/report, SHA256SUMS |

| Open-interest startup history depth | Implemented, unit tested | separate `HISTORY_BACKFILL_OPEN_INTEREST_PAGES_PER_SYMBOL=7` covers default 1206-hour training readiness at 200 OI rows/page |

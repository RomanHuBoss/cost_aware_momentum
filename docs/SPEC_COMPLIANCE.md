# Specification Compliance

Источник концепции: `docs/source/Cost_aware_hourly_ML_momentum_specification.docx`. Статусы ниже основаны на коде и доступных unit/static checks версии 1.52.1; они не означают полную production/economic validation.

| Требование | Статус | Evidence / ограничение |
|---|---|---|
| Advisory-only, без отправки ордеров | Implemented, statically reviewed | Bybit client и API не содержат order create/amend/cancel paths |
| PostgreSQL-only | Implemented, unit/static checked | SQLAlchemy/Alembic; integration DB в этой итерации не запускалась |
| Разделение API / inference / trainer | Implemented | `app/main.py`, `app/workers/runner.py`, `app/workers/trainer.py` |
| Market signal отделён от capital-dependent plan | Implemented, unit tested | `app/services/signals.py`, `app/services/execution.py` |
| Directional LONG/SHORT geometry | Implemented, unit tested | `app/risk/math.py`, barrier/tick tests |
| Cost-aware fee/slippage/funding math | Implemented, unit tested | Decimal risk math и policy/backtest tests |
| Safe qty rounding и min order blocking | Implemented, unit tested | floor-to-step и post-round checks |
| Point-in-time features/specs | Implemented, unit tested | training/context/spec timeline tests |
| Clean-install dynamic historical bootstrap | Implemented, unit tested | frozen hash-validated cohort, immutable preflight scope, conservative tick fallback, automatic prospective upgrade |
| Purged temporal split/final holdout | Implemented, unit tested | shared capacity contract, structured post-filter deferral, `chronological_split`, walk-forward tests |
| Immutable artifact + guarded activation | Implemented, unit tested | lifecycle/artifact/promotion tests |
| Drift/attrition/selection governance | Implemented, unit tested | соответствующие services и tests |
| Full PostgreSQL integration evidence | Not verified this iteration | отдельная TEST_DATABASE_URL не была настроена |
| Live Bybit/network smoke evidence | Not verified this iteration | внешняя сеть/credentials не использовались |
| Economic profitability | Not claimed | требуется paper/shadow/forward evidence |
| Fail-closed operator diagnostics | Implemented, unit tested | structured walk-forward capacity and safe decision-time contract JSON fields |
| Complete release attestation | Implemented since 1.51.1 | required docs, version agreement, patch/report, SHA256SUMS |

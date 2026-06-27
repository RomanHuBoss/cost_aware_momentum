# Трассировка требований спецификации

| Требование | Статус | Реализация / замечание |
|---|---|---|
| FastAPI/Uvicorn, PostgreSQL only | Да | `app/main.py`, `app/db/*`; SQLite URL отвергается |
| Отдельный market/inference worker | Да | `app/workers/runner.py` |
| Ручное исполнение, без order API | Да | public/read-only Bybit client; accept/fills — журнал, не ордер |
| Closed-candle cutoff | Да | confirmed candles; `close_time` и `available_at` ограничены event cutoff |
| Market signal отдельно от execution plan | Да | отдельные ORM-объекты и versioned profile recalculation |
| NO TRADE — policy, не класс модели | Да с 1.3.0 | ML выдает TP/SL/TIMEOUT; `publish_hourly_signals` применяет net policy |
| Direction-specific TP/SL/TIMEOUT | Да с 1.3.0 | `make_barrier_dataset`, `TemporalCalibratedBarrierModel` |
| Logistic baseline и nonlinear candidate | Да с 1.3.0 | logistic и HistGradientBoostingClassifier |
| Временная calibration | Да с 1.3.0 | later calibration window, sigmoid OVR |
| Purging и final holdout | Частично | один chronological split с purge gap; нет полноценного multi-fold walk-forward |
| Model registry/hash/activation/rollback | Да с 1.3.0 | SHA256 validation, activation CLI, unique active index, audit/outbox |
| Worker использует active registry model | Да с 1.3.0 | periodic reload и runtime/registry readiness match |
| Фоновое периодическое переобучение | Да с 1.4.0 | отдельный trainer process, minimum-new-data gate, rolling lookback и job heartbeat |
| Безопасное продвижение новой модели | Да с 1.4.0 | same-holdout incumbent comparison, absolute/relative quality gate, immutable artifact и guarded activation |
| Fail-closed при stale/missing data | Да для live inference | stale candle/ticker, missing features/bid-ask/spec и high spread блокируют публикацию |
| Dynamic universe | Частично | live selection есть; historical point-in-time membership snapshots отсутствуют |
| Издержки, net R/R, EV | Да, базовая модель | fee/slippage/funding scenario/stop reserve; account fee-rate и depth impact пока не подключены полностью |
| Профили капитала и sizing | Да | risk budget, qty rounding, margin/liquidity/portfolio/min-order caps |
| Компактные плитки и modal actions | Да | `web/*` |
| Versioned glossary и доступность | Да | DB glossary, hover/focus/tap tooltips |
| Одна текущая рекомендация на символ | Да | supersede transaction + PostgreSQL partial unique index |
| Audit/idempotency/outbox | Да | append-only hash chain, idempotency keys, outbox events |
| Counterfactual outcome | Нет | сохраняется сигнал, но итог исхода автоматически не рассчитывается |
| Event-driven portfolio backtest | Частично | barrier-policy test есть; нет no-fill/partial fills/operator latency/full portfolio simulator |
| Drift monitoring/fallback | Частично | pre-activation holdout gate есть; PSI/live calibration drift и realized-performance auto-rollback остаются roadmap |
| Historical orderbook impact | Нет | требуется собственный архив snapshots |
| Production evidence | Нет | требуется paper/shadow forward period и go/no-go evidence |

Подробная оценка: `docs/SPEC_COMPLIANCE.md`.

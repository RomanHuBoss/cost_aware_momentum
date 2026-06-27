# Трассировка требований спецификации

| Требование | Статус | Реализация / замечание |
|---|---|---|
| FastAPI/Uvicorn, PostgreSQL only | Да | `app/main.py`, `app/db/*`; SQLite URL отвергается |
| Отдельный market/inference worker | Да | `app/workers/runner.py` |
| Отдельный background trainer | Да с 1.4.0 | отдельный процесс, advisory lock, heartbeat и job history |
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
| Фоновое периодическое переобучение | Да с 1.4.0 | rolling lookback, minimum-new-time gate и guarded auto-activation |
| Dataset-aware trigger | Да с 1.5.0 | row growth, new-symbol coverage, top-N universe change и legacy profile detection |
| Training data lineage | Да с 1.5.0 | artifact/registry сохраняют rows, timestamps, full symbol scope, coverage и fingerprints |
| Progressive historical backfill | Да с 1.5.0 | отдельный `history_backfill` job до target days с batch/page limits и launch-time floor |
| Безопасное продвижение новой модели | Да с 1.5.0 | common holdout, ML gates, cost-aware policy gates, immutable artifact и atomic activation |
| Fail-closed при stale/missing data | Да для live inference | stale candle/ticker, missing features/bid-ask/spec и high spread блокируют публикацию |
| Dynamic universe | Частично | live selection и актуальная UI-фильтрация есть; historical point-in-time membership snapshots отсутствуют |
| Издержки, net R/R, EV | Да, базовая модель | fee/slippage/funding scenario/stop reserve; account fee-rate и depth impact пока не подключены полностью |
| Policy-aware model promotion | Да с 1.5.0 | trades, realized mean R, profit factor, drawdown и incumbent-relative regression limits |
| Профили капитала и sizing | Да | risk budget, qty rounding, margin/liquidity/portfolio/min-order caps |
| Компактные плитки и modal actions | Да | `web/*` |
| Актуальность status/universe UI | Да с 1.5.0 | периодическое обновление и фильтрация текущих рекомендаций по worker universe |
| Versioned glossary и доступность | Да | DB glossary, hover/focus/tap tooltips |
| Одна текущая рекомендация на символ | Да | supersede transaction + PostgreSQL partial unique index |
| Audit/idempotency/outbox | Да | append-only hash chain, idempotency keys, outbox events, job runs и heartbeats |
| Counterfactual outcome | Да, базовый TP1/SL/TIMEOUT с 1.6.0 | immutable signal outcome и отдельный result для каждой plan version; confirmed hourly path, conservative same-bar SL, legacy funding fail-closed, API/UI/audit |
| Event-driven portfolio backtest | Частично | barrier-policy test есть; нет no-fill/partial fills/operator latency/full portfolio simulator |
| Drift monitoring/fallback | Частично | pre-activation ML/policy gate есть; PSI/live calibration drift и realized-performance auto-rollback остаются roadmap |
| Historical orderbook impact | Нет | требуется собственный архив snapshots |
| Production evidence | Нет | требуется paper/shadow forward period и go/no-go evidence |

Подробная оценка: `docs/SPEC_COMPLIANCE.md`.

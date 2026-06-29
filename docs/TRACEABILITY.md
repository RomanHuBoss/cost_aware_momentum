# Трассировка требований спецификации

| Требование | Статус | Реализация / замечание |
|---|---|---|
| FastAPI/Uvicorn, PostgreSQL only | Да | `app/main.py`, `app/db/*`; SQLite URL отвергается |
| Отдельный market/inference worker | Да | `app/workers/runner.py` |
| Отдельный background trainer | Да; операторский контур с 1.8.0, crash recovery с 1.8.1 | отдельный процесс, advisory lock, heartbeat/job history, status dialog и PostgreSQL-backed control requests с linked retry после stale owner |
| Ручное исполнение, без order API | Да | public/read-only Bybit client; accept/fills — журнал, не ордер |
| Хронология фактических manual fills | Да с 1.7.12 | close под row lock; `fill_time` не раньше entry и последнего fill; invalid chronology отклоняется до mutation |
| Closed-candle cutoff | Да | confirmed candles; `close_time` и `available_at` ограничены event cutoff |
| Строгая hourly continuity для features/labels | Да с 1.7.11; segmented state с 1.8.8 | 24 последовательных валидных часов; gap/duplicate/invalid OHLCV сбрасывает EMA/ATR/rolling state; invalid future bar исключает label с diagnostics |
| Market signal отдельно от execution plan | Да | отдельные ORM-объекты и versioned profile recalculation |
| NO TRADE — policy, не класс модели | Да с 1.3.0; направление согласовано в 1.8.4 | ML выдает TP/SL/TIMEOUT для LONG и SHORT; `publish_hourly_signals` выбирает направление по текущему net EV/R и затем применяет execution gates |
| Direction-specific TP/SL/TIMEOUT | Да с 1.3.0 | `make_barrier_dataset`, `TemporalCalibratedBarrierModel` |
| Logistic baseline и nonlinear candidate | Да с 1.3.0 | logistic и HistGradientBoostingClassifier |
| Временная calibration | Да с 1.3.0 | later calibration window, sigmoid OVR |
| Корректный порядок классов и probability simplex | Да с 1.7.9; boundary усилена в 1.8.8 | class-order-safe log loss; runtime, holdout, EV/R math и backtest отвергают non-finite/out-of-range/non-unit probabilities |
| Полная directional-пара в research/lifecycle | Да с 1.8.9 | `make_barrier_dataset` атомарно сохраняет LONG+SHORT; chronological split, holdout и backtest требуют ровно одну строку каждого направления на `decision_time/symbol` |
| Purging и final holdout | Частично; усилено в 1.7.10 | один chronological split; overlap очищается по фактическому `label_end_time` плюс horizon-hour embargo, но нет полноценного multi-fold walk-forward |
| Model registry/hash/activation/rollback | Да с 1.3.0 | SHA256 validation, activation CLI, unique active index, audit/outbox |
| Worker использует active registry model | Да с 1.3.0 | periodic reload и runtime/registry readiness match |
| Exact artifact contract и inference features | Усилено в 1.8.10 | exact schema/horizon/calibration/classes; every required runtime feature must be present and finite, without silent zero-imputation |
| Fail-closed class/incumbent promotion metrics | Да с 1.8.10 | malformed class distribution and non-finite incumbent metrics block candidate comparison/activation |
| Фоновое периодическое переобучение | Да с 1.4.0 | rolling lookback, minimum-new-time gate и guarded auto-activation |
| Dataset-aware trigger | Да с 1.5.0 | row growth, new-symbol coverage, top-N universe change и legacy profile detection |
| Training data lineage | Да с 1.5.0 | artifact/registry сохраняют rows, timestamps, full symbol scope, coverage и fingerprints |
| Progressive historical backfill | Да с 1.5.0 | отдельный `history_backfill` job до target days с batch/page limits и launch-time floor |
| Безопасное продвижение новой модели | Да; усилено в 1.7.8 | common holdout, ML/policy gates, immutable artifact, optimistic active-version guard и единая register+activate транзакция |
| JSON-safe model lifecycle | Да с 1.7.1 | missing/non-finite gate metrics сохраняются как `null`; не прошедший кандидат регистрируется inactive без изменения incumbent |
| Controlled recovery при отсутствующем active artifact | Да с 1.7.2–1.7.3 | baseline только при явном non-production разрешении; DEGRADED diagnostics; immediate bootstrap/recovery scheduling; short same-episode technical backoff; absolute gates; invalid/hash mismatch остаются fail-closed |
| Диагностика и controlled recovery orphan model artifact | Да с 1.7.7 | status/UI различают inactive candidate и unregistered `.joblib`; explicit CLI повторно валидирует metadata и absolute gates, production и failed gate остаются blocked |
| Fail-closed при stale/missing data | Да; accept усилен в 1.8.7 | stale candle/ticker, missing/non-contiguous features, bid-ask/spec и high spread блокируют публикацию; stale/missing/future account snapshot блокирует execution plan и accept |
| Dynamic universe | Частично | live selection и актуальная UI-фильтрация есть; historical point-in-time membership snapshots отсутствуют |
| Издержки, net R/R, EV | Да, базовая модель | fee/slippage/funding scenario/stop reserve; account fee-rate и depth impact пока не подключены полностью |
| Знак funding и граница cost inputs | Да с 1.8.10 | trader-perspective sign: positive funding debits LONG and credits SHORT; non-finite/negative costs and invalid funding horizon/rate fail closed in live and research math |
| Фактический риск ручной позиции | Да с 1.8.10 | `initial_stress_loss` фиксируется по actual fill; `remaining_stress_loss` пропорционально освобождается partial closes и входит в aggregate open risk |
| Направленная геометрия entry/SL/TP | Да с 1.7.4; liquidation fail-open закрыт в 1.8.7 | LONG: `SL < entry < TP`; SHORT: `TP < entry < SL`; invalid geometry блокируется, а stop за оценочной liquidation boundary всегда получает `BLOCKED_LIQUIDATION` |
| Числовая граница position sizing | Да с 1.7.5 | non-finite/invalid capital, risk, costs, margin, caps и instrument constraints дают finite zero-sized `BLOCKED_INVALID_INPUT` без исключений |
| Числовая граница counterfactual plan valuation | Да с 1.7.6 | invalid qty/stress/cost/funding snapshot сохраняется как zero-valued `INVALID_INPUT`; поврежденная plan version не блокирует остальные outcomes |
| Policy-aware model promotion | Да с 1.5.0; exit-time accounting с 1.8.8 | один direction по `EV/R → net RR → LONG`; realized R/drawdown по modeled exit events; incumbent-relative regression limits |
| Профили капитала и sizing | Да; numeric boundary усилена в 1.8.8 | risk budget, qty rounding, margin/liquidity/portfolio/min-order caps; `max_leverage < 1` блокируется; executable ask/bid recheck и global advisory lock защищают общий open risk |
| Пересчет при adverse executable entry | Да с 1.8.10 | future ticker/spec блокируются; adverse ask/bid создает новую plan version и повторно проверяет qty, stress loss, margin, liquidation, R/R and EV |
| Компактные плитки и modal actions | Да | `web/*` |
| Актуальность status/universe UI | Да с 1.5.0 | периодическое обновление и фильтрация текущих рекомендаций по worker universe |
| Operator-visible trainer status/control | Да с 1.8.0; stale request recovery с 1.8.1 | heartbeat, phase, next check, wait progress, artifact, latest training/control jobs; CSRF-protected `CHECK_NOW`/`RECOVER_NOW`; abandoned `RUNNING` определяется по age+heartbeat, старый claim терминализируется и late completion отклоняется |
| Versioned glossary и доступность | Да | DB glossary, hover/focus/tap tooltips |
| Одна текущая рекомендация на символ | Да | supersede transaction + PostgreSQL partial unique index |
| Audit/idempotency/outbox | Да | append-only hash chain, idempotency keys, outbox events, job runs и heartbeats |
| Release tree / checksum integrity | Да; manifest repaired in 1.8.10 | `scripts/release_integrity.py`, `python manage.py release-check`, CI pre-install check; missing/modified/unlisted/forbidden artifacts fail closed |
| Counterfactual outcome | Да, с intrabar refinement в 1.7.0 | immutable signal outcome и отдельный result для каждой plan version; confirmed hourly path, exact 1/3/5-minute window для hourly TP/SL ambiguity, missing intrabar fail-closed, conservative same-finest-bar SL, API/UI/audit |
| Counterfactual valuation from plan snapshot | Да с 1.8.10 | recalculated plan uses its own immutable entry/planning time for P&L and funding timeline; signal entry is only a legacy fallback |
| Event-driven portfolio backtest | Частично, overlap accounting исправлен в 1.8.5 | EV/R policy, exact fee legs, H capital sleeves и active concurrency есть; нет no-fill/partial fills/intrahorizon MTM/operator latency/full execution simulator |
| Drift monitoring/fallback | Частично | pre-activation ML/policy gate есть; PSI/live calibration drift и realized-performance auto-rollback остаются roadmap |
| Historical orderbook impact | Нет | требуется собственный архив snapshots |
| Production evidence | Нет | требуется paper/shadow forward period и go/no-go evidence |

Подробная оценка: `docs/SPEC_COMPLIANCE.md`.

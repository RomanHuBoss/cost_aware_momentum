# Трассировка требований спецификации

## 1.8.18 trace additions

| Requirement / invariant | Implementation | Verification |
|---|---|---|
| Manual/paper risk isolation | `risk_scope_key`, `execution_plan_scope_clause`, scoped `open_risk_usdt` | `tests/unit/test_account_scope_integrity_2026_06_30.py` |
| Shared risk for profiles linked to one exchange account | account-scoped SQL predicates and advisory-lock key | same regression module; acceptance safety test |
| Account-specific reconciliation | filtered equity, positions and manual journal in `reconciliation_issues` | account reconciliation regressions |
| Position snapshot account identity | ORM field, account sync propagation, migration `0007_position_account_scope` | ORM/sync tests; PostgreSQL integration assertions |
| Scope-consistent API behavior | portfolio endpoint and same-symbol acceptance conflict use shared scope predicate | portfolio API regression plus full suite |
| Release reproducibility | regenerated `SHA256SUMS`, patch and iteration reports | `python manage.py release-check` |

## 1.8.17 trace additions

| Requirement | Implementation | Verification |
|---|---|---|
| Market signal remains capital-independent while plan economics follows planning inputs | `app/services/execution.py`, `app/api/serializers.py`, `web/js/app.js` | `test_detail_distinguishes_signal_and_execution_plan_economics`, snapshot-persistence regression |
| Break-even matches `TP / SL / TIMEOUT` EV | `app/risk/math.py`, `app/api/serializers.py` | exact zero-EV identity, non-binary API regression, 1,000 randomized independent identities |
| Corrupted plan economics is not presented as valid | `app/api/serializers.py`, `web/js/app.js` | `test_corrupted_execution_plan_economics_snapshot_is_not_presented_as_valid` |
| Read-only and unknown profile modes fail closed | `app/services/execution.py` | missing-account and unknown-mode regressions |
| Operator can distinguish scope and nullable integrity state | `web/js/app.js` | frontend contract regression plus `node --check` |

## 1.8.16 trace additions

| Requirement | Implementation | Verification |
|---|---|---|
| Fresh per-trade risk and margin before `ACCEPTED` | `app/services/execution.py`, `app/api/v1/recommendations.py` | capital-drop, insufficient-margin and valid-acceptance regressions |
| Current exchange constraints at acceptance | `app/services/execution.py`, `app/api/v1/recommendations.py` | changed `qtyStep`/`minQty` regression and off-tick legacy-plan regression |
| Current adverse funding and policy economics | `app/services/execution.py`, `app/api/v1/recommendations.py` | newly adverse funding regression |
| Tick-valid signal geometry | `app/services/signals.py` | LONG and SHORT conservative tick-rounding regressions |
| Auditability of fresh decision inputs | `app/api/v1/recommendations.py` | decision context stores current notional, margin, risk, funding, policy metrics and spec time |

## 1.8.15 trace additions

| Requirement | Implementation | Verification |
|---|---|---|
| Finite non-crossed executable quote | `app/services/execution.py`, `app/services/signals.py`, `app/services/universe.py` | crossed/non-finite quote regressions |
| Batch isolation for malformed ticker numerics | `app/services/market_data.py` | mixed malformed/valid ticker sync regression |
| Entry-zone based on executable side | `app/api/serializers.py` | LONG last-inside/ask-outside regression |
| Published targets match modeled economics | `app/services/signals.py`, `app/api/serializers.py` | single-TP scenario regression; TP1 weight fixed at 100% |


## 1.8.14 trace additions

| Requirement | Implementation | Verification |
|---|---|---|
| Funding only after crossed settlement | `app/risk/math.py`, `scripts/backtest.py` | `test_favorable_funding_cannot_improve_pretrade_rr_or_ev_without_exit_timing` plus corrected funding regressions |
| Independent policy evidence | `app/ml/training.py`, `app/ml/lifecycle.py` | cohort-weighting and one-hour pseudo-replication regressions |
| No parallel live/terminal plan recalculation | `app/services/execution.py`, `app/api/v1/recommendations.py` | immutable bulk-recalculation regression and API fail-closed branch |
| Atomic plan version allocation | `app/services/execution.py`, `app/db/locks.py` | transaction-lock ordering regression |
| Valid default model horizon | `app/config.py` | positive/membership configuration regression |

| Требование | Статус | Реализация / замечание |
|---|---|---|
| FastAPI/Uvicorn, PostgreSQL only | Да | `app/main.py`, `app/db/*`; SQLite URL отвергается |
| Отдельный market/inference worker | Да | `app/workers/runner.py` |
| Отдельный background trainer | Да; операторский контур с 1.8.0, crash recovery с 1.8.1 | отдельный процесс, advisory lock, heartbeat/job history, status dialog и PostgreSQL-backed control requests с linked retry после stale owner |
| Ручное исполнение, без order API | Да | public/read-only Bybit client; accept/fills — журнал, не ордер |
| Хронология фактических manual fills | Усилено в 1.8.11 | entry/close timestamps timezone-aware, не в будущем; close не раньше entry/последнего fill; invalid chronology отклоняется до mutation |
| Closed-candle cutoff | Да | confirmed candles; `close_time` и `available_at` ограничены event cutoff |
| Строгая hourly continuity для features/labels | Да с 1.7.11; segmented state с 1.8.8 | 24 последовательных валидных часов; gap/duplicate/invalid OHLCV сбрасывает EMA/ATR/rolling state; invalid future bar исключает label с diagnostics |
| Market signal отдельно от execution plan | Да | отдельные ORM-объекты и versioned profile recalculation |
| NO TRADE — policy, не класс модели | Да с 1.3.0; направление согласовано в 1.8.4 | ML выдает TP/SL/TIMEOUT для LONG и SHORT; `publish_hourly_signals` выбирает направление по текущему net EV/R и затем применяет execution gates |
| Direction-specific TP/SL/TIMEOUT | Да с 1.3.0; gap path исправлен в 1.8.12, propagation в 1.8.13 | `make_barrier_dataset`, `chronological_split`, `TemporalCalibratedBarrierModel`; favorable open-gap capped at TP, adverse stop-gap valued at open, split требует и сохраняет `exit_at_open` |
| Logistic baseline и nonlinear candidate | Да с 1.3.0 | logistic и HistGradientBoostingClassifier |
| Временная calibration | Да с 1.3.0 | later calibration window, sigmoid OVR |
| Корректный порядок классов и probability simplex | Да с 1.7.9; boundary усилена в 1.8.8 | class-order-safe log loss; runtime, holdout, EV/R math и backtest отвергают non-finite/out-of-range/non-unit probabilities |
| Полная directional-пара в research/lifecycle | Да с 1.8.9 | `make_barrier_dataset` атомарно сохраняет LONG+SHORT; chronological split, holdout и backtest требуют ровно одну строку каждого направления на `decision_time/symbol` |
| Purging и final holdout | Частично; усилено в 1.7.10 | один chronological split; overlap очищается по фактическому `label_end_time` плюс horizon-hour embargo, но нет полноценного multi-fold walk-forward |
| Model registry/hash/activation/rollback | Да с 1.3.0 | SHA256 validation, activation CLI, unique active index, audit/outbox |
| Worker использует active registry model | Да с 1.3.0 | periodic reload и runtime/registry readiness match |
| Exact artifact contract и inference features | Усилено в 1.8.10 | exact schema/horizon/calibration/classes; every required runtime feature must be present and finite, without silent zero-imputation |
| Fail-closed class/incumbent promotion metrics | Усилено в 1.8.14 | malformed class/incumbent metrics блокируют comparison; schema `exit-time-open-gap-propagated-cohort-weighted-v5`, horizon/capital sleeves обязаны совпадать с candidate artifact; affected v3 metrics отвергаются |
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
| Знак funding и граница cost inputs | Усилено в 1.8.11 | trader-perspective sign сохранен; execution plan пересчитывает cumulative funding от planning time, неизвестный interval при известном settlement блокирует plan |
| Фактический риск ручной позиции | Да с 1.8.10 | `initial_stress_loss` фиксируется по actual fill; `remaining_stress_loss` пропорционально освобождается partial closes и входит в aggregate open risk |
| Направленная геометрия entry/SL/TP | Да с 1.7.4; liquidation fail-open закрыт в 1.8.7 | LONG: `SL < entry < TP`; SHORT: `TP < entry < SL`; invalid geometry блокируется, а stop за оценочной liquidation boundary всегда получает `BLOCKED_LIQUIDATION` |
| Числовая граница position sizing | Да с 1.7.5 | non-finite/invalid capital, risk, costs, margin, caps и instrument constraints дают finite zero-sized `BLOCKED_INVALID_INPUT` без исключений |
| Числовая граница counterfactual plan valuation | Да с 1.7.6 | invalid qty/stress/cost/funding snapshot сохраняется как zero-valued `INVALID_INPUT`; поврежденная plan version не блокирует остальные outcomes |
| Policy-aware model promotion | Усилено в 1.8.14 | один direction по `EV/R → net RR → LONG`; exit-time R path делит capital на H sleeves; mean R/EV equal-weight по hourly cohorts; gate требует `policy_trades` и `policy_cohorts`; v4/legacy metrics отвергаются |
| Профили капитала и sizing | Да; numeric boundary усилена в 1.8.8 | risk budget, qty rounding, margin/liquidity/portfolio/min-order caps; `max_leverage < 1` блокируется; executable ask/bid recheck и global advisory lock защищают общий open risk |
| Пересчет при adverse executable entry | Да с 1.8.10 | future ticker/spec блокируются; adverse ask/bid создает новую plan version и повторно проверяет qty, stress loss, margin, liquidation, R/R and EV |
| Компактные плитки и modal actions | Да | `web/*` |
| Актуальность status/universe UI | Да с 1.5.0 | периодическое обновление и фильтрация текущих рекомендаций по worker universe |
| Operator-visible trainer status/control | Да с 1.8.0; stale request recovery с 1.8.1 | heartbeat, phase, next check, wait progress, artifact, latest training/control jobs; CSRF-protected `CHECK_NOW`/`RECOVER_NOW`; abandoned `RUNNING` определяется по age+heartbeat, старый claim терминализируется и late completion отклоняется |
| Versioned glossary и доступность | Да | DB glossary, hover/focus/tap tooltips |
| Одна текущая рекомендация на символ | Да | supersede transaction + PostgreSQL partial unique index |
| Audit/idempotency/outbox | Да | append-only hash chain, idempotency keys, outbox events, job runs и heartbeats |
| Release tree / checksum integrity | Да; manifest repaired in 1.8.10 | `scripts/release_integrity.py`, `python manage.py release-check`, CI pre-install check; missing/modified/unlisted/forbidden artifacts fail closed |
| Counterfactual outcome | Усилено в 1.8.12 | immutable outcome; full OHLC, open-first gap price/time, configured intrabar interval and fail-closed missing path; version `primary-barrier-intrabar-open-gap-v4` |
| Counterfactual valuation from plan snapshot | Усилено в 1.8.12 | recalculated plan uses immutable entry/planning time; SL valuation subtracts only residual stop-gap reserve not already embedded in observed exit; signal entry is only a legacy fallback |
| Event-driven portfolio backtest | Частично; gap accounting усилен в 1.8.12 | EV/R policy, exact fee legs, H capital sleeves, active concurrency и residual stop-gap reserve есть; нет no-fill/partial fills/intrahorizon MTM/operator latency/full execution simulator |
| Drift monitoring/fallback | Частично | pre-activation ML/policy gate есть; PSI/live calibration drift и realized-performance auto-rollback остаются roadmap |
| Historical orderbook impact | Нет | требуется собственный архив snapshots |
| Production evidence | Нет | требуется paper/shadow forward period и go/no-go evidence |

Подробная оценка: `docs/SPEC_COMPLIANCE.md`.

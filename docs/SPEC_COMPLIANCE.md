# Specification Compliance

Состояние на 2026-07-05. Статусы основаны на фактическом коде release 1.21.0, а не на заявлении о полной реализации спецификации.

| Требование | Статус | Доказательство / ограничение |
|---|---|---|
| Advisory-only, read-only Bybit | Реализовано | `app/bybit/client.py` содержит GET market/account reads; order mutation methods отсутствуют. |
| PostgreSQL-only | Реализовано | SQLAlchemy/PostgreSQL models и Alembic; SQLite fallback отсутствует. |
| Point-in-time confirmed hourly data | Реализовано | `Candle.close_time`, `available_at`, confirmed semantics, temporal tests. |
| LONG/SHORT executable-side entry semantics | Частично реализовано 1.10.0 | Direction-specific adverse spread proxy. Exact historical bid/ask и operator latency отсутствуют. |
| Historical orderbook depth/VWAP/no-fill/partial-fill | Частично реализовано 1.14.0 | Forward point-in-time REST snapshots сохраняются в PostgreSQL; plan/acceptance используют direction-aware bounded-depth simulation, complete-fill VWAP и FULL/PARTIAL/NO_FILL evidence. Исторический backfill до 1.14.0, RPI/queue position, limit-order fill probability и реальный partial-fill lifecycle отсутствуют; поэтому model/backtest gap не считается закрытым. |
| Historical funding tied to actual settlements in research labels | Реализовано 1.12.0 для realized costs | Progressive backfill сохраняет фактические settlement timestamps; training/backtest агрегируют только события `(entry, actual_exit]` и fail-closed при гэпах. Будущая фактическая ставка не участвует в ex-ante selection. Исторические forecast snapshots и point-in-time изменения interval пока отсутствуют. |
| Rolling/expanding walk-forward | Реализовано 1.11.0 | Три purged expanding folds внутри development period, fresh fit/calibration на каждом fold и отдельный final holdout. Не является nested CV/PBO. |
| Operator-selection bias correction | Частично реализовано 1.21.0 | Prospective ex-ante opportunity ledger, immutable first UI-exposure evidence и ACCEPT/REJECT/NO_DECISION сохранены. Denominator теперь включает только plan versions, действительно показанные first-party UI после ≥50% видимости в активной вкладке в течение ≥1 секунды; exposure time задаёт chronological ordering, coverage/anomalies публикуются и низкое coverage блокирует IPSW. Signal-atomic OOS propensity split и cluster moving-block intervals сохранены. Это не causal treatment model: eye tracking, comprehension, latent operator state, propensity refit внутри bootstrap, API/CLI exposures и pre-1.15 opportunities отсутствуют. |
| Intrahorizon MTM and liquidation simulation | Частично реализовано 1.13.0 | Training/backtest требуют exact hourly Bybit mark-price path, рассчитывают directional MAE/MFE/minimum equity и conservative isolated-margin liquidation proxy с actual funding timing; future mark path влияет только на realized evidence. Не реализованы sub-hour ordering, historical MMR/risk tiers, liquidation fees, cross/portfolio margin, ADL и точная exchange fill/liquidation mechanics. |
| OI/basis/funding/liquidity/context features | Частично реализовано 1.16.0 | Model использует 10 OHLCV-derived + 7 point-in-time context features: OI changes 1h/24h, mark/index basis и delta, latest settled funding/age и turnover/OI liquidity proxy. Exact OI/basis и funding anchor обязательны; same-split ablation и walk-forward non-inferiority входят в gate. Historical local receipt timestamps, funding forecasts, orderbook-depth features, cross-asset context и richer liquidity regimes отсутствуют. |
| PBO, Deflated Sharpe, full experiment ledger | Частично реализовано 1.20.0 | Prospective append-only trial ledger, aligned returns, contiguous CSCV/PBO, HAC-adjusted DSR и horizon-floored moving-block intervals сохранены. Новая family до первого `STARTED` требует immutable preregistration: hypothesis, exact cohort fingerprint/horizon, exhaustive fixed/search contract, primary metric, thresholds, stopping rule и exclusions. Trial outside contract и post-result policy override блокируются. Pre-1.18 trials не реконструируются; pre-1.20 families не считаются preregistered; external trusted timestamp, conditional search spaces, automated exclusion coding и automatic model-promotion gate отсутствуют. |
| Production drift monitoring | Частично реализовано 1.17.0 | Active-version monitor сравнивает production с immutable final-holdout reference: coverage/missingness, feature/probability PSI, selected-direction log-loss/Brier и actionability density. Failed jobs/insufficient evidence дают `BLOCKED`, critical drift деградирует heartbeat. Multivariate tests, adaptive control limits, delayed-label correction и automated rollback отсутствуют. |

## Work package: prospective recommendation UI exposure ledger

Release 1.21.0 устраняет предположение, что каждый созданный execution plan был доступен оператору. Реализовано:

- first-party browser evidence после ≥50% видимости recommendation tile в активной вкладке в течение ≥1 секунды;
- authenticated/CSRF-protected batch endpoint и идемпотентность по `plan_id` и `client_event_id`;
- server-side проверка plan/version, predecision opportunity, времени события, viewport ratio и dwell;
- append-only `advisory.selection_exposure_ledger` с canonical SHA-256 и PostgreSQL запретом UPDATE/DELETE;
- selection denominator только по verified exposed opportunities; exposure time используется как observation time;
- явные created/exposed/unexposed, coverage, legacy и decision-without-exposure diagnostics;
- `LOW_EXPOSURE_COVERAGE` и integrity errors блокируют corrected IPSW estimate;
- rollout boundary: unexposed pre-1.21 opportunities исключаются из coverage denominator, но legacy plan может войти после реального показа новым UI.

Ограничения: событие не является eye tracking и не доказывает внимание/понимание; exposure через API/CLI/уведомления не фиксируется; browser delivery может потеряться до retry; hidden operator state и bootstrap refit propensity отсутствуют. Exposure evidence не меняет plan status, model, risk или active artifact.

## Work package: formal experiment-family preregistration

Release 1.20.0 закрывает возможность создавать executable trial family только строковым именем после просмотра результатов. Для новых families обязательны:

- preregistration до первого `STARTED`;
- exact dataset fingerprint и horizon;
- полный partition всех backtest configuration keys на fixed и enumerated search parameters;
- primary metric `nonannualized_sharpe`, direction `maximize`;
- immutable PBO/DSR/dependence thresholds;
- maximum unique configuration budget и optional UTC deadline;
- substantive hypothesis и objective exclusion criteria;
- SHA-256 record integrity и PostgreSQL запрет UPDATE/DELETE.

`backtest --prepare-preregistration` формирует draft после построения exact cohort, но возвращается до model evaluation и trial event. `experiment-report` блокирует unregistered legacy family и threshold override. Ограничения: нет external trusted timestamp, conditional parameter spaces, automated failure-to-exclusion classification или automatic promotion gate.


# Operator Manual

## Upgrade and exposure workflow 1.21.0

1. Stop API/report processes and back up PostgreSQL.
2. Update sources and run `python manage.py migrate`; expected head is `0014_ui_exposure_ledger`.
3. Add or verify `SELECTION_MIN_EXPOSURE_COVERAGE=0.80`.
4. Restart the local API and open the normal first-party web terminal. No browser extension is required.
5. Leave the recommendation page visible while reviewing cards. A card is recorded only after at least 50% visibility for one second.
6. After evidence accumulates, run `python manage.py selection-report -- --days 90` and inspect `eligible_created_count`, `eligible_exposed_count`, `exposure_coverage_rate` and `decision_without_exposure_count`.
7. Do not lower the coverage threshold to force `READY`. Investigate browser authentication, CSRF, JavaScript errors, hidden tabs and reverse proxies first.

Переобучение market model is not required.

## Upgrade and preregistration workflow 1.20.0

1. Stop research/report processes and back up PostgreSQL.
2. Update source files and run `python manage.py migrate`; expected head is `0013_experiment_preregistration`.
3. For a new family, generate a template with `backtest --prepare-preregistration` and one or more `--search-parameter` arguments. This mode exits before model evaluation and writes no experiment event.
4. Replace every placeholder, enumerate the complete planned search space, set a maximum unique-configuration count, optional UTC deadline and objective exclusion criteria.
5. Run `python manage.py experiment-preregister -- --spec <file> --validate-only`.
6. Register once with `python manage.py experiment-preregister -- --spec <file>`. Never edit the database row or recompute its hash.
7. Run each planned backtest with `--experiment-family <exact-name>`. A mismatched dataset, horizon, fixed value, undeclared key, out-of-space value or exhausted stopping budget is rejected before `STARTED`.
8. Run `experiment-report` without changing thresholds. Optional report flags are compatibility assertions and must equal the preregistration.
9. A mistaken preregistration is not repaired in place: create a new family and preserve the abandoned registration as disclosed research history.


## Upgrade to 1.19.0

1. Stop research/reporting processes and back up PostgreSQL.
2. Update source files. No migration is required; expected head remains `0012_experiment_selection`.
3. Copy/review the six dependence settings from `.env.example`.
4. Restart normal processes. Market-model retraining is not required.
5. Re-run `selection-report` and `experiment-report` only when enough prospective evidence exists.
6. Treat `BLOCKED_INSUFFICIENT_DEPENDENCE_EVIDENCE` or `INSUFFICIENT_CLUSTER_EVIDENCE` as insufficient independent information, not as an invitation to shorten blocks after seeing outcomes.
7. For experiment families, set the requested block period to a defensible dependence horizon; the application automatically floors it at the declared trading horizon.
8. Confirm every report retains `automatic_model_action=none` and does not claim profitability or causal operator skill.

### Interpreting new intervals

- HAC mean interval: asymptotic uncertainty using Bartlett-weighted serial covariance.
- Moving-block experiment intervals: contiguous return blocks for mean and Sharpe.
- Signal-cluster intervals: complete signal clusters, preserving repeated plan versions and local chronological dependence.

The operator bootstrap conditions on fitted OOS propensities. It is not a fully nested bootstrap and should not be read as causal inference.

## Upgrade to 1.18.0

1. Stop API, worker and trainer; back up PostgreSQL.
2. Update sources and copy/review the five `EXPERIMENT_*` values from `.env.example`.
3. Run `python manage.py migrate`; expected Alembic head is `0012_experiment_selection`.
4. Restart normal processes. Active model retraining is not required for this release.
5. For every planned variant series, assign one stable family name or retain the deterministic family generated from the same final-test cohort. Do not merge unrelated datasets/horizons into one family.
6. Run each alternative through `python manage.py backtest ... --experiment-family <name>`. After artifact/cohort validation, a `STARTED` row is committed before model evaluation and a terminal event is appended after completion.
7. After at least the configured number of unique successful variants on one aligned period grid, execute `python manage.py experiment-report -- --family <name>`.
8. Treat `BLOCKED_*` as missing/invalid governance evidence. Do not delete failed/open trials or lower thresholds merely to obtain `READY`.
9. Treat `READY/REJECTED` as research classification only. Neither status activates, deactivates or rolls back a model.

Legacy backtests are intentionally absent. A process killed after `STARTED` may leave an open trial that blocks the family; resolve the operational cause and append an auditable terminal disposition instead of editing or deleting the row.

## Upgrade to 1.17.0

1. Back up PostgreSQL, model registry and the active artifact.
2. Update source files. Alembic migration is not required; expected head remains `0011_selection_experiment`.
3. Copy/review `DRIFT_*` values from `.env.example`.
4. Retrain a candidate. Artifact 1.16.0 is intentionally incompatible because it has no immutable drift reference.
5. Activate only a candidate that passes the existing quality gate and runtime validation.
6. Run `python manage.py drift-report` and inspect `reports/production_drift.json`.
7. Confirm worker heartbeat contains `production_drift` and that `automatic_model_action` is `none`.
8. Do not lower thresholds only to turn `BLOCKED/CRITICAL` green; first distinguish failed inference/data gaps, regime drift and delayed outcome availability.

## Interpreting drift status

- `OK`: minimum evidence exists and configured limits are not crossed.
- `WARN`: at least one PSI/actionability diagnostic crossed the warning level.
- `CRITICAL`: material feature/probability/calibration/actionability drift was detected.
- `BLOCKED`: evidence is insufficient or structurally unreliable, including failed inference jobs, low coverage, excessive missingness or incompatible reference.

`DEGRADED` heartbeat is an operator alert, not an automatic rollback. Preserve the incumbent artifact, investigate data quality and compare paper/shadow performance before any manual model action.

## Upgrade to 1.16.0

1. Остановите API, worker и trainer; сохраните backup PostgreSQL, model registry и active artifact.
2. Обновите исходники. Migration отсутствует; ожидаемый Alembic head остаётся `0011_selection_experiment`.
3. В существующем `.env` установите `UNIVERSE_SYNC_MARK_PRICE=true` и `UNIVERSE_ENRICH_FUNDING_OI=true`.
4. Запустите worker и проверьте `history_backfill.index_price_history` и `history_backfill.open_interest_history` для всех training symbols. Не подставляйте last price вместо index/mark и не заполняйте OI гэпы нулями.
5. Дождитесь достаточного покрытия, затем переобучите candidate. Artifact 1.15.0 несовместим с `hourly-barrier-market-context-v4` и должен быть отклонён fail-closed.
6. Перед activation проверьте artifact metadata: context/availability/ablation schemas, complete/incomplete row counts, final ablation benefit и число non-inferior walk-forward folds.
7. Проведите новый paper/shadow период. Расширение feature schema не является доказательством прибыльности.

## Upgrade to 1.15.0

1. Остановите процессы и сохраните backup PostgreSQL.
2. Обновите исходники; новые `.env` параметры и retraining ML artifact не требуются.
3. Выполните `python manage.py migrate`; ожидаемый head — `0011_selection_experiment`.
4. Запустите `python manage.py doctor` и обычные API/worker/trainer процессы.
5. Убедитесь, что новые execution plans создают строки в `advisory.selection_experiment_ledger`. Legacy opportunities до 1.15.0 намеренно не backfill-ятся.
6. После накопления минимум нескольких десятков ACCEPT и непринятых eligible plans выполните `python manage.py selection-report -- --days 90`.
7. Основной показатель — all-eligible counterfactual mean R. Selected-only mean показывает результат выбранного подмножества; IPSW является диагностикой смещения, а не доказательством того, что ручной выбор добавляет доходность.
8. При `LEDGER_INTEGRITY_ERROR`, class collapse, poor overlap или low ESS не используйте corrected estimate и не редактируйте ledger вручную.

## Интерпретация decision classes

- `ACCEPT`: оператор принял конкретную plan version.
- `REJECT`: оператор явно отклонил её.
- `NO_DECISION`: outcome уже доступен, но terminal operator decision отсутствует.
- Ineligible plans сохраняются для полноты ledger, но не входят в propensity/IPSW cohort.

Unit наблюдения — созданная plan version. Система пока не доказывает, что оператор действительно видел каждую карточку; автоматические пересчёты могут создавать коррелированные версии одной рекомендации.

## Upgrade to 1.14.0

1. Остановите API, worker и trainer; сохраните backup PostgreSQL и текущий model registry/artifact.
2. Обновите исходники и перенесите четыре orderbook-параметра из `.env.example` в локальный `.env` либо подтвердите defaults.
3. Выполните `python manage.py migrate`; ожидаемый head — `0010_orderbook_exec_evidence`.
4. Выполните `python manage.py doctor` и затем запустите worker.
5. В heartbeat/job details проверьте `orderbooks.requested/stored/duplicates/failed`. Повторные snapshots могут быть idempotent duplicates; систематические failures требуют расследования.
6. Дождитесь свежих snapshots для symbols. План без свежего depth evidence будет `BLOCKED_STALE_DATA`.
7. Existing `ACTIONABLE` plans 1.13.0 не принимайте как legacy contract: endpoint создаст новую версию с depth/VWAP evidence.
8. Перед ручным входом проверьте complete-fill VWAP, impact, worst level и operator latency в details. `PARTIAL/NO_FILL` означает запрет, а не предложение вручную округлить qty вверх.
9. Изменение `MAX_VWAP_IMPACT_BPS` или depth требует пересчёта plan; retraining модели не требуется.

## Как интерпретировать execution evidence

- `FULL`: весь плановый объём помещается в доступную snapshot depth внутри impact band. Это не гарантия фактического fill после задержки.
- `PARTIAL`: только часть объёма доступна; система блокирует plan/acceptance.
- `NO_FILL`: допустимая ликвидность отсутствует или snapshot некорректен; действие блокируется.
- `operator_latency_seconds`: время от plan calculation до acceptance revalidation. Большая задержка требует нового snapshot и обычно приводит к plan version change.

## Upgrade to 1.13.0

1. Сохраните backup PostgreSQL, model registry и active artifact.
2. Обновите исходники; Alembic migration и новые `.env` переменные не требуются.
3. Запустите worker и дождитесь progressive `history_backfill`, включая отдельный `mark_price_history` для всех training symbols.
4. Не обходите gaps: training требует точные consecutive hourly mark candles до каждого modeled exit.
5. Проверьте `DEFAULT_LEVERAGE`; это значение становится частью research artifact contract. Его изменение требует нового candidate.
6. Переобучите candidate. Artifact 1.12.0 не содержит обязательный intrahorizon-margin contract и должен быть отклонён runtime fail-closed.
7. Проверьте metadata: margin schema/status, mark source, research leverage, reserve, liquidation count/rate, MAE/MFE и minimum equity.
8. При `intrahorizon_*` gate reason не редактируйте joblib и не снижайте severity. Исправьте coverage/assumptions и переобучите.
9. После gates выполните новый paper/shadow период. Метрики 1.12.0 без mark-MTM напрямую несопоставимы с 1.13.0.

## Интерпретация liquidation evidence

`mark_liquidated=true` означает срабатывание консервативного hourly isolated-margin proxy. Это не подтверждение точного historical liquidation event на Bybit. Proxy намеренно ставит ambiguous same-bar mark liquidation раньше более позднего last-price TP/SL и не знает sub-hour order, historical risk tier/MMR, liquidation fee или cross/portfolio margin. Используйте его как fail-closed стресс для realized evidence, а не как точную цену ликвидации.

## Upgrade to 1.12.0

1. Сохраните backup PostgreSQL, model registry и active artifact.
2. Обновите исходники; Alembic migration и новые `.env` переменные не требуются.
3. Запустите worker и дождитесь progressive `history_backfill`, включая вложенный `funding_history` progress.
4. Проверьте покрытие всех training symbols до требуемого `HISTORY_BACKFILL_TARGET_DAYS`; ошибки или незавершённые symbols не обходите.
5. Переобучите candidate. Artifact 1.11.0 не содержит обязательный historical-funding contract и должен быть отклонён runtime fail-closed.
6. Проверьте artifact metadata: funding schema, symbols, settlements, start/end time и policy funding sources.
7. После gates выполните новый paper/shadow период. Старые backtest/policy metrics без settlement replay напрямую несопоставимы с 1.12.0.

## Upgrade to 1.11.0

1. Сохраните backup PostgreSQL, model registry и active artifact.
2. Обновите исходники. Alembic migration и новые `.env` переменные не требуются.
3. Запустите `python manage.py doctor` в настроенном локальном окружении.
4. Переобучите candidate: artifact 1.10.0 не содержит обязательную walk-forward schema и должен быть отклонён runtime fail-closed.
5. Проверьте diagnostics каждого fold: временные границы, rows, skill vs prior, Brier и policy mean R.
6. Не ослабляйте gate при `walk_forward_*` reason code. Сначала увеличьте историческое покрытие или исследуйте временную нестабильность.
7. После прохождения gates выполните paper/shadow validation; historical walk-forward не заменяет forward evidence.

## Требование к истории

При default horizon и quality settings trainer по-прежнему требует минимум 1206 уникальных hourly timestamps. Это теоретический минимум для непрерывной истории. Гэпы, invalid bars, class collapse или недостаточные TIMEOUT observations могут потребовать больше данных и должны блокировать обучение.

## Entry spread interpretation

`MODEL_ENTRY_SPREAD_BPS=18` означает полный 18 bps spread stress, то есть 9 bps adverse offset от next-hour open для каждой стороны. Это не historical orderbook reconstruction. Значение должно быть зафиксировано до OOS evaluation.

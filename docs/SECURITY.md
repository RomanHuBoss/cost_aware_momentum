# Security

## Production drift integrity boundary 1.17.0

- Drift reference is created from the untouched final holdout and embedded in the immutable artifact/registry evidence; production cannot redefine bins to hide drift.
- Runtime and promotion gate require exact reference, feature order and selected-direction calibration-cohort schemas.
- Monitoring filters by active model version and uses only resolved outcomes; future outcomes or another model's observations cannot enter the report.
- Failed inference jobs and invalid coverage accounting are visible `BLOCKED` conditions, not silently discarded observations.
- Reports contain model diagnostics but no API secrets, order mutation capability or raw credentials.
- `automatic_model_action=none`: monitor code cannot activate, deactivate, roll back or weaken gates.
- Disabling the monitor produces a visible blocked state; it is not treated as healthy.

## Market-context integrity boundary 1.16.0

- OI, mark/index and funding sources remain public/read-only GET; trade mutation methods are not introduced.
- Historical context uses only exchange event/close timestamps and explicitly records that local receipt times were not reconstructed.
- Live inference filters every context source by stored `available_at`; future or not-yet-received rows cannot enter the feature vector.
- Exact joins, positive/finiteness checks and duplicate rejection are fail-closed. Zero-fill, silent forward-fill and substitution of last price for mark/index are prohibited.
- Artifact validation covers exact feature order, context schema, availability schema and ablation schema; manual metadata editing does not make a legacy artifact compatible.
- Context ablation is independently refit on the same temporal splits, preventing an untested feature expansion from bypassing promotion gates.

## Selection ledger integrity boundary 1.15.0

- Ledger row создаётся до operator decision в транзакции execution-plan creation.
- Feature schema содержит только числовые ex-ante поля; action, outcome, counterfactual R и realized P&L запрещены.
- Canonical SHA-256 включает identifiers, timestamp, eligibility, schema, features и release version. Несовпадение блокирует analysis.
- Report не изменяет execution plan, decision, outcome или model artifact и не вызывает Bybit mutation endpoints.
- Raw comments/operator identifiers не входят в propensity features.
- IPSW не публикуется при слабом overlap или effective sample size; fail-open fallback отсутствует.

## Execution evidence boundary 1.14.0

- Orderbook endpoint остаётся public GET; create/amend/cancel order methods не добавлены.
- Snapshot payload проходит strict positive/sorted/uncrossed validation; stale, future-dated или malformed data блокирует execution.
- Natural key не доверяет `update_id` как вечному идентификатору и включает matching-engine source time.
- Legacy plan без совместимого depth evidence не может быть принят после обновления; создаётся новая версия.
- Full raw depth не отправляется в браузер как отдельный endpoint и не содержит credentials.
- Retention ограничивает объём prospective market evidence; реальные API keys и `.env` по-прежнему исключаются из release.
- Simulation не размещает ордер и не должна интерпретироваться как подтверждённый exchange fill.

- Default bind: `127.0.0.1`.
- `.env` и credentials запрещены в release archive.
- Bybit integration не содержит create/amend/cancel order methods.
- Mark-price history и funding history загружаются только public/read-only GET.
- PostgreSQL обязателен; SQLite fallback отсутствует.
- Model artifacts проверяются по SHA-256, version и semantic schemas.
- Runtime требует согласованные feature, label, execution, temporal, walk-forward, historical-funding и intrahorizon-margin schemas.
- Несовместимый/неполный margin metadata, mark timeline, leverage или reserve вызывает fail-closed error/gate failure, а не fallback на last price или старую модель.
- Future mark trajectory и future actual funding запрещены как ex-ante model/policy inputs; они применяются только к realized research evidence после direction selection.
- Candidate failure не деактивирует incumbent.
- Artifact 1.12.0 не загружается как 1.13.0 путём ручного добавления metadata; требуется retraining.
- Baseline остаётся diagnostic-only; production validation в 1.13.0 усилена, а advisory-only boundary не изменена.

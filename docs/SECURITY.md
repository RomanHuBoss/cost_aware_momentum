# Security

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

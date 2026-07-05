# Security

## Model activation integrity boundary 1.25.0

- Atomic candidate activation fails before artifact validation or database mutation unless the supplied quality gate is present, passed and internally consistent.
- Manual training cannot pass `quality_gate=None` into activation; failed candidates are retained inactive for review.
- Registered-model activation uses persisted registry evidence and rejects missing/failed gates by default.
- Emergency rollback is not an environment toggle. It requires an explicit one-shot CLI flag and human-readable incident reason, both stored with the original gate in the append-only activation audit event.
- The override does not bypass checksum, version, horizon or concurrent-active-version checks and grants no Bybit order permission.

## UI exposure integrity boundary 1.21.0

- Exposure ingestion requires an authenticated operator and the existing CSRF protection; anonymous impressions are rejected.
- The server never trusts plan identity or version from the browser without matching the immutable selection opportunity.
- Client timestamps must be timezone-aware, close to server receipt time and no earlier than the plan opportunity beyond limited clock skew.
- Each plan has at most one exposure row and each client event ID is unique. Retries are idempotent.
- Canonical SHA-256 detects application-level tampering; PostgreSQL rejects UPDATE and DELETE through an immutable trigger.
- `page_instance_id` is random and ephemeral. No cross-site identifier, browsing history or external telemetry service is introduced.
- Exposure recording has no exchange permissions and cannot mutate plan status, model lifecycle or risk settings.

## Experiment preregistration integrity boundary 1.20.0

- `research.experiment_family_registrations` is insert-once: a PostgreSQL trigger rejects UPDATE and DELETE.
- The canonical SHA-256 covers family name, UTC registration timestamp, normalized specification and release version.
- A family cannot be registered after any trial event already exists.
- STARTED acquires a row lock, verifies the registration hash, validates the full configuration contract and stores the registration hash in event evidence.
- Report-time threshold changes, search-space drift, missing registration and ledger/reference mismatches fail closed.
- Database-owner intervention can bypass ordinary controls; backups, least privilege and audit review remain required. Hashes provide tamper evidence, not an external trusted timestamp or protection against a fully compromised database owner.
- Preregistration has no path to order placement, active-model mutation or risk-limit weakening.


## Dependence-evidence integrity boundary 1.19.0

- Bootstrap seeds and algorithms are deterministic for identical evidence; researchers cannot repeatedly rerun random seeds and report only a favourable interval.
- Experiment blocks preserve chronological return segments and cannot be shorter than the ledger-declared horizon.
- Operator propensity train/OOS assignment is signal-cluster atomic; one signal cannot leak through another plan version into both sides.
- Cluster bootstrap resamples complete signal clusters and never modifies ledger, decisions or outcomes.
- Insufficient blocks/clusters and invalid evidence are visible blocked states; no IID fallback is permitted.
- Dependence reports remain read-only research diagnostics and cannot activate/rollback models, change risk or call Bybit order mutations.

## Research experiment integrity boundary 1.18.0

- Experiment events are append-only application records with unique trial sequence and record hash constraints.
- Configuration and evidence are canonicalized before SHA-256; terminal events link to the STARTED event hash.
- Error evidence is bounded and must not contain credentials, raw environment variables or exchange secrets.
- Manual updates/deletes of experiment JSONB or hashes invalidate governance evidence.
- The ledger stores research configurations and return evidence, not order-placement authority; Bybit order mutation methods remain absent.
- `experiment-report` is observational and cannot change active-model state, policy thresholds or risk limits.
- Release archives exclude `.env`, database dumps and generated reports.

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

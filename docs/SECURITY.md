# Security boundary

## Fail-closed profile and economics boundary in 1.8.17

Capital-profile mode is an allow-list, not a fallback. `manual` and `paper` use configured allocated capital; `bybit_read_only` requires a non-empty `source_account_id` and a fresh matching account snapshot. Unknown/legacy modes and missing account links return zero capital, zero available margin and `verified=false`. This prevents malformed database state from silently becoming an executable manual-capital plan.

Execution-plan economics is treated as integrity-sensitive operator data. The API recomputes it from immutable snapshot inputs and withholds the values when non-finite, missing or inconsistent data is detected. The control is diagnostic and fail-closed; it does not authenticate a malicious database writer and does not replace PostgreSQL access controls, audit-chain review or backups.

## Граница исполнения

Приложение является advisory-only. `app/bybit/client.py` намеренно содержит только HTTP GET. Запрещено добавлять `/v5/order/create`, amend, cancel, batch order или withdrawal endpoints без отдельного архитектурного решения и review.

## Ключи

Для account sync нужен отдельный Bybit API key только с read permission. IP allowlist обязателен при удаленном размещении. Секреты хранятся в environment/secret manager, а не в PostgreSQL, frontend, model artifacts или git.

## Web/API

- HMAC-signed session cookie;
- отдельный CSRF cookie/header для mutating requests;
- optional operator API token;
- idempotency key для accept/reject/manual fills;
- accept выполняет fail-closed server-side revalidation исполнимого bid/ask, возраста account snapshot и portfolio risk под transaction-scoped PostgreSQL advisory lock;
- Pydantic validation и server-side plan checks;
- trainer-control mutations требуют signed operator session/API token и CSRF; API записывает только команду в PostgreSQL и не выполняет fitting в request process;
- bind на localhost по умолчанию.

При публикации наружу используйте TLS reverse proxy, rate limiting, trusted network/VPN и централизованный secret manager. OpenAPI следует ограничить на proxy-уровне.

## Audit

События образуют append-only SHA256 chain. Это защита от незаметного изменения, но не замена WORM-хранилищу. Для повышенных требований экспортируйте ежедневный chain head во внешнее неизменяемое хранилище.
## Recovery после утраты model artifact

Операторская команда `RECOVER_NOW` также не является обходом artifact integrity или quality gate. Она доступна только при свежем heartbeat trainer и recoverable отсутствии active artifact; в production controlled baseline recovery остается запрещен.

Controlled baseline recovery не является обходом artifact integrity. Он применяется только к физически отсутствующему registry artifact в non-production при `ALLOW_BASELINE_MODEL=true`. Существующий файл с неверным SHA256, поврежденным bundle или несовместимыми metadata остается блокирующей ошибкой. `ACTIVE_MODEL_PATH` также никогда не fallback-ится. В production baseline запрещен validator-ом.

Команда `model-registry recover-artifact` должна использоваться только для доверенного локального `.joblib`, созданного этим проектом. Формат joblib/pickle не является безопасным для файлов неизвестного происхождения. Recovery требует размещение внутри `MODEL_DIR`, non-production режим, повторную schema/horizon/quality-gate проверку и не активирует failed candidate.
## Release boundary

Перед публикацией или передачей архива выполняется `python manage.py release-check`. Проверка fail-closed сопоставляет каждый файл с `SHA256SUMS`, выявляет missing/modified/unlisted entries и запрещает `.env`, секретные ключи, virtual environments, caches, `*.egg-info`, dumps, logs, model/runtime artifacts, symlinks и вложенные archives. `python manage.py release-check --write` пересоздает manifest только после успешной проверки чистоты дерева. SHA256 manifest подтверждает целостность конкретного содержимого, но не является внешней цифровой подписью и не доказывает происхождение файла.


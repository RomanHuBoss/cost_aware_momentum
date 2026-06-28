# Security boundary

## Граница исполнения

Приложение является advisory-only. `app/bybit/client.py` намеренно содержит только HTTP GET. Запрещено добавлять `/v5/order/create`, amend, cancel, batch order или withdrawal endpoints без отдельного архитектурного решения и review.

## Ключи

Для account sync нужен отдельный Bybit API key только с read permission. IP allowlist обязателен при удаленном размещении. Секреты хранятся в environment/secret manager, а не в PostgreSQL, frontend, model artifacts или git.

## Web/API

- HMAC-signed session cookie;
- отдельный CSRF cookie/header для mutating requests;
- optional operator API token;
- idempotency key для accept/reject/manual fills;
- Pydantic validation и server-side plan checks;
- bind на localhost по умолчанию.

При публикации наружу используйте TLS reverse proxy, rate limiting, trusted network/VPN и централизованный secret manager. OpenAPI следует ограничить на proxy-уровне.

## Audit

События образуют append-only SHA256 chain. Это защита от незаметного изменения, но не замена WORM-хранилищу. Для повышенных требований экспортируйте ежедневный chain head во внешнее неизменяемое хранилище.
## Recovery после утраты model artifact

Controlled baseline recovery не является обходом artifact integrity. Он применяется только к физически отсутствующему registry artifact в non-production при `ALLOW_BASELINE_MODEL=true`. Существующий файл с неверным SHA256, поврежденным bundle или несовместимыми metadata остается блокирующей ошибкой. `ACTIVE_MODEL_PATH` также никогда не fallback-ится. В production baseline запрещен validator-ом.


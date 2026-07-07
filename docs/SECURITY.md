# Security

## Access boundary

- По умолчанию сервис должен быть привязан к `127.0.0.1`.
- Bybit integration остаётся public/read-only; trade/withdrawal permissions не требуются.
- Ордерные create/amend/cancel методы не входят в проект.
- Реальные секреты хранятся только вне release tree; `.env.example` содержит шаблоны.

## Data and state

- PostgreSQL — единственный state store.
- State-changing API использует authentication, CSRF/idempotency и audit/outbox contracts проекта.
- Model artifacts проверяются по SHA-256 и metadata перед runtime/activation.

## Release boundary

`python manage.py release-check` блокирует:

- секреты, `.env`, private keys, dumps, model binaries, caches и build-мусор;
- отсутствующие governance/security/QA документы;
- version drift между package, runtime и README;
- отсутствующий patch/iteration evidence;
- unlisted, missing или modified files относительно `SHA256SUMS`.

Checksum подтверждает целостность только после прохождения полного release contract.

# Security

- Default bind: `127.0.0.1`.
- `.env` и credentials запрещены в release archive.
- Bybit integration не содержит create/amend/cancel order methods.
- PostgreSQL обязателен; SQLite fallback отсутствует.
- Model artifacts проверяются по SHA-256, version и semantic schemas.
- Несовместимый execution metadata вызывает fail-closed error, а не fallback на старую модель.
- Baseline остается diagnostic-only, если явно не изменена опасная конфигурация; production validation не ослаблялась в 1.10.0.

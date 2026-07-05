# Security

- Default bind: `127.0.0.1`.
- `.env` и credentials запрещены в release archive.
- Bybit integration не содержит create/amend/cancel order methods.
- PostgreSQL обязателен; SQLite fallback отсутствует.
- Model artifacts проверяются по SHA-256, version и semantic schemas.
- Runtime требует согласованные feature, label, execution, temporal и walk-forward schemas.
- Несовместимый или неполный validation metadata вызывает fail-closed error/gate failure, а не fallback на старую модель.
- Candidate failure не деактивирует incumbent.
- Baseline остаётся diagnostic-only; production validation в 1.11.0 усилена, а не ослаблена.

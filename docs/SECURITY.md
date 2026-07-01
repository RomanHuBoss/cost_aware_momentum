# Security

- По умолчанию приложение слушает `127.0.0.1`.
- Bybit integration предназначена для public/read-only GET endpoints; торговые и withdrawal permissions не требуются.
- Реальные secrets хранятся только в локальном `.env`, который не входит в release archive.
- Production mode обязан отклонять стандартные credentials, demo seed и небезопасные настройки через существующие config/runtime gates.
- PostgreSQL URLs валидируются; SQLite/file fallback отсутствует.
- Release tree проверяется fail-closed скриптом `scripts/release_integrity.py` и manifest `SHA256SUMS`.
- Логи и отчёты не должны содержать API secret, operator password, session secret или полные authentication headers.

Этот patch не меняет authentication, cookie, CSRF или network binding semantics.

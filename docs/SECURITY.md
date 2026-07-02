# Security

- По умолчанию приложение слушает `127.0.0.1`.
- Bybit integration предназначена только для public/read-only GET endpoints; торговые и withdrawal permissions не требуются.
- Для private GET подпись версии 2 рассчитывается по query string окончательно построенного `httpx.Request`; затем отправляется тот же request, что устраняет расхождение signed/transmitted payload.
- Реальные secrets хранятся только в локальном `.env`, который не входит в release archive.
- Production mode обязан отклонять стандартные credentials, demo seed и небезопасные настройки через существующие config/runtime gates. Любой режим отклоняет отрицательный `MIN_NET_EV_R`; при auto-activation также отклоняются отрицательный minimum realized mean R и profit factor ниже 1.
- PostgreSQL URLs валидируются; SQLite/file fallback отсутствует.
- Model artifacts проверяются fail-closed по ожидаемому SHA-256 (когда он зарегистрирован), task/classes/horizon/calibration, feature schema, label-path schema, temporal-split schema и положительной barrier geometry.
- Release tree проверяется fail-closed скриптом `scripts/release_integrity.py` и manifest `SHA256SUMS`.
- Логи и отчёты не должны содержать API secret, operator password, session secret или полные authentication headers.

Patch 1.8.30 не меняет authentication, cookie, CSRF, network binding, Bybit permissions или advisory-only semantics. Он добавляет fail-closed temporal accounting для plan outcomes, point-in-time instrument-spec receipt cutoff и корректную policy-econometrics schema.

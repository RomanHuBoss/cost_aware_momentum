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

Patch 1.8.31 не меняет права доступа, сетевые настройки, торговые возможности или секреты. Он устраняет только несовместимость идентификатора Alembic revision со стандартной 32-символьной колонкой version table и добавляет fail-fast regression contract.

Patch 1.8.32 не добавляет order mutations, новые права API, сетевые экспозиции или секреты. Он восстанавливает fail-closed migration graph/release manifest и предотвращает использование в promotion evidence сделок, которые live acceptance заблокировал бы как перекрывающуюся позицию того же символа.

Patch 1.8.33 сохраняет advisory-only и read-only границы. Он добавляет второй fail-closed барьер: некалиброванный baseline не может быть actionable по умолчанию и не может пройти acceptance из legacy-плана; production запрещает override `ALLOW_BASELINE_ACTIONABLE=true`.

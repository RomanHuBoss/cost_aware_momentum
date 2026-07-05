# Security

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

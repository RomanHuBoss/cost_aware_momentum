# Changelog

Все значимые изменения проекта фиксируются здесь. Формат версий — Semantic Versioning.

## [1.8.36] — 2026-07-02

### Fixed

- Устранена утечка pre-entry price movement в ML labels: entry proxy теперь равен `open` первой свечи, начинающейся в `decision_time`, а не close уже завершённой feature-свечи.
- ATR barrier geometry после гэпа рассчитывается как `entry_price × atr_pct_14 × multiplier`, что соответствует live signal policy.
- Dataset сохраняет `entry_price`; policy metadata проверяет его как положительное конечное значение.
- Старые artifacts и promotion evidence блокируются новыми `label_path_schema_version` и `policy_metric_schema`.
- Восстановлены отсутствовавшие release provenance files: changelog, patch note и checksum manifest.

### Tests

- Добавлены симметричные LONG/SHORT regression tests для гэпа между feature close и первым исполнимым entry.
- Добавлена проверка, что artifact со старой label-path schema отклоняется runtime.

## [1.8.35] — 2026-07-02

- Trainer ждёт математически достаточную историю для configured holdout gates.
- Auto-activation требует положительный log-loss skill относительно class-prior baseline.

Более ранняя история содержится в `docs/ITERATION_REPORT_*.md` и документации соответствующих релизов.

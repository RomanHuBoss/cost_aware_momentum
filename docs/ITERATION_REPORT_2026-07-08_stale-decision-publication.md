# Iteration report — 2026-07-08 — stale decision publication scheduling

Дата: 2026-07-08. Целевая версия: 1.52.3.

## 1. Входной архив

- Входной ZIP: `cost_aware_momentum-1.52.2-orderbook-vwap-sizing.zip`.
- SHA-256 входного ZIP: `6c2a57852410297823719c3105149562bea25df720fc7bff33b9de6a654623c5`.
- Исходная версия: 1.52.2.
- Alembic head: `0018_inference_observations`.

## 2. Цель итерации

После этой итерации worker не должен запускать stale hourly/catch-up signal publication, если event hour уже вышел за immutable `MAX_SIGNAL_PUBLICATION_DELAY_SECONDS`; это подтверждается unit regression tests и полным unit suite.

Критерии приёмки:

1. Publication window классифицирует lag `1886s > 600s` как `decision_publication_lag_exceeded`.
2. Hourly cycle, запущенный уже после окна, не вызывает market close/outcomes/drift/inference.
3. Catch-up inference после окна записывает terminal skip с per-symbol outcomes и не refreshes execution inputs.
4. Если hourly jobs стартовали вовремя, но inference reached late, `inference_job` повторно проверяет window перед refresh/publication.
5. Retry accounting не считает sparse-but-terminal inference незавершённым.
6. Publication delay limit не увеличивается и fail-closed semantics сохраняется.

## 3. Прочитанные источники и data flow

Прочитаны: `README.md`, `CHANGELOG.md`, `PATCH_1.52.2.md`, `pyproject.toml`, `.env.example`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/OPERATOR_MANUAL.md`, `app/config.py`, `app/workers/runner.py`, `app/services/signals.py`, связанные tests.

Затронутый flow:

`worker loop / startup catch-up -> event_time + checked_at -> publication-window validation -> execution input refresh -> publish_hourly_signals -> JobRun.details/operator diagnostics`.

## 4. Baseline до правок

| Команда | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | 854 passed, 8 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | FAILED / environment limitation | external venv is not project-local `.venv` |
| `python manage.py test --require-integration` | NOT RUN | safe PostgreSQL TEST_DATABASE_URL not configured |

## 5. Подтверждённые defects/gaps

### CONFIRMED DEFECT — stale catch-up/current-hour publication attempt

- Severity: high.
- Evidence: пользовательский лог показал `event_time=2026-07-08T01:00:00+00:00`, `publish_time=2026-07-08T01:31:26.062415+00:00`, `publication_lag_seconds=1886.062415`, `maximum_delay_seconds=600`.
- Файл: `app/workers/runner.py::catchup_inference_job` и worker loop.
- Фактическое поведение: worker мог доводить stale current-hour catch-up/hourly cycle до `publish_hourly_signals`; service корректно блокировал publication, но поздно, после лишних refresh/publication attempt.
- Ожидаемое поведение: stale event hour должен быть terminally skipped на scheduler/worker layer до execution input refresh/publication.
- Почему тесты не поймали: catch-up tests зависели от текущей минуты выполнения и не моделировали `31m > 600s` explicit checked_at.

### CONFIRMED DEFECT — retry accounting did not reuse terminal inference coverage helper in run_job

- Severity: medium.
- Файл: `app/workers/runner.py::run_job`.
- Фактическое поведение: `should_retry_incomplete_inference` существовал и был протестирован, но generic retry path продолжал смотреть только на `published/existing_current_hour`. Sparse, но terminal, inference мог быть ошибочно retryable.
- Исправление: inference retry path использует `should_retry_incomplete_inference`, сохраняя fallback для старых details.

## 6. План и фактический diff

Production:

- `app/workers/runner.py` — добавлен `DecisionPublicationWindow`, pre-publication stale skip, catch-up/hourly/inference guards, retry accounting fix.

Tests:

- `tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py` — новый regression module.
- `tests/unit/test_decision_execution_snapshot_freshness_2026_07_07.py` — existing fresh catch-up tests получили deterministic within-window timestamp.
- `tests/unit/test_decision_ticker_refresh_2026_07_07.py` — existing catch-up ticker test получил deterministic within-window timestamp.

Docs/version:

- `app/__init__.py`, `pyproject.toml`, `README.md`, `CHANGELOG.md`, `PATCH_1.52.3.md`, `docs/OPERATOR_MANUAL.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, this report, `SHA256SUMS`.

Миграции, `.env`, API, model artifact schema: без изменений.

## 7. Red → green evidence

Red на 1.52.2 после добавления нового regression module:

```bash
python -m pytest -q tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py
```

Результат: `3 failed`. Причины: отсутствовали `resolve_decision_publication_window`, `cycle_started_at` и `checked_at` contracts.

Green после исправления:

```bash
python -m pytest -q tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py
```

Результат: `3 passed`.

Targeted regression set:

```bash
python -m pytest -q \
  tests/unit/test_inference_retry.py \
  tests/unit/test_inference_terminal_coverage_accounting_2026_07_07.py \
  tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py \
  tests/unit/test_critical_drift_interlock_2026_07_06.py
```

Результат: `21 passed`.

## 8. Compatibility

- DB migration: not required.
- `.env`: no new variables; `MAX_SIGNAL_PUBLICATION_DELAY_SECONDS` remains unchanged.
- API contract: unchanged.
- Model artifact contract: unchanged.
- Rollback: restore 1.52.2 archive and restart worker/API; no schema downgrade.

## 9. Post-check

| Команда | Статус | Результат |
|---|---|---|
| `python -m pip check` | PASSED | No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | 857 passed, 8 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python -B manage.py release-check --write` | PASSED | clean manifest written |
| `python -B manage.py release-check` | PASSED | release contract and checksums confirmed |
| ZIP integrity / re-extract | PASSED | archive opens, one root dir, internal release-check passes |

## 10. Не удалось проверить

- PostgreSQL integration tests: no safe isolated `TEST_DATABASE_URL`.
- `manage.py doctor`: project-local `.venv` absent by design in this environment.
- Live Bybit read-only smoke: no network/credentials used.

## 11. Остаточные риски

- Если startup/backfill/drift фактически занимает больше 10 минут, текущий hour будет корректно пропущен. Первопричину задержки нужно диагностировать отдельно по JobRun and heartbeat details.
- 62 dependency deprecation warnings remain.
- No claim of profitability or economic edge.

## 12. Rollback

No migration rollback is required. Stop worker/API, deploy the previous 1.52.2 archive, restart worker/API. Existing DB rows and active artifact remain compatible.

## 13. Следующий work package

Разделить long-running maintenance/backfill и hourly decision publication budget так, чтобы startup/history tasks не конкурировали с narrow decision-time window.

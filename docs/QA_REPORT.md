# QA Report — 1.9.2

Дата: 2026-07-04

## Входной архив

- Архив: `cost_aware_momentum-main.zip`.
- SHA-256: `276e17e3f527cfe1a228f9030ab25ba00cc63056ff71c64d49adfa819d5894ce`.
- Исходная версия: `1.9.1`; Python requirement: `>=3.12`.
- Исходный состав: 70 production/maintenance Python files (включая `manage.py`), 52 `test_*.py` modules, 20 Markdown files в `docs/`, 9 Alembic revisions.
- Исходный Alembic head: `0009_candle_receipt_availability`.
- ZIP содержал 169 файлов; `.env`, credentials, virtualenv, caches, dumps и реальные model artifacts не обнаружены.
- Архив не содержал `SHA256SUMS`, `CHANGELOG.md` и `PATCH_*.md`, хотя iteration report 1.9.1 ссылался на эти release-файлы.
- Заявленные внешними экспертами количества ошибок не сопровождались файлами, stack traces или reproductions; severity присвоена только воспроизведённым дефектам/пробелам.

## Baseline до правок

Первый запуск в общем системном Python не являлся валидным project environment: `ruff` отсутствовал, `psycopg` отсутствовал и pytest завершился 23 collection errors, а глобальный `pip check` содержал посторонний конфликт MoviePy/Pillow. Эти результаты классифицированы как environment failure, не как дефекты проекта.

Повторный baseline выполнен в изолированном virtualenv после `pip install -e '.[dev]'`:

| Проверка | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5; requirement `>=3.12` выполнен |
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| `python -m pytest -q` | PASSED | **434 passed, 4 skipped, 55 warnings** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | one head: `0009_candle_receipt_availability` |
| `python manage.py release-check` | FAILED | 169 files checked, 0 manifest entries; `SHA256SUMS` missing |
| `python manage.py doctor` | NOT RUN | operator `.env` и project PostgreSQL отсутствуют |
| `python manage.py test --require-integration` | NOT RUN | isolated `TEST_DATABASE_URL`/PostgreSQL недоступны; user/production DB не использовалась |

Warnings — third-party NumPy/joblib deprecations в serialization tests.

## Подтверждённый дефект

### HIGH — previous-hour candle могла публиковать current-hour signal

Production path: `app/services/signals.py::publish_hourly_signals`.

До исправления worker выбирал последнюю candle с `close_time <= event_time`, затем разрешал её при:

```text
(event_time - latest_candle_close) <= MAX_CANDLE_AGE_SECONDS
```

Default равен 4200 секунд. Сразу после часовой границы последняя доступная свеча предыдущего часа имеет age 3600 секунд и проходила gate. После этого signal получал natural key нового `event_time`. Когда точная decision candle становилась доступна, idempotency check находил уже существующий natural key и не заменял раннюю рекомендацию.

Влияние:

- features и market economics относились к предыдущему часовому окну, а signal metadata — к текущему;
- корректный retry после ingestion блокировался как already published;
- оператор мог видеть temporally misaligned LONG/SHORT recommendation;
- outcome/model-quality attribution могла быть искажена.

Это высокий дефект временной и торговой целостности, но source-only reproduction не доказывает, что он вызвал конкретные убытки пользователя.

Почему прежние тесты не поймали: покрывались stale cutoff, point-in-time query и retry/idempotency по natural key, но отсутствовал контракт `latest close_time == event_time` до scenario economics.

## Подтверждённый release gap

### MEDIUM — release tree не проходил собственную проверку provenance

Чистая распаковка входного ZIP завершала `python manage.py release-check` с ошибкой: `SHA256SUMS` отсутствовал, 169 release-файлов не были перечислены. Также отсутствовали changelog и patch note, заявленные внутренней документацией. Исправленный release содержит пересчитанный manifest и текущие release notes; непроверенная прежняя история не реконструировалась.

## Исправление

- Hourly publication требует точного `latest_candle_close == event_time`.
- Previous-hour candle возвращает fail-closed `missing_decision_candle` до spread/funding/model-scenario/natural-key processing.
- Невозможная future candle и явно старая candle имеют отдельные diagnostics `future_decision_candle` и `stale_candle_cutoff`.
- ML gates, risk limits, fee/slippage/funding math, barrier geometry и auto-activation thresholds не изменены.
- Добавлен независимый regression test и восстановлены release provenance files.

## Red → green

RED на неизменённом 1.9.1:

```text
PYTHONPATH=. python -m pytest -q /tmp/test_hourly_decision_candle_integrity_2026_07_04.py
1 failed
AssertionError: a prior-hour feature window reached current-hour signal economics
```

GREEN после production fix:

```text
python -m pytest -q \
  tests/unit/test_hourly_decision_candle_integrity_2026_07_04.py \
  tests/unit/test_quant_integrity_2026_07_02.py \
  tests/unit/test_inference_retry.py
13 passed
```

Новый test oracle задаёт independently controlled `event_time` и previous-hour `close_time`; ожидаемый результат не вычисляется тестируемой функцией.

## Post-check

| Проверка | Статус | Результат |
|---|---|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| `python -m pytest -q` | PASSED | **435 passed, 4 skipped, 55 warnings** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | one head: `0009_candle_receipt_availability` |
| `python -m alembic upgrade head --sql` | PASSED | complete offline PostgreSQL SQL generated, 853 lines |
| Static Bybit order-mutation scan | PASSED | create/amend/cancel routes/methods not found |
| Secret filename scan | PASSED | `.env`, private keys/certificates not found |
| PostgreSQL integration | NOT RUN | isolated database unavailable |
| `python manage.py doctor` | NOT RUN | no local operator configuration/database |

Final release tree passed `python manage.py release-check`: 173 eligible files, 173 manifest entries. Repacked-archive verification is recorded in final delivery metadata.

## Compatibility and operator actions

- Version: `1.9.2` patch release.
- New `.env` variables: none.
- Database migration: none; head remains `0009_candle_receipt_availability`.
- Public API, DB schema, artifact and policy schemas: unchanged.
- Retraining: not required solely by this patch.
- Replace the release tree, run `python manage.py release-check`, then `python manage.py doctor` in the configured installation and restart worker/API/trainer.

## Residual risks

- Real PostgreSQL integration, configured `doctor` and running-data behavior were not verified in this environment.
- The archive contains no live database, candidate metrics, rejected-gate evidence, signal/plan snapshots or fill journal; therefore it cannot explain every rare recommendation or loss.
- One day of hourly history is intentionally insufficient for current temporal validation. Defaults require at least 1206 unique hourly timestamps before candidate training can be mathematically feasible, and later quality gates may still reject it.
- Full historical order book/fill/operator-delay replay, exact funding timeline, walk-forward/drift governance and PBO/DSR remain incomplete.
- Passing tests and corrected temporal semantics do not establish profitability.

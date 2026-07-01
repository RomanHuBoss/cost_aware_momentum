# QA Report — 1.8.28

Дата: 2026-07-01

## Входной baseline 1.8.27

- Архив: `cost_aware_momentum-main.zip`
- SHA-256: `7de869737d976f86e3ed8ee6fd0c316afccedf2ceb4dc583a9d4abc1863c8954`
- Версия: `1.8.27`
- Python requirement: `>=3.12`
- Alembic head: `0007_position_account_scope`
- Состав исходного архива: 70 production Python files, 44 test Python files, 10 documentation/source-specification files, 8 migration Python files, 147 files total.
- В архиве не обнаружены `.env`, реальные secrets, virtual environments, caches, `*.pyc`, `*.egg-info`, `build/`, `dist/`, database dumps или реальные model artifacts.
- В исходном root отсутствовали `CHANGELOG.md` и `PATCH_*.md`; они восстановлены с этой итерации.

Глобальное окружение Python 3.13.5 не использовалось как доказательство качества: глобальный `pip check` обнаружил посторонний конфликт MoviePy/Pillow, Ruff отсутствовал, а pytest остановился на 21 collection error из-за отсутствующего `psycopg`. Для проекта создано отдельное изолированное окружение `.audit-venv` с `-e .[dev]`; оно исключено из release archive.

### Baseline в изолированном окружении до правок

| Проверка | Статус и результат |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 389 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — single head `0007_position_account_scope` |
| `python manage.py doctor` | NOT RUN — launcher требует project-local `.venv`; внешняя audit-venv намеренно отвергнута |
| `python manage.py test --require-integration` | NOT RUN — тот же guard project-local `.venv` |
| PostgreSQL integration suite | NOT RUN — отсутствуют безопасные отдельные `TEST_DATABASE_URL`/`POSTGRES_ADMIN_URL` |

Baseline suite был зелёным. Заявленные внешними экспертами количества ошибок не сопровождались файлами, примерами или тестами и поэтому не использовались как доказательство.

## Подтверждённые дефекты

| Severity | Defect | Evidence / impact |
|---|---|---|
| HIGH | Entry-zone расширялась наружу при округлении к `tickSize` | Для reference 100, ATR%=2% и tick 1 непрерывная зона `[99.76, 100.24]` превращалась в `[99, 101]`; execution plan мог разрешить неоценённую policy цену. |
| HIGH | Private GET signature могла не соответствовать фактически отправленной query string | Подпись строилась по отдельной отсортированной строке, а отправка выполнялась из исходного dict; mock transport воспроизвёл несовпадение подписи с реальным URL. Read-only account sync мог получать auth failure. |
| HIGH | Известные новые TradFi `symbolType` не исключались из crypto universe | `stock`, `forex` и `commodity` проходили фильтр и могли смешать другой market domain с криптовалютным обучением/inference. |

## Red → green evidence

| Regression contract | Red before fix | Green after fix |
|---|---|---|
| Tick rounding не расширяет policy band | Expected `[100, 100]`, actual `[99, 101]` | PASSED |
| Signature соответствует exact transmitted query | HMAC assertion failed на query фактически принятой mock transport | PASSED |
| TradFi-типы исключены по умолчанию | `AAPLUSDT`, `FOREXUSDT`, `GOLDUSDT` и `OLDSTOCKUSDT` попали в selected universe | PASSED |
| Explicit non-crypto opt-in сохраняется | Acceptance test добавлен после исправления для обратной совместимости | PASSED |

Первые три теста были реально запущены на исходном поведении и упали по ожидаемым причинам. После исправления новый модуль содержит четыре проходящих теста; связанный набор universe/execution/external-state содержит 23 проходящих теста.

## Post-check 1.8.28

| Проверка | Статус и результат |
|---|---|
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED — all checks passed |
| `python -m pytest -q` | PASSED — 393 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — single head `0007_position_account_scope` |
| Independent randomized execution/math audit | PASSED — 20,000 deterministic entry-band and directional-P&L cases |
| Advisory-only static mutation scan | PASSED — Bybit client has no HTTP write calls or order-mutation endpoint literals |
| Strict `mypy app scripts manage.py` (ancillary, not configured release gate) | FAILED — 175 existing diagnostics in 31 files, predominantly missing third-party stubs and legacy typing debt |
| `python -m scripts.test_runner --require-integration` | NOT RUN — fail-closed: `POSTGRES_ADMIN_URL`/`TEST_DATABASE_URL` not configured |
| Release tree + `SHA256SUMS` | PASSED — 151 source files checked, 151 manifest entries |

## Compatibility and release boundary

- No database schema change and no Alembic migration.
- No new or renamed environment variable.
- No API schema change.
- No Bybit write endpoint or order placement/amend/cancel capability added.
- Failure mode is conservative: no executable tick inside the policy interval blocks publication instead of widening acceptance.
- `UNIVERSE_ALLOW_NON_CRYPTO_SYMBOL_TYPES=true` remains an explicit operator opt-in.

## Not verified / residual evidence gap

- PostgreSQL integration and migration upgrade/downgrade against a real isolated database.
- Live Bybit private-auth smoke with real read-only credentials.
- End-to-end browser/operator smoke.
- Strict static typing is not green and is not presently a configured release gate.
- Aggregate coverage measured 66%; API/worker paths remain less covered than core math/training modules.
- Historical order-book/fill/funding replay, full walk-forward, drift/regime governance, PBO/DSR and forward profitability evidence remain incomplete.

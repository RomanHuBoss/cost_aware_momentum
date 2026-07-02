# QA Report — 1.8.29

Дата: 2026-07-02

## Входной baseline 1.8.28

- Архив: `cost_aware_momentum-main.zip`
- SHA-256: `a9be1f4321153df46b716ab7c2df547aadd1db4a1e227b75819690551744d67b`
- Версия: `1.8.28`
- Python requirement: `>=3.12`
- Alembic head: `0007_position_account_scope`
- Состав: 70 production Python files, 45 test Python files, 12 documentation/source-specification files, 8 migration Python files, 149 clean files total.
- Секреты, `.env`, virtual environments, caches, bytecode, build/dist, dumps и реальные model artifacts в исходном ZIP не обнаружены.
- Подтверждён release-provenance gap: `CHANGELOG.md`, `PATCH_*.md` и `SHA256SUMS` отсутствовали, хотя предыдущие QA/iteration documents заявляли их наличие и успешную проверку.

Глобальный Python 3.13.5 не использовался как доказательство проекта: глобальный `pip check` обнаружил посторонний MoviePy/Pillow conflict, Ruff отсутствовал, а pytest остановился на 21 collection error из-за отсутствующего `psycopg`. Создано отдельное `.audit-venv` с `-e .[dev]`; оно исключается из release.

### Baseline в изолированном окружении до правок

| Проверка | Статус и результат |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 393 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — single head `0007_position_account_scope` |
| `python manage.py doctor` | NOT RUN — no project-local `.venv`, `.env` or safe PostgreSQL configuration |
| `python manage.py test --require-integration` | NOT RUN — no isolated `TEST_DATABASE_URL`/`POSTGRES_ADMIN_URL` |
| Input release integrity | FAILED — manifest missing; 149 files checked, 0 entries |

Заявленные внешними экспертами количества ошибок не сопровождались модулями, воспроизведениями или тестами. Они не использовались как доказательство и не подтверждены этим аудитом.

## Подтверждённые дефекты

| Severity | Defect | Impact |
|---|---|---|
| HIGH | Hidden ATR clipping between training and inference | Probabilities and published SL/TP/EV could describe different barrier tasks. |
| HIGH | Runtime omitted label-path and temporal-split schema validation | Legacy/leaky/incompatible artifacts could enter inference despite feature-schema compatibility. |
| HIGH | Incumbent compared on candidate labels with different ATR multipliers | Auto-activation could use an invalid apples-to-oranges relative comparison. |
| MEDIUM | Positive no-loss holdout represented as missing profit factor | Economically positive candidate was falsely rejected; no-trade and no-loss states were conflated. |
| HIGH (research integrity) | Backtest bypassed production artifact validation | Research results could be generated from incompatible artifacts or silent default geometry. |
| MEDIUM | Release manifest/changelog/patch missing despite contrary QA claim | Archive provenance and reproducibility were not verifiable. |

No evidence-backed P0/critical defect was confirmed. This does not prove that none exists; PostgreSQL integration, live API and forward trading evidence were unavailable.

## Red → green evidence

Dedicated module: `tests/unit/test_quant_integrity_2026_07_02.py`.

- Initial run before fixes: 6 failures for exact ATR parity, four semantic-schema rejection cases and no-loss profit factor.
- Backtest loader acceptance test before implementation: ImportError for missing validated loader.
- Barrier-geometry comparison test before fix: incumbent metrics were evaluated (`{'rows': 1}`) instead of being skipped.
- Final dedicated result: 8 passed.

## Post-check 1.8.29

| Проверка | Статус и результат |
|---|---|
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED — all checks passed |
| `python -m pytest -q` | PASSED — 401 passed, 4 skipped, 19 warnings |
| dedicated regression module | PASSED — 8 tests |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — single head `0007_position_account_scope` |
| Independent randomized quant audit | PASSED — 20,000 deterministic cases |
| Advisory-only static mutation scan | PASSED — no order/withdraw methods or endpoint literals |
| Release tree + `SHA256SUMS` | PASSED — 153 source files checked, 153 manifest entries |

## Compatibility

- No database schema change and no Alembic migration.
- No new or renamed environment variable.
- No API/JSON schema change.
- No dependency change.
- Active legacy artifact without required label/temporal schema metadata must be retrained; this intentional fail-closed incompatibility prevents silent use of an undefined training task.

## Not verified / residual evidence gap

- PostgreSQL integration, migration upgrade/downgrade and concurrency against a real isolated database.
- Real Bybit public/private read-only smoke and current exchange behavior.
- Browser end-to-end/operator workflow.
- Exact historical order book, fills, no-fill/partial-fill process, funding timeline and operator latency in research.
- Full walk-forward, drift/regime governance, PBO/DSR and forward profitability evidence.
- Technical correctness and green tests are not evidence of economic edge.

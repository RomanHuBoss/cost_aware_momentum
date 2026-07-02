# QA Report — 1.8.30

Дата: 2026-07-02

## Входной baseline 1.8.29

- Архив: `cost_aware_momentum-main.zip`
- SHA-256: `8063d87fc2d769b0505cba80cf33353ebea928a5dd335de84d2dad8455addb6f`
- Версия: `1.8.29`
- Python requirement: `>=3.12`
- Alembic head: `0007_position_account_scope`
- Состав: 69 production Python files, 45 `test_*.py`, 7 Alembic revision files и 12 documentation/source-specification files.
- Секреты, `.env`, virtual environments, caches, bytecode, build/dist, dumps и реальные model artifacts в исходном ZIP не обнаружены.
- `CHANGELOG.md`, `PATCH_*.md` и `SHA256SUMS` отсутствовали, хотя документы 1.8.29 заявляли их наличие.

Глобальный Python 3.13.5 не использовался как доказательство проекта: глобальный `pip check` обнаружил посторонний MoviePy/Pillow conflict, Ruff отсутствовал, а pytest не мог собрать проект без `psycopg`. Для baseline создано отдельное `.audit-venv` с `-e .[dev]`; оно исключено из release.

### Baseline в изолированном окружении до правок

| Проверка | Статус и результат |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 401 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — single head `0007_position_account_scope` |
| `python manage.py doctor` | NOT RUN — отсутствуют project-local `.env` и безопасная PostgreSQL-конфигурация |
| `python manage.py test --require-integration` | NOT RUN — отсутствует отдельная тестовая PostgreSQL |

Заявленные третьими сторонами количества «20/18 critical» и «7 medium» не сопровождались файлами, функциями, входными данными или воспроизведением. Они не использовались как доказательство. Эта итерация подтверждает только дефекты ниже.

## Подтверждённые дефекты и gap

| Severity | Класс | Дефект | Влияние |
|---|---|---|---|
| HIGH | CONFIRMED DEFECT | Late execution plan повторно использовал signal-level path, начавшийся до `planning_time` | Ретроактивный TP/SL, неверные plan P&L/R и искажённый audit/research evidence |
| HIGH | CONFIRMED DEFECT | Profit factor вычислял gross gain/loss после netting по `exit_time` | Одновременные выигрыш и проигрыш взаимопогашались; promotion metric могла быть ложной |
| MEDIUM | CONFIRMED DEFECT | `projected_funding_rate` переносил старый settlement anchor циклом | Повреждённый/старый timestamp мог надолго заблокировать worker |
| MEDIUM | CONFIRMED DEFECT | Execution spec query не ограничивал `received_at <= cutoff` | Point-in-time replay мог использовать запись, ещё не доступную в момент решения |
| MEDIUM | CONFIRMED GAP | Release provenance files отсутствовали вопреки QA 1.8.29 | Нельзя было воспроизводимо проверить состав архива |

Критический P0, способный разместить ордер, вывести средства или обойти advisory-only, не подтверждён. Это не доказательство отсутствия всех дефектов: PostgreSQL integration, live Bybit smoke и forward evidence недоступны.

## Red → green evidence

Dedicated module: `tests/unit/test_quant_outcome_integrity_2026_07_02.py`.

### Red на неизменённом 1.8.29

Команда с пятью первоначальными regression tests завершилась `5 failed`:

- late plan получил `VALUED`, ожидался `PATH_UNAVAILABLE`;
- ORM constraint не содержал `PATH_UNAVAILABLE`;
- simultaneous winner/loser дали gross gain/loss `0/0`, ожидалось `0.5/0.5`;
- stale one-minute funding anchor превысил три итерации и был остановлен test guard;
- SQL instrument-spec query не содержал `received_at <= cutoff`.

### Green после исправления

- `python -m pytest -q tests/unit/test_quant_outcome_integrity_2026_07_02.py` — PASSED, 6 tests.
- Совместный outcome regression suite — PASSED, 28 tests.
- Полный suite — PASSED, 407 tests; 4 integration tests корректно skipped без PostgreSQL.

## Post-check 1.8.30

| Проверка | Статус и результат |
|---|---|
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED — all checks passed |
| `python -m pytest -q` | PASSED — 407 passed, 4 skipped, 19 warnings |
| dedicated regression module | PASSED — 6 tests |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — single head `0008_plan_outcome_path_unavailable` |
| Advisory-only/DB boundary static scan | PASSED — production code не содержит order create/amend/cancel, withdraw, SQLite или `create_all` flow |
| `python manage.py doctor` | NOT RUN — отсутствуют локальная конфигурация и PostgreSQL service |
| `python manage.py test --require-integration` | NOT RUN — отдельная тестовая PostgreSQL не предоставлена |
| Migration upgrade/backfill/downgrade on PostgreSQL | NOT RUN — нет безопасной test DB |
| Release tree + `SHA256SUMS` | PASSED — 156 files checked, 156 manifest entries |

## Compatibility and operator action

- Новых зависимостей и `.env`-переменных нет.
- API поля не удалены; `plan.valuation_status` получает новое значение `PATH_UNAVAILABLE`.
- Требуется `python manage.py migrate`; новый head — `0008_plan_outcome_path_unavailable`.
- Migration переводит исторические late-plan `VALUED`/`FUNDING_UNAVAILABLE` rows в `PATH_UNAVAILABLE` и обнуляет недостоверные P&L/R.
- Downgrade намеренно fail-closed, если `PATH_UNAVAILABLE` rows существуют; сначала нужен осознанный data remediation.
- Policy metric schema повышена с v5 до v6. Promotion evidence v5 необходимо пересчитать текущим trainer; active incumbent не деактивируется при неудаче candidate.

## Остаточные риски

- Полная денежная оценка plan, созданного позже signal event, невозможна без сохранённого entry-aligned intrabar path. Статус `PATH_UNAVAILABLE` устраняет ложную точность, но не добавляет отсутствующие данные.
- SQL backfill migration не проверен на копии реальной PostgreSQL-базы и может fail-closed остановиться на нестандартном повреждённом `planning_time`.
- Integration tests, live read-only Bybit smoke, restore test, paper/shadow forward evidence и экономическая доходность не проверены.
- Предупреждения NumPy/joblib относятся к upstream deprecation и не являются падением suite.

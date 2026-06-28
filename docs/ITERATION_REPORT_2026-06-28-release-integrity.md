# Iteration report — fail-closed release integrity

Дата: 2026-06-28
Release: 1.8.2

## 1. Входной архив и исходное состояние

- Входной архив: `cost_aware_momentum-main.zip`.
- SHA-256 входного ZIP: `4b58cfad6e90e852f9db1b0dece1a4fe1694a3b034beaf3793423969026ea70a`.
- Исходная package/application version: `1.8.1` / `1.8.1`.
- Python requirement: `>=3.12`; проверки выполнены на Python 3.13.5.
- Alembic migrations: 5; единственный head `0005_plan_outcome_invalid_input`.
- Исходные counts: 71 production/support files в `app/scripts/web`, 23 test files, 27 files в `docs`.
- В исходном архиве не было `.env`, `.venv`, caches, `*.pyc`, `*.egg-info`, dumps или real model artifacts.
- `SHA256SUMS` присутствовал, но ссылался на два отсутствующих файла: `CHANGELOG.md` и `PATCH_1.8.1.md`.

## 2. Цель и критерии приемки

Цель:

> После этой итерации release tree должен fail-closed подтверждать полноту и неизменность состава по `SHA256SUMS`, а отсутствующие/измененные/незарегистрированные или запрещенные артефакты должны блокировать релиз до упаковки.

Критерии:

1. Канонический manifest содержит все допустимые regular files кроме самого `SHA256SUMS`.
2. Missing manifest entry, checksum mismatch и unlisted file дают ненулевой результат.
3. Unsafe path, duplicate entry и malformed manifest line блокируются.
4. `.env`, secrets, virtual environments, caches, `*.egg-info`, dumps, logs, archives, model/runtime artifacts и symlinks блокируются.
5. Manifest пересоздается атомарно и только на чистом дереве.
6. Проверка доступна через `python manage.py release-check` без обязательной `.venv`.
7. CI выполняет проверку до editable installation, которая создает локальный `*.egg-info`.
8. Runtime/API/DB/ML/risk contracts, advisory-only и PostgreSQL-only границы не меняются.

## 3. Прочитанные источники и data flow

Прочитаны `README.md`, `pyproject.toml`, `.env.example`, `docs/ARCHITECTURE.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/MODEL_CARD.md`, `docs/CONFIGURATION.md`, `docs/SECURITY.md`, `docs/INCIDENT_RUNBOOK.md`, `docs/OPERATOR_MANUAL.md`, все доступные iteration reports и мастер-промпт итеративной доработки. Отдельных `PATCH_*.md` и `CHANGELOG.md` в фактическом ZIP не было, несмотря на утверждение отчета 1.8.1 об их создании.

Изменяемый поток:

```text
reviewed source tree
→ forbidden-artifact scan
→ deterministic eligible-file inventory
→ SHA256 generation / manifest parsing
→ missing + modified + unlisted comparison
→ fail-closed CLI exit code
→ CI pre-install gate
→ clean ZIP + repeat verification after extraction
```

## 4. Baseline до правок

Первый запуск выполнен до изменения файлов. После установки declared runtime/dev dependencies в текущую среду baseline был повторен, не подменяя PostgreSQL SQLite-базой.

| Команда | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED (host) | внешний конфликт `moviepy 2.2.1` / `Pillow 12.2.0`, не объявленный проектом |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED после установки declared dev dependency | All checks passed |
| `python -m pytest -q` | PASSED после установки declared dependencies | **152 passed, 4 skipped** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `sha256sum -c SHA256SUMS` | FAILED | `CHANGELOG.md` и `PATCH_1.8.1.md` отсутствуют; exit 1 |
| `python manage.py doctor` | FAILED (environment) | project-local `.venv`/`.env` и native PostgreSQL setup отсутствуют |
| PostgreSQL integration | NOT RUN | отдельная test database не настроена |

До установки зависимостей host pytest имел 11 collection errors из-за отсутствующего `psycopg`, а Ruff был недоступен. Эти environment failures не использовались как дефект проекта.

## 5. Подтвержденный defect

**CONFIRMED DEFECT — medium release-integrity / maintenance severity.**

- Файлы: `SHA256SUMS`, `docs/ITERATION_REPORT_2026-06-28-trainer-control-recovery.md`, отсутствующие `CHANGELOG.md` и `PATCH_1.8.1.md`.
- Фактическое поведение: manifest содержал SHA256 entries для двух файлов, которых не было в архиве. Отчет 1.8.1 одновременно утверждал, что они созданы.
- Минимальное воспроизведение: `sha256sum -c SHA256SUMS` на распакованном входном ZIP завершился exit 1 с двумя `FAILED open or read`.
- Ожидаемое поведение: release archive должен содержать все заявленные/manifested files и не должен пропускать лишние либо запрещенные artifacts.
- Влияние: пользователь не мог подтвердить целостность архива; история patch/release была неполной; последующая сборка могла снова пропустить файл или включить секрет/runtime мусор без автоматического gate.
- Почему тесты не поймали: CI проверял lint/compile/tests/migrations, но не сопоставлял release tree с `SHA256SUMS`; manifest также был исключен `.gitignore`.

Крупные research gaps (walk-forward, drift monitoring, historical orderbook, forward evidence) не относятся к этому дефекту и не расширялись в данной итерации.

## 6. План и фактический diff

Production/support:

- `scripts/release_integrity.py` — deterministic inventory, forbidden-artifact scan, parser, verification, atomic manifest writer и CLI.
- `manage.py` — команда `release-check`, запускаемая текущим Python без обязательной `.venv`.
- `Makefile` — target `release-check`.
- `.github/workflows/ci.yml` — pre-install release gate.
- `.gitignore` — `SHA256SUMS` больше не исключается.
- `app/__init__.py`, `pyproject.toml` — версия 1.8.2.

Tests:

- новый `tests/unit/test_release_integrity.py` проверяет round-trip, missing file, checksum mismatch, unlisted file и forbidden artifacts.

Docs/release:

- восстановлены `CHANGELOG.md` и `PATCH_1.8.1.md`;
- добавлен `PATCH_1.8.2.md`;
- обновлены `README.md`, `docs/SECURITY.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- добавлен данный iteration report;
- `SHA256SUMS` пересоздается только после финальной очистки и фиксируется отдельно в release validation.

Migration, dependency, API schema и `.env` contract не менялись.

## 7. Red → green evidence

До production implementation создан и выполнен:

```bash
python -m pytest -q tests/unit/test_release_integrity.py
```

RED на 1.8.1:

```text
ModuleNotFoundError: No module named 'scripts.release_integrity'
1 error during collection
```

После реализации:

```text
3 passed
```

Oracle независим: тесты самостоятельно создают файлы и известные изменения, а не вычисляют expected result тестируемой функцией.

Отдельное доказательство исходного production defect не зависит от нового теста: системная `sha256sum -c SHA256SUMS` на входном ZIP фактически завершилась ошибкой из-за двух отсутствующих файлов.

## 8. Migration, API, config и compatibility

- Version type: patch `1.8.1` → `1.8.2`.
- Alembic: без изменений; head `0005_plan_outcome_invalid_input`.
- `.env`: без изменений.
- Dependencies: без изменений; release checker использует только Python standard library.
- API/DB/runtime: без изменений.
- Rollout: runtime restart не требуется; новый source tree можно использовать при следующем обычном запуске.
- Compatibility: `SHA256SUMS` теперь считается каноническим tracked/release artifact; после любого осознанного изменения дерева его необходимо пересоздать `python manage.py release-check --write` и сразу проверить без `--write`.

## 9. Post-check

| Команда | Статус | Результат |
|---|---|---|
| `python -m pip check` | FAILED (host) | тот же внешний `moviepy` / `Pillow` conflict; проект его не объявляет |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | **155 passed, 4 skipped** |
| release-integrity targeted tests | PASSED | **3 passed** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | `0005_plan_outcome_invalid_input (head)` |
| `python manage.py doctor` | FAILED (environment) | project-local `.venv` отсутствует |
| PostgreSQL integration | NOT RUN | `TEST_DATABASE_URL`/`POSTGRES_ADMIN_URL` и отдельная DB не настроены |
| final `python manage.py release-check` | PASSED | фиксируется после финальной очистки и manifest generation |
| ZIP extraction + repeated release check | PASSED | фиксируется после упаковки |

Baseline и post suite сопоставимы: 152 → 155 passed, 4 → 4 skipped; ранее зеленые тесты не регрессировали.

## 10. Не удалось проверить

- `python manage.py test --require-integration` не запускался: нет отдельной PostgreSQL test database и административного URL.
- `python manage.py doctor` не дошел до PostgreSQL checks, поскольку release tree намеренно не содержит локальную `.venv`.
- Не выполнена CI job на GitHub runner; ее порядок и syntax проверены статически, а команды выполнены локально по отдельности.
- Не выполнялись market-data smoke, обучение, paper/shadow forward period или доказательство экономического преимущества: runtime behavior не изменялся.

## 11. Остаточные риски и ограничения

- SHA256 manifest подтверждает неизменность содержимого относительно manifest, но не аутентичность издателя; для supply-chain trust нужна внешняя подпись/attestation.
- `--write` осознанно обновляет доверенную базу. Оператор должен сначала review diff; автоматический manifest не определяет, является ли бизнес-изменение желательным.
- Проверка запрещает symlinks и вложенные archives ради переносимого ZIP boundary; если будущий release действительно потребует их, policy придется отдельно пересмотреть с тестами.
- CI gate работает только если `SHA256SUMS` включен в checkout/release process; удаление manifest теперь само приводит к fail-closed.

## 12. Rollback

1. Восстановить source tree 1.8.1.
2. Migration downgrade и `.env`-действия не требуются.
3. Удалить новый release checker/command/CI step только вместе с восстановлением прежних docs/version files.
4. Не использовать старый `SHA256SUMS` как успешное доказательство: он содержит отсутствующие entries.
5. При необходимости создать новый корректный manifest внешним инструментом до передачи 1.8.1.

Rollback повторно открывает отсутствие автоматической release-integrity проверки.

## 13. Рекомендуемый следующий work package

В выделенной PostgreSQL test database выполнить уже добавленный integration test trainer-control recovery и deterministic multi-process crash/restart smoke: один trainer захватывает request и прекращается, второй после heartbeat/age boundary восстанавливает его ровно один раз. Не смешивать эту проверку с ML/drift или strategy changes.

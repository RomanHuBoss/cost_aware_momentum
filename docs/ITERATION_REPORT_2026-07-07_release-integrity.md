# Iteration Report — 2026-07-07 — release integrity

## 1. Входной архив

- Архив: `cost_aware_momentum-main.zip`.
- SHA-256: `40243ac666ae53d0e62dc73cbd28ae0a6c8ff581378c3cc7034610ef6f005deb`.
- Исходная версия: 1.51.0.
- Python requirement: `>=3.12`.
- Alembic head: `0018_inference_observations`.
- Исходный inventory без test/build-мусора: 252 файлов; 99 production Python files, 118 test Python files, 2 documentation files.

## 2. Цель и критерии приёмки

После итерации release verification должна fail-closed доказывать не только checksum-consistency, но и полноту обязательного release contract и идентичность версии.

Критерии:

1. Самосогласованный manifest неполного tree получает `ok=False`.
2. Несовпадение версии package/runtime/README получает `ok=False`.
3. Для текущей версии обязательны `PATCH_<version>.md` и iteration report.
4. В release присутствуют architecture, security, configuration, model, operator, incident, QA, compliance и traceability документы.
5. Старые release-integrity проверки сохраняются зелёными.
6. Полный suite не регрессирует.
7. Чистый итоговый tree проходит повторный checksum verification и ZIP re-extract.

## 3. Прочитанные источники и data flow

Прочитаны README, `pyproject.toml`, `.env.example`, техническая DOCX-спецификация, migrations, release script, release tests, risk math, execution acceptance/manual fill paths, signal policy, training policy evaluation и model lifecycle gates. Во входном архиве отсутствовали заявленные master-протоколом changelog/patch/QA/compliance/traceability документы; старую историю нельзя было достоверно восстановить.

Изменяемый flow:

release tree → forbidden/eligible inventory → required contract/version extraction → manifest parsing → per-file SHA-256 → `ReleaseIntegrityReport` → operator CLI.

## 4. Baseline

- Python 3.13.5: PASSED.
- pip check: PASSED.
- compileall: PASSED.
- Ruff: PASSED.
- Pytest: 836 passed, 8 skipped, 62 warnings.
- Node syntax: PASSED.
- Release check: FAILED — отсутствовал manifest; после baseline-команд tree также содержал caches/egg-info.
- PostgreSQL integration: NOT RUN — отдельная test DB не настроена.

## 5. Подтверждённые defects/gaps

### HIGH — incomplete release tree мог пройти verification

- Файл: `scripts/release_integrity.py`, исходный `verify_release_tree()`.
- Reproducer: создать tree только с README и Python-файлом, вызвать `write_manifest()`, затем `verify_release_tree()`.
- Фактически: `ReleaseIntegrityReport(ok=True, checked_files=2, listed_files=2, errors=())`.
- Ожидалось: fail-closed из-за отсутствующих QA/security/operations/compliance artifacts.
- Влияние: неполный или ошибочно собранный release мог быть аттестован как корректный; checksum доказывал неизменность неполного набора, а не его полноту.
- Почему тесты не поймали: существующие tests проверяли missing/unlisted/modified/forbidden files только относительно manifest, но не независимый release contract.

### HIGH — version drift не обнаруживался

- Файлы evidence: `pyproject.toml`, `app/__init__.py`, README.
- Reproducer: сформировать полный tree, записать 1.51.1 в TOML/README и 1.51.0 в runtime module, пересчитать manifest.
- Фактически: `ok=True`.
- Ожидалось: version mismatch blocks release.
- Влияние: archive label, package metadata и runtime diagnostics могли относиться к разным версиям при валидных checksums.

### Review outcome для quant paths

В пределах этой итерации проверены sign geometry LONG/SHORT, fee normalization, funding signs, qty flooring, acceptance risk reservation и policy expected/realized accounting. Подтверждённого mathematical defect не воспроизведено; gates не ослаблялись и фиктивные «15/8 ошибок» не заявлялись.

## 6. План и фактический diff

### Production

- `scripts/release_integrity.py`: required file contract, independent version extraction, version-specific patch и iteration evidence checks.
- `pyproject.toml`, `app/__init__.py`, README: версия 1.51.1.

### Tests

- `tests/unit/test_release_contract_2026_07_07.py`: два regression cases.
- `tests/unit/test_release_integrity.py`: fixtures обновлены до valid release contract; прежние assertions сохранены.

### Documentation

Добавлены `CHANGELOG.md`, `PATCH_1.51.1.md`, architecture/config/security/model/operator/incident/QA/compliance/traceability документы и этот report.

### Migration/config/API

- Migration: нет.
- Новые `.env` variables: нет.
- API/JSON/DB semantics: без изменений.

## 7. Red → green evidence

Red command:

```bash
python -m pytest -q tests/unit/test_release_contract_2026_07_07.py
```

Результат на исходном production code: 2 failed; обе проверки наблюдали ошибочный `report.ok is True`.

Green command:

```bash
python -m pytest -q \
  tests/unit/test_release_contract_2026_07_07.py \
  tests/unit/test_release_integrity.py
```

Результат после исправления: 5 passed.

## 8. Compatibility и rollback

Изменение обратно совместимо для корректно собранных releases, но намеренно делает verification строже. Старый неполный архив 1.51.0 не пройдёт новый contract без восстановления документов и version-specific evidence.

Rollback к 1.51.0 технически возможен заменой изменённых release files, но не рекомендуется: он вновь открывает fail-open. DB rollback не требуется.

## 9. Post-check

- pip check: PASSED.
- compileall: PASSED.
- Ruff: PASSED.
- Pytest: 838 passed, 8 skipped, 62 warnings.
- Node syntax: PASSED.
- Alembic head: единственный `0018_inference_observations`.
- Final release check/write/verify: PASSED после очистки tree.
- ZIP test и clean re-extract: PASSED.

## 10. Непроверенное

- PostgreSQL integration/upgrade на чистой и существующей БД: отдельная test DB отсутствовала.
- `manage.py doctor`: external venv не распознан, project-local `.venv` не создавался.
- Bybit network/read-only smoke: не выполнялся.
- Реальная paper/shadow/forward profitability: не проверялась и не заявляется.
- История изменений до 1.51.1: отсутствовала во входном ZIP и не реконструирована.

## 11. Остаточные риски

- 62 dependency deprecation warnings могут стать failures после будущего pandas/NumPy update.
- Наличие документов теперь проверяется, но их содержательная актуальность остаётся review responsibility; checksum не доказывает истинность текста.
- Release contract требует осознанного обновления списка при легитимном изменении структуры проекта.

## 12. Rollback procedure

1. Остановить API/worker/trainer.
2. Вернуть исходные `scripts/release_integrity.py`, version files и tests из доверенного 1.51.0 source.
3. Удалить добавленные 1.51.1 docs только при полном rollback.
4. Пересобрать manifest и проверить archive.
5. Учитывать, что rollback снова допускает неполный self-consistent tree.

## 13. Рекомендуемый следующий work package

Отдельно устранить pandas/NumPy timedelta deprecation warnings с regression tests, не совмещая это с изменением model gates или торговой математики.

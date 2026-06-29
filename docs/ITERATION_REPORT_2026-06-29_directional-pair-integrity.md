# Итерационный отчет: directional pair integrity

Дата: 2026-06-29
Итоговая версия: 1.8.9

## 1. Входной архив и исходная версия

- Входной файл: `cost_aware_momentum-main.zip`.
- SHA-256 входного ZIP: `fa64fe822e3857a28f25fa5f333ebdc6de502408a65580d928205cd7256e8c2b`.
- Исходная версия: 1.8.8.
- Python requirement: `>=3.12`; проверки выполнены на Python 3.13.5.
- Alembic: единственный head `0005_plan_outcome_invalid_input`.
- Исходный архив уже содержал patch, заявляющий 7 critical и 3 medium исправления. Они были проверены существующим regression module и полным baseline suite; эта итерация не приписывает их своему diff.

## 2. Цель и критерии приемки

После этой итерации research/lifecycle pipeline должен оценивать model policy только на тех directional cohorts, которые допустимы в production: ровно один LONG и один SHORT для каждого `decision_time/symbol`.

Критерии:

1. Dataset не сохраняет одно направление отдельно от второго.
2. Причина атомарного исключения отражается в diagnostics.
3. Chronological split fail-closed отклоняет неполную либо дублированную пару.
4. Holdout policy fail-closed отклоняет такой вход до расчета metrics.
5. Research backtest использует тот же контракт.
6. Regression tests дают доказуемый red → green.
7. Публичный API, DB schema, `.env`, advisory-only и PostgreSQL-only границы не меняются.

## 3. Прочитанные источники и data flow

Прочитаны `README.md`, `CHANGELOG.md`, `PATCH_1.8.7.md`, `PATCH_1.8.8.md`, последние iteration reports, `pyproject.toml`, `.env.example`, `docs/ARCHITECTURE.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`, приложенный master prompt и относящиеся к задаче production/tests.

Проверенный поток:

`confirmed hourly candles → features → LONG/SHORT barrier geometry and labels → make_barrier_dataset → chronological_split → model probabilities → evaluate_policy_model / policy_backtest → candidate/incumbent gate or research report`.

Production reference contract:

`ModelRuntime.predict_scenarios → select_cost_aware_scenario`, где уже требуется точная пара LONG/SHORT.

## 4. Baseline до правок

Authoritative checks выполнены в отдельной virtual environment вне release tree:

| Команда | Результат |
|---|---|
| `python --version` | Python 3.13.5 |
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | 194 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | один head: `0005_plan_outcome_invalid_input` |

Четыре PostgreSQL integration tests корректно skipped: `TEST_DATABASE_URL` не настроен. Первичная попытка в глобальном Python была отвергнута как неавторитетная: там отсутствовали project dependencies и присутствовал посторонний конфликт `moviepy/pillow`. `manage.py doctor` и `manage.py test --require-integration` были запущены, но получили статус `UNAVAILABLE`: обе команды завершились до проверок сообщением `Виртуальная среда не найдена`, поскольку чистый release tree не содержит локальной `.venv`; безопасная PostgreSQL test DB также не настроена.

## 5. Подтвержденный дефект

### Critical — неполная directional-пара проходила в research и auto-activation

Статус: `CONFIRMED DEFECT`.

- Файлы: `app/ml/training.py` (`make_barrier_dataset`, `chronological_split`, `evaluate_policy_model`), `scripts/backtest.py` (`policy_backtest`).
- Минимальный пример: 80 последовательных hourly candles с ценой около 1 и ATR-диапазоном 0.6. LONG barrier оставался положительным, а SHORT TP уходил в неположительную цену и отклонялся geometry validator.
- Фактическое поведение 1.8.8: dataset создавал 52 строки, и все `(decision_time, symbol)` groups содержали только один LONG. Split, holdout и backtest принимали эти rows.
- Ожидаемое поведение: directional decision является сравнением LONG против SHORT; при отсутствии хотя бы одного направления весь cohort недопустим.
- Влияние: selection bias и research/live mismatch; candidate/incumbent policy gate и backtest могли учитывать сделки, которые production fail-closed отклоняет.
- Почему прежние тесты не поймали: production selector имел парный контракт, но training fixtures обычно содержали обе строки, а dataset tests проверяли labels/continuity без group cardinality invariant.

Исходные 7 critical и 3 medium из 1.8.8 дополнительно проверены существующим `tests/unit/test_quant_correctness_hardening.py`; новые доказательства их регрессии не обнаружены.

## 6. План и фактический diff

Production:

- `app/ml/training.py`: атомарное построение пары, diagnostics и общий `validate_directional_scenario_pairs` на dataset/split/holdout boundaries.
- `scripts/backtest.py`: обязательная проверка пары до policy calculations.

Tests:

- новый `tests/unit/test_directional_pair_integrity.py` с четырьмя независимыми tests;
- `tests/unit/test_backtest_econometrics.py` и `tests/unit/test_quant_correctness_hardening.py`: старые LONG-only fixtures получили заведомо low-edge SHORT counterpart, чтобы продолжать проверять прежнюю математику под новым production contract.

Docs/release:

- version 1.8.9, `README.md`, `CHANGELOG.md`, `PATCH_1.8.9.md`;
- `docs/QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `ARCHITECTURE.md`;
- этот report и пересчитанный `SHA256SUMS`.

Scope не расширялся до нового backtest engine либо walk-forward framework.

## 7. Red → green evidence

Команда:

```bash
python -m pytest -q tests/unit/test_directional_pair_integrity.py
```

На исходном 1.8.8: `4 failed`.

Тесты независимо доказали, что:

- dataset создавал 52 односторонние строки вместо нуля;
- chronological split принимал missing SHORT;
- holdout policy рассчитывал metrics на missing SHORT;
- backtest формировал отчет на missing SHORT.

После исправления: `4 passed`.

Оракулы независимы от тестируемой реализации: cardinality определяется точным множеством `{LONG, SHORT}`, а synthetic geometry вручную делает только один barrier допустимым до атомарной фильтрации.

## 8. Миграции, API/config/env и совместимость

- Alembic migration: нет; head остается `0005_plan_outcome_invalid_input`.
- DB schema и stored rows: без изменений.
- HTTP/API schema: без изменений.
- `.env.example`: без изменений.
- Artifact serialization contract: без изменений.
- Поведенческая совместимость: некорректные неполные research cohorts теперь fail-closed; это намеренное ужесточение уже существующего production invariant.
- Рекомендуется retraining/re-evaluation, потому что dataset и holdout composition могут измениться.

## 9. Post-check

| Команда | Post 1.8.9 |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | 198 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | один head: `0005_plan_outcome_invalid_input` |
| Release integrity | PASSED после очистки и regeneration manifest |

Новый module отдельно: `4 passed`. Соседние econometric/hardening tests: `19 passed` после приведения fixtures к парному контракту.

## 10. Что не удалось проверить

- PostgreSQL integration/concurrency tests: безопасная отдельная `TEST_DATABASE_URL` отсутствовала.
- `manage.py doctor` и `manage.py test --require-integration`: `UNAVAILABLE`, поскольку wrapper требует локальную `.venv`; безопасная PostgreSQL test DB не была настроена.
- Реальная active-model recalibration, paper/shadow и forward performance: пользовательские artifacts/market period не предоставлены.
- Bybit network/API не требовались и не вызывались.

## 11. Остаточные риски и ограничения

- Исправление устраняет cardinality bias, но не доказывает прибыльность.
- Удаление неполных cohorts может непропорционально затрагивать низкоценовые/высоковолатильные инструменты; dataset diagnostics следует контролировать по symbol.
- Текущий final holdout остается единичным chronological split, а не multi-fold purged walk-forward.
- Cross-sectional dependence уменьшает effective sample size; intrahorizon mark-to-market, historical orderbook/no-fill и фактическая funding timeline не моделируются полностью.

## 12. Rollback procedure

1. Остановить API, worker и trainer.
2. Восстановить release 1.8.8 целиком и его `SHA256SUMS`; не смешивать отдельные Python files.
3. Выполнить `python manage.py release-check` в штатной локальной среде.
4. DB rollback не нужен: migration отсутствует.
5. Перезапустить процессы.

Rollback возвращает подтвержденный research/live mismatch и допустим только как аварийная мера.

## 13. Следующий рекомендуемый work package

Реализовать multi-fold purged walk-forward с fold-level calibration, policy stability, symbol/time cluster-aware uncertainty и агрегированным candidate/incumbent gate. Это отдельная итерация; версия 1.8.9 не заявляет полноценную эконометрическую валидацию стратегии.

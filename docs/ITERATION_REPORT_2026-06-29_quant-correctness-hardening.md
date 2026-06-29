# Iteration report — quant correctness hardening

## 1. Входной архив и baseline identity

- Вход: `cost_aware_momentum-main.zip`.
- SHA-256: `3f2e2a89d8ab0906b67a7e9928b2ac22ff1c2bd80c4d21228a32b846b11e8c05`.
- Исходная версия: `1.8.7` (`pyproject.toml`, `app/__init__.py`).
- Python requirement: `>=3.12`.
- Alembic migrations: `0001`–`0005`; единственный head `0005_plan_outcome_invalid_input`.
- Исходное дерево: 69 production Python files, 27 test modules, 16 Markdown documents, 5 migrations, 135 files всего.
- В release tree не обнаружены `.env`, credentials, `.venv`, model artifacts, database dumps или production data. Служебные каталоги `backups/`, `models/`, `reports/` содержали только release-safe placeholders.

Системный Python не использовался как источник истины: в нем отсутствовали project dependencies/Ruff и присутствовал посторонний конфликт Pillow. Для воспроизводимого baseline создано изолированное окружение `/mnt/data/cam_venv` вне release tree и установлен `.[dev]`.

## 2. Цель и критерии приемки

Цель: после итерации все вычислительные слои должны fail-closed обрабатывать разрывы/повреждение рынка и невалидные probabilities, а holdout policy должна выбирать направление и считать realized risk в тех же временных и tie-break semantics, что production/backtest.

Критерии:

1. Stateful features не зависят от цен до gap/duplicate/invalid bar.
2. Invalid OHLCV в обязательном feature/label window не становится actionable feature или `TIMEOUT` label.
3. Runtime, Decimal EV/R, holdout и backtest отвергают probability rows вне TP/SL/TIMEOUT simplex.
4. Production policy получает ровно один LONG и один SHORT scenario и использует `EV/R → net RR → LONG`.
5. Holdout realized total R и drawdown строятся по modeled exit events, а не decision timestamps.
6. Exchange `max_leverage < 1` дает `BLOCKED_INVALID_INPUT`.
7. Все прежние тесты остаются зелеными; новые regression tests проходят отдельно и в полном suite.
8. Advisory-only, PostgreSQL-only, API schema и migration head не изменяются.

## 3. Прочитанные источники и data flow

Прочитаны `README.md`, `CHANGELOG.md`, `PATCH_1.8.7.md`, последние iteration reports, `pyproject.toml`, `.env.example`, `docs/ARCHITECTURE.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`, master prompt и относящиеся к задаче production/tests.

Проверенный поток:

`confirmed candles → build_feature_frame/latest_feature_snapshot → ModelRuntime.predict_scenarios → select_cost_aware_scenario → net_rr_and_ev → MarketSignal/ExecutionPlan`

и research/lifecycle:

`confirmed candles → make_barrier_dataset → chronological_split → artifact.predict_proba → evaluate_policy_model / policy_backtest → candidate/incumbent gates`.

## 4. Baseline до правок

Authoritative checks в изолированном окружении:

| Команда | Результат |
|---|---|
| `python --version` | Python 3.13.5 |
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | 184 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | один head: `0005_plan_outcome_invalid_input` |

Четыре PostgreSQL integration tests были корректно skipped: `TEST_DATABASE_URL` не настроен. `python manage.py doctor` и `python manage.py test --require-integration` не запускались, поскольку безопасной отдельной PostgreSQL test DB не было. Production DB не использовалась.

## 5. Подтвержденные дефекты

### Critical 1 — stateful features пересекали gap

- Файл: `app/ml/features.py`, `build_feature_frame`.
- Доказательство: две истории с одинаковыми 40 post-gap bars, но prefix prices `1` и `1,000,000`, давали разные `ema_distance_12`/`ema_slope_12` после восстановления continuity.
- Факт: rolling continuity была boolean gate, но EMA/ATR/rolling calculations группировались только по symbol и сохраняли pre-gap state.
- Влияние: model feature и direction/EV могли зависеть от экономически недоступного старого режима.
- Почему тесты не поймали: проверяли только блокировку первых 24 часов после gap, не независимость состояния после восстановления.

### Critical 2 — invalid OHLCV могла стать actionable feature

- Файл: `app/ml/features.py`, `build_feature_frame`/`latest_feature_snapshot`.
- Доказательство: `close=0` внутри последних 24 часов проходил через `clip(lower=1e-18)` и latest snapshot возвращал значения.
- Влияние: ложный экстремальный return/EMA state и потенциальная публикация рекомендации.
- Почему тесты не поймали: имелись gap/duplicate tests, но отсутствовал OHLCV validity contract.

### Critical 3 — malformed future bar превращался в label

- Файл: `app/ml/labels.py`, `triple_barrier_outcome`.
- Доказательство: future `high=NaN` не вызывал ошибку; сравнения были false и функция возвращала `TIMEOUT`.
- Влияние: label contamination, calibration bias и неверный holdout.
- Почему тесты не поймали: проверяли TP/SL ordering и hourly ambiguity только на конечных ценах.

### Critical 4 — runtime доверял artifact probabilities

- Файл: `app/ml/runtime.py`, `_predict_artifact_scenarios`.
- Доказательство: artifact row `[0.8, 0.4, -0.2]` попадала в `Prediction` без ошибки.
- Влияние: математически невозможный EV/R мог выбрать и опубликовать направление.
- Почему тесты не поймали: fixtures выдавали только нормализованные probabilities.

### Critical 5 — core EV/R принимал невалидный simplex

- Файл: `app/risk/math.py`, `net_rr_and_ev`.
- Доказательство: `p_tp=.8, p_sl=.4, p_timeout=-.2` давали числовой EV/R.
- Влияние: центральная денежная математика не имела независимого probability boundary.
- Почему тесты не поймали: все тесты подавали корректные probabilities.

### Critical 6 — direction policy не требовала парного сравнения

- Файл: `app/services/signals.py`, `select_cost_aware_scenario`.
- Доказательство: единственный LONG scenario считался достаточным и возвращался как победитель.
- Влияние: missing/corrupt SHORT output мог незаметно превратить comparative policy в однонаправленную.
- Почему тесты не поймали: два прежних geometry tests сами использовали один scenario.

### Critical 7 — auto-activation drawdown имел look-ahead timing

- Файл: `app/ml/training.py`, `evaluate_policy_model`.
- Доказательство: TP, открытый в `t0` и закрытый в `t2`, и SL, открытый в `t1` и также закрытый в `t2`, строили промежуточную equity/drawdown по `decision_time`; фактически одновременные outcomes должны агрегироваться в одном exit event.
- Влияние: candidate/incumbent gate мог принять/отклонить модель по хронологически неверному drawdown.
- Почему тесты не поймали: прежний test проверял initial loss, но не overlapping decisions с одинаковым exit.

### Medium 1 — holdout direction tie зависел от row order

- Файл: `app/ml/training.py`, `evaluate_policy_model`.
- Доказательство: при одинаковом EV/R SHORT стоял первым и выбирался через `idxmax`, хотя LONG имел выше net RR и production/backtest выбирали LONG.
- Влияние: research/activation policy drift относительно live.

### Medium 2 — backtest не проверял probabilities

- Файл: `scripts/backtest.py`, `policy_backtest`.
- Доказательство: та же invalid row `[0.8, 0.4, -0.2]` проходила в backtest calculations.
- Влияние: недостоверный research report вместо fail-closed ошибки.

### Medium 3 — max leverage ниже 1 молча переопределялся

- Файл: `app/risk/math.py`, `calculate_position_plan`.
- Доказательство: `max_leverage=0.5` приводил к actionable 1x через `max(1, int(max_leverage))`.
- Влияние: plan нарушал instrument constraint вместо блокировки malformed spec.

## 6. Реализация и diff

Production:

- `app/ml/features.py`: OHLCV/time validity, duplicate detection, continuous valid segments, segmented EMA/ATR/rolling state, `INVALID_MARKET_BAR`.
- `app/ml/labels.py`: finite positive and coherent high/low/close validation.
- `app/ml/training.py`: shared probability matrix validator, invalid label-window exclusion, deterministic policy selection, exit-time event accounting.
- `app/ml/runtime.py`: Decimal probability simplex validation active artifact output.
- `app/risk/math.py`: shared Decimal simplex validator; invalid max leverage block.
- `app/services/signals.py`: exact LONG/SHORT pair contract; no score-based tie-break; executable side required.
- `scripts/backtest.py`: shared probability matrix validation.

Tests:

- новый `tests/unit/test_quant_correctness_hardening.py` — 10 independent regression tests;
- `tests/unit/test_cost_aware_direction_selection.py` — existing geometry tests приведены к production paired-scenario contract;
- `tests/unit/test_training.py` — policy fixtures дополнены фактическим `exit_index`.

Docs/release:

- version `1.8.8`, `README.md`, `CHANGELOG.md`, `PATCH_1.8.8.md`;
- `docs/QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `ARCHITECTURE.md`;
- данный iteration report и пересчитанный `SHA256SUMS`.

Migration/API/config:

- migrations: нет;
- `.env`: без изменений;
- HTTP/API response schema: без изменений;
- advisory-only и read-only Bybit boundary сохранены.

## 7. Red → green

Команда:

```bash
python -m pytest -q tests/unit/test_quant_correctness_hardening.py
```

На исходном 1.8.7: `10 failed`. Существенные red assertions: EMA зависела от prefix; invalid snapshot возвращал values; NaN label не отклонялся; runtime/core/backtest принимали invalid probabilities; selector принимал один LONG; drawdown был `1.0` вместо `0.0`; row-order выбирал SHORT вместо LONG; `max_leverage=0.5` оставался actionable.

После исправления: `10 passed`.

Ни один тест не использует результат тестируемой функции как oracle: ожидаемые свойства основаны на invariance, simplex identity, explicit exit timestamps, independent EV/R tie geometry и exchange constraint.

## 8. Post-check

| Команда | Post 1.8.8 |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | 194 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | один head: `0005_plan_outcome_invalid_input` |
| Release integrity | PASSED после очистки и regeneration manifest |

## 9. Непроверенное

- PostgreSQL integration/concurrency tests: нет безопасной `TEST_DATABASE_URL`.
- `manage.py doctor`: требует штатную локальную `.venv`, `.env` и PostgreSQL service; release tree намеренно оставлен чистым.
- Реальная active-model calibration и paper/shadow performance: отсутствуют пользовательские market/model artifacts и forward period.
- Bybit network/API не требовались и не вызывались.

## 10. Остаточные риски

- Исправление не доказывает прибыльность и не заменяет walk-forward/paper/shadow evidence.
- Рекомендуется переобучить model artifact: strict-hourly schema уже была заявлена как contiguous, но теперь фактически сбрасывает state после invalid segment.
- Holdout `policy_realized_total_r`/drawdown изменили эконометрическую семантику; исторические metrics до 1.8.8 нужно пересчитать, а не склеивать.
- Полноценные multi-fold walk-forward, intraday mark-to-market, historical orderbook/no-fill и drift-control остаются незакрыты.

## 11. Rollback

1. Остановить API, worker и trainer.
2. Восстановить release 1.8.7 целиком, не смешивая отдельные Python files.
3. Восстановить соответствующий `SHA256SUMS` и выполнить `python manage.py release-check`.
4. DB rollback не нужен: migration отсутствует.
5. Перезапустить процессы. Уже созданные DB rows/API contracts совместимы.

Rollback возвращает подтвержденные математические дефекты; предпочтителен только как аварийная мера.

## 12. Следующий рекомендуемый work package

Реализовать multi-fold purged walk-forward с fold-level calibration/policy stability, effective sample-size diagnostics по symbol/time dependence и сравнимым candidate/incumbent aggregation. Это отдельная итерация: текущий patch не заявляет полноценную эконометрическую валидацию стратегии.

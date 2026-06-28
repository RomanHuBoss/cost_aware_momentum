# Iteration report — class-order-safe log loss

## 1. Вход

- Archive: `cost_aware_momentum-1.7.8-root-clean.zip`
- Input SHA-256: `27742e2e3b4649e0161015e4b7dfc4c9813afbcda2a92b72b82b92b761028fc0`
- Source version: `1.7.8`
- Release version: `1.7.9`

## 2. Цель и критерии приемки

После этой итерации model quality gate должен вычислять multiclass log loss в том же порядке `TP / SL / TIMEOUT`, в котором model artifact возвращает probability columns.

Критерии:

1. Вероятность истинного класса выбирается по `model.classes_`, а не по лексикографической сортировке.
2. Идеально упорядоченная toy-модель с `p_true=0.90` получает `-ln(0.90)`.
3. Невалидная probability matrix блокируется явным `ValueError`.
4. Metrics содержат raw/calibrated и prior/uniform diagnostics.
5. Quality-gate threshold/config не ослабляются.
6. Migration и новые `.env` variables не требуются.
7. Полный unit suite не регрессирует.

## 3. Изменяемый поток

```text
model.predict_proba(final holdout)
→ declared model.classes_ mapping
→ class-order-safe log loss
→ classification/policy metrics
→ absolute and incumbent-relative quality gate
→ registry candidate decision
```

Прочитаны `README.md`, `docs/MODEL_CARD.md`, `docs/ARCHITECTURE.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/OPERATOR_MANUAL.md`, `app/ml/training.py`, `app/ml/lifecycle.py` и соответствующие tests.

## 4. Baseline

Isolated environment создан из `.[dev]` на Python 3.13.5.

| Команда | Результат |
|---|---|
| `python -m pip check` | PASSED — No broken requirements found |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 129 passed, 3 skipped, 20 warnings |
| `python -m pytest -q tests/unit/test_training.py` | PASSED — 4 passed |

Host environment отдельно имел внешний MoviePy/Pillow conflict и не использовался как project oracle.

## 5. Подтвержденный дефект

**Severity:** high, поскольку ошибочная classification metric непосредственно блокировала auto-activation и оставляла систему на deterministic baseline при отсутствующем trained active artifact.

`TemporalCalibratedBarrierModel.classes_` имеет порядок:

```text
TP, SL, TIMEOUT
```

`evaluate_model()` до исправления вызывал:

```python
log_loss(y, probabilities, labels=list(model.classes_))
```

Текущая поддерживаемая версия scikit-learn предупредила, что labels предполагаются лексикографически упорядоченными. Regression fixture с тремя правильными прогнозами вернула:

```text
actual:   2.995732273553991
expected: 0.10536051565782628
```

Другие метрики уже использовали собственный `class_to_index`, поэтому Brier/ECE/AUC не имели той же перестановки. Это объясняет наблюдавшуюся комбинацию нормальных Brier/ECE и аномально плохого log loss.

## 6. Red → green

Команда:

```text
python -m pytest -q tests/unit/test_training.py -k log_loss_respects_declared_probability_order
```

RED:

```text
1 failed
obtained 2.995732273553991
expected 0.10536051565782628
```

GREEN:

```text
1 passed
```

Полный `tests/unit/test_training.py` после изменения: `6 passed`.

## 7. Реализация

### Production

- `app/ml/training.py`
  - удалена зависимость расчета от `sklearn.metrics.log_loss`;
  - добавлен `_ordered_multiclass_log_loss()` с fail-closed validation;
  - добавлен training class-prior benchmark;
  - сохранены raw/calibrated log loss и calibration improvement;
  - добавлен metric schema marker.

### Tests

- `tests/unit/test_training.py`
  - regression test проверяет non-lexicographic artifact class order;
  - отдельно проверяет raw/calibrated diagnostics и prior/uniform benchmarks.

### Documentation/version

- version `1.7.9` в `pyproject.toml` и `app/__init__.py`;
- обновлены README, architecture, model card, operator manual, QA, compliance и traceability;
- root directory по требованию пользователя по-прежнему содержит только `README.md` среди Markdown-файлов.

## 8. Compatibility

- DB schema: unchanged.
- Alembic head: unchanged, `0005_plan_outcome_invalid_input`.
- API: unchanged.
- Environment: unchanged.
- Artifact class order: unchanged.
- Existing registry metrics: immutable historical values, автоматически не пересчитываются.

## 9. Post-check

| Команда | Результат |
|---|---|
| `python -m pip check` | PASSED — No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 131 passed, 3 skipped, 20 warnings |
| `python -m pytest -q tests/unit/test_training.py` | PASSED — 6 passed |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | PASSED — `0005_plan_outcome_invalid_input` |

## 10. Непроверенное

- Реальная пользовательская PostgreSQL database и artifacts не были доступны в среде сборки.
- Значение исправленного log loss для `barrier-hist_gradient_boosting-h8-20260628T132920Z` здесь не пересчитано.
- PostgreSQL integration suite с `--require-integration` не запускался без отдельной test database.

## 11. Остаточные риски

- Старые candidate rows продолжают показывать исторически ошибочный `log_loss`.
- Исправленный log loss может пройти absolute threshold, но candidate все равно может быть отклонен другими ML/policy/relative gates.
- Положительный class-prior skill не является доказательством торговой прибыльности.

## 12. Rollback

1. Остановить API/worker/trainer.
2. Вернуть source files версии 1.7.8.
3. Перезапустить процессы.
4. Migration rollback не требуется.

Rollback возвращает прежний ошибочный расчет log loss и поэтому не рекомендуется для model promotion.

## 13. Следующий рекомендуемый work package

Добавить read-only CLI повторной оценки существующего registered artifact на воспроизводимом final holdout с отдельным audit report, без автоматической activation. Это позволит исследовать уже созданные artifacts без полного fitting, но требует точного dataset snapshot/lineage contract и не включено в текущую итерацию.

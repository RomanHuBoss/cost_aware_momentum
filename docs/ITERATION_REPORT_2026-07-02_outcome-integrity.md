# Iteration report — outcome integrity — 2026-07-02

## 1. Входной архив и baseline identity

- Input: `cost_aware_momentum-main.zip`
- SHA-256: `8063d87fc2d769b0505cba80cf33353ebea928a5dd335de84d2dad8455addb6f`
- Исходная версия: `1.8.29`
- Python: `>=3.12`; isolated audit runtime: Python 3.13.5
- Исходный Alembic head: `0007_position_account_scope`
- Исходный full suite: 401 passed, 4 skipped, 19 warnings

## 2. Цель и критерии приемки

После этой итерации контрфактические plan outcomes и promotion metrics не должны использовать временно невозможный price path или взаимно погашать отдельные прибыли/убытки, что подтверждается red→green regression tests и полным suite.

Критерии:

1. Plan с `planning_time > signal.event_time` не получает денежный P&L/R из signal path.
2. ORM/DB contract поддерживает append-only status `PATH_UNAVAILABLE`.
3. Existing late-plan rows исправляются migration, а не остаются недостоверными.
4. Profit factor сохраняет gross gains/losses до exit-time netting.
5. Funding anchor advancement имеет O(1) по числу пропущенных settlements.
6. Instrument spec соблюдает point-in-time receipt cutoff.
7. UI не показывает placeholder zero как рассчитанный P&L.
8. Полный suite и release boundaries не регрессируют.

## 3. Прочитанные источники и data flow

Прочитаны README, pyproject, архитектура, QA, compliance, traceability, model card, configuration, security, incident runbook, operator manual, предыдущие iteration reports, исходная DOCX specification и релевантные production/tests/migrations.

Изменяемые потоки:

- `signal.event_time → confirmed candle path → SignalOutcome → ExecutionPlan snapshot → PlanOutcome → API serializer → UI`;
- `holdout trades → weighted trade contributions → exit-time equity buckets / gross gain-loss → profit factor → quality gate`;
- `funding anchor + interval → projected settlements → risk/economics`;
- `instrument spec valid_from + received_at → execution cutoff → plan validation`.

## 4. Baseline до правок

Изолированный baseline:

- pip check: passed;
- compileall: passed;
- Ruff: passed;
- pytest: 401 passed, 4 skipped, 19 warnings;
- frontend syntax: passed;
- Alembic: one head `0007_position_account_scope`.

`doctor` и PostgreSQL integration не запускались из-за отсутствия безопасной отдельной БД и локальной конфигурации. Глобальная Python-среда была исключена из evidence из-за постороннего Pillow/MoviePy conflict, отсутствующего Ruff и `psycopg`.

## 5. Доказанные defects/gap

### HIGH — retroactive late-plan valuation

- Path: `app/services/outcomes.py::_record_plan_outcome`.
- Фактическое поведение: plan с entry/planning time позже signal event использовал уже разрешённый `SignalOutcome`, включая движение цены до существования plan.
- Минимальный пример: signal 00:00, plan 00:30, signal TP at 02:00; исходный код записывал `VALUED` и P&L от entry 101 до exit 104, не проверяя, был ли TP/SL раньше 00:30.
- Ожидаемое: без exact path от 00:30 денежная оценка недоказуема.
- Почему тесты не ловили: существующий test прямо закреплял поздний `planning_time` как допустимый для расчёта.

### HIGH — profit factor after exit-time netting

- Path: `app/ml/training.py::evaluate_policy_model`.
- Фактическое поведение: individual contributions сначала суммировались по `exit_time`; +0.5R и -0.5R давали bucket 0, gross gain/loss 0/0 и missing PF.
- Ожидаемое: стандартный PF = сумма положительных отдельных результатов / абсолютная сумма отрицательных; в примере PF=1.
- Влияние: false pass/fail promotion evidence и неверная эконометрическая интерпретация.

### MEDIUM — unbounded funding-anchor loop

- Path: `app/risk/math.py::projected_funding_rate`.
- Фактическое поведение: `while next_settlement <= start_time` выполнял по шагу на каждый пропущенный interval.
- Влияние: старый timestamp при минутном interval мог надолго заблокировать worker.

### MEDIUM — missing spec receipt cutoff

- Path: `app/services/execution.py::latest_spec`.
- Фактическое поведение: фильтр только `valid_from <= cutoff`, без `received_at <= cutoff`.
- Влияние: historical/point-in-time execution validation могла использовать будущую по доступности строку.

### MEDIUM — release provenance gap

`CHANGELOG.md`, `PATCH_*.md`, `SHA256SUMS` отсутствовали, несмотря на противоположное утверждение QA 1.8.29.

## 6. План и фактический diff

Production:

- `app/services/outcomes.py` — temporal anchor validation и `PATH_UNAVAILABLE`;
- `app/db/models.py` — ORM constraint;
- `app/ml/training.py` — PF по individual contributions, schema v6;
- `app/risk/math.py` — arithmetic funding advancement;
- `app/services/execution.py` — receipt cutoff и deterministic ordering;
- `web/js/app.js` — status label и suppression недостоверного P&L;
- `app/__init__.py`, `pyproject.toml` — 1.8.30.

Migration:

- `migrations/versions/0008_plan_outcome_path_unavailable.py` — constraint, historical backfill, fail-closed downgrade.

Tests:

- новый `tests/unit/test_quant_outcome_integrity_2026_07_02.py`;
- corrected aligned-anchor expectation in `test_counterfactual_outcomes.py`;
- PostgreSQL constraint expectation and policy-schema fixtures updated.

Docs/release:

- README, architecture, model card, config, operator manual, security, incident runbook, compliance, traceability, QA;
- `CHANGELOG.md`, `PATCH_1.8.30.md`, this report and regenerated `SHA256SUMS`.

## 7. Red → green

На неизменённой 1.8.29 пять первоначальных tests завершились `5 failed` по ожидаемым причинам: `VALUED` вместо `PATH_UNAVAILABLE`, отсутствующий constraint status, PF 0/0 вместо 0.5/0.5, settlement-by-settlement loop и отсутствующий SQL receipt cutoff.

После исправления:

- dedicated module: 6 passed;
- outcome regression group: 28 passed;
- full suite: 407 passed, 4 skipped, 19 warnings.

Тестовые expected values выведены независимо: PF example использует +0.5/-0.5 weighted contributions, funding example — 480 settlements × 0.0001 = 0.048.

## 8. Migration/API/config compatibility

- New head: `0008_plan_outcome_path_unavailable`.
- Upgrade adds status then backfills late plans to zero financial values plus diagnostics.
- Downgrade refuses to continue while such rows exist; silent restoration of false P&L запрещена.
- API shape unchanged; enum-like string adds `PATH_UNAVAILABLE`.
- No new dependencies or environment variables.
- Policy metric schema v6 intentionally invalidates v5 promotion evidence; retraining/re-evaluation is required.

## 9. Post-check

- pip check: passed;
- compileall: passed;
- Ruff: passed;
- pytest: 407 passed, 4 skipped, 19 warnings;
- dedicated module: 6 passed;
- node syntax: passed;
- Alembic: one head `0008_plan_outcome_path_unavailable`;
- static advisory-only/PostgreSQL boundary scan: passed.

Release tree check: PASSED — 156 files checked, 156 manifest entries. Test/build environments are excluded.

## 10. Не проверено

- Migration upgrade/backfill/downgrade на отдельной PostgreSQL;
- `manage.py doctor`;
- integration suite with `--require-integration`;
- live Bybit read-only responses;
- paper/shadow forward performance, slippage realism and profitability.

## 11. Остаточные риски

- `PATH_UNAVAILABLE` is an honest gap: exact late-plan economics requires persisted entry-aligned intrabar data.
- Corrupted historical JSON timestamp can intentionally stop migration rather than be guessed.
- Profit-factor correction changes model promotion comparisons; v5 and v6 evidence must not be mixed.
- Technical correctness does not establish positive expected return.

## 12. Rollback

1. Stop API/worker/trainer.
2. Restore pre-upgrade PostgreSQL backup for a full rollback.
3. Code-only rollback without DB restore is unsafe after backfilled `PATH_UNAVAILABLE` rows.
4. Alembic downgrade is allowed only after explicit remediation/removal of `PATH_UNAVAILABLE` rows; it otherwise raises an exception.
5. Reinstall/restart 1.8.29 only after schema and data are consistent.

## 13. Рекомендуемый следующий work package

Добавить immutable entry-aligned intrabar path snapshots для каждой plan version и независимо вычислять её TP/SL/TIMEOUT от `planning_time`, включая point-in-time availability and no-fill semantics. Это отдельная функция и не реализована скрытно в текущем patch.

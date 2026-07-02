# Iteration report — 2026-07-02 — training gate feasibility

## 1. Входной архив

- Input: `cost_aware_momentum-main.zip`.
- SHA-256: `a2b44aac0985a86bb3fdf45d53c1fc7813b26170873d80d4afe4b8565f1d7c89`.
- Исходная версия: 1.8.34.
- Python: `>=3.12`; фактический test runtime: 3.13.5.
- Alembic: revisions `0001`–`0008`, один head `0008_outcome_path_unavailable`.

## 2. Цель и критерии приемки

После этой итерации trainer не должен запускать candidate до момента, когда configured temporal split и final-holdout gates хотя бы математически достижимы, а auto-activation не должна пропускать модель без положительного information skill относительно class-prior baseline.

Критерии:

1. Минимальная история выводится из фактических feature/split/gate semantics, а не из несвязанной константы.
2. При defaults 900 timestamps блокируются, required value равно 1206.
3. Operator diagnostics содержит фактические/требуемые timestamps, holdout rows/span и horizon.
4. Отрицательный, нулевой, missing/non-finite или внутренне несогласованный prior skill блокирует promotion.
5. Incumbent, advisory-only, PostgreSQL-only, process separation и risk gates не изменяются.
6. Новые regression tests проходят отдельно и в полном suite.
7. Release tree содержит changelog, patch note, report и checksum manifest.

## 3. Прочитанные источники и data flow

Прочитаны README, pyproject, `.env.example`, architecture, QA, compliance, traceability, model card, configuration, security, incident/operator docs, предыдущие iteration reports, исходная DOCX specification, ML/risk/signal/execution/trainer modules, tests и migration graph.

Изменяемый flow:

`confirmed PostgreSQL hourly candles → TrainingDataProfile → BackgroundTrainer.due_reason → make_barrier_dataset → chronological_split → evaluate_model/evaluate_policy_model → evaluate_quality_gate → immutable registry candidate → guarded activation`.

Параллельно проверены directional/cost/risk invariants. Нового доказуемого LONG/SHORT sign error, leverage-to-edge error или fee double-count в изменяемом пути не найдено. Historical orderbook/fills/funding/operator-latency realism остаётся documented limitation, а не считался исправленным.

## 4. Baseline

В чистом внешнем virtualenv:

- `python --version`: 3.13.5.
- `python -m pip check`: PASSED.
- `python -m compileall -q app scripts tests manage.py`: PASSED.
- `python -m ruff check .`: PASSED.
- `python -m pytest -q`: **420 passed, 4 skipped, 19 warnings**.
- `node --check web/js/app.js`: PASSED.
- `alembic heads`: `0008_outcome_path_unavailable`.

System Python имел внешние dependency defects и не использовался как project result. `manage.py doctor`/required integration не завершены без штатной local `.venv`, `.env` и отдельной test PostgreSQL.

## 5. Defects и доказательства

### D1 — CONFIRMED DEFECT / HIGH / operational + model lifecycle

- Файл: `app/workers/trainer.py`, `BackgroundTrainer.due_reason`.
- Было: `minimum_bootstrap = 300 + default_horizon_hours + 72`, то есть 380.
- Фактическая математика: 24-hour warm-up + horizon labels; split boundaries 70%/85%; train/cal label purge; horizon embargo перед final holdout; configured holdout span 168h.
- Независимый пример: 900 непрерывных raw timestamps → 868 labeled timestamps → 123 final-holdout decision timestamps → span 122h. Candidate не может пройти 168h gate.
- Влияние: лишний fit, неизбежный rejection, cooldown/wait, misleading operator state.
- Почему тесты не поймали: scheduling fixture использовал 900 timestamps и не связывал preflight с split/gate semantics.

### D2 — CONFIRMED DEFECT / HIGH / econometric + activation safety

- Файлы: `app/ml/training.py::evaluate_model`, `app/ml/lifecycle.py::evaluate_quality_gate`.
- Было: skill вычислялся, но gate проверял только absolute log loss/Brier/ECE и policy metrics.
- Минимальный пример: `log_loss=1.07`, `class_prior_log_loss=1.05`, `skill=-0.02`; при absolute max 1.20 старый gate мог вернуть passed.
- Влияние: auto-activation допускает classifier хуже no-feature class-prior baseline.
- Почему тесты не поймали: tests проверяли правильность расчёта skill, но не его использование в gate.

### D3 — CONFIRMED DEFECT / MEDIUM / release integrity

Входной archive не содержал `CHANGELOG.md`, `PATCH_*.md`, `SHA256SUMS`, хотя QA/traceability утверждали обратное.

## 6. План и фактический diff

Production:

- `app/ml/training.py`: theoretical-history calculator.
- `app/workers/trainer.py`: fail-closed preflight and diagnostics.
- `app/ml/lifecycle.py`: prior-skill gate and diagnostics.
- `app/__init__.py`, `pyproject.toml`: version 1.8.35.

Tests:

- scheduling regression for impossible holdout;
- promotion regression for negative prior skill;
- passing metric fixtures updated to include independently consistent prior/skill evidence.

Docs/release:

- README, changelog, patch note, QA, configuration, model card, operator, security, architecture, compliance, traceability and this report.
- `SHA256SUMS` generated only after final tree cleanup.

Migrations/API/env:

- DB migration: none.
- New environment variables: none.
- External API schema: unchanged.
- Job/gate diagnostics: expanded backward-compatibly.

## 7. Red → green evidence

Command:

```text
python -m pytest -q \
  tests/unit/test_trainer_recovery_scheduling.py::test_bootstrap_waits_until_configured_holdout_span_is_mathematically_possible \
  tests/unit/test_training_evidence_integrity_2026_07_02.py::test_quality_gate_rejects_model_without_skill_over_class_prior
```

Red before production change:

- 2 failed.
- First failure: expected `due is False`, actual `True`.
- Second failure: expected gate `passed is False`, actual `True`.

Green after production change:

- 2 passed.
- Related focused suite: 96 passed.

## 8. Совместимость и rollback

Нет schema migration и config migration. Active incumbent остаётся активным при failed candidate. Для rollback остановить API/worker/trainer, восстановить 1.8.34 source tree и перезапустить; PostgreSQL rollback не требуется. Candidates, отклонённые 1.8.35, не следует вручную активировать без review.

## 9. Post-check

- `python -m pip check`: PASSED.
- `python -m compileall -q app scripts tests manage.py`: PASSED.
- `python -m ruff check .`: PASSED.
- `python -m pytest -q`: **422 passed, 4 skipped, 19 warnings**.
- `node --check web/js/app.js`: PASSED.
- Alembic single head: PASSED.
- Release manifest/check: PASSED on cleaned tree, 164 eligible files and 164 manifest entries.
- ZIP integrity and clean re-extraction are verified after this report is finalized and reported to the user.

## 10. Непроверенное

- Real PostgreSQL migration/integration and concurrency tests: отдельная test DB отсутствует.
- `manage.py doctor`: нет штатной local `.venv`, `.env` и DB service.
- Live Bybit/network smoke, реальная candidate registry, signals/plans/fills и forward P&L: данные/credentials не предоставлены.
- Exact historical operator latency, orderbook/no-fill/partial-fill and funding settlement: остаются partial.

## 11. Остаточные риски

1206 — theoretical minimum для непрерывной валидной hourly series при текущих defaults. Гэпы, invalid bars, class collapse, symbol/regime concentration и слабая policy economics могут требовать больше истории. Positive prior skill также не доказывает торговое преимущество после costs.

## 12. Следующий рекомендуемый work package

Добавить execution-latency-aware walk-forward evidence на point-in-time 5-minute data: вход после фактической publication/operator delay, no-fill/entry-zone handling, funding settlement timeline и per-regime/symbol rejection dossier. До этого текущий hourly backtest нельзя трактовать как доказательство live profitability.

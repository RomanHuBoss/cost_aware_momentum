# Iteration report — experiment overfitting governance

## 1. Input and baseline

- Input: `cost_aware_momentum-1.17.0-production-drift-monitoring(1).zip`
- SHA-256: `9c779cac82da74377c6d428dd76346c3d52946bcc15aca56af5844d9f322773c`
- Source version: 1.17.0
- Source Alembic head: `0011_selection_experiment`
- Baseline: 540 passed, 4 skipped; pip check, compileall, Ruff and frontend syntax passed in an isolated project environment.

## 2. Goal and acceptance criteria

After this iteration, every prospective validated research backtest evaluation must disclose its immutable configuration before results, append a terminal success/failure event, and expose comparable period returns so a family-level report can calculate PBO and DSR or block on incomplete evidence.

Acceptance criteria:

1. STARTED is committed before evaluation and configuration cannot change.
2. Exactly one terminal SUCCEEDED/FAILED event is appendable per trial.
3. Hash mutation or chain break is detected.
4. Successful trials contain aligned hourly period returns including zero-return hours.
5. Repeated identical configurations do not inflate the unique trial count.
6. CSCV/PBO and DSR are independently tested.
7. Open/failed/missing/unmatched evidence blocks the report.
8. Governance cannot mutate model lifecycle or claim profitability.

## 3. Sources and data flow

Read: README, changelog, recent patches, architecture, QA, compliance, traceability, model card, configuration, security, incident runbook, operator manual, backtest, model registry and existing migrations/tests.

Data flow: artifact + final-test dataset → sanitized configuration/family → STARTED event → prediction/policy backtest → aligned hourly sleeve returns → SUCCEEDED/FAILED event → verified family matrix → PBO/DSR report.

Methodology follows the combinatorially symmetric cross-validation definition of Probability of Backtest Overfitting and the Deflated Sharpe framework. The implementation uses contiguous segments and non-annualized period Sharpe.

## 4. Confirmed defect/gap

### CONFIRMED GAP — high

Files: prior `scripts/backtest.py`, `research.backtest_runs`, `docs/SPEC_COMPLIANCE.md`.

Expected: selection-aware experiment history must disclose all tried alternatives and provide aligned return paths for multiple-testing diagnostics.

Actual: backtest runs stored final summaries only. There was no pre-result trial event, no family-level completeness contract, no PBO and no DSR. Failed or abandoned variants could not be distinguished from variants never tried.

Impact: a selected high Sharpe could be presented without quantifying search breadth or the probability that in-sample selection fails out of sample. Existing walk-forward evidence did not solve cross-configuration selection bias.

Why tests missed it: no experiment-family contract or overfitting-governance module existed.

## 5. Change plan and actual diff

Production/research files:

- `app/research/overfitting.py` — PBO, DSR, effective trial count and family analysis.
- `app/services/experiment_ledger.py` — canonical hashes, append-only trial events and report assembly.
- `app/db/models.py` — `ResearchExperimentEvent`.
- `scripts/backtest.py` — prospective events and aligned hourly return evidence.
- `scripts/experiment_report.py`, `manage.py`, `pyproject.toml` — CLI integration.
- `app/config.py`, `.env.example` — fail-closed governance thresholds.
- `migrations/versions/0012_experiment_selection.py` — PostgreSQL table/indexes.
- tests and affected documentation/version files.

## 6. Red → green evidence

Command on untouched source with the new test module:

```bash
python -m pytest -q tests/unit/test_experiment_overfitting_governance_2026_07_05.py
```

Red: collection failed with `ModuleNotFoundError: No module named 'app.research.overfitting'`.

Green: focused tests passed after implementation; full suite changed from 540 passed/4 skipped to 550 passed/4 skipped.

## 7. Compatibility

- Version: 1.18.0 minor release.
- Migration required: `0012_experiment_selection`.
- New `.env` names: five `EXPERIMENT_*` governance parameters.
- Public API and frontend schema unchanged.
- Active model artifact and training schema unchanged; retraining is not required.
- Advisory-only and PostgreSQL-only boundaries preserved.

## 8. Post-check

- Dependency check: PASSED.
- Compileall: PASSED.
- Ruff: PASSED.
- Pytest: 550 passed, 4 skipped, 61 warnings.
- Frontend syntax: PASSED.
- Alembic: single head `0012_experiment_selection`.
- Clean release manifest: 211/211 files.
- Freshly extracted ZIP: manifest 211/211 and full suite 550 passed/4 skipped.

## 9. Not verified

- PostgreSQL integration and migration upgrade/downgrade were not run without an isolated `TEST_DATABASE_URL`.
- No production-history experiment family was executed.
- No numerical claim about the strategy's actual PBO, DSR or profitability is made.

## 10. Residual risks and limitations

- Evidence is prospective from 1.18.0; prior search history cannot be reconstructed honestly.
- A hard-killed process can leave an open STARTED trial; fail-closed reporting requires explicit resolution.
- Researchers can still define families too narrowly or perform unlogged exploration elsewhere.
- Hourly returns are serially dependent; current DSR does not provide HAC/bootstrap correction.
- Correlation-based effective trial count is an approximation.
- CSCV segment choice and minimum sample thresholds affect stability.
- READY is research governance evidence, not live-performance proof or automatic promotion.

## 11. Rollback

1. Stop research/backtest processes.
2. Export `research.experiment_events` if evidence must be retained.
3. Downgrade Alembic to `0011_selection_experiment`.
4. Restore 1.17.0 sources and remove unused `EXPERIMENT_*` variables if desired.
5. Do not present deleted 1.18 evidence as if it never existed.

## 12. Recommended next package

Add cluster-/dependence-aware uncertainty for experiment and operator-selection reports: stationary/block bootstrap or HAC confidence intervals, explicit family pre-registration metadata and audit of externally attempted configurations. This should remain separate from automatic model activation.

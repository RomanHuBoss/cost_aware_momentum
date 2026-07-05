# Iteration report — cost-stress promotion gate

## 1. Input and identification

- Input archive: `cost_aware_momentum-main.zip`
- Input SHA-256: `1ef3ca05de319366abc9db5fc207b59d8814f54d1728016ab6f4b7fd9a9ed3ab`
- Source release: 1.26.6; target release: 1.26.7
- Python requirement: >=3.12; tested with 3.13.5
- Inventory before changes: 223 files; 73 app, 83 tests, 9 docs; 14 Alembic revisions; single head `0014_ui_exposure_ledger`
- Input release contained no `.env`, credentials, virtual environment, model artifact or database dump. Generated caches/egg-info were excluded from the output.

## 2. Goal and acceptance criteria

After this iteration, normal model promotion must require aligned hourly ×1.5 and ×2 cost-stress evidence for the selected preregistered trial and reject a negative terminal stressed capital return.

Acceptance criteria:

1. Backtest emits both stress paths on the exact nominal timestamps.
2. Each path reconciles terminal return and maximum drawdown.
3. Missing/malformed stress evidence fails closed.
4. Selected trial with either terminal stress return <0 is not `READY`.
5. Old persisted promotion gate cannot bypass the new requirement.
6. Advisory-only, PostgreSQL-only and existing recommendation thresholds remain unchanged.
7. Full available unit/static suite remains green.

## 3. Sources and data flow

Read: `README.md`, `CHANGELOG.md`, patches 1.26.3–1.26.6, `pyproject.toml`, `.env.example`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, the embedded DOCX specification, and relevant backtest/research/ledger/promotion modules and tests. The repository does not contain the architecture/security/operator documents named generically in the master prompt; they were not invented.

Changed flow:

`policy_backtest` trade/path economics → nominal plus ×1.5/×2 hourly capital paths → append-only `SUCCEEDED` event → strict ledger parser → selected-trial governance → persisted promotion gate → activation validation.

## 4. Baseline

Isolated environment `/mnt/data/cam_venv`:

- `python --version`: PASSED, 3.13.5
- `python -m pip check`: PASSED
- `python -m compileall -q app scripts tests manage.py`: PASSED
- `python -m ruff check .`: PASSED
- `python -m pytest -q`: PASSED, 622 passed / 4 skipped / 62 warnings
- `node --check web/js/app.js`: PASSED

Global Python was not used as the authority because `ruff`/`psycopg` were absent and unrelated MoviePy/Pillow packages conflicted.

## 5. Confirmed gap

**CONFIRMED GAP — high.** `scripts/backtest.py::policy_backtest` exposed terminal ×1.5/×2 totals, but `experiment_evidence` and `app/services/experiment_ledger.py::_trial_evidence_from_success` contained only nominal period returns. `app/research/overfitting.py::analyze_experiment_family` could therefore return `READY` without stress evidence. Existing tests checked the diagnostic totals but not their governance use.

Impact: a model configuration could pass PBO/DSR/dependence checks and normal promotion despite loss of sign under modest mandatory cost stress. This can contribute to paper/live disappointment when fee/slippage assumptions are optimistic. It does not by itself explain recommendation rarity; loosening gates without attrition/forward evidence would be unsafe.

## 6. Plan and actual diff

Production:

- `scripts/backtest.py`: scenario-specific terminal and cumulative MTM paths; event/report evidence.
- `app/services/experiment_ledger.py`: strict cost-stress schema, alignment and reconciliation validation.
- `app/research/overfitting.py`: selected-trial stress statistics and `REJECTED_COST_STRESS`.
- `app/services/model_promotion.py`: report v4/gate v3, persisted stress validation, legacy-gate rejection.
- `app/__init__.py`, `pyproject.toml`: version 1.26.7.

Tests:

- `test_experiment_observed_period_path_2026_07_05.py`
- `test_experiment_overfitting_governance_2026_07_05.py`
- `test_experiment_bound_model_promotion_2026_07_05.py`
- `test_experiment_policy_binding_2026_07_05.py`
- `test_atomic_model_promotion.py`
- `test_dependence_aware_inference_2026_07_05.py`

Docs/release: README, CHANGELOG, patch, QA, compliance, traceability, this report and regenerated `SHA256SUMS`. No migration or environment-variable change.

## 7. Red → green evidence

Command:

```text
python -m pytest -q \
  tests/unit/test_experiment_observed_period_path_2026_07_05.py::test_experiment_evidence_carries_aligned_cost_stress_paths \
  tests/unit/test_experiment_observed_period_path_2026_07_05.py::test_success_event_without_cost_stress_evidence_is_rejected
```

Before implementation: 2 failed — `KeyError: cost_stress` and `DID NOT RAISE ValueError`.
After implementation: 2 passed.

Additional green coverage proves independent stress arithmetic, negative-stress rejection, missing READY evidence rejection and legacy gate v2 rejection.

## 8. Compatibility

- Migration: none; Alembic head remains `0014_ui_exposure_ledger`.
- HTTP API: unchanged.
- `.env`: unchanged.
- Model feature/label/runtime artifact schema: unchanged.
- Active model: not deactivated.
- Existing successful experiment events without cost-stress v1 cannot authorize new normal promotion; rerun their preregistered backtests.
- Existing persisted promotion gate v2 is intentionally invalid for new activation.

## 9. Post-check

- `python -m pip check`: PASSED
- `python -m compileall -q app scripts tests manage.py`: PASSED
- `python -m ruff check .`: PASSED
- `python -m pytest -q`: PASSED, 627 passed / 4 skipped / 62 warnings
- `node --check web/js/app.js`: PASSED
- `alembic heads`: PASSED, single head `0014_ui_exposure_ledger`
- `sha256sum -c SHA256SUMS`: PASSED, 224 release files
- `unzip -t` and clean re-extraction: PASSED, one root directory and no forbidden artifacts

## 10. Not verified

- `manage.py doctor`: environment FAILED because `.env`, production secrets, PostgreSQL tools and server are absent.
- PostgreSQL integration: NOT RUN because `POSTGRES_ADMIN_URL`/`TEST_DATABASE_URL` is unset.
- No live Bybit, forward profitability or recommendation-frequency evidence was available.

## 11. Residual risks

- Fixed multipliers do not represent nonlinear market impact, queue/partial fills, latency or dynamic fees.
- Hourly closes do not reconstruct sub-hour adverse paths.
- A non-negative stressed total is a minimum sign check, not evidence of attractive risk-adjusted return.
- Sparse recommendations should be diagnosed from `candidate/live recommendation attrition` reports and mature outcomes before changing any gate.

## 12. Rollback

1. Stop API/inference/trainer processes.
2. Restore the 1.26.6 source archive; no database downgrade is required.
3. Do not reuse a v3 promotion gate in 1.26.6 code.
4. Be aware that rollback restores the gap where normal promotion ignores cost-stress paths.

## 13. Recommended next work package

Use prospective attrition evidence to quantify the dominant cause of rare recommendations by stage (data/model/direction economics/execution/risk), then select one measured bottleneck. Do not lower thresholds until forward outcomes show that the blocked cohort has positive net value.

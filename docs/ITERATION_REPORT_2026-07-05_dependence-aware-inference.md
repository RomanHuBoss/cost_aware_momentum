# Iteration report — 2026-07-05 — dependence-aware inference

## 1. Input archive and source release

- Input: `cost_aware_momentum-1.18.0-experiment-overfitting-governance(1).zip`
- Input SHA-256: `605887261acc2b38e88a31f6ff2d06a84ca7902e9028c1482328f1721f0d6e9c`
- Input size: 670203 bytes
- Source version: 1.18.0
- Source Alembic head: `0012_experiment_selection`

## 2. Iteration objective and acceptance criteria

Objective:

> After this iteration, experiment-selection and operator-selection reports must explicitly account for serial and within-signal dependence, and must fail closed when the number of independent temporal blocks or signal clusters is insufficient.

Acceptance criteria:

1. Experiment DSR uses a conservative HAC-implied effective observation count rather than nominal hourly rows.
2. Selected experiment returns receive deterministic moving-block confidence intervals for mean and non-annualized Sharpe.
3. Experiment block length cannot be shorter than the declared trading horizon; mixed horizons in one explicit family are blocked.
4. `READY` additionally requires positive lower dependence-aware confidence bounds.
5. All plan versions of one signal remain in one chronological propensity cluster and cannot be split between training and OOS scoring.
6. Operator-selection estimates receive signal-cluster moving-block intervals; insufficient clusters block the corrected report.
7. No model lifecycle, risk, execution, advisory-only or automatic activation behavior changes.
8. Full unit/static suite remains green and the final archive is clean and reproducible.

## 3. Sources read and affected data flow

Read before modification:

- `README.md`, `CHANGELOG.md`, `PATCH_1.16.0.md`–`PATCH_1.18.0.md`;
- `pyproject.toml`, `.env.example`;
- `docs/ARCHITECTURE.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- `docs/MODEL_CARD.md`, `docs/CONFIGURATION.md`, `docs/SECURITY.md`, `docs/INCIDENT_RUNBOOK.md`, `docs/OPERATOR_MANUAL.md`;
- `app/research/overfitting.py`, `app/research/selection_bias.py`;
- `app/services/experiment_ledger.py`, `app/services/selection_experiments.py`;
- experiment/selection CLI and tests.

Affected experiment flow:

`append-only experiment ledger → aligned periodic return matrix → selected configuration → Newey–West/HAC effective observations + horizon-floored moving-block bootstrap → PBO/DSR classification → JSON report`

Affected operator-selection flow:

`immutable selection ledger + decisions + resolved counterfactual outcomes → signal-cluster chronological OOS propensity scoring → overlap/ESS checks → signal-cluster moving-block bootstrap → diagnostic JSON report`

## 4. Baseline before modification

Commands executed from the untouched source in an isolated project environment:

| Command | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | no syntax errors |
| `python -m ruff check .` | PASSED | no findings |
| `python -m pytest -q` | PASSED | 550 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED | valid syntax |
| `python -m alembic heads` | PASSED | one head: `0012_experiment_selection` |

`python manage.py test --require-integration` was not run because no isolated `TEST_DATABASE_URL` was supplied. No production database was accessed.

## 5. Confirmed defects and gaps

### 5.1 Nominal DSR sample size under serial dependence

- Classification: **CONFIRMED DEFECT**
- Severity: high
- Location: `app/research/overfitting.py::deflated_sharpe_ratio`
- Previous behavior: DSR used `sqrt(n - 1)` with nominal hourly observation count.
- Expected behavior: effective evidence must decrease when returns are positively serially dependent.
- Impact: understated uncertainty and potentially optimistic experiment-family classification.
- Why tests missed it: prior tests validated the IID formula only and supplied no autocorrelated sequence.

### 5.2 No dependence-aware confidence intervals

- Classification: **CONFIRMED GAP**
- Severity: high
- Locations: experiment and operator-selection reports.
- Previous behavior: point estimates, PBO/DSR probability and IPSW diagnostics were emitted without HAC/block-bootstrap intervals.
- Impact: reports could appear more precise than supported by independent temporal evidence.

### 5.3 Signal versions could cross propensity train/OOS boundaries

- Classification: **CONFIRMED DEFECT**
- Severity: high
- Location: `app/research/selection_bias.py` chronological scorer.
- Previous behavior: split boundaries were row-based; multiple plan versions of one signal could land on opposite sides.
- Expected behavior: `signal_id` is the dependence cluster and must be atomic.
- Impact: information from nearly identical plan versions could leak across OOS evaluation boundaries.

### 5.4 Operator observations treated as independent rows

- Classification: **CONFIRMED GAP**
- Severity: medium/high
- Previous behavior: several plan versions of one signal contributed as separate observations without clustered uncertainty.
- Impact: narrow apparent uncertainty and inflated effective evidence.

### 5.5 Explicit experiment family could mix trading horizons

- Classification: **CONFIRMED DEFECT**
- Severity: medium/high
- Previous behavior: return rows from variants with different horizons could be compared under one explicit family.
- Impact: no single defensible dependence block length and potentially incomparable economic geometry.

## 6. Plan and actual file changes

### Production/research code

- Added `app/research/dependence.py`.
- Updated `app/research/overfitting.py`.
- Updated `app/research/selection_bias.py`.
- Updated `app/services/experiment_ledger.py`.
- Updated `app/services/selection_experiments.py`.
- Updated `scripts/experiment_report.py`.
- Updated `scripts/selection_report.py`.
- Updated `scripts/daily_report.py`.
- Updated `app/config.py`, `.env.example`, `app/__init__.py`, `pyproject.toml`.

### Tests

- Added `tests/unit/test_dependence_aware_inference_2026_07_05.py` with nine tests.

### Documentation

- Added `PATCH_1.19.0.md`.
- Updated `README.md`, `CHANGELOG.md` and affected architecture/configuration/model/operator/security/incident/compliance/traceability/QA documents.
- Added this iteration report.

No ORM model or database migration changed.

## 7. Red → green evidence

The new regression module was copied to untouched 1.18.0 and executed before implementation:

```text
python -m pytest -q tests/unit/test_dependence_aware_inference_2026_07_05.py
```

Red result:

```text
ModuleNotFoundError: No module named 'app.research.dependence'
```

Green result after implementation:

```text
9 passed
```

The tests use independently computed Bartlett-weighted covariance arithmetic and deterministic synthetic clusters rather than the tested functions as their own oracle.

## 8. Implemented mathematics and governance

### 8.1 Bartlett/Newey–West mean inference

The implementation estimates long-run variance from lagged autocovariances with Bartlett weights. It reports the HAC standard error, normal confidence interval and a conservative effective observation count. Negative autocorrelation is not allowed to claim more evidence than the nominal sample.

### 8.2 Moving-block bootstrap

Contiguous blocks are resampled with replacement using a fixed release seed. Reports include percentile intervals for mean return and non-annualized Sharpe. The effective experiment block is:

```text
max(configured block periods, declared trading horizon)
```

Too few complete independent blocks returns `BLOCKED_INSUFFICIENT_DEPENDENCE_EVIDENCE`.

### 8.3 DSR adjustment

DSR retains multiple-trial, skewness and kurtosis adjustments, but uses HAC effective observations for its sampling term. A family cannot become `READY` unless:

- existing PBO and DSR thresholds pass;
- HAC lower mean bound is positive;
- moving-block lower mean bound is positive;
- moving-block lower Sharpe bound is positive.

### 8.4 Signal-cluster operator inference

All rows sharing `signal_id` form one dependence cluster. OOS blocks contain whole clusters; training includes only clusters whose latest timestamp is strictly earlier than the OOS block start. Cluster blocks are then resampled chronologically to construct intervals for:

- all-eligible mean;
- selected-only mean;
- stabilized IPSW mean;
- selected-subset bias.

This remains a diagnostic conditional on fitted OOS propensities, not a causal estimator of operator skill.

## 9. Configuration and compatibility

New settings:

```env
RESEARCH_BOOTSTRAP_REPLICATES=1000
RESEARCH_CONFIDENCE_LEVEL=0.95
EXPERIMENT_DEPENDENCE_BLOCK_PERIODS=8
EXPERIMENT_MIN_INDEPENDENT_BLOCKS=6
SELECTION_DEPENDENCE_BLOCK_CLUSTERS=5
SELECTION_MIN_INDEPENDENT_CLUSTERS=30
```

Validation is fail-closed. Bootstrap replicates must be at least 100, confidence must lie in `(0.5, 1)`, block sizes must be at least two and minimum selection clusters must cover at least two cluster blocks.

Compatibility:

- Database migration: none.
- Expected Alembic head: `0012_experiment_selection`.
- Market-model artifact: unchanged; retraining not required.
- Existing prospective experiment/selection ledger rows remain readable.
- Report schema versions change, so downstream consumers must accept the new JSON contracts.

## 10. Post-change verification

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | no syntax errors |
| `python -m ruff check .` | PASSED | no findings |
| `python -m pytest -q` | PASSED | 559 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED | valid syntax |
| `python -m alembic heads` | PASSED | one head: `0012_experiment_selection` |

Release-stage and fresh-extraction results are recorded in `docs/QA_REPORT.md`.

## 11. What could not be verified

- PostgreSQL integration tests and migration upgrade/downgrade were not run because no isolated test database was supplied.
- No real multi-variant experiment family was accumulated under 1.19.0.
- No real operator-selection window with enough independent signals was evaluated.
- No production profitability, causal operator effect or live-edge conclusion is claimed.

## 12. Residual risks and limitations

- Block length remains a governance assumption; misspecification can under- or overstate uncertainty.
- Percentile bootstrap intervals are not studentized, BCa or block-length optimized.
- Newey–West uses a deterministic bandwidth rule and normal critical values.
- Operator bootstrap conditions on already fitted OOS propensities rather than refitting them in every replicate.
- Hidden operator state, UI exposure and unrecorded external context remain unobserved.
- Pre-1.15 selection opportunities and pre-1.18 experiment attempts cannot be reconstructed honestly.
- A researcher can still define an inappropriately narrow family unless formal preregistration is added.

## 13. Rollback procedure

1. Stop research/report processes.
2. Restore 1.18.0 source code.
3. Restore previous `.env` or remove the six new settings.
4. Do not downgrade PostgreSQL; no schema change occurred.
5. Existing experiment and selection ledgers remain valid.
6. Treat 1.19.0 report JSON as incompatible with the old consumer schema.

## 14. Recommended next work package

Add formal experiment-family preregistration metadata and lifecycle before the first trial, with immutable hypothesis, parameter search space, horizon, primary metric, block policy and stopping rule. This would reduce researcher degrees of freedom that PBO/DSR cannot correct after an overly narrow family has already been chosen.

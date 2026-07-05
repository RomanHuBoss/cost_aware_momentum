# Iteration Report — prospective operator-selection bias diagnostics

## 1. Input and version

- Input archive: `cost_aware_momentum-1.14.0-orderbook-execution-evidence(1).zip`
- Input SHA-256: `77c293d747f45a7c4897ef1c88f8c95b079404c49049bc035002fe422e4be96e`
- Input version: 1.14.0
- Output version: 1.15.0
- Input Alembic head: `0010_orderbook_exec_evidence`
- Output Alembic head: `0011_selection_experiment`

## 2. Goal and acceptance criteria

After this iteration, the system must preserve every created execution-plan version as a tamper-evident ex-ante experiment opportunity and report operator-selection diagnostics over accepted, rejected and no-decision eligible plans rather than accepted trades alone.

Acceptance criteria:

1. Exactly one ledger opportunity is linked to each new plan version.
2. Ledger creation occurs in the plan transaction before operator action.
3. The feature vector contains only fixed pre-decision fields and has a canonical hash.
4. ACCEPT, REJECT and NO_DECISION valued outcomes enter the eligible comparison cohort.
5. Propensity scores are generated out-of-sample using only earlier observations.
6. All-eligible, selected-only and unselected outcome estimates are reported separately.
7. IPSW is omitted on class collapse, missing OOS evidence, poor overlap, low ESS or hash failure.
8. Documentation states that the result is descriptive, prospective and non-causal.

## 3. Sources and data flow

Read before changes:

- `README.md`, `CHANGELOG.md`, `PATCH_1.12.0.md`, `PATCH_1.13.0.md`, `PATCH_1.14.0.md`;
- `docs/ARCHITECTURE.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`;
- `app/db/models.py`, `app/services/execution.py`, `app/services/outcomes.py`, `app/api/v1/recommendations.py`, `scripts/daily_report.py`;
- migrations `0004_counterfactual_outcomes` and `0010_orderbook_exec_evidence`;
- relevant unit and PostgreSQL integration tests.

Data flow after the change:

```text
market signal + profile + point-in-time execution state
  -> execution plan calculation
  -> immutable pre-decision selection ledger row (same transaction)
  -> ACCEPT / REJECT / no terminal decision
  -> counterfactual plan outcome
  -> hash verification and complete eligible cohort
  -> chronological OOS propensity scores
  -> direct all-eligible benchmark + selected/unselected + IPSW diagnostics
  -> JSON selection/daily report
```

## 4. Baseline

| Check | Result |
|---|---|
| Python | 3.13.5 |
| `python -m pip check` | FAILED: external `moviepy`/`pillow` host conflict |
| Compileall | PASSED |
| Ruff | PASSED |
| Pytest | 514 passed, 4 skipped |
| Node syntax | PASSED |
| Alembic head | `0010_orderbook_exec_evidence` |

## 5. Confirmed defects and gaps

### High — eligibility was not frozen at decision opportunity time

**Classification:** CONFIRMED GAP.

`ExecutionPlan.status` is mutable and later becomes ACCEPTED, REJECTED, SUPERSEDED or EXPIRED. Existing outcomes could be joined to a plan, but the project did not preserve whether that exact version was actionable when created or which operator-visible covariates existed before the decision.

**Impact:** retrospective cohort definitions could depend on later state and could not prove absence of outcome leakage.

### High — operational performance could be restricted to selected plans

**Classification:** CONFIRMED DEFECT in reporting coverage.

`scripts/daily_report.py` counted decisions and manual trades but did not compare accepted plans with the resolved outcomes of every eligible opportunity. Counterfactual tables existed, yet no complete selection report used them.

**Impact:** accepted-only outcome summaries can reflect operator preference, market regime and sizing differences rather than strategy quality.

### Medium — no propensity/overlap/effective-sample diagnostics

**Classification:** CONFIRMED GAP.

No causal or sampling-selection model existed. The project could not quantify whether accepted plans occupied a different ex-ante covariate region or whether any reweighting was supportable.

**Why existing tests missed these issues:** outcome tests verified valuation correctness per plan, while decision tests verified safe mutations. No test treated plan creation as the experiment unit or compared selected and unselected populations.

## 6. Implementation and diff

### Production/research

- `app/db/models.py`: added `SelectionExperimentLedger`.
- `app/services/selection_experiments.py`: fixed ex-ante feature schema, canonical hashing, DB report assembly and integrity checks.
- `app/research/selection_bias.py`: chronological expanding propensity model, overlap/ESS gates and IPSW diagnostics.
- `app/services/execution.py`: transactionally records ledger opportunity for every plan version and adds hash metadata to audit payload.
- `scripts/selection_report.py`: dedicated JSON report.
- `scripts/daily_report.py`: embeds selection diagnostics over a separate lookback window.
- `manage.py`, `pyproject.toml`: command/entry point and version updates.

### Database

- `migrations/versions/0011_selection_experiment.py`.
- New table `advisory.selection_experiment_ledger`.
- One row per `plan_id`; FKs to plan, signal and profile; positive plan version; 64-character hash constraint.
- No automatic legacy backfill.

### Tests

- Added `tests/unit/test_operator_selection_bias_2026_07_05.py` with seven tests.
- Added one execution transaction regression.
- Updated expected Alembic head and one signal fixture with its required gross-edge field.

### Documentation

Updated README, changelog, patch note, architecture, configuration, model card, compliance, traceability, security, incident runbook, operator manual and QA report.

## 7. Red → green evidence

Command against untouched 1.14.0 with the new regression module:

```text
python -m pytest -q tests/unit/test_operator_selection_bias_2026_07_05.py
```

Red:

```text
ModuleNotFoundError: No module named 'app.research'
```

Green on 1.15.0:

```text
7 passed
```

The full suite increased from 514 to 522 passing tests.

## 8. Compatibility

- Advisory-only boundary preserved; no order mutation methods added.
- PostgreSQL-only preserved.
- API response contracts unchanged.
- Migration required: `0011_selection_experiment`.
- No new `.env` variables.
- No model artifact schema change and no ML retraining requirement.
- Existing plans remain usable under their existing execution rules but do not gain trustworthy pre-1.15 ledger history.

## 9. Post-check

| Check | Result |
|---|---|
| `python -m pip check` | FAILED: unchanged external host conflict |
| Compileall | PASSED |
| Ruff | PASSED |
| Pytest | 522 passed, 4 skipped |
| Node syntax | PASSED |
| Alembic heads | single head `0011_selection_experiment` |
| PostgreSQL integration | 4 skipped: no `TEST_DATABASE_URL` |
| `manage.py doctor` | environment failure: project `.venv` absent |
| Required integration command | not run against production DB |

## 10. Not verified

- Migration upgrade/downgrade on an isolated real PostgreSQL database.
- Long-running prospective accumulation with real operator behavior.
- Statistical stability under rare recommendations and repeated plan recalculation.
- Actual UI exposure/impression logging.
- Exchange-confirmed fills and actual trade P&L.
- Causal operator skill or economic profitability.

## 11. Residual risks and limitations

- Plan creation is used as the opportunity unit; an operator may not have viewed every plan.
- Multiple versions from one signal/profile are correlated.
- Features represent observed plan economics and timing, but unmeasured operator context remains.
- Counterfactual outcomes use advisory valuation and can be unavailable for late entry-aligned paths.
- IPSW can only correct measured covariate imbalance with adequate overlap.
- Pre-1.15 history is intentionally excluded rather than reconstructed from mutable final states.

## 12. Rollback

1. Stop API/worker/trainer and back up PostgreSQL.
2. Restore the 1.14.0 application tree.
3. If no 1.15.0 ledger evidence must be retained, run Alembic downgrade to `0010_orderbook_exec_evidence` on the isolated/approved database.
4. Otherwise leave the additive table in place and restore only application code after compatibility review.
5. Run doctor, migration-head check and smoke tests before resuming operation.

## 13. Recommended next work package

Add a point-in-time market-context feature package limited to open interest, perp/index basis, current funding state and liquidity regime. It should include historical availability timestamps, gap handling, feature ablation and a new artifact schema, without enabling automatic activation until walk-forward and forward evidence demonstrate incremental value.

## 14. Release verification

| Check | Result |
|---|---|
| Clean staged manifest | 193/193 files |
| Clean staged full suite | 522 passed, 4 skipped |
| Clean staged compile/Ruff/Node | PASSED |
| Clean staged Alembic head | `0011_selection_experiment (head)` |
| ZIP structural test | PASSED |
| Fresh re-extraction manifest | 193/193 files |
| Fresh re-extraction full suite | 522 passed, 4 skipped |
| Fresh re-extraction compile/Ruff/Node | PASSED |
| Fresh re-extraction Alembic head | `0011_selection_experiment (head)` |

The final archive contains one root directory, `cost_aware_momentum-1.15.0`, and excludes credentials, runtime `.env`, virtual environments, model artifacts, database dumps and generated test/build caches.

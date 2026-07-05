# Iteration Report — 2026-07-05 — formal experiment preregistration

## 1. Input and baseline identity

- Input archive: `cost_aware_momentum-1.19.0-dependence-aware-inference(1).zip`
- Input SHA-256: `b95b220814ba41f3c378b6a6478643d88e74209449c59594fe7f6edd1fbcba03`
- Source version: `1.19.0`
- Source Alembic head: `0012_experiment_selection`
- Target version: `1.20.0`

The archive was unpacked into a clean directory before edits. Baseline commands were executed in an isolated virtual environment with no production PostgreSQL connection.

## 2. Goal and acceptance criteria

Goal:

> After this iteration, a new experiment family cannot record its first trial unless a complete immutable preregistration was created before result evaluation; every trial and report must remain inside that precommitted contract.

Acceptance criteria:

1. A family registration must precede every new `STARTED` event.
2. Registration must contain a substantive hypothesis, exact dataset fingerprint/horizon, primary metric, full fixed/search configuration contract, governance policy, stopping rule and objective exclusions.
3. Trial configuration must contain no undeclared key and every search value must be explicitly enumerated.
4. A new unique configuration must be blocked after the preregistered maximum or deadline.
5. Registration mutation must be detectable in application code and rejected by PostgreSQL UPDATE/DELETE protection.
6. Report-time PBO/DSR/dependence overrides must either match registration exactly or be blocked.
7. A template-generation path must exit before `STARTED` and model/policy evaluation.
8. Legacy pre-1.20 families must not be retrospectively described as preregistered.

## 3. Sources read and affected data flow

Read before modification:

- `README.md`, `CHANGELOG.md`, `PATCH_1.18.0.md`, `PATCH_1.19.0.md`;
- `docs/ARCHITECTURE.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`;
- `app/research/overfitting.py`, `app/research/dependence.py`;
- `app/services/experiment_ledger.py`;
- `scripts/backtest.py`, `scripts/experiment_report.py`, `manage.py`;
- `app/db/models.py`, migration `0012_experiment_selection` and relevant tests.

Affected flow:

```text
validated artifact + exact final-test cohort
  -> unevaluated preregistration template
  -> edited formal JSON specification
  -> immutable PostgreSQL family registration
  -> locked validation before STARTED
  -> append-only trial events and aligned return evidence
  -> preregistration-bound PBO/DSR/dependence report
```

## 4. Baseline

| Command | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | no broken requirements in isolated environment |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| `python -m pytest -q` | PASSED | 559 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | `0012_experiment_selection` |

The first installation attempt exceeded the command timeout before all packages were committed. The installation was completed and the clean baseline was rerun successfully. The global host environment was not used because it lacked project packages and contained an unrelated `moviepy/pillow` conflict.

## 5. Confirmed defect/gap

### CONFIRMED GAP — high severity: experiment family could be defined post hoc

Evidence:

- `scripts/backtest.py` accepted an arbitrary `--experiment-family` and otherwise derived a family name automatically.
- The first durable family record was a `STARTED` trial event. No earlier immutable hypothesis or search plan existed.
- `scripts/experiment_report.py` accepted PBO, DSR, block and confidence thresholds at report time.
- `research.experiment_events` protected trial disclosure but did not contain a family-level hypothesis, enumerated search space, stopping rule or exclusion criteria.

Impact:

- researcher degrees of freedom remained after observing results;
- the family boundary could be narrowed around favourable variants;
- thresholds and stopping behaviour could be changed post hoc;
- PBO/DSR could appear rigorous while operating on a selectively defined family.

Why prior tests did not catch it:

Existing tests validated trial disclosure, PBO/DSR arithmetic and dependence adjustments, but no contract existed for a family before its first trial.

## 6. Change plan and actual diff

Production/research:

- added `app/research/preregistration.py` for strict normalization, search-space validation, stopping enforcement and record hashing;
- added `app/services/experiment_preregistration.py` for registration, integrity verification, row locking and trial admission;
- updated `app/services/experiment_ledger.py` so STARTED/terminal events require the same registration and reports use immutable governance;
- updated `scripts/backtest.py` with explicit family requirement and pre-evaluation `--prepare-preregistration` mode;
- added `scripts/experiment_preregister.py`;
- updated `scripts/experiment_report.py`, `manage.py` and console entry points.

Database:

- added `ResearchExperimentFamilyRegistration`;
- added migration `0013_experiment_preregistration`;
- added a trigger rejecting UPDATE or DELETE.

Tests:

- added `tests/unit/test_experiment_preregistration_2026_07_05.py`;
- updated expected migration head.

Documentation/version:

- bumped package/application to 1.20.0;
- added `PATCH_1.20.0.md` and changelog entry;
- synchronized README, architecture, configuration, operator, security, incident, model-card, compliance, traceability and QA documents.

## 7. Red → green evidence

Command on the pre-implementation tree:

```text
python -m pytest -q tests/unit/test_experiment_preregistration_2026_07_05.py
```

Red result:

```text
ModuleNotFoundError: No module named 'app.research.preregistration'
```

Green result after implementation:

```text
9 passed
```

The tests use independent expected contracts rather than the output of the functions under test as their oracle.

## 8. Migration, API, configuration and compatibility

- New Alembic head: `0013_experiment_preregistration`.
- Upgrade creates `research.experiment_family_registrations`, index, mutation-rejection function and trigger.
- Downgrade removes trigger, function and table.
- No HTTP API contract is changed.
- No new environment variable is introduced.
- Existing `EXPERIMENT_*`/`RESEARCH_*` settings seed draft templates only; registered reports use the immutable specification.
- Model artifacts, feature schemas, inference and risk semantics are unchanged; retraining is unnecessary.
- Pre-1.20 experiment events remain intact. Their family reports return `BLOCKED_UNREGISTERED_FAMILY` rather than a false preregistration claim.

## 9. Post-change checks

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests migrations manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| `python -m pytest -q` | PASSED | 568 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | `0013_experiment_preregistration` |

Staged release verification:

- clean release tree: 222 eligible files;
- `SHA256SUMS`: 222/222 verified;
- forbidden cache, credential, model-artifact, dump and runtime-report files absent;
- one expected Alembic head: `0013_experiment_preregistration`.

Fresh-extraction verification:

- `unzip -t`: PASSED;
- release integrity before tests: 222/222;
- dependency check, compileall, Ruff and frontend syntax: PASSED;
- full pytest: 568 passed, 4 skipped, 61 warnings;
- Alembic head: `0013_experiment_preregistration`.

The final ZIP SHA-256 is delivered externally because an archive cannot reliably contain its own digest.

## 10. Not verified

- PostgreSQL integration suite and migration upgrade/downgrade were not executed because no isolated `TEST_DATABASE_URL` was supplied.
- No production model artifact, dataset or research database was available to execute a real template/register/multi-trial workflow.
- `manage.py doctor` was not run from the release tree because it intentionally contains no local `.venv`; equivalent checks ran in the isolated environment.
- External trusted timestamping was not implemented or tested.

## 11. Residual risks and limitations

- A database owner can bypass normal trigger protections; SHA-256 is tamper evidence, not external notarization.
- Search space is the Cartesian product of per-parameter enumerations; conditional search spaces are not modeled.
- Exclusion criteria are immutable text/code disclosures, but runtime failures are not automatically mapped to an exclusion code.
- Research performed outside this application remains undisclosed.
- A preregistered `READY` report is not an active-model promotion decision or profitability proof.

## 12. Rollback

1. Stop research/backtest/report processes.
2. Preserve a PostgreSQL backup and exported preregistration specifications.
3. Downgrade one revision only if no 1.20 family registration is needed:

```text
python -m alembic downgrade 0012_experiment_selection
```

4. Restore 1.19.0 source files.
5. Do not rewrite 1.20 trial events as legacy events. If trials already reference a preregistration, prefer forward repair rather than destructive downgrade.

## 13. Recommended next work package

Add prospective operator UI-exposure evidence: record when a recommendation card was actually rendered/visible, not merely created, and use that exposure cohort in selection-bias analysis. This addresses the remaining distinction between generated opportunities and opportunities genuinely available to the operator.

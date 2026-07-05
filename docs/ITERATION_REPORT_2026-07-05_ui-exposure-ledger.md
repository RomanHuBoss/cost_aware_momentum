# Iteration Report — 2026-07-05 — prospective UI exposure ledger

## 1. Input and baseline identity

- Input archive: `cost_aware_momentum-1.20.0-experiment-preregistration(1).zip`
- Input SHA-256: `4415ec63775348d8b9cbd45fc5f369529467de95a2b23205322d1f231535501b`
- Source version: `1.20.0`
- Source Alembic head: `0013_experiment_preregistration`
- Target version: `1.21.0`

The archive was unpacked into clean work and untouched red-test directories. Baseline commands were executed in an isolated virtual environment with no production PostgreSQL connection.

## 2. Goal and acceptance criteria

Goal:

> After this iteration, an execution plan enters the operator-selection denominator only after immutable point-in-time evidence shows that its exact version was actually visible in the first-party UI; missing or low-coverage instrumentation must block corrected inference rather than be interpreted as operator non-selection.

Acceptance criteria:

1. A created plan must not be assumed exposed.
2. Exposure must require at least 50% visible tile area, active document visibility and at least 1000 ms dwell.
3. Evidence must be bound to the exact immutable plan opportunity and version.
4. Retries must be idempotent and unable to create multiple first exposures.
5. Server-side validation must reject stale, future, pre-plan, malformed or tampered evidence.
6. Exposure evidence must be append-only and tamper-evident in PostgreSQL.
7. Propensity/IPSW must use only verified exposed opportunities and `exposed_at` chronological order.
8. Low coverage and decisions without exposure must be explicit diagnostics; insufficient coverage must block the corrected estimate.
9. Legacy pre-1.21 plans must not create false missing-exposure counts.
10. Exposure insertion must not mutate plan status, market model, risk or exchange state.

## 3. Sources read and affected data flow

Read before modification:

- `README.md`, `CHANGELOG.md`, `PATCH_1.18.0.md`, `PATCH_1.19.0.md`, `PATCH_1.20.0.md`;
- `docs/ARCHITECTURE.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`;
- `app/services/selection_experiments.py`, `app/research/selection_bias.py`;
- `app/services/execution.py`, `app/api/v1/recommendations.py`, `app/api/schemas.py`;
- `web/js/app.js`, `app/db/models.py`, migration `0013_experiment_preregistration` and related tests.

Affected flow:

```text
execution plan creation
  -> immutable ex-ante selection opportunity
  -> recommendation tile rendered in local UI
  -> >=50% visible + active document + >=1000 ms dwell
  -> authenticated idempotent batch exposure event
  -> immutable first-exposure PostgreSQL evidence
  -> decision/outcome join
  -> exposure-conditioned chronological propensity/IPSW report
```

## 4. Baseline

| Command | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | no broken requirements in isolated environment |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| `python -m pytest -q` | PASSED | 568 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | `0013_experiment_preregistration` |

The global host environment was unsuitable because it lacked project dependencies and contained an unrelated `moviepy/pillow` conflict. No production database was used.

## 5. Confirmed defect/gap

### CONFIRMED GAP — high severity: plan creation was used as a proxy for operator exposure

Evidence:

- `SelectionExperimentLedger.observed_at` was written when the plan was created.
- `selection_bias_report` treated every eligible plan as an opportunity in the denominator regardless of UI state.
- The frontend did not report card rendering, viewport visibility or dwell.
- A hidden tab, unopened browser or below-viewport card was indistinguishable from an exposed plan left without a decision.

Impact:

- `NO_DECISION` mixed non-selection with non-exposure;
- propensity estimates could learn application availability rather than operator choice;
- all-eligible and selected-only comparisons used a contaminated denominator;
- selection coverage appeared complete even when the operator had not seen many plans.

Why prior tests did not catch it:

Prior tests verified ex-ante opportunity integrity, chronological signal-cluster propensity splits and IPSW/dependence mathematics, but no observable exposure contract existed.

## 6. Change plan and actual diff

Production/API/UI:

- added `app/services/ui_exposures.py` for strict evidence validation, canonical hashing and insert payloads;
- added `SelectionExposureLedger` in `app/db/models.py`;
- added request schemas and authenticated `POST /api/v1/recommendations/exposures`;
- instrumented recommendation tiles in `web/js/app.js` with `IntersectionObserver`, active-tab dwell and idempotent batch retry;
- updated `selection_bias_report` to join exposure evidence, use `exposed_at`, publish coverage/anomalies and exclude unexposed plans;
- updated report schema to `operator-selection-ipsw-exposure-clustered-report-v3`;
- added `selection_min_exposure_coverage` configuration and report wiring.

Database:

- added migration `0014_ui_exposure_ledger`;
- unique first exposure by `plan_id` and unique client event ID;
- canonical evidence hash constraints;
- PostgreSQL trigger rejecting UPDATE and DELETE.

Tests:

- added `tests/unit/test_ui_exposure_ledger_2026_07_05.py`;
- updated operator-selection and dependence fixtures for exposure-conditioned rows;
- updated migration-head contract.

Documentation/version:

- bumped package/application to 1.21.0;
- added `PATCH_1.21.0.md` and changelog entry;
- synchronized README, architecture, configuration, operator, security, incident, model-card, compliance, traceability and QA documents.

## 7. Red → green evidence

Command on untouched 1.20.0:

```text
python -m pytest -q tests/unit/test_ui_exposure_ledger_2026_07_05.py
```

Red result:

```text
ImportError: cannot import name 'SelectionExposureLedger' from 'app.db.models'
```

Green result after implementation:

```text
14 passed
```

The tests use fixed expected timestamps, hashes, cohort counts and source contracts rather than the tested function's output as their own oracle.

## 8. Migration, API, configuration and compatibility

- New Alembic head: `0014_ui_exposure_ledger`.
- Upgrade creates `advisory.selection_exposure_ledger`, constraints, indexes and mutation-rejection trigger.
- Downgrade removes trigger, function, indexes and table.
- New authenticated endpoint: `POST /api/v1/recommendations/exposures`.
- New environment setting: `SELECTION_MIN_EXPOSURE_COVERAGE=0.80`.
- No model artifact, feature, inference, signal, execution-plan or risk schema changes; model retraining is unnecessary.
- Pre-1.21 unexposed opportunities are excluded from rollout coverage, not labelled as missing exposure. A legacy plan with a real 1.21 UI exposure remains eligible.
- Operator report consumers must accept schema `operator-selection-ipsw-exposure-clustered-report-v3`.

## 9. Post-change checks

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests migrations manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| `python -m pytest -q` | PASSED | 582 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | `0014_ui_exposure_ledger` |

Staged release verification:

- clean release tree: 227 eligible files;
- `SHA256SUMS`: 227/227 verified;
- forbidden cache, credential, model-artifact, dump and runtime-report files absent;
- advisory-only Bybit-client scan, secret-pattern scan and trailing-whitespace scan: PASSED;
- dependency check, compileall, Ruff, full pytest (`582 passed, 4 skipped`), frontend syntax and Alembic head passed.

Fresh-extraction verification:

- `unzip -t`: PASSED;
- one root directory: `cost_aware_momentum-1.21.0`;
- release integrity before tests: 227/227;
- dependency check, compileall, Ruff and frontend syntax: PASSED;
- full pytest: 582 passed, 4 skipped, 61 warnings;
- Alembic head: `0014_ui_exposure_ledger`.

Generated verification caches are not copied back into the release. The final ZIP SHA-256 is delivered externally because an archive cannot reliably contain its own digest.

## 10. Not verified

- PostgreSQL integration suite and live migration upgrade/downgrade were not executed because no isolated `TEST_DATABASE_URL` was supplied.
- No configured application database and authenticated browser session were available for a full tile-visible → endpoint → PostgreSQL → selection-report smoke test.
- `manage.py doctor` was not run from the release tree because it intentionally contains no local `.venv`; equivalent checks ran in the isolated environment.
- Eye tracking, comprehension and latent operator state cannot be inferred from visible dwell.

## 11. Residual risks and limitations

- A browser can report a visible tile even when the operator is not looking at the screen.
- Client clock errors are bounded but not cryptographically trusted; server receipt time and age/skew checks limit abuse.
- A tab/browser crash before event delivery can lose exposure evidence, causing conservative exclusion.
- API, CLI, notifications and external dashboards are not instrumented exposure surfaces.
- One first exposure does not measure repeated viewing, reading duration after the threshold or attention quality.
- Propensity bootstrap remains conditional on fitted OOS scores and does not refit inside each replicate.
- Selection estimates remain descriptive and do not prove causal operator skill or profitability.

## 12. Rollback

1. Stop API and report processes.
2. Preserve a PostgreSQL backup and any exposure rows already collected.
3. Prefer forward repair once 1.21 evidence exists. If destructive rollback is explicitly accepted, downgrade one revision:

```text
python -m alembic downgrade 0013_experiment_preregistration
```

4. Restore 1.20.0 sources.
5. Do not backfill or reinterpret collected exposure evidence manually.

## 13. Recommended next work package

Add explicit outcome-resolution and report-quality monitoring for exposure instrumentation: browser/API delivery failure rates, exposure-to-decision latency distributions, duplicate/conflict diagnostics and surface-specific coverage. A larger alternative is point-in-time historical execution evidence for model/backtest, but that requires a separate data-collection iteration rather than synthetic reconstruction.

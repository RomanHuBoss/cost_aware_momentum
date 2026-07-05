# Iteration Report — candidate/live attrition diagnostics

Date: 2026-07-05
Target release: 1.24.0

## 1. Input archive

- Archive: `cost_aware_momentum-1.23.0-maturity-aware-drift-calibration(1).zip`
- SHA-256: `249a9f1023741134d4d65d5bb6f6b982b5f6c666aaba5d6ec0511df0cff43a18`
- Source version: `1.23.0`
- Root: `cost_aware_momentum-1.23.0`
- Alembic head: `0014_ui_exposure_ledger`

## 2. Goal and acceptance criteria

After this iteration the system must produce a prospective, integrity-checked explanation of where background candidates and live recommendation opportunities terminate, without relaxing model, policy, risk or safety gates.

Acceptance criteria:

1. Every selected symbol in hourly/catch-up inference has exactly one terminal outcome per job.
2. Repeated attempts are deduplicated by `symbol × event_time`, and recovery after an initial skip is visible.
3. Every initial execution plan has one stable machine-readable primary cause plus contributing reasons.
4. Background training attempts expose failed training, failed quality gate, activation and activation-skip outcomes.
5. Missing, duplicate, conflicting, legacy or contradictory evidence blocks the report.
6. A CLI and daily report expose one bounded JSON contract.
7. Existing advisory-only, PostgreSQL-only and fail-closed invariants remain intact.

## 3. Sources read and data flow

Reviewed `README.md`, `CHANGELOG.md`, recent patch reports, `docs/ARCHITECTURE.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/MODEL_CARD.md`, `docs/CONFIGURATION.md`, `docs/SECURITY.md`, `docs/INCIDENT_RUNBOOK.md`, `docs/OPERATOR_MANUAL.md`, `pyproject.toml`, `.env.example`, signal publication, execution planning, trainer job details, daily reporting and related tests.

Changed flow:

- trainer lifecycle → `JobRun.details.quality_gate/activated/activation_skipped`;
- market/inference validation → one symbol terminal outcome in inference `JobRun.details`;
- execution planning → structured attrition evidence in `ExecutionPlan.sizing_snapshot` and inference plan outcomes;
- report service → integrity validation, retry deduplication and aggregate counts;
- CLI/daily report → `reports/candidate_live_attrition.json` / embedded section.

## 4. Baseline

Authoritative checks used fresh isolated environment `/mnt/data/cam_124_venv`:

| Command | Result |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — `588 passed, 4 skipped, 61 warnings` |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0014_ui_exposure_ledger` |

The host environment was non-authoritative because it lacked Ruff/psycopg and had an unrelated Pillow/MoviePy conflict.

## 5. Confirmed gap

### CONFIRMED GAP — no exact prospective attrition denominator

Severity: high operational/model-governance impact.

Evidence:

- `publish_hourly_signals` recorded aggregate skip/status counters but no terminal row per selected symbol;
- hourly and catch-up attempts could not be reconciled as one opportunity;
- initial execution plans had statuses and free-form diagnostics but no stable primary cause contract;
- background candidate gate failures were not combined with live attrition;
- no fail-closed aggregate service or operator command existed.

Expected: exact per-opportunity terminal evidence and one integrity-checked report.

Actual: operators could observe few recommendations but could not distinguish data readiness, model/policy economics, liquidity, minimum-size, margin/portfolio caps or candidate quality gates without manual log reconstruction.

Existing tests checked individual gates and safety states, but not denominator completeness, retry reconciliation or a cross-stage report contract.

## 6. Plan and implemented diff

Production:

- added `app/services/attrition.py`;
- instrumented `app/services/signals.py` with per-symbol and per-plan terminal outcomes;
- added structured reason accumulation to `app/services/execution.py`;
- added `scripts/attrition_report.py` and daily-report integration;
- exposed `attrition-report` through `manage.py` and project console scripts;
- bumped version to 1.24.0.

Tests:

- added inference terminal-outcome regression;
- added retry/candidate/live aggregate and integrity regressions;
- extended execution acceptance safety assertions.

Documentation:

- updated release, architecture, configuration, operator, incident, compliance, traceability and QA documents;
- added `PATCH_1.24.0.md` and this report.

No migration or `.env` change was required.

## 7. Red → green evidence

Before implementation:

```text
KeyError: 'attrition_schema'
ModuleNotFoundError: No module named 'app.services.attrition'
```

After implementation:

```text
4 passed
```

The broader focused execution/inference/report set then passed:

```text
48 passed
```

The tests use independent expected dictionaries/counts rather than the production report as their own oracle.

## 8. Contracts and compatibility

- `hourly-inference-terminal-outcomes-v1`
- `execution-plan-attrition-v1`
- `candidate-live-attrition-report-v1`

Compatibility:

- database schema unchanged;
- active artifacts remain compatible and retraining is not required;
- no thresholds, risk limits or actionability rules changed;
- no exchange mutation capability added;
- legacy inference `JobRun` payloads are not fabricated into the new schema and cause `BLOCKED` when included in the report window.

## 9. Post-check

| Command | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — `592 passed, 4 skipped, 61 warnings` |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0014_ui_exposure_ledger` |

Final staged archive checks are appended after packaging.

## 10. Not verified

- `manage.py doctor`: no project-local `.venv` in the clean release; equivalent direct checks were run in the isolated environment.
- PostgreSQL integration suite: no isolated `TEST_DATABASE_URL`.
- Live report against the user's database.
- Live Bybit calls; client unchanged.
- Economic profitability or causal opportunity-cost attribution.

## 11. Residual risks and limitations

- Evidence is prospective from 1.24.0; legacy job payloads cannot be reconstructed reliably.
- Primary reason is deterministic first-cause attribution, not a causal decomposition of interacting constraints.
- Contributing reasons are multi-label and their counts are not additive denominators.
- A short window can be statistically unrepresentative even when structurally complete.
- Training aggregation covers background `model_retraining` jobs, not every possible manually invoked research CLI.
- Diagnostic frequency alone does not justify weakening a safety or economics gate.

## 12. Rollback

1. Stop API/worker/trainer.
2. Restore release 1.23.0 application files.
3. Restart processes; no database downgrade is required.
4. Ignore post-1.24 attrition fields in historical `JobRun.details` and plan snapshots; they are additive JSON evidence and do not affect execution semantics.

## 13. Recommended next work package

Accumulate a stable post-upgrade window and use the report to select one empirically dominant bottleneck. Do not pre-emptively relax gates. If no single operational bottleneck dominates, the next bounded specification package should be multivariate production-drift testing with preregistered fixed thresholds and no automatic rollback.

## 14. Final release archive

- Root: `cost_aware_momentum-1.24.0`.
- Files: 238 including `SHA256SUMS`; checksum entries: 237.
- Production files under `app/scripts/web`: 95; test files: 76; documentation files: 25; migrations: 14.
- Staged full suite: `592 passed, 4 skipped, 61 warnings`.
- `unzip -t`: PASSED.
- Fresh extraction and `sha256sum -c SHA256SUMS`: PASSED.
- Cache, virtualenv, `.env`, credentials, model artifacts, reports and database dumps are excluded.
- One project root is present in the archive.

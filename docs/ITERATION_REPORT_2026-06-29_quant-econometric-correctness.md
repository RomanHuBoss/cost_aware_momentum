# Iteration report — quantitative and econometric correctness

Date: 2026-06-29
Release: 1.8.10
Scope: risk/cost mathematics, temporal/econometric validation, model lifecycle/runtime, execution revalidation, actual manual-position risk and release integrity.

## 1. Input and baseline identity

- Input archive: `cost_aware_momentum-main.zip`
- Input SHA-256: `68da697d04d279a719cd42e279ecdb79305a4e4fe72e0da50fe4b769e099dde6`
- Source version: `1.8.9`
- Python requirement: `>=3.12`
- Baseline Alembic head: `0005_plan_outcome_invalid_input`
- Baseline release counts: 79 production/source files, 30 test files, 17 documentation files; 137 non-cache files overall.
- Input release manifest was invalid: it referenced absent `CHANGELOG.md`, `PATCH_1.8.7.md`, `PATCH_1.8.8.md` and `PATCH_1.8.9.md`.

## 2. Goal and acceptance criteria

After this iteration, the system must fail closed on invalid quantitative/econometric inputs, preserve trader-perspective funding signs, recalculate risk at an adverse executable entry, reserve actual remaining manual-position risk, validate model artifacts/features and produce internally consistent research metrics.

Acceptance criteria:

1. LONG/SHORT funding cash flow has the correct sign in live math and backtest.
2. Non-finite/negative cost/risk/config values cannot enter arithmetic.
3. Every directional metadata row is validated before direction selection.
4. Label availability and barrier/return consistency are enforced.
5. Model promotion rejects malformed candidate/incumbent metrics.
6. Runtime rejects incompatible artifacts and missing/non-finite features.
7. Execution uses only non-future data and adverse entry drift triggers a newly sized plan.
8. Open risk equals accepted-plan reservations plus actual remaining manual-trade risk.
9. Full unit/static suite remains green and release manifest is reproducible.

## 3. Sources and data flow reviewed

Read: `README.md`, `pyproject.toml`, `.env.example`, architecture/configuration/security/operator/model/QA/compliance/traceability documents, all available 2026-06-29 iteration reports, risk math, signal/execution/outcome services, training/labels/runtime/lifecycle, backtest, ORM/migrations, API endpoints and related tests.

Changed flow:

```text
Settings / market + artifact inputs
    -> fail-closed numeric, temporal and schema validation
    -> LONG/SHORT outcome and cost mathematics
    -> policy ranking / model gate
    -> MarketSignal / versioned ExecutionPlan
    -> executable-price revalidation
    -> ManualTrade actual + remaining stress risk
    -> portfolio API / acceptance risk lock
    -> PlanOutcome and research reports
```

## 4. Baseline before changes

Isolated environment outside the release tree, Python 3.13.5:

| Command | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | 198 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -B -m scripts.release_integrity` | FAILED: four manifest entries absent |
| `python manage.py doctor` | NOT RUN: no configured local `.env`/PostgreSQL instance |
| `python manage.py test --require-integration` | NOT RUN: no isolated PostgreSQL URL |

The first host-environment attempt was not authoritative because global packages lacked `psycopg`/Ruff and had unrelated dependency conflicts. All reported baseline/post results use the isolated environment.

## 5. Confirmed defects

Severity is assigned by this audit and does not claim to reproduce the unnamed experts’ exact categorization.

### Critical / high

| ID | Defect and evidence | Impact | Fix |
|---|---|---|---|
| Q01 | `app/risk/math.py`: positive funding was treated as adverse for SHORT or omitted from upside | reversed/understated economics | trader-perspective signed funding helper used everywhere |
| Q02 | `scripts/backtest.py`: the same funding-sign error existed in research reports | biased OOS/policy metrics | signed funding aligned with live math |
| Q03 | `app/config.py`: NaN/Infinity, negative fee/slippage/gap and contradictory risk caps could pass startup | unsafe sizing or non-deterministic Decimal/float behavior | cross-field finite/range validation |
| Q04 | direct `CostScenario` calls accepted negative/NaN costs even when Settings was valid | callers could reduce downside or crash on Decimal NaN | `validate_cost_scenario` before arithmetic |
| Q05 | `projected_funding_rate` accepted zero/fractional horizon and non-finite rate | invalid settlement projection | strict positive-integer horizon/interval and finite rate |
| Q06 | `evaluate_policy_model` validated selected rows too late; a corrupt losing LONG/SHORT row could disappear after ranking | biased policy metrics and model promotion | validate every directional row before ranking |
| Q07 | backtest did not enforce `label_end_time >= modeled exit_time` | temporal leakage / impossible outcome availability | explicit label-availability gate |
| Q08 | TP/SL labels could claim returns inconsistent with modeled barriers | inflated or mislabeled backtest results | strict barrier/return consistency checks |
| Q09 | malformed/NaN holdout class distribution could bypass auto-activation gates | unsafe model activation | exact keys, finite simplex and class-fraction checks |
| Q10 | corrupted incumbent metrics could create NaN deltas, bypass comparisons or raise | unsafe/unstable auto-activation | fail-closed incumbent metric validation |
| Q11 | artifact runtime accepted missing/wrong feature schema version and invalid horizon | incompatible model could become active | exact schema and positive integer horizon validation |
| Q12 | artifact inference silently replaced missing features with zero and accepted non-finite values | hidden distribution shift / false predictions | complete finite feature-vector requirement |
| Q13 | future ticker snapshot was considered current | look-ahead/stale-data boundary violation | closed age interval `[0,max]` |
| Q14 | future-dated instrument spec could be selected | look-ahead and wrong contract limits | point-in-time `valid_from <= planning time` query |
| Q15 | adverse executable price inside entry zone could be accepted against old qty/risk/RR/EV | actual stop risk could exceed intended economics | new versioned plan at executable entry before acceptance |
| Q16 | manual entry calculated actual stress loss but did not persist/use it; open risk kept the plan value | portfolio risk could be understated | migration plus actual initial/remaining risk columns |
| Q17 | partial close did not release risk proportionally | stale over-reservation and false portfolio blocks | deterministic remaining-risk update |

### Medium

| ID | Defect and evidence | Impact | Fix |
|---|---|---|---|
| Q18 | empty label window returned synthetic `TIMEOUT` with invalid return/index | fabricated labels | reject empty future window |
| Q19 | inverted LONG/SHORT barrier geometry was accepted by label helper | wrong labels | directional geometry validation |
| Q20 | profit factor used raw trades while equity/drawdown used cohort weights | mutually inconsistent metrics | common weighted contribution basis |
| Q21 | mean concurrent trades excluded idle observed periods | upward-biased utilization | include zero-concurrency intervals |
| Q22 | reconciliation dictionary overwrote multiple same-side manual trades | false mismatch/no-mismatch | sum quantities by symbol/direction |
| Q23 | reconciliation iterated only exchange keys and missed journal-only positions | unknown local exposure not surfaced | compare union of exchange/journal keys |
| Q24 | PlanOutcome used original signal entry/time after a recalculated plan | wrong counterfactual P&L/funding settlements | immutable plan entry/planning time |
| Q25 | release manifest referenced four absent files | release could not verify itself | regenerate clean manifest and add current changelog/patch |
| Q26 | settings allowed zero ticker/candle age and signal TTL | guaranteed stale/expired semantics | positive-value validation |
| Q27 | outcome target/exit index/non-finite barriers were not comprehensively validated in one contract | fragmented fail-open research boundary | shared metadata validator |

## 6. Red-to-green evidence

- Initial regression module on pre-fix code: `33 failed` (`red_quant_audit.log`).
- Follow-up tests for direct cost math, actual manual risk, artifact/runtime, incumbent gate and plan valuation: `20 failed, 32 passed` (`red_followup.log`).
- After implementation: audit module `53 passed`; follow-up counterfactual test passed.
- Full suite after all changes: `252 passed, 4 skipped`.

The tests use independent numerical expectations: e.g. positive 1% funding changes LONG TP return from 4% to 3% and SHORT TP return from 4% to 5%; remaining risk for 2/3 open quantity of a 12 USDT initial risk is 8 USDT.

## 7. Files changed

Production/source:

- `app/config.py`
- `app/risk/math.py`
- `app/ml/labels.py`
- `app/ml/training.py`
- `app/ml/lifecycle.py`
- `app/ml/runtime.py`
- `app/services/execution.py`
- `app/services/outcomes.py`
- `app/api/v1/recommendations.py`
- `app/api/v1/trades.py`
- `app/api/v1/portfolio.py`
- `app/db/models.py`
- `scripts/backtest.py`
- `app/__init__.py`
- `pyproject.toml`

Tests:

- new `tests/unit/test_quant_econometric_audit_2026_06_29.py`
- expanded execution, outcome, chronology, runtime, artifact recovery and quant-hardening tests.

Migration:

- `migrations/versions/0006_manual_trade_remaining_risk.py`

Documentation/release:

- `README.md`, `CHANGELOG.md`, `PATCH_1.8.10.md`
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`
- `docs/ARCHITECTURE.md`, `docs/CONFIGURATION.md`, `docs/MODEL_CARD.md`, `docs/OPERATOR_MANUAL.md`
- this report and regenerated `SHA256SUMS`.

## 8. Compatibility and migration

- Public advisory-only boundary is unchanged; no order create/amend/cancel method was added.
- PostgreSQL remains mandatory.
- Apply Alembic `0006` before starting 1.8.10.
- No new environment variables.
- Old active artifacts without the current exact schema metadata are intentionally rejected. Retraining/recovery is required; silent zero-imputation is not retained for compatibility.
- Existing open/partial manual trades are conservatively backfilled from plan risk because historical actual-entry downside was not persisted.

## 9. Post-change verification

| Command | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | 252 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | `0006_manual_trade_remaining_risk` |
| `python manage.py release-check` | PASSED after manifest regeneration |
| ZIP integrity/re-extraction | PASSED |

## 10. Not verified

- PostgreSQL migration upgrade/downgrade and DB integration tests: no isolated PostgreSQL URL/service was available.
- `manage.py doctor`: no configured runtime `.env` and database.
- Live Bybit behavior and forward trading evidence were not exercised.

## 11. Residual risks and limitations

- Migration backfill cannot reconstruct exact historical actual-entry stress loss; it uses the prior plan risk scaled by remaining quantity.
- Backtest still lacks historical order book, no-fill/partial-fill simulation, operator latency and exact funding timeline.
- No full multi-fold walk-forward, PBO/DSR, online drift-control or profitability claim is provided.
- Intrabar refinement exists in outcome journaling but not yet in the training/backtest labels.

## 12. Rollback

1. Stop API, worker and trainer.
2. Preserve a PostgreSQL backup.
3. Downgrade to revision `0005_plan_outcome_invalid_input` only after confirming no 1.8.10 process is writing manual trades.
4. Restore 1.8.9 application files and restart.
5. Re-run `doctor` and release checks.

Downgrade drops the two manual-risk columns; exact risk values written by 1.8.10 will be lost from the schema, so backup is mandatory.

## 13. Recommended next work package

Build a PostgreSQL-backed integration package for migration `0006` and concurrent accept/manual-entry/partial-close risk reservation, including clean upgrade, populated upgrade, downgrade and two-session serialization tests.

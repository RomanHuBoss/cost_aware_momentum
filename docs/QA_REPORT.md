# QA Report

Release: **1.35.1**

Date: **2026-07-06**  
Scope: **current-entry repricing of conditional TIMEOUT economics**

## Environment

- Python: 3.13.5 in the same isolated virtual environment used for baseline and post-checks.
- Project requirement: Python >=3.12.
- Node syntax check: available.
- Separate PostgreSQL integration database: not configured.
- Input archive: `cost_aware_momentum-1.35.0-outcome-attribution.zip`.
- Input archive SHA-256: `5aa987b761d8ccd4f5554e1dd17b724b2ce6bc5340d167700e01b80ed0375f88`.
- Source version: 1.35.0.

## Baseline before changes

| Check | Result |
|---|---|
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | PASSED: no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 699 passed, 7 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | PASSED: one head, `0016_universe_replay_asof` |

The seven skipped tests require an isolated PostgreSQL integration database.

## Confirmed defect

`app/services/signals.py::select_cost_aware_scenario` stores both the model's conditional `timeout_return_r` and its absolute gross return at the signal reference. The estimator target is explicitly defined in `app/ml/training.py::timeout_return_r_targets` as realized TIMEOUT gross return divided by contemporaneous gross stop distance.

`app/services/execution.py::signal_timeout_return_rate` nevertheless read only the stored signal-reference absolute rate. Both `create_execution_plan` and `validate_execution_plan_for_acceptance` could then evaluate a different current ask/bid or depth VWAP while retaining the old absolute TIMEOUT percentage.

Impact: current plan EV did not preserve the trained stop-risk-unit semantics. An adverse entry could make TIMEOUT less negative than the model implies and create a false-positive policy pass; the reverse move could create a false block. Severity: **high mathematical/trading correctness defect**.

Existing tests checked reuse of the stored signal assumption but did not change entry geometry while retaining conditional `R`.

## Red evidence

Before implementation, the new LONG and SHORT contract cases failed:

```text
test_execution_reprojects_conditional_timeout_r_to_current_entry_geometry
TypeError: signal_timeout_return_rate() got an unexpected keyword argument 'entry'
```

Command:

```bash
python -m pytest -q tests/unit/test_conditional_timeout_economics_2026_07_02.py -k reprojects
```

Result: **2 failed** for the expected missing current-entry contract.

The independent gate regression demonstrates material impact:

- stale absolute TIMEOUT rate: `EV = 0.0526131219700800R`;
- current-entry `R` projection: `EV = 0.0234824376171073R`;
- configured minimum: `0.05R`.

The stale calculation would pass; the corrected calculation blocks.

## Implemented correction

- Added optional current execution entry to `signal_timeout_return_rate`.
- For conditional signals, validate finite `timeout_return_r`, current directional TP/SL geometry and positive gross stop distance.
- Reproject immutable `R` onto the current gross stop distance.
- Clamp to current support `[-1R, gross TP distance / gross stop distance]` exactly as signal publication/policy evaluation do.
- Pass converged plan bid/ask/depth VWAP during plan creation.
- Pass fresh executable price during acceptance validation.
- Preserve stored absolute TIMEOUT rate for legacy signals without conditional `R`.
- Raise plan evidence schema to `tp-sl-timeout-current-entry-r-v2`.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 704 passed, 7 skipped, 62 warnings |
| focused conditional TIMEOUT/execution suite | PASSED: 58 passed |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | PASSED: one head, `0016_universe_replay_asof` |

## Not run / residual limitations

- PostgreSQL integration tests and `manage.py test --require-integration`: NOT RUN because no isolated `TEST_DATABASE_URL` was available.
- `manage.py doctor`: NOT RUN because this sandbox does not contain the operator's configured PostgreSQL/Bybit runtime.
- Actual exchange/orderbook forward evidence: NOT RUN; the project remains advisory-only.
- This correction prevents one EV misclassification mechanism. It does not establish profitability, calibrate thresholds, or explain every past loss.
- Previously persisted execution plans remain immutable historical evidence and are not rewritten. They should be recalculated before acceptance.

# Iteration report — conditional TIMEOUT current-entry repricing

## 1. Input

- Archive: `cost_aware_momentum-1.35.0-outcome-attribution.zip`
- SHA-256: `5aa987b761d8ccd4f5554e1dd17b724b2ce6bc5340d167700e01b80ed0375f88`
- Source version: 1.35.0
- Target version: 1.35.1

## 2. Goal and acceptance criteria

After this iteration, execution-plan creation and acceptance must preserve the trained conditional TIMEOUT estimate in stop-risk units when the executable entry differs from the signal reference.

Acceptance criteria:

1. LONG and SHORT current-entry projections equal bounded `timeout_return_r × current gross stop distance`.
2. Current ask/bid or converged depth VWAP is used by plan economics.
3. Fresh acceptance price is used by acceptance economics.
4. A stale absolute rate cannot falsely pass `MIN_NET_EV_R` in the demonstrated boundary case.
5. Legacy signals without conditional `R` remain compatible.
6. Invalid/non-finite conditional estimates and invalid geometry fail closed.
7. Full suite and static checks remain green.

## 3. Sources and data flow

Read: README, CHANGELOG, patches 1.34.0–1.35.0, QA, compliance, traceability, package/config, signal publication, ML target construction, risk math, execution-plan construction/acceptance and related tests.

Changed flow:

`artifact timeout_return_r` → signal scenario bounded by signal TP/SL geometry → immutable signal snapshot → current ask/bid/depth VWAP → current TP/SL gross support → plan EV/RR → persisted plan evidence → fresh acceptance price → acceptance EV/RR.

## 4. Baseline

- pip check: PASSED
- compileall: PASSED
- Ruff: PASSED
- pytest: 699 passed, 7 skipped, 62 warnings
- JavaScript syntax: PASSED
- Alembic: one head, `0016_universe_replay_asof`

## 5. Confirmed defect

**Severity: high. Category: mathematical/trading correctness.**

`timeout_return_r_targets` defines the learned TIMEOUT estimate in gross stop-risk units. Signal publication correctly maps it to signal-reference absolute return. Execution and acceptance later reused that absolute return after entry/VWAP changed, rather than preserving `R`.

Minimal LONG example:

- signal reference: 100;
- stop: 98;
- current entry: 100.4;
- conditional estimate: -0.5R;
- stale absolute rate: -1.0%;
- correct current rate: `-0.5 × (100.4-98)/100.4 = -1.195219...%`.

With TP 104, probabilities 0.36/0.24/0.40 and configured cost structure, stale EV is 0.0526R while correct EV is 0.0235R. The stale calculation crosses the 0.05R gate in the unsafe direction.

Tests missed this because the existing contract asserted immutable absolute-rate reuse without changing entry geometry.

## 6. Diff

Production:

- `app/services/execution.py`
- `app/__init__.py`
- `pyproject.toml`

Tests:

- `tests/unit/test_conditional_timeout_economics_2026_07_02.py`
- `tests/unit/test_execution_acceptance_safety.py`

Docs/release:

- `README.md`
- `CHANGELOG.md`
- `PATCH_1.35.1.md`
- `docs/QA_REPORT.md`
- `docs/SPEC_COMPLIANCE.md`
- `docs/TRACEABILITY.md`
- this report
- `SHA256SUMS`

No migration or environment change.

## 7. Red → green

Red command:

```bash
python -m pytest -q tests/unit/test_conditional_timeout_economics_2026_07_02.py -k reprojects
```

Red result: 2 failed with unexpected `entry` argument.

Green evidence:

- LONG and SHORT projection regressions pass;
- false-positive EV boundary regression passes;
- current-VWAP plan evidence regression passes;
- non-finite conditional `R` fail-closed regression passes;
- focused suite: 58 passed;
- full suite: 704 passed, 7 skipped.

## 8. Compatibility and rollback

- Migration: none.
- `.env`: none.
- Artifact schema: unchanged.
- API: backward compatible.
- Legacy signal without `timeout_return_r`: stored absolute return/fallback retained.
- Existing plans are not rewritten.

Rollback: restore 1.35.0 code and restart processes. This reintroduces stale absolute TIMEOUT repricing; do not accept recalculated plans under 1.35.0 when current entry differs materially from signal reference.

## 9. Unverified

- Live PostgreSQL integration and production-size orderbook paths.
- Real forward performance and actual manual fills.
- Whether this defect is the dominant source of historical losses.
- Statistical adequacy of current thresholds after enough v1.35.1 forward outcomes accumulate.

## 10. Recommended next work package

Audit point-in-time quote selection: a future-dated/latest ticker row can currently mask an older valid recent row and suppress publication. Prove the condition against DB ordering and add latest-available-at-`now` semantics without weakening stale-data gates.

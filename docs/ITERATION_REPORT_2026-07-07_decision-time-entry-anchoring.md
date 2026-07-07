# Iteration report — decision-time entry anchoring

Date: 2026-07-07

## 1. Input and baseline

- Input archive: `cost_aware_momentum-1.39.0-decision-execution-snapshot-freshness.zip`.
- Input SHA-256: `8638c6a90a77ee07ab30142914294f6fc9ae200ddce8ca65d4d91e4202fbb875`.
- Source version: `1.39.0`.
- Python: 3.13.5; project requirement: Python >=3.12.
- Alembic head: `0017_model_artifact_blobs`.
- Baseline inventory: 124 production/config/migration files, 104 test files and 31 documentation/release files.

Baseline commands:

| Command | Result |
|---|---|
| `python -m pip check` | FAILED only because the shared environment has `moviepy 2.2.1` requiring `pillow<12` while Pillow 12.2.0 is installed; the project does not depend on moviepy |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 755 passed, 8 skipped |
| `node --check web/js/app.js` | PASSED |

No operator PostgreSQL database or live Bybit account was accessed.

## 2. Goal and acceptance criteria

After this iteration, a model decision must remain bound to the exact confirmed decision-candle close. Historical labels and live publication must reject an entry that has moved outside the same ATR-scaled zone, late publication must fail closed, and the contract must be immutable in model/promotion evidence.

Acceptance criteria:

1. Live entry zone is not centered on the latest quote.
2. A quote outside the decision zone cannot produce a signal.
3. Historical next-hour-open proxies outside the same zone are excluded as complete LONG/SHORT pairs.
4. Publication beyond the configured lag is blocked.
5. Expiry is anchored to event time.
6. Artifact and promotion schemas bind the new parameters, and live publication rejects artifact/config drift.
7. Existing risk, EV/RR, spread, holdout and walk-forward thresholds remain unchanged.

## 3. Read sources and data flow

Reviewed README, changelog, patches 1.36.0–1.39.0, QA/spec/traceability documents, configuration, model training/lifecycle/runtime, signal publication, execution repricing, outcomes and relevant tests.

Affected flow:

`confirmed decision candle close → feature snapshot → directional probabilities → fixed decision entry zone → current bid/ask validation → stop/TP/net economics → MarketSignal → ExecutionPlan`

Research flow:

`decision candle close → next-hour open ± half spread → fixed decision entry-zone validation → TP/SL/TIMEOUT path → temporal split → policy evaluation → artifact/promotion evidence`

## 4. Confirmed defects

### HIGH — live entry zone moved with the current quote

File: `app/services/signals.py`, `select_cost_aware_scenario`.

Actual behavior: the function validated `last_price` but centered `entry_low`/`entry_high`, stop and TP around current ask or bid. A delayed inference therefore converted old probabilities into a new trade at a new price.

Expected behavior: the admissible entry zone is immutable and centered on the price available at model decision time.

Impact: financial/model risk; potentially stale edge, distorted barrier geometry and losses after late catch-up or rapid post-close movement.

Why tests missed it: prior tests verified tick alignment and current-quote geometry but did not use a distinct decision anchor.

### HIGH — historical labels did not enforce the live entry band

File: `app/ml/training.py`, `make_barrier_dataset`.

Actual behavior: any finite next-hour open became the entry proxy, even after a large gap from decision close. Live displayed an entry band, but research did not reject observations outside it.

Expected behavior: the exact same entry admissibility contract is applied to research and live paths.

Impact: research/live distribution mismatch and overstated actionability for entries unavailable at the original decision.

### HIGH — late publication extended and re-anchored the decision

File: `app/services/signals.py`, `publish_hourly_signals`.

Actual behavior: catch-up could publish at an arbitrary later minute and `expires_at` was calculated from publish time.

Expected behavior: a bounded publication delay and expiry fixed to event time.

Impact: recommendations could be acted upon after their intended entry opportunity had disappeared.

### MEDIUM — entry timing was absent from promotion binding

File: `app/services/model_promotion.py`.

Actual behavior: the immutable deployment policy included spread and cost thresholds but not entry-zone width or publication lag.

Impact: evidence could be reused under a different live timing contract.

## 5. Red → green evidence

Command:

```text
python -m pytest -q tests/unit/test_decision_anchor_entry_alignment_2026_07_07.py
```

On untouched 1.39.0: `7 failed` for missing decision anchor, missing research zone, missing publication boundary and absent binding/config fields.

After correction: `7 passed`.

The tests independently check a far-moved quote, exact zone coordinates, historical gap exclusion, persisted label metadata, event-time expiry/publication lag, promotion binding changes and fail-closed artifact/runtime contract mismatch.

## 6. Implemented diff

Production/configuration:

- `app/config.py`
- `app/ml/training.py`
- `app/ml/lifecycle.py`
- `app/ml/runtime.py`
- `app/services/signals.py`
- `app/services/model_promotion.py`
- `app/workers/trainer.py`
- `scripts/train.py`
- `scripts/backtest.py`
- `.env.example`
- `app/__init__.py`
- `pyproject.toml`

Tests:

- added `tests/unit/test_decision_anchor_entry_alignment_2026_07_07.py`;
- updated existing artifact, promotion, entry-label and signal tests to the new contract.

Documentation/release:

- `README.md`, `CHANGELOG.md`, `PATCH_1.40.0.md`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- this report and `SHA256SUMS`.

## 7. Compatibility and rollback

- Migration: none.
- New configuration defaults: `ENTRY_ZONE_ATR_FRACTION=0.12`, `MAX_SIGNAL_PUBLICATION_DELAY_SECONDS=600`.
- Old artifacts are intentionally incompatible and fail closed. Retraining is required.
- Rollback requires restoring 1.39.0 code and its compatible artifact; do not relabel a 1.40 artifact as an older schema.
- Existing DB rows are not changed.

## 8. Post-check

| Command | Result |
|---|---|
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| new regression suite | PASSED: 7 passed |
| `python -m pytest -q` | PASSED: 762 passed, 8 skipped |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED: one head, `0017_model_artifact_blobs` |

`pip check` retained the same unrelated shared-environment moviepy/Pillow conflict.

## 9. Not verified and residual risks

- No isolated PostgreSQL integration run.
- No real Bybit public/private API run.
- No full retraining on the operator dataset.
- No measurement of how many historical/live opportunities are removed by the new zone.
- Historical depth, queue/fill probability and sub-hour path remain unavailable.
- Operator latency inside the allowed zone remains only prospectively observable.
- Technical correctness does not establish economic profitability.

## 10. Recommended next work package

Build a forward outcome attribution report that separates losses by publication lag, distance from decision anchor, spread, depth/VWAP impact, baseline versus artifact model, and gate margin. This should use actual immutable signal/plan/fill evidence and must not change thresholds until enough forward observations exist.

# Iteration report — executable-spread replay alignment

Date: 2026-07-07
Target release: 1.37.0

## 1. Input archive and baseline identity

- Input: `cost_aware_momentum-1.36.0-model-artifact-durability.zip`
- SHA-256: `2d9b7a6d824a714c8c01a4bf8cbd68ee2018ccd911cf232b5ce959339b84e0e0`
- Source version: 1.36.0
- Python requirement: >=3.12
- Runtime used: Python 3.13.5
- Alembic head: `0017_model_artifact_blobs`
- Inventory: 98 production/script Python files, 101 original test files, 13 documentation files, 4 web files, 17 migration revisions.

## 2. Iteration objective and acceptance criteria

Objective:

> After this iteration, dynamic training, candidate policy evaluation and formal backtest must exclude every symbol-hour that the live publication layer would deterministically reject under the configured executable spread limit, and normal promotion must be bound to that exact limit.

Acceptance criteria:

1. Full immutable universe rows remain hash-validated before compact replay data is retained.
2. Selected symbols are partitioned by stored point-in-time spread against exact `MAX_SPREAD_BPS`.
3. Training and backtest use the execution-eligible partition rather than broad discovery membership.
4. Replay fails closed when its stored threshold differs from the requested threshold.
5. Promotion-policy evidence changes when `MAX_SPREAD_BPS` changes.
6. Candidate profile describes actual post-replay model rows, not pre-replay raw candles.
7. Background preflight and actual fit receive the same configured spread contract.
8. Existing spread/quality/holdout/walk-forward/EV/RR/risk thresholds are not weakened.

## 3. Sources read and affected data flow

Read before modification:

- `README.md`, `CHANGELOG.md`, `PATCH_1.35.3.md`, `PATCH_1.35.5.md`, `PATCH_1.36.0.md`;
- `pyproject.toml`, `.env.example`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- `app/config.py`, `app/services/universe.py`, `app/services/signals.py`;
- `app/ml/universe_replay.py`, `app/ml/lifecycle.py`, `app/ml/training.py`;
- `app/services/model_promotion.py`, `app/workers/trainer.py`;
- `scripts/train.py`, `scripts/backtest.py`;
- related unit and PostgreSQL integration contracts.

Affected flow:

`Bybit all-tickers → dynamic universe decision with immutable bid/ask/spread → PostgreSQL universe snapshot → latest-prior as-of loader → executable-spread partition → barrier dataset replay → temporal split/model/policy metrics → preregistered backtest configuration → promotion binding → ordinary activation`.

Live comparison path:

`fresh decision-time ticker → app.services.signals._spread_bps → MAX_SPREAD_BPS hard skip → signal publication`.

Both spread formulas use `(ask - bid) / midpoint × 10000`.

## 4. Baseline before production changes

Commands and results:

| Command | Result |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | FAILED — unrelated global environment conflict: moviepy 2.2.1 requires Pillow <12, installed Pillow 12.2.0 |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 738 passed, 8 skipped |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — one head `0017_model_artifact_blobs` |

`manage.py doctor` and required PostgreSQL integration were not run because no isolated database/operator configuration was available.

## 5. Confirmed defects and evidence

### DEFECT-1 — research/live spread cohort mismatch

Classification: `CONFIRMED DEFECT`
Severity: HIGH

Files/functions:

- `app/services/universe.py::select_dynamic_universe`
- `app/ml/universe_replay.py::load_point_in_time_universe_snapshots`
- `app/ml/universe_replay.py::apply_point_in_time_universe_replay`
- `app/services/signals.py::_spread_bps` and `publish_hourly_signals`

Evidence:

- Default broad universe threshold: 30 bps.
- Default live executable threshold: 18 bps.
- Snapshot decision payload already stored exact per-symbol spread.
- Compact loader discarded decision spread and retained only selected symbols.
- Replay admitted all selected symbols.
- Live publication skipped spread >18 bps, matching the supplied `CHILLGUYUSDT` and `MOVRUSDT` logs.

Expected: historical policy cohort matches the hard executable live cohort.
Actual: observations in the 18–30 bps band entered research but could not enter live publication.

Impact:

- biased/incomparable trade-rate evidence;
- candidate/live attrition mismatch;
- OOS metrics could include structurally untradeable observations;
- rare live recommendations could coexist with apparently less restrictive research evidence.

Existing tests checked point-in-time membership and stale/hash behavior, but not the second live spread boundary.

### DEFECT-2 — executable limit absent from promotion binding

Classification: `CONFIRMED DEFECT`
Severity: HIGH

File: `app/services/model_promotion.py`

Expected: changing a hard live eligibility contract invalidates prior promotion evidence.
Actual: binding v2 omitted `MAX_SPREAD_BPS`; only entry stress and other cost/risk parameters were bound.

Impact: an experiment produced for one executable cohort could be reused after changing the live hard spread gate.

### DEFECT-3 — candidate profile described pre-replay source data

Classification: `CONFIRMED DEFECT`
Severity: MEDIUM

File/function: `app/ml/lifecycle.py::build_model_candidate`

Expected: artifact/registry profile reflects rows actually available to the fitted candidate.
Actual: profile was computed from raw input candles with a cutoff, before point-in-time universe replay. It could include pre-rollout, universe-ineligible and live-spread-ineligible symbols. LONG/SHORT model rows also require deduplication for candle-level profile counts.

Impact: incorrect retraining comparison, row/symbol coverage and operator diagnostics.

### Observed but not changed in this work package

- `not_enough_history_for_bootstrap` with 1206 required timestamps is a deliberate necessary precondition derived from warm-up, horizon, split, purge and walk-forward geometry.
- Pre-ledger history cannot be honestly assigned historical dynamic-universe membership from current data.
- Lowering holdout, stability, trade-rate or spread gates would be a fail-open workaround and was rejected.

## 6. Plan and actual diff

Production:

- `app/ml/universe_replay.py`
- `app/ml/lifecycle.py`
- `app/services/model_promotion.py`
- `app/workers/trainer.py`
- `scripts/train.py`
- `scripts/backtest.py`
- `app/__init__.py`
- `pyproject.toml`
- `.env.example`

Tests:

- new `tests/unit/test_executable_spread_replay_alignment_2026_07_07.py`
- updated point-in-time replay, PostgreSQL loader, policy binding, activation and integration contracts.

Documentation:

- `README.md`
- `CHANGELOG.md`
- `PATCH_1.37.0.md`
- `docs/QA_REPORT.md`
- `docs/SPEC_COMPLIANCE.md`
- `docs/TRACEABILITY.md`
- this report.

Migration: none.

## 7. Red → green evidence

Command:

```text
python -m pytest -q tests/unit/test_executable_spread_replay_alignment_2026_07_07.py
```

Untouched 1.36.0 result: **6 failed**.

Substantive red causes:

- replay APIs did not accept an executable spread contract;
- compact loader had no executable partition;
- profile helper did not exist;
- promotion binding was v2;
- preflight did not forward the threshold.

After correction: **6 passed**.

Focused compatibility command covering old replay, loader, promotion, activation and quant-integrity tests: **38 passed**.

## 8. Compatibility

- Alembic migration: none; head remains `0017_model_artifact_blobs`.
- New environment variables: none.
- Existing snapshot rows: compatible because spread evidence was already inside immutable decisions.
- Public HTTP API: unchanged.
- Advisory-only/read-only Bybit boundary: unchanged.
- Active artifacts: continue runtime inference.
- Inactive candidates/experiment evidence using policy binding v2: ordinary activation must fail closed and new evidence must be produced under binding v3.
- Universe replay evidence schema: v1 → v2.

Rollback:

1. Stop trainer/research processes.
2. Restore 1.36.0 application files.
3. No database downgrade is needed.
4. Do not treat any v3 experiment evidence as v2 evidence; retraining/backtest should be repeated after rollback if ordinary promotion is required.

## 9. Post-change verification

| Command | Result |
|---|---|
| `python -m pip check` | FAILED — unchanged unrelated moviepy/Pillow conflict |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| focused new suite | PASSED — 6 passed |
| focused compatibility suites | PASSED — 38 passed |
| `python -m pytest -q` | PASSED — 744 passed, 8 skipped |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — one head `0017_model_artifact_blobs` |

No previously green test became red.

## 10. Not verified

- Real PostgreSQL as-of query and streaming behavior in the operator environment.
- Full trainer/backtest run against the operator's historical database.
- Actual proportion of rows excluded by spread in the user's database.
- Live forward profitability, manual fill quality or causal source of past losses.
- Historical orderbook depth, latency, queue position and partial fill probability.

## 11. Residual risks and limitations

- The executable historical spread is the latest committed universe observation available at decision time; it is not guaranteed to equal a later decision-publication refresh tick exactly.
- Universe snapshots begin prospectively; pre-ledger history remains unavailable for honest dynamic replay.
- Static-mode historical datasets do not have the same prospective spread ledger.
- A stricter honest cohort can reduce data and delay training; the patch does not fabricate observations or lower 1206/holdout/walk-forward requirements.
- Low live recommendation rate may also arise from EV/RR, funding, context completeness, min-size, margin or activation blockers; this iteration fixes one demonstrated mismatch only.

## 12. Recommended next work package

Build a bounded **history-readiness attribution report** that decomposes the 1206-timestamp shortfall by stage:

`raw confirmed candles → continuity → mark/index/OI/funding completeness → prospective universe coverage → executable-spread coverage → barrier labels → final split/holdout/walk-forward eligibility`.

The report should expose per-stage timestamp/symbol losses in trainer status without weakening any gate. That will distinguish slow prospective ledger accumulation from a broken 365-day backfill or missing market-context history.

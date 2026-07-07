# QA Report

Release: **1.37.0**

Date: **2026-07-07**
Scope: **point-in-time executable-spread cohort alignment across dynamic research and live publication**

## Environment

- Python: 3.13.5.
- Project requirement: Python >=3.12.
- Input archive: `cost_aware_momentum-1.36.0-model-artifact-durability.zip`.
- Input SHA-256: `2d9b7a6d824a714c8c01a4bf8cbd68ee2018ccd911cf232b5ce959339b84e0e0`.
- Source version: 1.36.0.
- Alembic head before and after: `0017_model_artifact_blobs`.
- Input inventory: 98 production/script Python files, 101 existing test Python files plus one new regression file, 13 files in `docs/`, 4 web files and 17 migration revisions.
- Separate PostgreSQL integration database: not configured.

Dependencies were installed from `pyproject.toml`. The baseline and post-change checks were run in the same container environment.

## Baseline before production changes

| Check | Result |
|---|---|
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | FAILED: unrelated environment conflict — `moviepy 2.2.1` requires `pillow<12`, installed Pillow is 12.2.0 |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 738 passed, 8 skipped |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED: one head, `0017_model_artifact_blobs` |

`python manage.py doctor` and `python manage.py test --require-integration` were not run because no operator configuration or isolated PostgreSQL test URL was available. The operator database was not accessed.

## Confirmed defects

### 1. Research/live executable-spread cohort mismatch — HIGH

`UNIVERSE_MAX_SPREAD_BPS=30` is a broad discovery threshold, while `MAX_SPREAD_BPS=18` is the live executable publication threshold. Immutable universe snapshots retained per-symbol point-in-time spread, but `app/ml/universe_replay.py` discarded it and replayed membership using only `selected_symbols`.

A symbol with spread 25 bps therefore entered training, holdout and formal policy evaluation, while `app/services/signals.py` deterministically skipped it in live operation. The supplied logs for `CHILLGUYUSDT` and `MOVRUSDT` demonstrate this live terminal path. This mismatch could distort policy trade rate, OOS metrics and candidate/live attrition.

### 2. Executable spread absent from immutable promotion binding — HIGH

`model-promotion-policy-binding-v2` bound entry stress, fees, slippage, risk and EV/RR thresholds, but not `MAX_SPREAD_BPS`. A governed experiment generated under one hard live spread limit could therefore remain syntactically eligible after the live threshold changed.

### 3. Candidate data profile described the wrong cohort — MEDIUM

`build_model_candidate` computed `training_data_profile` from raw input candles, while the model was fit on the smaller point-in-time replayed direction-specific dataset. This could misstate row/symbol coverage and produce incorrect retraining comparisons. LONG/SHORT rows also needed deduplication back to one source candle per symbol/hour for a candle-oriented profile.

## Red evidence

The final regression file was run against an untouched 1.36.0 tree:

```text
python -m pytest -q tests/unit/test_executable_spread_replay_alignment_2026_07_07.py
```

Result: **6 failed**. The failures established that:

- loader/replay had no executable-spread contract;
- replay did not exclude selected-but-live-untradeable symbols;
- threshold mismatch could not be detected;
- candidate profile helper for actual model rows did not exist;
- promotion binding remained schema v2;
- background profile did not forward the live spread threshold.

## Implemented correction

- Raised universe replay evidence to `point-in-time-universe-replay-v2`.
- Raised PostgreSQL compact loader evidence to `postgresql-native-universe-asof-loader-v2`.
- Full immutable snapshots remain hash-validated before compacting.
- For each selected decision, stored `ticker.spread_bps` is compared with exact `MAX_SPREAD_BPS`; invalid/missing spread is fail-closed ineligible.
- Replay partitions selected symbols into executable and spread-ineligible cohorts and filters both LONG and SHORT model rows consistently.
- Replay evidence records exact threshold, excluded row count and affected selected symbols.
- Threshold mismatch between loader evidence and caller blocks research.
- Background preflight, fit, manual train and formal backtest pass the same settings value.
- Promotion-policy binding is now v3 and includes `maximum_executable_spread_bps`.
- Candidate data profile is based on actual post-replay model rows and deduplicated to source candle identity.
- Existing live threshold values and all model/risk gates remain unchanged.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | FAILED: same unrelated `moviepy`/Pillow environment conflict as baseline |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| focused new regression suite | PASSED: 6 passed |
| focused compatibility suites | PASSED: 38 passed |
| `python -m pytest -q` | PASSED: 744 passed, 8 skipped |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED: one head, `0017_model_artifact_blobs` |

No previously passing test regressed. The eight skipped tests are PostgreSQL integration contracts requiring an isolated database.

## Migration, configuration and compatibility

- New migration: none.
- New `.env` variable: none.
- Existing `UNIVERSE_MAX_SPREAD_BPS` and `MAX_SPREAD_BPS` values are unchanged.
- Existing universe snapshot rows remain usable because bid/ask and `spread_bps` were already stored in immutable decision payloads.
- Existing active artifact can continue inference.
- Inactive candidates and experiment evidence with policy-binding v2 require retraining/re-evaluation for ordinary activation under v3.
- Universe replay evidence v1 is not accepted as equivalent to v2 for new research evidence.

## Not run / residual limitations

- PostgreSQL execution of the as-of loader and integration suite was not run.
- No operator database, Bybit account or live services were accessed.
- Historical membership before the prospective universe ledger began cannot be reconstructed; those rows remain excluded.
- Snapshot spread is the latest committed point-in-time observation used for the decision timestamp, not historical orderbook depth, queue position or guaranteed fill evidence.
- Static-universe historical research has no prospective universe spread ledger and therefore cannot receive the same dynamic replay filter; production defaults are dynamic.
- This correction can reduce the eligible historical sample and does not solve insufficient prospective history by weakening the 1206-timestamp requirement.
- Technical alignment does not establish economic edge or explain the user's historical manual losses causally.

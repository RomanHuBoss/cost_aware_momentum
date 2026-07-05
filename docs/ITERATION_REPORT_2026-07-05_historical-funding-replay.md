# Iteration report — historical funding settlement replay

## 1. Input and baseline

- Input archive: `cost_aware_momentum-1.11.0-walk-forward-validation(1).zip`
- Input SHA-256: `baa8f91d086ed91358ae67a4c6f9a0f646963ad6f006bcae7e26e3dcb45442bd`
- Input version: 1.11.0
- Python: 3.13.5
- Alembic head: `0009_candle_receipt_availability` (9 revisions)
- Reproducible baseline after installing declared review tooling: 476 passed, 4 skipped; Ruff/compileall/Node passed.

## 2. Goal and acceptance criteria

After this iteration, research evaluation must debit or credit funding only when a modeled position actually crosses an observed Bybit settlement timestamp, must fail closed on an incomplete settlement timeline, and must not use future actual funding rates to select a direction.

Acceptance criteria:

1. Historical funding events are progressively fetched with bounded read-only pagination and stored idempotently.
2. Aggregation uses the exact interval `(entry_time, actual_exit_time]`.
3. Missing anchor or expected settlement blocks the cohort rather than imputing zero.
4. Positive exchange funding costs LONG and benefits SHORT; negative funding reverses the sign.
5. Future actual rates affect realized PnL only, never ex-ante RR/EV/actionability/direction.
6. Candidate artifact, runtime and promotion gate enforce one historical-funding schema.
7. Existing advisory-only, PostgreSQL-only and incumbent-safety invariants remain unchanged.

## 3. Sources and affected data flow

Read: README, CHANGELOG, PATCH_1.10.0/1.11.0, architecture, QA, compliance, traceability, model card, configuration, security, runbook, operator manual, Bybit client, market-data worker, training/lifecycle/runtime and related tests.

Affected flow:

`Bybit public funding history → market.funding → TrainingMarketData → HistoricalFundingTimeline → label metadata → final holdout/walk-forward policy realized PnL → artifact/gate/runtime → research report`.

The endpoint contract was checked against official Bybit V5 documentation: funding history is exposed as a public GET endpoint, returns `fundingRateTimestamp`, caps `limit` at 200 and supports bounded history retrieval with `endTime`; instrument metadata supplies `fundingInterval`.

## 4. Baseline

| Command | Result |
|---|---|
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | 476 passed, 4 skipped |
| `node --check web/js/app.js` | PASSED |
| `python -m pip check` | FAILED only on unrelated host moviepy/pillow conflict |
| PostgreSQL integration | NOT RUN/SKIPPED: isolated test URL absent |

## 5. Confirmed defects and gaps

### HIGH — scalar funding was not tied to actual settlement events

- Evidence: input `scripts/backtest.py` and training policy accepted a scalar scenario; no event-by-event timeline was loaded into research labels.
- Actual behavior: funding could be charged without proving a settlement occurred before the modeled exit.
- Expected behavior: count only actual settlements in `(entry, exit]`.
- Impact: biased realized returns, policy metrics and promotion evidence.
- Why tests missed it: no independent settlement-boundary or missing-event test existed.

### HIGH — no progressive research-grade funding history coverage

- Evidence: the live worker fetched recent funding observations, while deep history backfill covered candles only.
- Impact: even a correct replay could not establish complete historical coverage.
- Classification: confirmed gap.

### Design hazard prevented during implementation — future-funding look-ahead

Actual future settlement rates are valid realized costs but invalid ex-ante inputs. A dedicated regression now proves they cannot alter direction selection, and the activation gate rejects evidence claiming such a source.

## 6. Implemented diff

Production:

- `app/ml/funding.py`: validated event-time timeline, completeness and directional cash-flow signs.
- `app/bybit/client.py`: bounded funding-history parameters and response validation.
- `app/services/market_data.py`: candidate detection and progressive settlement backfill.
- `app/workers/runner.py`: candle and funding history progress in the existing backfill job.
- `app/ml/lifecycle.py`: unified training market-data load, artifact metadata and gate checks.
- `app/ml/training.py`: horizon/actual-exit settlement metadata and realized policy cash flows.
- `app/ml/runtime.py`: mandatory funding schema/timeline validation.
- `app/workers/trainer.py`, `scripts/train.py`: pass funding context into candidate training.
- `scripts/backtest.py`: actual settlement replay for realized PnL; scalar override remains adverse ex-ante stress only.

Tests:

- New `tests/unit/test_historical_funding_replay_2026_07_05.py`.
- Added gate regression in `tests/unit/test_model_lifecycle.py`.
- Updated artifact/metrics fixtures to the new mandatory schema.

No migration and no new environment variable were required.

## 7. Red → green

Red on untouched 1.11.0:

```text
ModuleNotFoundError: No module named 'app.ml.funding'
```

Green on 1.12.0:

- 7 tests in the new funding replay module passed.
- Gate regression passed.
- Full suite increased from 476 to 484 passing tests; 4 PostgreSQL tests remain skipped.

## 8. Compatibility

- Database: existing `market.funding` table reused; Alembic head unchanged.
- API/UI: unchanged.
- `.env`: unchanged; existing `HISTORY_BACKFILL_*` settings drive both candle and funding backfill.
- Artifacts: 1.11.0 and older are intentionally incompatible because they lack funding timeline evidence.
- Incumbent: training/backfill failure does not deactivate the active model.

## 9. Post-check

| Command | Result |
|---|---|
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | 484 passed, 4 skipped |
| `node --check web/js/app.js` | PASSED |
| `python -m pytest -q -rs tests/integration_postgres` | 4 SKIPPED: `TEST_DATABASE_URL` absent |
| `python manage.py doctor` | environment-blocked: project `.venv` absent |
| `python -m pip check` | unrelated host moviepy/pillow conflict |

## 10. Not verified

- Real PostgreSQL migration/transaction integration in an isolated database.
- Network backfill across many pages and rate-limit behavior against live Bybit.
- Full-history model retraining and wall-clock resource consumption.
- Paper/shadow forward performance or profitability.

## 11. Residual risks and limitations

- Funding completeness currently uses the latest known instrument funding interval; historical interval changes are not reconstructed point-in-time.
- Historical indicative/forecast funding snapshots at decision time are unavailable; expected policy funding is therefore explicitly `none-no-point-in-time-forecast`.
- Funding remains a realized cost, not a model feature.
- Historical order book, VWAP impact, no-fill/partial-fill, intrahorizon MTM/liquidation and operator-selection correction remain separate work packages.

## 12. Rollback

1. Preserve the 1.12.0 artifact and database rows for audit; funding rows are append-only/idempotent observations and need not be deleted.
2. Restore the 1.11.0 code and its matching artifact.
3. Do not load a 1.12.0 artifact with 1.11.0 runtime.
4. Re-run doctor and paper/shadow checks after rollback.

## 13. Recommended next work package

Implement intrahorizon mark-to-market and path-dependent liquidation simulation using mark-price candles, without combining it with historical order-book/no-fill work in the same iteration.

## 14. Release archive verification

- Clean staged tree: 176 eligible files; forbidden caches, credentials, model artifacts and dumps absent.
- `scripts/release_integrity.py --write` and verify: PASSED, 176/176 entries.
- `unzip -t`: PASSED.
- Fresh re-extraction before test-generated caches: release integrity PASSED.
- Fresh re-extraction after execution: compileall, Ruff, Node syntax and full suite PASSED; 484 passed, 4 skipped.
- Order-mutation scan of `app/bybit`: no create/amend/cancel methods or endpoints found.

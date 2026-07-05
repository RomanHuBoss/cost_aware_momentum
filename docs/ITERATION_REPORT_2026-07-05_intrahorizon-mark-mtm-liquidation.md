# Iteration report — intrahorizon mark-to-market and liquidation proxy

Date: 2026-07-05

## 1. Input archive and baseline identity

- Input archive: `cost_aware_momentum-1.12.0-historical-funding-replay(1).zip`
- Input SHA-256: `292ecb76a87438dfe08700a28d7b822c897631357b9d1562d9551b88c0195a6e`
- Input version: `1.12.0`
- Python requirement: `>=3.12`; review host: Python 3.13.5
- Alembic revisions: 9; single head `0009_candle_receipt_availability`
- Input source counts: 71 production/research Python files, 62 test Python files, 13 documentation files, 9 migrations
- Input release integrity: PASSED, 176/176 manifest entries; no `.env`, secrets, virtual environments, caches, bytecode, model artifacts or dumps in the original ZIP

## 2. Iteration goal and acceptance criteria

Goal:

> After this iteration, research training and backtest must replay a complete hourly mark-price path through the modeled exit and apply a conservative realized-only isolated-margin liquidation proxy, while future mark data remains unable to affect model features, class labels, direction selection, RR, EV or actionability.

Acceptance criteria:

1. Progressive history backfill requests and stores explicit `price_type=mark` candles without adding order mutations.
2. Each label requires an exact continuous hourly mark timeline through the modeled last-price exit; missing or malformed bars fail closed for the whole LONG/SHORT cohort.
3. LONG and SHORT mark-to-market signs, MAE/MFE and minimum equity are directionally correct.
4. Exit-at-open and funding-settlement timing do not use information occurring after the effective exit.
5. A conservative mark liquidation can shorten only realized exit/PnL and cannot change `TP / SL / TIMEOUT`, probabilities or ex-ante policy ranking.
6. Artifact, runtime, promotion gate and candidate/incumbent comparison require compatible margin schema, leverage and reserve assumptions.
7. New regression tests pass, the full prior suite does not regress, and the release archive is clean and reproducible.

## 3. Sources read and affected data flow

Read before changes:

- `README.md`, `CHANGELOG.md`, `PATCH_1.10.0.md`, `PATCH_1.11.0.md`, `PATCH_1.12.0.md`
- `pyproject.toml`, `.env.example`
- `docs/ARCHITECTURE.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`
- market-data models/services, Bybit read-only client, training/labels/policy/lifecycle/runtime, trainer/worker, backtest and related unit/integration tests

Affected flow after the change:

```text
Bybit public mark-price kline GET
  -> progressive history backfill with price_type=mark
  -> existing PostgreSQL candle table
  -> TrainingMarketData(last candles + mark candles + funding)
  -> direction-specific last-price TP/SL/TIMEOUT label
  -> exact hourly mark path through modeled exit
  -> conservative isolated-margin MTM/liquidation replay
  -> realized-only exit/PnL/funding evidence
  -> walk-forward/final-holdout policy metrics
  -> immutable artifact + runtime/activation validation
  -> research report/backtest
```

The model features continue to come only from point-in-time last-price OHLCV. Future mark prices are not model inputs.

## 4. Baseline before changes

| Command | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED | Unrelated host conflict: `moviepy 2.2.1` requires `pillow<12`; host has `pillow 12.2.0`. |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0 |
| `python -m ruff check .` | PASSED | Exit 0 |
| `python -m pytest -q` | PASSED | 484 passed, 4 skipped |
| `node --check web/js/app.js` | PASSED | Exit 0 |
| `python manage.py doctor` | FAILED (environment) | Project `.venv` absent |
| PostgreSQL integration | NOT RUN | No isolated `TEST_DATABASE_URL`; production DB was not used |

## 5. Confirmed defect/gap

### HIGH — confirmed gap: no intrahorizon mark-to-market or path-dependent liquidation evidence

Evidence before the fix:

- `scripts/backtest.py` explicitly reported that intrahorizon mark-to-market was not modeled.
- `app/ml/training.py::make_barrier_dataset` used only last-price OHLC and terminal barrier outcome; it accepted no mark-price history.
- `TrainingMarketData` did not load hourly mark candles.
- Artifact/runtime/quality-gate contracts had no margin-path schema, leverage or liquidation evidence.
- A static pre-trade liquidation-distance guard in the live risk layer did not answer whether a historical position would have crossed a mark-price liquidation threshold before its modeled last-price exit.

Minimal failure mode:

1. Historical LONG is labelled/profitable by a later last-price TP.
2. Earlier within the horizon, the hourly mark low is adverse enough to exhaust the selected isolated-margin proxy.
3. Version 1.12.0 still records the later TP realized return because no mark path is evaluated.

Expected behavior: the class target may remain the market-model `TP`, but realized OOS economics must record the earlier margin failure and must not let future mark data influence the ex-ante decision.

Impact: optimistic policy/backtest evidence, distorted realized PnL and promotion metrics at leveraged assumptions.

Why tests missed it: no mark-path data contract, simulator or regression tests existed; artifacts were considered complete without margin evidence.

Classification boundary: this iteration fixes a research gap, not an exact exchange execution engine. Exact historical Bybit liquidation remains a documented limitation.

## 6. Plan and actual diff

### Production/research files

- Added `app/ml/mtm.py`: validated directional mark returns and conservative hourly isolated-margin path simulation.
- Updated `app/ml/training.py`: exact mark timeline, funding timing, realized-only application, policy metrics/schema.
- Updated `app/ml/lifecycle.py`: mark-data loading, candidate metadata, compatibility and promotion gates.
- Updated `app/ml/runtime.py`: fail-closed artifact validation and exposed assumptions.
- Updated `app/services/market_data.py`: typed last/mark/index historical backfill support.
- Updated `app/workers/runner.py`: independent mark-price history progress/backfill.
- Updated `app/workers/trainer.py`, `scripts/train.py`, `scripts/backtest.py`: pass/load/apply mark evidence.

### Tests

- Added `tests/unit/test_intrahorizon_liquidation_mtm_2026_07_05.py` with 9 tests.
- Updated artifact/metric fixtures in 13 existing unit modules to satisfy the new mandatory immutable contract.

### Version/docs

- Version raised from 1.12.0 to 1.13.0.
- Added `PATCH_1.13.0.md` and changelog entry.
- Updated README, architecture, model card, configuration, compliance, traceability, QA, security, runbook and operator manual.

### Scope deliberately excluded

- historical order book/depth/VWAP/no-fill/partial-fill;
- sub-hour mark event ordering;
- point-in-time historical Bybit MMR/risk tiers;
- liquidation fee, bankruptcy-price, cross/portfolio margin, ADL and insurance-fund mechanics;
- new ML features, PBO/Deflated Sharpe and production drift monitoring.

## 7. Red → green evidence

New regression module copied into an untouched 1.12.0 test tree:

```text
python -m pytest -q tests/unit/test_intrahorizon_liquidation_mtm_red_2026_07_05.py
```

Red result (exit 2):

```text
ModuleNotFoundError: No module named 'app.ml.mtm'
```

After implementation:

```text
python -m pytest -q tests/unit/test_intrahorizon_liquidation_mtm_2026_07_05.py
```

Green result:

```text
9 passed
```

The tests use manually constructed mark paths and independent directional/equity expectations rather than calling the tested function as their oracle.

## 8. Migration, API, configuration and compatibility

- Database migration: none. Existing candle storage already distinguishes `price_type`.
- Alembic head remains `0009_candle_receipt_availability`.
- Public API/UI: unchanged.
- `.env`: no new variable.
- Existing `HISTORY_BACKFILL_*` controls also govern mark-price backfill.
- Existing `DEFAULT_LEVERAGE` becomes part of the research artifact contract; changing it requires retraining.
- Fixed reserve is 10% of initial margin and is not exposed as a casual tuning knob.
- Artifacts 1.12.0 and older are intentionally incompatible and fail closed because they lack `bybit-mark-price-hourly-isolated-margin-proxy-v1` evidence.

## 9. Post-change checks

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | FAILED | Same unrelated host `moviepy`/`pillow` conflict |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0 |
| `python -m ruff check .` | PASSED | Exit 0 |
| `python -m pytest -q` | PASSED | 493 passed, 4 skipped |
| Targeted regression module | PASSED | 9 passed |
| `node --check web/js/app.js` | PASSED | Exit 0 |
| `python -m pytest -q -rs tests/integration_postgres` | SKIPPED | 4 skipped; `TEST_DATABASE_URL` absent |
| `python manage.py doctor` | FAILED (environment) | Project `.venv` absent |
| `python manage.py test --require-integration` | NOT RUN | No project `.venv` or isolated PostgreSQL test DB |
| Order-mutation source scan | PASSED | No create/amend/cancel order methods/endpoints found |

Final packaging verification:

| Check | Status | Result |
|---|---|---|
| Clean staged tree | PASSED | 180 eligible source/test/doc/config files plus `SHA256SUMS`; no forbidden cache, credential, model or dump artifacts |
| `scripts/release_integrity.py --write` + verify | PASSED | 180/180 manifest entries |
| `unzip -t` | PASSED | No compressed-data errors |
| Fresh re-extraction integrity | PASSED | 180/180 entries |
| Fresh re-extraction compile/Ruff/Node | PASSED | Exit 0 |
| Fresh re-extraction full suite | PASSED | 493 passed, 4 skipped |

## 10. Not verified

- Real network multi-page Bybit mark-price history backfill.
- PostgreSQL migration/integration suite against a disposable PostgreSQL instance.
- Full production-history retraining and candidate activation.
- Paper/shadow forward evidence.
- Exact historical exchange liquidation price/event.
- Profitability or live trading advantage.

## 11. Residual risks and limitations

1. Hourly OHLC does not reveal exact sub-hour ordering. Same-bar liquidation is conservatively placed before a later unordered last-price barrier outcome.
2. The proxy uses `initial_margin=1/leverage` and a fixed 10% initial-margin reserve; it does not reconstruct point-in-time MMR/risk tiers.
3. Liquidation gross loss is conservatively the full initial margin; exchange liquidation fee, bankruptcy price and possible residual equity are not modeled.
4. Cross/portfolio margin, shared account equity, ADL and insurance-fund mechanics are absent.
5. Historical mark candles do not solve entry bid/ask, depth, VWAP impact, no-fill, partial-fill or operator latency.
6. Historical funding interval changes remain approximated by the latest known interval metadata.

## 12. Rollback procedure

1. Preserve the 1.13.0 candidate artifacts and mark candles for audit; mark candles are read-only observations and need not be deleted.
2. Restore source release 1.12.0 and its previously active compatible artifact.
3. No database downgrade is needed.
4. Do not load a 1.13.0 artifact with 1.12.0 runtime.
5. Confirm model registry active version and perform the normal local doctor/smoke checks in the configured environment.

## 13. Recommended next work package

Implement point-in-time historical execution-quality evidence: best bid/ask and bounded depth snapshots with explicit operator latency, VWAP impact, no-fill and partial-fill outcomes. Keep it separate from feature expansion and operator-selection-bias correction so execution semantics can be tested independently.

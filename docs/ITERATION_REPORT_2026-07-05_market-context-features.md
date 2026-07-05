# Iteration Report — 2026-07-05 — point-in-time market-context features

## 1. Input archive and baseline identity

- Input archive: `cost_aware_momentum-1.15.0-operator-selection-bias(1).zip`
- Input SHA-256: `8d893f086785ddeaada52e0cf9c53687cc65b81023fbb81a7634aa001abb531d`
- Input size: 595458 bytes
- Input version: 1.15.0
- Input Alembic head: `0011_selection_experiment`
- Output version: 1.16.0
- Output Alembic head: unchanged, `0011_selection_experiment`
- Baseline inventory: 77 app/script Python files, 65 test Python files, 15 documentation files and 11 migration Python files

## 2. Iteration goal and acceptance criteria

Goal:

> After this iteration the artifact market model must consume strictly point-in-time OI, mark/index basis, settled funding and liquidity-context features, and activation must be blocked if those features are incomplete, temporally unsafe or materially inferior to the same model trained without them.

Acceptance criteria:

1. Add explicit OI momentum, basis, settled funding state and liquidity proxy features without future-event leakage.
2. Require exact timestamps and fail closed on gaps, duplicates, non-positive OI or non-finite values.
3. Backfill hourly index-price and open-interest history using bounded public/read-only requests.
4. Apply recorded receipt-time cutoff during live inference and document the weaker historical event-time replay boundary honestly.
5. Persist exact context/availability/ablation schemas in immutable artifacts and reject legacy/inconsistent artifacts at runtime.
6. Compare enriched and core-only models by independent refit on identical final holdout and three walk-forward folds.
7. Preserve advisory-only, PostgreSQL-only and existing process boundaries.
8. Add tests, synchronize release documentation and produce a clean verified ZIP.

## 3. Sources read and affected data flow

Read before and during implementation:

- `README.md`, `CHANGELOG.md`, `PATCH_1.13.0.md`, `PATCH_1.14.0.md`, `PATCH_1.15.0.md`;
- `pyproject.toml`, `.env.example`;
- `docs/ARCHITECTURE.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`;
- Bybit client, market-data service, worker, feature/training/lifecycle/runtime modules, signal publication, trainer/backtest scripts and related tests;
- official Bybit V5 open-interest, mark-price kline, index-price kline and funding-history documentation, checked 2026-07-05.

Affected flow:

```text
Bybit public GET
  -> confirmed last/mark/index candles + hourly OI + settled funding
  -> PostgreSQL event time and receipt time
  -> strict exact/backward-only market-context join
  -> 17-feature LONG/SHORT scenario rows
  -> purged train/calibration/walk-forward/final holdout
  -> independently refit context ablation
  -> immutable artifact and activation gate
  -> live receipt-filtered feature vector
  -> market signal
```

## 4. Baseline before changes

Validation used `/mnt/data/cam_venv_115`, an isolated environment installed from `pyproject.toml`, because the host interpreter lacked project packages. No production database was contacted.

| Command | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | No broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0 |
| `python -m ruff check .` | PASSED | Exit 0 |
| `python -m pytest -q` | PASSED | 522 passed, 4 skipped |
| `node --check web/js/app.js` | PASSED | Exit 0 |
| `python -m alembic heads` | PASSED | `0011_selection_experiment (head)` |

## 5. Confirmed defects and gaps

### CONFIRMED GAP — high — market model omitted available market context

Evidence:

- `app/ml/training.py::MODEL_FEATURE_NAMES` contained only ten OHLCV-derived features and `scenario_direction`.
- `docs/SPEC_COMPLIANCE.md` explicitly marked OI/basis/funding/liquidity/context features as not implemented in the model.
- OI and funding were stored for other purposes, but they were not part of training, artifacts or live inference.

Impact: the model could not condition probabilities on position build-up, perpetual/index dislocation, current settled funding state or a basic liquidity/participation regime.

Why tests did not catch it: the previous feature schema intentionally asserted the smaller input contract.

### CONFIRMED RISK — critical if implemented naively — temporal leakage and silent imputation

Historical public market endpoints expose exchange event timestamps but do not reconstruct the local receipt time that existed years ago. Joining the latest stored value without exact event semantics, or filling missing context with zero/forward values, would let unavailable or fabricated state enter training.

Resolution: exact OI and basis timestamps, backward-only settled funding, explicit historical-receipt limitation and live `available_at` filtering.

### CONFIRMED GAP — high — no evidence that added features improve or preserve OOS quality

No same-split ablation existed. Adding more inputs could worsen final holdout performance while appearing architecturally complete.

Resolution: independently refit a context-zeroed comparator on every final/walk-forward split; block material final regression and unstable folds.

### CONFIRMED OPERATIONAL DEFECT — high — live enrichment disabled by defaults

`UNIVERSE_SYNC_MARK_PRICE=false` and `UNIVERSE_ENRICH_FUNDING_OI=false` could stop current mark/index/OI/funding refresh once progressive historical coverage became complete. A context artifact would then skip nearly all live signals as incomplete.

Resolution: defaults and `.env.example` are true; existing `.env` requires explicit update.

### DOCUMENTED LIMITATIONS

- historical local receipt timestamps are not reconstructed;
- settled funding is not a funding forecast;
- liquidity feature is turnover/OI, not historical depth or fill probability;
- cross-asset and richer regime features remain absent.

## 6. Plan and actual file diff

Production/configuration:

- new `app/ml/context.py`;
- modified `app/ml/training.py`, `app/ml/lifecycle.py`, `app/ml/runtime.py`;
- modified `app/services/market_data.py`, `app/services/signals.py`, `app/workers/runner.py`, `app/workers/trainer.py`;
- modified `app/bybit/client.py`, `scripts/train.py`, `scripts/backtest.py`;
- modified `app/config.py`, `.env.example`, `app/__init__.py`, `pyproject.toml`.

Tests:

- new `tests/unit/test_market_context_features_2026_07_05.py`;
- updated model lifecycle, artifact/runtime and policy metric fixtures in the existing unit suite.

Documentation:

- `README.md`, `CHANGELOG.md`, `PATCH_1.16.0.md`;
- `docs/ARCHITECTURE.md`, `CONFIGURATION.md`, `MODEL_CARD.md`, `OPERATOR_MANUAL.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `QA_REPORT.md`;
- this iteration report.

Migration files: none.

## 7. Red → green evidence

The new regression module was copied into an untouched 1.15.0 tree.

Command:

```text
python -m pytest -q tests/unit/test_market_context_features_2026_07_05.py
```

Red result:

```text
ModuleNotFoundError: No module named 'app.ml.context'
```

Green result after implementation:

```text
7 passed
```

The new module verifies:

- exact OI at `t`, `t-1h`, `t-24h`;
- exact mark/index basis and prior-hour basis;
- future funding exclusion;
- fail-closed missing context;
- duplicate rejection;
- bounded read-only OI request contract;
- honest availability metadata;
- required dataset sources;
- live refresh defaults.

Two further existing-suite regressions verify the context ablation gate and runtime artifact contract. Net suite growth: 9 passing tests.

## 8. Migration, API, config and compatibility

- Database migration: none.
- Alembic head: remains `0011_selection_experiment`.
- Public API response contract: unchanged; stored feature snapshots now include seven additional model inputs for artifact signals.
- Bybit access: public/read-only GET only; no order mutations added.
- New environment variable names: none.
- Changed defaults/recommended values:
  - `UNIVERSE_SYNC_MARK_PRICE=true`;
  - `UNIVERSE_ENRICH_FUNDING_OI=true`.
- Artifact compatibility: intentionally breaking at the model-artifact semantic level. Pre-1.16 artifacts lack required context schemas and are rejected fail-closed. Retraining is required.
- Rollout must wait for index/OI/funding context coverage; no synthetic backfill is allowed.

## 9. Post-change verification

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | PASSED | No broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0 |
| `python -m ruff check .` | PASSED | Exit 0 |
| `python -m pytest -q` | PASSED | 531 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED | Exit 0 |
| `python -m alembic heads` | PASSED | Single head `0011_selection_experiment` |
| `python -m pytest -q -rs tests/integration_postgres` | SKIPPED | 4 skipped: `TEST_DATABASE_URL` absent |
| `python manage.py doctor` | FAILED (environment) | Project-local `.venv` absent |
| `python manage.py test --require-integration` | NOT RUN | No isolated PostgreSQL test database |

Release verification completed from the clean staged tree and a fresh extraction of the ZIP:

| Check | Status | Result |
|---|---|---|
| Clean release composition | PASSED | One root directory; no caches, secrets, dumps or real model artifacts. |
| Release manifest | PASSED | 197/197 eligible files. |
| `unzip -t` | PASSED | No archive errors. |
| Manifest after fresh extraction | PASSED | 197/197 files. |
| Full suite after fresh extraction | PASSED | 531 passed, 4 skipped, 61 warnings. |
| Frontend syntax after extraction | PASSED | Exit 0. |
| Alembic head after extraction | PASSED | Single head `0011_selection_experiment`. |

The final ZIP SHA-256 and size are reported outside the archive after final packaging, avoiding a circular checksum dependency.

## 10. Unverified items

- PostgreSQL integration and migration smoke tests were not executed without a dedicated `TEST_DATABASE_URL`.
- No real multi-page Bybit index/OI backfill was run against the network.
- No full production-history retraining was executed.
- No paper/shadow forward period was accumulated with the new feature schema.
- No economic benefit or profitability is claimed.

## 11. Residual risks and limitations

1. Public historical rows support event-time replay, not reconstruction of old local receipt latency.
2. OI delivery can be delayed during volatile periods; live inference correctly skips incomplete context, which may reduce recommendation density.
3. Current instrument funding interval is applied to historical funding-age validation; point-in-time interval changes are not reconstructed.
4. Turnover/OI is a coarse liquidity proxy and can vary by contract unit semantics; current scope is linear USDT only.
5. Same-split ablation reduces feature-inflation risk but is not nested model selection, PBO or a causal attribution of feature value.
6. Cross-asset context, historical orderbook features, funding forecasts and production drift monitoring remain absent.

## 12. Rollback procedure

1. Preserve the 1.16 artifact, metrics and database observations for audit.
2. Stop API, worker and trainer.
3. Restore 1.15.0 sources and the previous compatible artifact/registry activation.
4. No Alembic downgrade is required because this iteration adds no migration.
5. Restoring the old `UNIVERSE_*` values is optional; leaving read-only enrichment enabled is backward compatible.
6. Run doctor/static/unit checks and restart paper/shadow before production advisory use.

## 13. Recommended next work package

Implement production drift monitoring for the active feature schema: feature distribution drift, missingness/coverage, predicted-probability and calibration drift, actionability density and alert/report thresholds. Keep monitoring advisory/fail-closed and do not auto-retrain or weaken gates merely because drift is detected.

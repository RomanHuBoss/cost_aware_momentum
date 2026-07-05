# QA Report — 1.16.0

Date: 2026-07-05

Scope: point-in-time hourly market-context features, index/open-interest backfill, live receipt-time gating, context ablation and fail-closed artifact/runtime promotion contracts.

## Environment

- Python: 3.13.5
- Project requirement: Python >=3.12
- Isolated validation environment: `/mnt/data/cam_venv_115`
- Input release: 1.15.0
- Output release: 1.16.0
- Input ZIP SHA-256: `8d893f086785ddeaada52e0cf9c53687cc65b81023fbb81a7634aa001abb531d`
- Input Alembic head: `0011_selection_experiment`
- Output Alembic head: `0011_selection_experiment`
- Baseline tree: 77 app/script Python files, 65 test Python files, 15 documentation files, 11 migration Python files

The host interpreter initially lacked project packages such as `psycopg` and Ruff. Baseline and post-change verification were therefore executed in a clean isolated environment installed from the project `pyproject.toml`; no production PostgreSQL database was contacted.

## Baseline before code changes

| Check | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5. |
| `python -m pip check` | PASSED | No broken requirements in the isolated project environment. |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0. |
| `python -m ruff check .` | PASSED | Exit 0. |
| `python -m pytest -q` | PASSED | 522 passed, 4 skipped. |
| `node --check web/js/app.js` | PASSED | Exit 0. |
| `python -m alembic heads` | PASSED | Single head `0011_selection_experiment`. |

## Red → green

The new regression module was copied into an untouched 1.15.0 tree and executed:

```text
python -m pytest -q tests/unit/test_market_context_features_2026_07_05.py
```

Red result during collection:

```text
ModuleNotFoundError: No module named 'app.ml.context'
```

Green result after implementation:

```text
7 passed
```

Two additional regressions in existing suites verify that the quality gate rejects a material context-ablation regression and runtime rejects an artifact without the new market-context contract.

## Post-change checks

| Check | Status | Result |
|---|---|---|
| `python -m pip check` | PASSED | No broken requirements. |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0. |
| `python -m ruff check .` | PASSED | Exit 0. |
| `python -m pytest -q` | PASSED | 531 passed, 4 skipped, 61 pre-existing dependency/test deprecation warnings. |
| `node --check web/js/app.js` | PASSED | Exit 0. |
| `python -m alembic heads` | PASSED | Single head `0011_selection_experiment`. |
| `python -m pytest -q -rs tests/integration_postgres` | SKIPPED | 4 skipped because `TEST_DATABASE_URL` is not configured. |
| `python manage.py doctor` | FAILED (environment) | The command requires a project-local `.venv`; validation used a separate isolated environment. |
| `python manage.py test --require-integration` | NOT RUN | No isolated PostgreSQL test database was configured. |

## Mathematical, temporal and API checks

- OI changes require exact event timestamps at `t`, `t-1h` and `t-24h`; no forward fill or zero fill is used.
- Mark/index basis requires exact confirmed hourly closes at `t` and `t-1h`.
- Funding feature uses only the latest settlement at or before decision time and rejects an anchor older than one instrument funding interval.
- A future funding event cannot change the decision-time feature vector.
- Duplicate symbol/time rows, non-finite values and non-positive OI fail closed.
- Live inference queries only rows whose recorded `available_at` does not exceed the current availability cutoff.
- Historical artifact metadata explicitly records that local receipt timestamps were not reconstructed from public history.
- Bybit OI requests are public/read-only, preserve start/end/cursor parameters and clamp page size to 200.
- Enriched and core models are independently refit on identical final-holdout and walk-forward splits; final log-loss regression beyond 0.005 or instability in more than one fold blocks activation.
- Runtime requires exact feature order and context/availability/ablation schemas.
- `UNIVERSE_SYNC_MARK_PRICE` and `UNIVERSE_ENRICH_FUNDING_OI` default to true so live context continues refreshing after historical backfill is complete.

## External contract verification

Checked against official Bybit V5 documentation on 2026-07-05:

- Open-interest history supports `intervalTime`, start/end timestamps, cursor pagination and a maximum page size of 200; linear-contract OI is reported in base-coin units.
- Mark-price and index-price kline endpoints return reverse-ordered candles keyed by candle start time and support up to 1000 rows for futures.
- Funding history exposes actual `fundingRateTimestamp` settlement events.

## Release archive verification

| Check | Status | Result |
|---|---|---|
| Clean staged release tree | PASSED | One root directory, runtime placeholders only, no caches, credentials, dumps or model artifacts. |
| `python -B -m scripts.release_integrity --write` | PASSED | 197 eligible files and 197 manifest entries. |
| `unzip -t` | PASSED | No archive errors. |
| Manifest after fresh extraction | PASSED | 197/197 files. |
| Full suite after fresh extraction | PASSED | 531 passed, 4 skipped, 61 warnings. |
| Frontend syntax after extraction | PASSED | `node --check web/js/app.js`. |
| Alembic head after extraction | PASSED | Single head `0011_selection_experiment`. |

The final archive SHA-256 and byte size are calculated after the immutable release ZIP is created and are reported to the user outside the archive, avoiding a circular checksum dependency.

## Interpretation

The change closes the basic model-feature gap for OI, basis, settled funding state and a turnover/OI liquidity proxy. It does not reconstruct historical receipt latency, forecast future funding, add historical orderbook features, prove causal feature value or establish profitability. The ablation gate only demonstrates non-inferiority under the implemented temporal protocol.

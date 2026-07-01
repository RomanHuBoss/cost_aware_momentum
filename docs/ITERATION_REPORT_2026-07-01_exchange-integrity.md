# Iteration Report — 2026-07-01 — exchange integrity

## 1. Входной архив и исходная версия

- Input: `cost_aware_momentum-main.zip`
- SHA-256: `7de869737d976f86e3ed8ee6fd0c316afccedf2ceb4dc583a9d4abc1863c8954`
- Source version: `1.8.27`
- Python requirement: `>=3.12`
- Alembic head: `0007_position_account_scope`
- Input composition: 70 production Python files, 44 test Python files, 10 documentation/source-specification files, 8 migration Python files, 147 files total.

## 2. Цель и критерии приемки

Цель: после итерации все цены, запросы и инструменты, участвующие в execution/exchange boundary, должны соответствовать именно тому контракту, который policy оценивал и который Bybit получает; это подтверждается независимыми regression tests и полным зелёным suite.

Критерии:

1. Tick rounding не расширяет entry-zone за непрерывный policy band.
2. Если внутри band нет исполнимого тика, flow блокируется, а не разрешает внешнюю цену.
3. HMAC private GET соответствует exact query фактически отправленного request.
4. Crypto universe по умолчанию исключает известные TradFi product families.
5. Существующий explicit non-crypto opt-in остаётся рабочим.
6. Advisory-only, PostgreSQL-only, API schema и migrations не изменяются.
7. Новые regressions проходят отдельно и в полном suite; ранее зелёные тесты не регрессируют.

## 3. Прочитанные источники и data flow

Прочитаны: `README.md`, `pyproject.toml`, `.env.example`, все актуальные документы в `docs/`, Alembic migrations, production/test modules для risk math, labels/outcomes, features, temporal split, training/lifecycle/runtime, signals/execution/universe, market data, Bybit client, API, workers и frontend; исходная спецификация `docs/source/Cost_aware_hourly_ML_momentum_specification.docx` в релевантных разделах.

Потоки:

- prediction → executable bid/ask + ATR → continuous entry policy band → exchange tick projection → market signal DB → execution plan/API/UI;
- read-only account sync → final HTTP GET request → exact URL query → HMAC headers → Bybit response → account snapshot;
- Bybit instruments/tickers → point-in-time parsing → domain/liquidity/age filters → current universe → history/training/inference.

Официальная Bybit документация использовалась только для изменяемого external contract: GET signature payload и новые значения `symbolType`.

## 4. Baseline до правок

Изолированное `.audit-venv`:

| Command | Result |
|---|---|
| `python --version` | PASSED — 3.13.5 |
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 389 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — one head `0007_position_account_scope` |
| PostgreSQL integration | NOT RUN — no safe isolated database URL |

Глобальная среда была непригодна для baseline из-за постороннего dependency conflict, отсутствующего Ruff и отсутствующего `psycopg`; эти проблемы не приписаны проекту.

## 5. Подтверждённые defects/gaps

### HIGH — outward entry-zone rounding

- Path: `app/services/signals.py::select_cost_aware_scenario`.
- Reproduction: reference `100`, `atr_pct=0.02`, zone half-width `0.24`, `tickSize=1`.
- Expected: only executable tick `100` lies inside `[99.76, 100.24]`.
- Actual before fix: `[99, 101]` because lower used floor and upper used ceil.
- Impact: current quote outside evaluated policy band could pass zone validation.
- Test gap: existing tests checked tick alignment and stop/TP conservatism, but not set containment of entry ticks.

### HIGH — signed query differed from transmitted query

- Path: `app/bybit/client.py::BybitClient._get`.
- Reproduction: private GET parameters inserted as `category`, `settleCoin`, `limit`; signature built from a separately sorted representation while `httpx` transmitted the original order.
- Expected: HMAC input contains the exact query string of the sent URL.
- Actual before fix: mock transport recomputation from `request.url.query` did not match `X-BAPI-SIGN`.
- Impact: intermittent/deterministic auth rejection of read-only account endpoints depending on parameter ordering.
- Test gap: previous tests mocked response payloads but did not verify cryptographic binding to the transmitted request.

### HIGH — incomplete non-crypto domain filter

- Path: `app/services/universe.py::select_dynamic_universe`.
- Reproduction: eligible `stock`, `forex` and `commodity` instruments passed all current filters with default settings.
- Expected: crypto model domain rejects known TradFi product families unless explicitly enabled.
- Actual before fix: only `xstocks/xstock` was excluded.
- Impact: mixed market domains can invalidate feature, cost, liquidity and label assumptions and contaminate retraining/inference.
- Test gap: only historical xStocks naming was considered.

### Unsupported external claim

The statement that external reviewers found approximately 38 critical defects and 7 medium defects was not accompanied by modules, reproductions, commits, tests or reports. It is therefore neither confirmed nor refuted as a count. This audit reports only evidence-backed findings.

## 6. План и фактический diff

Production:

- `app/services/signals.py` — inward entry-band rounding and empty-band fail-closed guard.
- `app/bybit/client.py` — build, sign and send one exact private GET request.
- `app/services/universe.py` — normalized exact known-TradFi filter.
- `app/__init__.py`, `pyproject.toml` — patch version 1.8.28.

Tests:

- `tests/unit/test_execution_exchange_integrity_2026_07_01.py` — four regressions/acceptance tests.

Configuration/docs:

- `.env.example`, `README.md`, `CHANGELOG.md`, `PATCH_1.8.28.md` and affected `docs/*.md`.

No migration, API schema, dependency or new env variable.

## 7. Red → green evidence

Command used for the initial three regressions:

```text
python -m pytest -q tests/unit/test_execution_exchange_integrity_2026_07_01.py
```

Before production changes: 3 failed for the expected reasons — widened `[99,101]` zone, HMAC mismatch, and four non-crypto symbols admitted. After fixes: all three passed. A fourth acceptance test then verified explicit TradFi opt-in; final module result is four passed.

## 8. Compatibility

- DB migration: none.
- API: unchanged.
- Environment: no action; `.env.example` comment clarified only.
- Rollout: restart API/worker/trainer.
- Behavioral compatibility: explicit non-crypto opt-in preserved. Entry bands may become narrower by design.

## 9. Post-check

| Command | Result |
|---|---|
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 393 passed, 4 skipped, 19 warnings |
| dedicated regression module | PASSED — 4 tests |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0007_position_account_scope` |
| 20,000-case independent Decimal audit | PASSED |
| Bybit advisory-only boundary scan | PASSED |
| whitespace/version consistency | PASSED |
| PostgreSQL integration runner | NOT RUN — separate test/admin DB URL is not configured |
| release tree and `SHA256SUMS` | PASSED — 151 source files / 151 entries |

## 10. Не проверено

- PostgreSQL integration/migration against a separate real DB.
- Real read-only Bybit credential smoke.
- Browser end-to-end workflow.
- Strict mypy baseline: extra non-gating run produced 175 diagnostics in 31 files, mostly third-party stub absence and legacy typing debt.
- Profitability or production edge.

## 11. Остаточные риски и ограничения

- Research backtest/promotion still lacks exact historical order book/fill/funding timeline; static assumptions can bias economics.
- Full walk-forward, drift/regime monitoring and PBO/DSR are incomplete.
- Aggregate test coverage was 66%; API/workers have thinner coverage than risk math and ML core.
- Bybit can introduce future `symbolType` values; unknown types remain allowed because many valid crypto region values are non-empty. A future schema-driven product taxonomy is preferable to blindly rejecting all unknown values.

## 12. Rollback

1. Stop API/worker/trainer.
2. Restore version 1.8.27 source archive; no DB downgrade is needed.
3. Restart processes.
4. Do not cherry-pick only the version/docs files: the three production changes and regression tests form one patch.

## 13. Следующий рекомендуемый work package

Implement a point-in-time historical funding timeline for research/promotion policy evaluation, with settlement-crossing logic shared with production economics and purged OOS tests. Do not combine it with full walk-forward/PBO/DSR in the same iteration.

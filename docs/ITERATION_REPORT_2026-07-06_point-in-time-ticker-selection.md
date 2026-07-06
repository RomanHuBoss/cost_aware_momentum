# Iteration report — point-in-time ticker selection

## 1. Input archive and source state

- Input: `cost_aware_momentum-1.35.1-timeout-current-entry-repricing.zip`
- Input SHA-256: `fa119cdfae6432bac3a3bfa0de2c2affc9997cc735fa2f5e690cbee8b157435c`
- Source version: 1.35.1
- Target version: 1.35.2
- Python requirement: >=3.12
- Alembic head: `0016_universe_replay_asof`

## 2. Goal and acceptance criteria

After this iteration, ticker consumers must select the latest snapshot already available at the exact decision/request cutoff, so a future-dated latest row cannot mask an older fresh row.

Acceptance criteria:

1. Filter by both source and local receipt availability.
2. Apply filtering before ordering and limiting.
3. Use deterministic tie-breaking.
4. Apply one shared contract in signal publication, execution planning and recommendation API/acceptance.
5. Retain stale-data fail-closed checks.
6. Add a red → green regression for all former duplicate loaders.
7. Do not change database, model, policy, risk or API response contracts.

## 3. Sources and data flow

Read: README, CHANGELOG, patches 1.34.2–1.35.1, architecture/security/QA/compliance/traceability documents, ticker ORM/sync code, signal publication, execution and recommendation API code, and related tests.

Affected flow:

`Bybit read-only ticker response → TickerSnapshot(source_time, received_at) → latest-prior lookup at decision/request cutoff → freshness validation → signal/plan/API state`.

## 4. Baseline

Environment: isolated Python 3.13.5 virtual environment.

- pip check: PASSED
- compileall: PASSED
- Ruff: PASSED
- pytest: PASSED — 704 passed, 7 skipped, 62 warnings
- JavaScript syntax: PASSED
- Alembic: one head, `0016_universe_replay_asof`
- PostgreSQL integration: NOT RUN; no isolated TEST_DATABASE_URL

## 5. Confirmed defect

Classification: **CONFIRMED DEFECT**
Severity: **high operational/temporal correctness**

Files/functions:

- `app/services/signals.py::_latest_ticker`
- `app/services/execution.py::latest_ticker`
- `app/api/v1/recommendations.py::latest_ticker`

Actual behavior: each query ordered every row by `source_time DESC` and selected one before the caller checked whether its timestamp was in the future.

Minimal state:

- cutoff: 18:00 UTC;
- valid prior row: source 17:59:55, received 17:59:56;
- future row: source/received 18:05;
- old query selected 18:05, then rejected it;
- expected query excludes 18:05 and returns the fresh prior row.

Impact: false `missing/stale/future ticker` suppression in publication, planning and acceptance. Existing tests validated freshness but not latest-prior database selection.

## 6. Plan and actual diff

Production:

- add shared point-in-time ticker query/loader;
- delegate three consumers to it;
- pass stable cutoffs through affected request/decision paths.

Tests:

- add parametrized three-consumer SQL/behavior regression;
- adapt ticker test doubles to the explicit cutoff contract.

No migration, configuration, artifact or API schema changes.

## 7. Red → green evidence

Red command:

```bash
python -m pytest -q tests/unit/test_point_in_time_ticker_selection_2026_07_06.py
```

Red result: 3 failed with unexpected `cutoff` keyword; the old SQL had no source/receipt cutoff predicates.

Green result: 3 passed. Focused affected suite: 70 passed.

The test uses an independent query-aware session: it returns the prior row only if both cutoff predicates are present, then separately verifies deterministic SQL ordering.

## 8. Compatibility

- Migration: none.
- `.env`: none.
- API response schema: unchanged.
- Model artifacts/features/labels/classes: unchanged.
- Risk/policy/activation gates: unchanged.
- Advisory-only and PostgreSQL-only boundaries: preserved.
- Existing snapshots: not rewritten.

## 9. Post-check

- pip check: PASSED
- compileall: PASSED
- Ruff: PASSED
- pytest: PASSED — 709 passed, 7 skipped, 62 warnings
- JavaScript syntax: PASSED
- Alembic: one head, `0016_universe_replay_asof`

## 10. Not verified

- Real PostgreSQL execution and query plan.
- Production recommendation-density change after restart.
- Real Windows clock rollback scenario.
- PostgreSQL integration suite and manage.py doctor.

## 11. Residual risks and limitations

The fix chooses a usable prior ticker but does not widen freshness limits. If the prior row is stale, the caller still blocks. It does not prove profitability or alter model activation.

The orderbook lookup has an analogous absolute-latest shape and remains outside this bounded ticker iteration.

## 12. Rollback

Restore release 1.35.1 and restart API/worker. No database rollback is needed because schema and stored rows are unchanged.

## 13. Recommended next work package

Audit and, if reproduced, apply latest-prior availability semantics to `OrderBookSnapshot` selection in plan construction and acceptance, including both exchange source time and local receipt time without weakening depth freshness or sequence validation.

# PATCH 1.52.23 — locked-ticker-validation

Date: 2026-07-10  
Scope: `locked-ticker-validation`  
Version type: patch

## Summary

This patch closes an execution-data integrity inconsistency. Release 1.52.20 rejected locked orderbook depth (`best_ask == best_bid`), but ticker-based paths still accepted the same geometry as a valid zero-spread quote. The locked ticker could enter dynamic-universe eligibility, be stored as executable bid/ask, pass market-signal economics, and pass acceptance-side entry-price selection.

## Confirmed defect

Type: CONFIRMED DEFECT  
Severity: high

Affected paths:

- `app/services/execution.py::validated_bid_ask`
- `app/services/market_data.py::sync_tickers`
- `app/services/universe.py::_spread_bps_from_prices`
- downstream signal selection, plan construction, acceptance revalidation, entry-state rendering, and spread diagnostics

Actual behavior: `ask < bid` was rejected, while `ask == bid` was treated as valid. Dynamic universe computed zero spread; ticker ingestion persisted both executable sides; shared plan/signal validation returned an entry price.

Expected behavior: executable top-of-book evidence must have a strictly positive spread (`ask > bid`). Locked and crossed quotes must fail closed, consistent with orderbook validation.

Impact: malformed or transient exchange ticker data could understate execution friction, select a symbol into the eligible universe, and allow signal/plan calculations to use an unsafe quote. No exchange order was placed because the system remains advisory-only.

Why previous tests missed it: the quote contract covered crossed (`ask < bid`) but not locked (`ask == bid`) ticker geometry. Locked coverage existed only for orderbook depth normalization.

## Fix

- Shared ticker quote validation now rejects `ask <= bid` with an explicit `locked or crossed` diagnostic.
- Dynamic-universe spread calculation returns invalid for `ask <= bid`.
- Ticker ingestion retains the valid last price but stores `bid_price=None` and `ask_price=None` when the quote is locked or crossed.
- No fallback to last price was added for executable entry selection.

## Red → green evidence

Red command on 1.52.22 plus tests:

```bash
python -m pytest -q \
  tests/unit/test_quote_plan_contract_2026_06_30.py::test_signal_policy_rejects_locked_quote \
  tests/unit/test_quote_plan_contract_2026_06_30.py::test_acceptance_rejects_locked_quote \
  tests/unit/test_quote_plan_contract_2026_06_30.py::test_dynamic_universe_rejects_locked_quote \
  tests/unit/test_quote_plan_contract_2026_06_30.py::test_ticker_sync_drops_locked_bid_ask
```

```text
4 failed in 3.06s
```

Green after implementation:

```text
4 passed in 2.75s
```

Related subset:

```text
79 passed in 3.68s
```

## Compatibility

- Alembic migration: not required; head remains `0018_inference_observations`.
- `.env.example`: unchanged.
- Public API schema: unchanged.
- Model artifact/schema: unchanged.
- Bybit endpoint set: unchanged; public/read-only market data and read-only account endpoints only.
- Advisory-only invariant preserved.
- Operator action: restart API and inference worker after deployment; no database or environment action is required.

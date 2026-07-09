# PATCH 1.52.15 — bybit-list-payload-validation

Date: 2026-07-09

## Summary

This patch hardens the read-only Bybit client response contract for list-shaped endpoints. `get_tickers()`, `get_kline()`, and `get_fee_rate()` now reject malformed `result.list` payloads instead of returning a dict/string/scalar to downstream market-data, universe, or account-cost logic.

## Confirmed defect fixed

### Malformed Bybit list payloads could pass through as valid endpoint output

- Type: CONFIRMED DEFECT
- Severity: high
- File: `app/bybit/client.py`
- Functions: `BybitClient.get_tickers()`, `BybitClient.get_kline()`, `BybitClient.get_fee_rate()`
- Actual behavior: when a successful Bybit response had `retCode == 0` but `result.list` was not a JSON array, those methods returned the malformed object directly.
- Expected behavior: list endpoints must fail closed on non-list response payloads so stale/partial/malformed exchange responses cannot masquerade as valid market-data/account-cost lists.
- Fix: added `_require_result_list()` and routed tickers, kline, and fee-rate list extraction through it.
- Regression: `tests/unit/test_bybit_response_contract_2026_07_09.py::test_bybit_list_endpoints_reject_non_list_payloads`.

## Compatibility

- Version type: patch.
- Database migration: not required.
- `.env` changes: none.
- API schema changes: none.
- Bybit endpoint set: unchanged; still public/read-only GET operations only.
- Advisory-only invariant: preserved; no order create/amend/cancel/withdraw capability added.

## Verification

```bash
python -m pytest -q tests/unit/test_bybit_response_contract_2026_07_09.py
# ... [100%]
# 3 passed in 0.40s

python -m pytest -q \
  tests/unit/test_bybit_response_contract_2026_07_09.py \
  tests/unit/test_execution_exchange_integrity_2026_07_01.py \
  tests/unit/test_market_context_features_2026_07_05.py::test_open_interest_client_supports_bounded_historical_queries
# ........ [100%]
# 8 passed in 3.00s
```

Full pytest remains blocked in this sandbox by missing `psycopg`; ruff remains unavailable because the module is not installed. See `docs/QA_REPORT.md` and `docs/ITERATION_REPORT_2026-07-09_bybit-list-payload-validation.md`.

# PATCH 1.52.16 — bybit-list-presence

Date: 2026-07-09

## Summary

This patch closes a remaining fail-open branch in the read-only Bybit client response contract. The previous release rejected non-list `result.list` payloads for selected methods, but all list-shaped methods still accepted missing or `null` lists as empty arrays through `result.get("list") or []`. That could make a stale, partial, or schema-broken exchange response look like a genuine empty market/account result.

## Confirmed defect fixed

### Missing Bybit list payloads could masquerade as valid empty lists

- Type: CONFIRMED DEFECT
- Severity: high
- File: `app/bybit/client.py`
- Functions: `_require_result_list()`, `BybitClient.get_tickers()`, `BybitClient.get_kline()`, `BybitClient.get_fee_rate()`, `BybitClient.get_instruments()`, `BybitClient.get_funding_history()`, `BybitClient.get_open_interest()`, `BybitClient.get_positions()`
- Actual behavior: a successful `retCode == 0` response with missing `result.list` or `result.list == null` returned an empty list/page.
- Expected behavior: mandatory list-shaped Bybit responses must fail closed unless `result.list` is present and is a JSON array; an actual empty exchange result remains valid only when Bybit returns `"list": []`.
- Fix: `_require_result_list()` now checks result shape, presence, nullness, and list type; all list-shaped methods route mandatory list extraction through it.
- Regression: `tests/unit/test_bybit_response_contract_2026_07_09.py::test_bybit_list_endpoints_reject_missing_or_null_list_payloads`.

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
# ................. [100%]
# 17 passed in 0.51s

python -m pytest -q \
  tests/unit/test_bybit_response_contract_2026_07_09.py \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_get_instruments_follows_all_bybit_cursor_pages \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_get_instruments_rejects_repeated_cursor_instead_of_looping \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_get_instruments_rejects_non_list_page \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_get_positions_follows_all_bybit_cursor_pages \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_get_positions_rejects_repeated_cursor_instead_of_looping \
  tests/unit/test_historical_funding_replay_2026_07_05.py::test_bybit_funding_history_uses_bounded_end_time_pagination \
  tests/unit/test_historical_funding_replay_2026_07_05.py::test_bybit_funding_history_rejects_start_without_end \
  tests/unit/test_market_context_features_2026_07_05.py::test_open_interest_client_supports_bounded_historical_queries
# ......................... [100%]
# 25 passed in 2.62s
```

Full pytest remains blocked in this sandbox by missing `psycopg`; ruff remains unavailable because the module is not installed. See `docs/QA_REPORT.md` and `docs/ITERATION_REPORT_2026-07-09_bybit-list-presence.md`.

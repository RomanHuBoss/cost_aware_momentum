# Traceability

| Requirement / invariant | Evidence in 1.52.13 | Verification status |
|---|---|---|
| Advisory-only: no order create/amend/cancel/withdraw methods | `app/bybit/client.py`, `tests/unit/test_runtime_auth_config.py` | Existing unit coverage; full suite blocked by missing `psycopg` in sandbox |
| PostgreSQL-only | `app/config.py`, `.env.example`, `tests/unit/test_runtime_auth_config.py` | Existing unit coverage; full suite blocked by missing `psycopg` in sandbox |
| Safe position sizing never rounds risk upward | `app/risk/math.py`, `tests/unit/test_risk_math.py` | Targeted unit suite passed |
| Exchange cap is not min-order failure | `app/risk/math.py`, `tests/unit/test_risk_math.py::test_exchange_cap_block_is_not_reported_as_min_order` | New regression passed |
| Exchange-limited plan warns operator | `app/risk/math.py`, `tests/unit/test_risk_math.py::test_exchange_cap_limited_plan_has_operator_warning` | New regression passed |
| Exchange block attrition remains execution-risk evidence | `app/services/attrition.py`, `tests/unit/test_candidate_live_attrition_report_2026_07_05.py::test_exchange_block_is_risk_execution_attrition` | New regression passed |
| UI exposes exchange block separately | `web/js/app.js` | `node --check web/js/app.js` passed |
| Release evidence exists | `CHANGELOG.md`, `PATCH_1.52.13.md`, docs files, `SHA256SUMS` | `scripts.release_integrity --write` and verify planned after cache cleanup |

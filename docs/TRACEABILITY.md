# Traceability

| Requirement / invariant | Evidence in 1.52.25 | Verification status |
|---|---|---|
| Transient market-data skips remain recoverable inside the immutable publication window | `app/workers/runner.py::should_retry_incomplete_inference`; `test_complete_hourly_inference_retries_transient_market_data_skip` | Red→green; passed |
| Policy/market/model rejects are not retried for a more favorable state | explicit retry reason allowlist; `test_complete_hourly_inference_does_not_retry_policy_skip` | Passed |
| Transient inference recovery is bounded | existing `inference_retry_count`/maximum; `test_transient_market_data_skip_stops_after_retry_limit` | Passed |
| Private financial/advisory GET routes require operator authentication | `app/api/v1/capital.py`, `recommendations.py`, `trades.py`, `portfolio.py`; `test_sensitive_financial_read_endpoints_require_operator_authentication` | Red→green; passed |
| Detailed operational diagnostics require operator authentication | `app/api/v1/status.py`; `test_operational_status_endpoints_require_operator_authentication` | Red→green; passed |
| SSE outbox stream requires operator authentication | `app/api/v1/events.py`; `test_outbox_event_stream_requires_operator_authentication` | Red→green; passed |
| Production authentication cookies must be Secure | `app/config.py`; `test_production_requires_secure_authentication_cookies` | Red→green; passed |
| Logout requires authenticated CSRF | `app/api/v1/session.py`; `test_logout_requires_authenticated_csrf_protection` | Red→green; passed |
| Minimal anonymous liveness remains available | `app/api/v1/status.py::live` | Verified by route review and full suite |
| Advisory-only: no order create/amend/cancel/withdraw methods | `app/bybit/client.py`; forbidden endpoint scan in `app scripts web` | Passed; no exchange write implementation found |
| PostgreSQL-only | `app/config.py`, `.env.example`, unit suite | Full non-integration suite passed; PostgreSQL integration not run without safe test DB |
| Existing risk/market/model contracts are not weakened | no changes under `app/risk`, `app/ml`, market/execution services, or migrations | Full suite passed |
| Release evidence and archive hygiene | `CHANGELOG.md`, `PATCH_1.52.25.md`, `docs/QA_REPORT.md`, iteration report, `SHA256SUMS`, `scripts/release_integrity.py` | Passed: 300 files checked; clean ZIP re-extraction |

# Iteration report — operator-surface-auth

Date: 2026-07-10  
Release: 1.52.24  
Version type: patch security hardening

## 1. Input archive and evidence

- Input ZIP: `cost_aware_momentum-main.zip`
- Input SHA-256: `01406528d18eb7164fa4ea245fc67f228303ea567dacc413f32a158e7dfdea46`
- Detected root: `cost_aware_momentum-main/`
- Source version: 1.52.23
- Python requirement: `>=3.12`
- Alembic head: `0018_inference_observations`
- Baseline release inventory: 105 production/runtime/config files, 128 test files, 33 documentation/release files, and 20 migration files under the report's classification rules.

The attached PDF was read as an iteration protocol. It did not contain a Claude/Fable finding table, affected files, stack traces, or reproduction commands for the stated “3 critical and 2 medium” findings. Therefore this iteration did not invent those details: it independently reproduced and fixed a coherent operator-surface security package consisting of three critical and two medium defects.

## 2. Goal and acceptance criteria

Goal: after this iteration, anonymous clients must not access private operator financial/advisory data, detailed runtime diagnostics, or the live outbox stream; production cookies must be transport-secure; logout must follow the existing authenticated-CSRF contract.

Acceptance criteria:

1. Capital profiles, recommendations/details, trades, and portfolio risk require `current_operator`.
2. Detailed readiness and status require `current_operator`; minimal `/health/live` remains anonymous.
3. `/api/v1/events` requires `current_operator`.
4. `APP_MODE=production` rejects `COOKIE_SECURE=false`.
5. Logout requires `require_csrf` through `MutatingOperatorDep`.
6. Five regressions fail on 1.52.23 and pass after the patch.
7. Full non-integration suite, Ruff, compile, dependency, JavaScript syntax, Alembic-head, release-integrity, and archive checks pass.
8. No migration, exchange write endpoint, model artifact, or trading/risk policy change is introduced.

## 3. Context read and data-flow map

Read before selecting the fix:

- `README.md`, `CHANGELOG.md`, `PATCH_1.52.23.md`, and recent release notes;
- `pyproject.toml`, `.env.example`;
- `docs/ARCHITECTURE.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, and `OPERATOR_MANUAL.md`;
- `app/main.py`, `app/config.py`, `app/api/deps.py`, all `app/api/v1` routers, relevant ORM/service dependencies, and existing account-scope tests;
- release integrity and packaging scripts.

Relevant data flow:

1. Browser login verifies `OPERATOR_PASSWORD`, sets signed `cam_session` and `cam_csrf` cookies.
2. `current_operator` accepts a valid signed session or exact `X-Operator-Token`.
3. `require_csrf` layers cookie CSRF validation over `current_operator`; API-token requests are explicit non-cookie requests and bypass cookie CSRF.
4. API read handlers query PostgreSQL for profiles, recommendations/plans, trades, portfolio exposure, model/job/worker status, or outbox events.
5. Browser `EventSource` refreshes operator UI state from `/api/v1/events` using same-origin cookies.
6. The advisory system never places, amends, cancels, or withdraws exchange orders.

## 4. Baseline

### Host environment

| Command | Status | Result |
|---|---:|---|
| `python --version` | PASSED | `Python 3.13.5` |
| `python -m pip check` | FAILED | host-only `moviepy` / `pillow` conflict |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | UNAVAILABLE | host had no `ruff` module |
| `python -m pytest -q` | FAILED | 62 collection errors; representative missing `psycopg` |
| `node --check web/js/app.js` | PASSED | exit 0 |

### Clean isolated project environment, before production changes

| Command | Status | Result |
|---|---:|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| `python -m pytest -q` | PASSED | 909 passed, 8 skipped in 24.37s |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | one head: `0018_inference_observations` |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL deployment |
| `python manage.py test --require-integration` | SKIPPED | no `TEST_DATABASE_URL` |

Baseline counts: 909 passed / 0 failed / 8 skipped / 0 xfailed / 0 errors. The eight skips are PostgreSQL integration tests.

## 5. Confirmed defects and evidence

### D1 — CONFIRMED DEFECT — critical — anonymous financial/advisory reads

- Files/functions: `capital.list_profiles`, `recommendations.list_recommendations`, `recommendations.recommendation_detail`, `trades.list_trades`, `portfolio.portfolio_risk`.
- Path: anonymous HTTP GET → handler → PostgreSQL query → financial/operator JSON response.
- Actual: routes had database/settings dependencies but no `current_operator` dependency.
- Expected: all private operator data requires signed session or `X-Operator-Token`.
- Impact: exposure of allocated capital/risk settings, actionable signal/plan diagnostics, manual trade journal, and portfolio risk. This is confidentiality and operational-security impact; no exchange order placement exists.
- Why tests missed it: prior tests concentrated on mutation authentication/CSRF and business logic, not the dependency graph for read routes.
- Reproduction: inspect each `APIRoute.dependant.dependencies`; `current_operator` is absent on 1.52.23.
- Regression: `test_sensitive_financial_read_endpoints_require_operator_authentication`.

### D2 — CONFIRMED DEFECT — critical — anonymous detailed runtime diagnostics

- File/functions: `app/api/v1/status.py::ready`, `status`.
- Path: anonymous GET → database/migration/model/job/heartbeat/account/signal diagnostics.
- Actual: `/health/ready` and `/api/v1/status` exposed detailed control-plane state without operator authentication.
- Expected: detailed readiness/status is operator-only; only minimal liveness stays anonymous.
- Impact: reconnaissance of database revision, model artifact/version/quality, workers, trainer/jobs, active profile, data-quality and plan state.
- Why tests missed it: no route-boundary assertion distinguished minimal liveness from detailed readiness/status.
- Reproduction: route dependency graph lacks `current_operator` on 1.52.23.
- Regression: `test_operational_status_endpoints_require_operator_authentication`, including proof that `/health/live` remains public.

### D3 — CONFIRMED DEFECT — critical — anonymous SSE outbox stream

- File/function: `app/api/v1/events.py::events`.
- Path: anonymous long-lived GET → `SessionFactory` polling → persisted `OutboxEvent` payloads → SSE.
- Actual: no authentication dependency.
- Expected: stream requires the same operator identity as the private UI data it refreshes.
- Impact: continuous observation of system/operator transitions and identifiers; long-lived passive disclosure.
- Why tests missed it: SSE syntax/behavior existed without an authorization-boundary regression.
- Reproduction: route dependency graph is empty on 1.52.23.
- Regression: `test_outbox_event_stream_requires_operator_authentication`.

### D4 — CONFIRMED DEFECT — medium — insecure authentication cookies allowed in production

- File/function: `app/config.py::Settings.validate_settings` production block.
- Path: production environment → settings validation → login cookie `secure=settings.cookie_secure`.
- Actual: production accepted `COOKIE_SECURE=false`.
- Expected: production must fail closed unless both authentication cookies are Secure.
- Impact: a deployment mistake could transmit session/CSRF cookies over cleartext HTTP, enabling network disclosure. Local paper/development HTTP remains a distinct supported mode.
- Why tests missed it: production configuration tests covered demo/baseline/default secrets but not cookie transport security.
- Reproduction: construct production `Settings` with strong secret/password and `cookie_secure=False`; 1.52.23 accepts it.
- Regression: `test_production_requires_secure_authentication_cookies`.

### D5 — CONFIRMED DEFECT — medium — logout bypassed authenticated CSRF contract

- File/function: `app/api/v1/session.py::logout`.
- Path: cross-site POST → unauthenticated logout → deletion of session/CSRF cookies.
- Actual: logout had no `current_operator` or `require_csrf` dependency.
- Expected: cookie session termination is a mutating session action and must use `MutatingOperatorDep`.
- Impact: forced operator logout and availability disruption; not a trading mutation or privilege escalation.
- Why tests missed it: login/session helper behavior existed without a route dependency assertion for logout.
- Reproduction: route dependency graph is empty on 1.52.23.
- Regression: `test_logout_requires_authenticated_csrf_protection`.

## 6. Red → green

Red command, run after adding the five tests and before changing production code:

```bash
python -m pytest -q tests/unit/test_operator_surface_security_2026_07_10.py
```

Material red result:

```text
5 failed in 6.30s
```

The failures showed missing `current_operator` on the three route groups, no production exception for `COOKIE_SECURE=false`, and no `require_csrf` dependency on logout.

Green after implementation:

```text
5 passed in 6.44s
```

A later documentation-only rerun reported `5 passed in 6.83s`; no production behavior changed between these green runs.

Full suite after the patch:

```text
914 passed, 8 skipped in 22.21s
```

One pre-existing unit test directly called `portfolio_risk()` outside FastAPI dependency injection. It was updated to pass a synthetic authenticated operator value; no production fallback or optional authentication was introduced.

## 7. Implementation and actual diff

Production/configuration:

- `app/api/v1/capital.py`
- `app/api/v1/recommendations.py`
- `app/api/v1/trades.py`
- `app/api/v1/portfolio.py`
- `app/api/v1/status.py`
- `app/api/v1/events.py`
- `app/api/v1/session.py`
- `app/config.py`
- `app/__init__.py`
- `pyproject.toml`
- `.env.example`

Tests:

- added `tests/unit/test_operator_surface_security_2026_07_10.py`
- updated direct-call fixture in `tests/unit/test_account_scope_integrity_2026_06_30.py`

Documentation/release evidence:

- `README.md`, `CHANGELOG.md`, `PATCH_1.52.24.md`
- `docs/ARCHITECTURE.md`, `CONFIGURATION.md`, `OPERATOR_MANUAL.md`, `QA_REPORT.md`, `SECURITY.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`
- this report and regenerated `SHA256SUMS`

No migration, frontend JavaScript, ML, risk math, market data, trading semantics, execution sizing, or Bybit-client file changed.

## 8. Migration, API, and configuration compatibility

- Alembic: no new migration; head remains `0018_inference_observations`.
- Database: no schema or stored-data semantic change.
- API response bodies: unchanged for authenticated callers.
- Authentication behavior: intentionally stricter. Anonymous private reads now return `401`. Authenticated cookie logout without matching CSRF returns `403`. API-token authentication remains explicit and does not require cookie CSRF.
- Public routes intentionally retained: `/health/live`, `/api/v1/session/login`, static UI assets/routes, UI glossary, and public candle chart.
- Environment names: unchanged.
- Required production action: set `COOKIE_SECURE=true`. Configure `OPERATOR_API_TOKEN` and `X-Operator-Token` for automated `/health/ready` probes that cannot use a browser session.
- Model artifact/schema, feature/label contract, promotion gate, risk thresholds, signal/plan semantics, and Bybit endpoint set: unchanged.

## 9. Post-check

| Command/check | Status | Result |
|---|---:|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| new security tests | PASSED | 5 passed in 6.44s |
| `python -m pytest -q` | PASSED | 914 passed, 8 skipped in 22.21s |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | one head: `0018_inference_observations` |
| version consistency | PASSED | README / package / app = 1.52.24 |
| forbidden exchange mutation scan | PASSED | no order create/amend/cancel, leverage mutation, or withdrawal endpoint implementation |
| credential/runtime artifact scan | PASSED | no `.env`, key/cert, SQLite/database dump, or real model artifact in release tree |
| source-code trailing whitespace | PASSED | no findings in source/config files; Markdown hard-break spaces are intentional |
| release integrity and manifest | PASSED | 298 eligible files checked; 298 manifest entries |
| ZIP integrity and clean re-extraction | PASSED | `unzip -t` clean; exactly one root `cost_aware_momentum-1.52.24/`; re-extracted release integrity passed |

The final archive is `cost_aware_momentum-1.52.24-operator-surface-auth.zip`. The archive was re-extracted, the three key patched contracts were verified inside the extracted copy, and the final response provides its SHA-256 because a ZIP cannot contain a stable hash of itself.

## 10. Not verified

- PostgreSQL integration tests, migration upgrade/downgrade, append-only/outbox concurrency, and `manage.py doctor`: no safe test database/deployment was available.
- Real HTTPS/TLS cookie transport, reverse-proxy headers, and orchestrator readiness configuration.
- Browser reconnection of `EventSource` through a real proxy after session expiration and subsequent login.
- External penetration testing, login brute-force resistance, host/network hardening, and secret rotation procedures.
- Real Bybit paper/shadow/forward operation and strategy profitability.

## 11. Residual risks and limitations

1. `OPERATOR_API_TOKEN` is bearer-equivalent and must be strong, transported only over TLS, excluded from logs, and rotated operationally.
2. The signed session is stateless until expiry/logout; this patch does not add a server-side revocation list or RBAC.
3. Authentication dependency tests prove the application route contract, but deployment-level TLS/proxy/CORS behavior still requires smoke evidence.
4. Public candle charts expose only exchange-derived market data, not profiles, recommendations, positions, model state, or audit events; that boundary remains intentional.
5. PostgreSQL-backed end-to-end behavior remains unverified in this sandbox despite a green non-integration suite.

## 12. Rollback

1. Stop the API process.
2. Restore the 1.52.23 application/configuration files listed in section 7; no database downgrade is required.
3. Restore the previous probe configuration if `/health/ready` was changed to send `X-Operator-Token`.
4. Restart the API and verify liveness.
5. Treat rollback as emergency-only: it reopens the anonymous data/status/event surfaces, insecure-production-cookie acceptance, and forced-logout issue.

## 13. Recommended next work package

Add deployment-level security smoke tests using a temporary PostgreSQL database and HTTPS/reverse-proxy fixture: prove anonymous `401`, session and API-token success, cookie Secure/SameSite behavior, CSRF failure/success, SSE authorization/reconnect, and authenticated readiness probes. Keep this separate from login rate limiting, server-side session revocation, and RBAC design.

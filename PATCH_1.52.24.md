# PATCH 1.52.24 — operator-surface-auth

Date: 2026-07-10  
Scope: `operator-surface-auth`  
Version type: patch (security hardening with intentionally stricter authentication behavior)

## Summary

This patch closes an authentication boundary gap across the operator-facing API. Release 1.52.23 authenticated state-changing trading/admin actions, but several high-value read routes, the detailed operational status surface, and the live outbox stream were anonymous. Production also allowed non-secure authentication cookies, and logout did not require the existing authenticated-CSRF contract.

## Confirmed defects

### D1 — critical — anonymous financial/advisory reads

Affected routes: `GET /api/v1/capital-profiles`, `GET /api/v1/recommendations`, `GET /api/v1/recommendations/{signal_id}`, `GET /api/v1/trades`, and `GET /api/v1/portfolio/risk`.

Actual behavior: a network client could read allocated capital/risk profile settings, actionable recommendation and execution-plan details, manual trade journal data, and current portfolio-risk information without an operator credential.

Expected behavior: the operator data plane must require a signed session or explicit operator API token even when the HTTP method is read-only.

Fix: every affected handler now depends on `OperatorDep` (`current_operator`).

### D2 — critical — anonymous detailed operational diagnostics

Affected routes: `GET /health/ready` and `GET /api/v1/status`.

Actual behavior: anonymous clients could inspect database/migration readiness, active model registry and artifact diagnostics, worker/trainer/job state, active profile, data-quality and signal/plan operational state.

Expected behavior: detailed readiness and control-plane state are operator-only. Only a minimal liveness response should remain anonymous.

Fix: both detailed routes now depend on `OperatorDep`; `GET /health/live` remains public and minimal.

### D3 — critical — anonymous SSE outbox stream

Affected route: `GET /api/v1/events`.

Actual behavior: an unauthenticated long-lived client could subscribe to persisted outbox events and observe live operator/system state transitions and identifiers.

Expected behavior: the event stream follows the same authentication boundary as the UI data it refreshes.

Fix: the SSE handler now depends on `OperatorDep`. Same-origin browser `EventSource` sends the signed session cookie; machine consumers may use an operator-authenticated client.

### D4 — medium — insecure cookies allowed in production

Affected code: `app.config.Settings` production validation.

Actual behavior: `APP_MODE=production` accepted `COOKIE_SECURE=false`, allowing session and CSRF cookies to be sent over cleartext HTTP when deployed incorrectly.

Expected behavior: production settings must reject non-secure authentication cookies fail-closed.

Fix: production validation now raises `ValueError` unless `COOKIE_SECURE=true`.

### D5 — medium — logout lacked authenticated CSRF protection

Affected route: `POST /api/v1/session/logout`.

Actual behavior: logout cleared cookies without operator authentication or CSRF, allowing cross-site forced logout/availability disruption.

Expected behavior: cookie-authenticated logout must use the existing `MutatingOperatorDep` contract. API-token authentication remains exempt from cookie CSRF by design.

Fix: logout now depends on `MutatingOperatorDep`.

## Red → green evidence

The five regressions in `tests/unit/test_operator_surface_security_2026_07_10.py` were added before production changes.

Red on 1.52.23:

```text
5 failed in 6.30s
```

The failures independently showed missing `current_operator`, accepted production `COOKIE_SECURE=false`, and missing `require_csrf` on logout.

Green after the patch:

```text
5 passed in 6.44s
```

Full post suite:

```text
914 passed, 8 skipped
```

## Compatibility and operator action

- Alembic migration: none; head remains `0018_inference_observations`.
- Database semantics: unchanged.
- Response schemas: unchanged; unauthenticated callers now receive `401`, and cookie logout without valid CSRF receives `403` after authentication.
- Model artifacts, feature/label schemas, strategy/risk thresholds: unchanged.
- Bybit endpoint set: unchanged; advisory-only invariant preserved.
- Production `.env`: set `COOKIE_SECURE=true`. For automated `/health/ready`, configure `OPERATOR_API_TOKEN` and send `X-Operator-Token`. `/health/live` remains anonymous.
- Restart API after deployment; worker/trainer restart is not required by this code path but may be performed as part of the normal release restart.

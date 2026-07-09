# Incident runbook

## Fail-closed events

When publication, plan creation, acceptance, model activation, or drift monitoring blocks a workflow:

1. Preserve the audit event and outbox record.
2. Do not lower risk/security/model gates to clear the state.
3. Confirm database migration head and active model artifact integrity.
4. Check market data freshness, instrument specs, ticker/funding state, orderbook evidence, and account snapshot freshness.
5. Re-run the smallest reproducing unit test or CLI command.
6. Escalate only with exact status, reason code, signal/plan identifiers, and UTC timestamps.

## Exchange-cap sizing events

For `BLOCKED_EXCHANGE` or exchange-limited `LIMITED` plans:

- verify current instrument `max_qty`, notional constraints, qty step, and min notional;
- verify the latest instrument-spec snapshot source time;
- do not round quantity upward to bypass a cap;
- treat the event as `RISK_EXECUTION` attrition evidence.

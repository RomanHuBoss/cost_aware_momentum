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

## No recommendations after an hourly decision

1. Inspect authenticated `/api/v1/status` and the latest `hourly_inference` `skip_counts`, `symbol_outcomes`, `inference_retry_count`, and `publication_boundary`.
2. Treat delayed candle/context/ticker/spec reason codes as data incidents. Release 1.52.25 retries those reasons at most five times and only while the original decision remains publishable.
3. Do not override spread, entry-zone, model, drift, economics, or stale-publication rejects; they intentionally remain terminal for that decision hour.
4. If retries are exhausted, preserve the exact JobRun evidence and check market-close coverage, Bybit errors/rate limits, worker duration, database latency, and clock synchronization.
5. Do not extend the publication window or weaken thresholds merely to increase recommendation count.

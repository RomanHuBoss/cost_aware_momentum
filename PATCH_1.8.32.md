# Patch 1.8.32 — migration graph and live/research policy parity

## Problems confirmed

1. The supplied archive contained two 0008 migrations with the same parent and effectively identical DDL. Alembic therefore exposed two heads; the obsolete revision ID was 34 characters and violated the project's own standard-version-table contract.
2. Live acceptance rejects a second `ACCEPTED`/`ENTERED`/`PARTIAL` plan for the same symbol and account scope, but research backtest and promotion evaluation counted overlapping hourly candidates for that symbol. Those impossible live trades could inflate trade count and alter OOS return, drawdown, concurrency and model activation evidence.
3. The archive omitted `CHANGELOG.md`, `PATCH_1.8.31.md` and `SHA256SUMS` although its QA report stated that the release manifest had passed.

## Solution

- Removed `migrations/versions/0008_plan_outcome_path_unavailable.py`; retained the compatible head `0008_outcome_path_unavailable`.
- Added one shared, fail-closed overlap filter in `app/ml/training.py` and used it in both holdout policy evaluation and `scripts/backtest.py`.
- A candidate is blocked only while `decision_time < prior modeled exit`; an entry exactly at the exit timestamp is allowed because exit is processed before entry at that boundary.
- Bumped policy metrics to `exit-time-open-gap-single-symbol-cohort-v7` and exposed blocked/actionable counters.
- Restored release-history/provenance files and synchronized documentation.

## Compatibility

- Patch release; no API endpoint, database column, environment variable, dependency or live execution behavior changed.
- Existing v6 policy evidence is intentionally not accepted by the v7 promotion gate. Candidate and incumbent are recalculated by the current trainer on the same final holdout; the active incumbent remains active if candidate evaluation fails.
- No new Alembic migration is required. Operators must verify that only `0008_outcome_path_unavailable` is present as head before running `migrate`.

## Verification limitations

- Unit/static/offline Alembic SQL checks were run.
- A safe PostgreSQL test server was unavailable, so real upgrade/backfill/downgrade and PostgreSQL integration tests were not run.
- The research layer still lacks full historical order-book/fill/funding timelines, walk-forward governance, drift/regime control and PBO/DSR; this patch does not claim profitability.

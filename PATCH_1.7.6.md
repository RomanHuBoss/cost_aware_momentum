# Patch 1.7.6 — fail-closed counterfactual plan valuation

## Problem

`estimate_plan_outcome()` converted immutable execution-plan values directly to `Decimal` and compared them without a finite-value boundary. PostgreSQL `NUMERIC` and imported JSON snapshots can contain non-finite or malformed values. Confirmed behavior in 1.7.5 included:

- `qty=NaN` and `slippage_rate=NaN` raising `decimal.InvalidOperation`;
- infinite stress loss or reserve values being accepted as `VALUED`;
- `funding_rate=NaN` producing non-finite P&L instead of a blocked valuation;
- malformed funding timeline values escaping validation;
- one damaged plan version being able to abort the counterfactual outcome job before later plans were processed.

## Change

- Shared finite/positive/non-negative Decimal validators are now reusable across risk sizing and outcome valuation.
- Plan valuation validates qty, entry/exit, stress loss, fee, slippage, stop reserve and signed funding before arithmetic.
- Invalid plan inputs produce zero gross/cost/funding/net values, `counterfactual_r=null`, `valuation_status=INVALID_INPUT` and a field-specific `validation_error`.
- `_record_plan_outcome()` stores invalid plan snapshots with `qty=0`, preserves the valid market entry/exit, emits audit/outbox status and does not fabricate P&L.
- Invalid market outcome prices are not substituted; they remain in per-job diagnostics while other plan versions continue.
- Funding timeline parsing rejects non-finite rates and malformed timestamps/intervals. Settlement counts use bounded arithmetic.
- UI shows `Некорректный snapshot плана`.

## Compatibility

- Patch release; valid plan outcomes and existing REST fields are unchanged.
- Alembic migration `0005_plan_outcome_invalid_input` expands the valuation-status check constraint.
- No new `.env` variables are required.
- Downgrade is blocked while `INVALID_INPUT` rows exist, preventing silent deletion or relabeling of audit data.

## Verification

- RED: `python -m pytest -q tests/unit/test_counterfactual_outcomes.py` → `8 failed, 12 passed`. Failures reproduced exceptions, fail-open `VALUED` results, non-finite funding acceptance and missing DB status.
- GREEN targeted: the same module → `21 passed`.
- Full suite, Ruff, compileall, JavaScript syntax and Alembic head are recorded in `docs/QA_REPORT.md` and `docs/ITERATION_REPORT_2026-06-28-plan-outcome-input-validation.md`.

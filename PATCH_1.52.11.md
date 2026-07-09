# Patch 1.52.11 — Acceptance entry-zone validator hardening

Дата: 2026-07-09.

## Problem

`app.api.v1.recommendations.accept_recommendation()` already checked that the fresh orderbook FULL-fill VWAP was inside `signal.entry_low` / `signal.entry_high` before calling `validate_execution_plan_for_acceptance()`.

However, the validator itself did not enforce the immutable decision-time entry band. A direct caller of `validate_execution_plan_for_acceptance()` could accept a stale `ACTIONABLE` plan at a fresh executable price outside the model's decision-time support if that price was favorable enough for risk, RR and EV checks to remain green.

This is a trading-logic safety boundary defect: the model probabilities are bound to the decision-time entry-zone contract, so acceptance must not be allowed outside that support merely because the fresh price improved the apparent economics.

## Solution

- `validate_execution_plan_for_acceptance()` now validates `signal.entry_low` and `signal.entry_high` as positive finite decimals.
- Invalid zone ordering fails closed with `Signal entry zone is invalid`.
- Any fresh executable price outside `[entry_low, entry_high]` fails closed with `Current executable price is outside entry zone` before quantity, margin, funding, risk, RR or EV checks continue.
- The API-level check remains in place; the validator is now self-contained for this invariant.

## Compatibility

- No database migration.
- No new `.env` variable.
- No API-breaking change.
- No model-artifact schema change.
- No quality/promotion/risk gate weakening.
- Advisory-only boundary is unchanged; no order create/amend/cancel capability was added.

## Verification

Red evidence on 1.52.10 with the new regression test:

```text
FAILED tests/unit/test_execution_acceptance_safety.py::test_acceptance_validator_rejects_current_entry_outside_signal_zone
E   Failed: DID NOT RAISE <class 'ValueError'>
```

Green after fix:

```bash
python -m pytest -q tests/unit/test_execution_acceptance_safety.py::test_acceptance_validator_rejects_current_entry_outside_signal_zone
# 1 passed in 4.37s
```

Focused post-check:

```bash
python -m pytest -q tests/unit/test_execution_acceptance_safety.py tests/unit/test_manual_entry_risk_integrity_2026_07_01.py tests/unit/test_orderbook_vwap_sizing_integrity_2026_07_08.py tests/unit/test_decision_anchor_entry_alignment_2026_07_07.py tests/unit/test_risk_math.py
# 97 passed in 6.00s
```

Post-check summary is recorded in `docs/QA_REPORT.md` and the iteration report.

## Operational note

If acceptance reports `Current executable price is outside entry zone`, do not force acceptance. The current FULL-fill VWAP is outside the immutable decision-time support of the old signal. Recalculate from fresh market state or wait for the next eligible signal.

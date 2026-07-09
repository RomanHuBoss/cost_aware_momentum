# PATCH 1.52.13 — exchange-cap status hardening

## Scope

This patch fixes a confirmed execution-plan diagnostics defect in the risk sizing layer. The sizing API accepted an `exchange_notional_cap`, but when that cap made the safe size unexecutable it returned `BLOCKED_MIN_SIZE` and `MIN_ORDER`, hiding the actual exchange-cap cause. A limited exchange-capped plan also had no operator warning.

## Changed files

- `app/risk/math.py`
- `app/services/attrition.py`
- `web/js/app.js`
- `tests/unit/test_risk_math.py`
- `tests/unit/test_candidate_live_attrition_report_2026_07_05.py`
- release evidence and documentation files for 1.52.13

## Behavioral changes

- `EXCHANGE` and `EXCHANGE_MAX_QTY` limiting caps now map to `BLOCKED_EXCHANGE` when they make the safe position size unexecutable.
- The normalized limiting cap for this blocked condition is `EXCHANGE`.
- Limited exchange-capped plans include the Russian operator warning `Размер позиции ограничен биржевыми лимитами инструмента`.
- `BLOCKED_EXCHANGE` is classified as `RISK_EXECUTION` in attrition evidence.
- The browser UI has a dedicated label for `BLOCKED_EXCHANGE`.

## Verification

- Red evidence: the newly added targeted tests failed on 1.52.12 with `BLOCKED_MIN_SIZE` instead of `BLOCKED_EXCHANGE`, and with a missing exchange-limit warning.
- Green evidence: targeted regression suite passes on 1.52.13: `32 passed`.

## Migration and configuration

No migration is required. `.env.example` is unchanged in behavior.

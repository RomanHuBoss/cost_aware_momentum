# QA Report — 1.8.27

Дата: 2026-07-01

## Входной baseline 1.8.26

- Архив: `cost_aware_momentum-main.zip`
- SHA-256: `2941e23479306b89ab1f286eb12cc229152116e8a21e3d427368ecc89614cb71`
- Версия: `1.8.26`
- Python requirement: `>=3.12`
- Alembic head: `0007_position_account_scope`
- Состав исходного архива: 69 production Python files, 43 test Python files, 10 documentation/source-specification files, 8 migration Python files, 146 files total.
- В архиве не обнаружены `.env`, реальные секреты, виртуальные окружения, кэши, `*.pyc`, `*.egg-info`, `build/`, `dist/`, dumps или реальные model artifacts.
- В исходном root отсутствовали `CHANGELOG.md` и `PATCH_*.md`; исторический контекст восстанавливался по текущему `docs/QA_REPORT.md`, compliance/traceability и коду.

Глобальное окружение Python 3.13.5 не использовалось как итоговое доказательство качества: `pip check` обнаружил посторонний конфликт MoviePy/Pillow, `ruff` отсутствовал, а pytest не собирался без `psycopg`. Для воспроизводимой проверки создано отдельное изолированное окружение `/mnt/data/cam_audit_venv` с зависимостями проекта.

### Baseline в изолированном окружении до правок

| Проверка | Статус и результат |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 379 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — single head `0007_position_account_scope` |
| `python manage.py doctor` | NOT RUN — launcher correctly requires a project-local `.venv`; external audit venv is intentionally rejected |
| `python manage.py test --require-integration` | NOT RUN — same project-local `.venv` guard |
| `python -m scripts.test_runner --require-integration` | NOT RUN — safe stop because neither `POSTGRES_ADMIN_URL` nor `TEST_DATABASE_URL` is configured |

The baseline was green, so undocumented claims about fixed counts of critical errors were not treated as evidence. Only reproducible defects were changed.

## Confirmed defects in this iteration

| Severity | Defect | Evidence / impact |
|---|---|---|
| HIGH | Manual/paper profiles had no available-margin basis | `effective_capital()` returned `available_margin=None`; sizing could be risk-valid but infeasible against allocated capital as theoretical margin capacity. |
| HIGH | Existing accepted plans were not deducted from margin capacity | Multiple individually valid plans could reserve more account/profile margin than available. |
| HIGH | Open manual/paper journal positions were not deducted from theoretical margin capacity | New plans could overbook capital already tied to open positions. |
| HIGH | Actual entry fee did not replace the modeled entry-fee leg in stop-scenario loss | A materially higher cash fee could remain hidden behind the modeled round-trip fee assumption. |
| HIGH | Manual fill was checked against broad `risk_budget`, not the accepted plan's immutable stress-loss reservation | A fill could consume risk that the portfolio had never reserved. |
| HIGH | Lower operator-entered leverage could increase actual margin above `plan.margin_estimate` without rejection | A fill could exceed the accepted immutable margin reservation despite being directionally/risk valid. |
| MEDIUM | UI label did not state that `fee` is a cash amount in USDT | Operator could confuse a monetary amount with a fee rate. |

## Red → green evidence

Tests were first run against the original 1.8.26 behavior.

| Contract | Red before fix | Green after fix |
|---|---|---|
| Manual/paper allocated capital is the margin basis | Expected `available_margin == 1000`; actual value was `None` | PASSED |
| Actual cash fee replaces only modeled entry fee | Endpoint did not reject a fee-driven stress-loss overrun | PASSED; independent exact Decimal result `3.049` |
| Actual margin cannot exceed accepted reservation | Endpoint did not reject a 1x fill requiring 100 USDT versus 33.33 USDT reserved | PASSED |
| UI declares fee unit | Missing text `Комиссия входа, USDT` | PASSED |
| Existing reservations reduce sizing capacity | `calculate_position_plan()` had no `reserved_margin` contract | PASSED; capacity independently verified as `1000 × 75% − 600 = 150` USDT |
| Acceptance fails when aggregate reservations exhaust margin | No aggregate reservation check; no exception | PASSED |

Initial red runs: 3/3 execution-risk tests failed, 1/1 UI unit-label test failed, and 2/2 aggregate-margin tests failed for the expected missing behavior. The final dedicated module contains 10 passing regression/acceptance tests.

## Post-check 1.8.27

| Проверка | Статус и результат |
|---|---|
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 389 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — single head `0007_position_account_scope` |
| Independent cash-risk arithmetic audit | PASSED — 10,000 deterministic randomized Decimal cases against an independent formula |
| Advisory-only static mutation scan | PASSED — no order create/amend/cancel tokens in production Python scope |
| `python manage.py doctor` | NOT RUN — project-local `.venv` guard; the audit used an external isolated venv |
| `python manage.py test --require-integration` | NOT RUN — project-local `.venv` guard |
| `python -m scripts.test_runner --require-integration` | NOT RUN — no isolated PostgreSQL admin/test URL configured |
| PostgreSQL migration/integration suite | NOT RUN — no safe separate PostgreSQL test database was available |

The 19 warnings are existing joblib/NumPy 2.5 deprecation warnings in artifact runtime tests; there are no new failures.

## Compatibility and release boundary

- No database schema change and no Alembic migration.
- No new or changed environment variable.
- No Bybit write endpoint or order placement/cancellation capability added.
- API request/response field names remain unchanged.
- The behavioral change is fail-closed: fills that exceed accepted risk or margin reservations now return HTTP 422 and leave the plan accepted/unmodified for recalculation or reduction.
- Release integrity, clean re-extraction and final ZIP SHA-256 are verified after building the release archive.

## Not verified

- PostgreSQL integration and migration upgrade/downgrade against a real isolated database.
- Live/manual end-to-end browser smoke test with a real operator workflow.
- Dynamic mark-to-market risk/margin reconciliation after prices move or partial exits occur.
- Economic profitability, forward performance or live trading advantage.

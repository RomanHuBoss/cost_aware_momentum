# Patch 1.52.10 — Signal economics skip diagnostics

Дата: 2026-07-08.

## Problem

В предыдущей версии `app.services.signals` при любой `ValueError` из `select_cost_aware_scenario()` писал общий warning:

```text
Skipping symbol with invalid tick-aligned signal economics
```

и фиксировал `reason_code=invalid_signal_economics`. Поле `error` передавалось через `logger.warning(..., extra={...})`, но `JsonFormatter` его не выводил. В результате оператор видел только symbol и не мог отличить нормальную fail-closed блокировку из-за ухода bid/ask за decision-time entry zone от реального tick/spec/alignment дефекта.

## Solution

- Добавлен классификатор `classify_signal_economics_skip()` для безопасных операторских причин:
  - `quote_outside_decision_entry_zone`;
  - `executable_quote_not_tick_aligned`;
  - `no_tick_inside_decision_entry_zone`;
  - `directional_prediction_contract_invalid`;
  - `signal_policy_funding_contract_invalid`;
  - fallback `invalid_signal_economics`.
- Лог `Skipping symbol with invalid signal economics` теперь содержит `reason_code`, `contract_error`, `reason_detail`, bid/ask, decision anchor, tick-aligned entry band и tick size.
- `symbol_outcomes` в inference diagnostics для этого fail-closed path содержит тот же per-symbol context.
- Gate не ослаблен: если экономика сигнала невалидна, symbol по-прежнему пропускается и signal не публикуется.

## Compatibility

- Миграций нет.
- Новых `.env` variables нет.
- API-breaking changes нет.
- Advisory-only boundary не менялся; order create/amend/cancel не добавлялись.
- Model/trainer/risk thresholds и activation gates не менялись.

## Verification

Red evidence on 1.52.9 with the new tests:

```text
tests/unit/test_signal_economics_diagnostics_2026_07_08.py::test_json_formatter_preserves_signal_economics_skip_context
KeyError: 'reason_detail'

tests/unit/test_signal_economics_diagnostics_2026_07_08.py::test_invalid_signal_economics_skip_is_classified_in_diagnostics
AssertionError: {'invalid_signal_economics': 1} != {'quote_outside_decision_entry_zone': 1}
```

Green after fix:

```bash
python -m pytest -q tests/unit/test_signal_economics_diagnostics_2026_07_08.py
# 2 passed

python -m pytest -q tests/unit/test_signal_economics_diagnostics_2026_07_08.py tests/unit/test_attrition_inference_instrumentation_2026_07_05.py
# 3 passed
```

Post-check summary is recorded in `docs/QA_REPORT.md` and the iteration report.

## Operational note

Если в логах появляется серия `quote_outside_decision_entry_zone` по многим symbols, это обычно означает, что текущий executable bid/ask уже ушёл за immutable decision-time entry band до публикации. Это штатная защитная блокировка, а не причина увеличивать entry-zone или publication-delay без отдельного evidence. Проверьте лаг decision pipeline, свежесть ticker/candle/spec и ширину текущего spread.

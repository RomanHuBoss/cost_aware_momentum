# PATCH 1.52.22 — frontend-data-list-escaping

Date: 2026-07-09
Scope: `frontend-data-list-escaping`
Version type: patch

## Summary

This patch hardens frontend recommendation-detail rendering. The generic `dataList()` renderer previously interpolated labels and values directly into HTML assigned through `innerHTML`. Several values are normally controlled enums or formatted numbers, but profile names and other persisted/display strings can originate from operator-managed database state. They must be treated as text, not trusted HTML.

## Confirmed defect

Type: CONFIRMED DEFECT  
Severity: high  
Files: `web/js/app.js`, `tests/unit/test_frontend_html_escaping_2026_07_09.py`

- Actual behavior: `dataList()` generated `<dt>${k}</dt><dd>${v ?? '—'}</dd>` and let raw label/value text enter the DOM when the caller later assigned generated detail markup to `#detail-content.innerHTML`.
- Expected behavior: generic detail-list labels and values are HTML-escaped before insertion. Intentional multi-line display is represented by escaped newline-to-`<br>` conversion, not by raw HTML fragments passed as field values.
- Impact: a malicious or corrupted persisted string, for example a capital profile name, model/version display field, or audit/display value rendered through `dataList()`, could become scriptable markup in the operator UI.
- Why existing checks did not catch it: `node --check web/js/app.js` validates syntax only; existing UI tests did not assert escaping behavior for the reusable detail-list helper.

## Fix

- Added `formatDataListValue()` to escape `dataList()` values and preserve newlines as `<br>` after escaping.
- Changed `dataList()` to escape both labels and values.
- Changed Take Profit list rendering from raw `<br>` joining to newline joining so the generic formatter can preserve line breaks safely.
- Removed unnecessary pre-escaping at two `dataList()` call sites that now rely on the central formatter.

## Tests

New regression:

- `tests/unit/test_frontend_html_escaping_2026_07_09.py::test_data_list_escapes_labels_and_values_before_inner_html_insertion`

Red evidence before implementation:

```text
FAILED tests/unit/test_frontend_html_escaping_2026_07_09.py::test_data_list_escapes_labels_and_values_before_inner_html_insertion - AssertionError: assert 'function formatDataListValue' in ...
1 failed in 0.16s
```

Green evidence after implementation:

```text
1 passed in 0.08s
```

Related UI subset after implementation:

```text
3 passed in 0.09s
```

## Compatibility

- Database migration: not required.
- Alembic head unchanged: `0018_inference_observations`.
- `.env.example`: unchanged.
- Public API schema: unchanged.
- Bybit endpoint set: unchanged.
- Advisory-only invariant preserved; no order create/amend/cancel/withdraw capability added.

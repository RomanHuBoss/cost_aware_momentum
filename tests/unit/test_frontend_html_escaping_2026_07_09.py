from __future__ import annotations

from pathlib import Path


def _data_list_source(source: str) -> str:
    marker = "function dataList"
    assert marker in source, "dataList function is missing"
    return source.split(marker, 1)[1].split("function renderDetail", 1)[0]


def test_data_list_escapes_labels_and_values_before_inner_html_insertion() -> None:
    source = Path("web/js/app.js").read_text(encoding="utf-8")
    data_list = _data_list_source(source)

    assert "function formatDataListValue" in source
    assert "escapeHtml(k)" in data_list
    assert "formatDataListValue(v)" in data_list
    assert "replaceAll('\\n', '<br>')" in source
    assert "<dt>${k}</dt><dd>${v ?? '—'}</dd>" not in data_list

from __future__ import annotations

from pathlib import Path


STATIC_HTML = Path("src/litschema/webapp/static/index.html")


def test_verifier_defaults_to_review_table_not_pivot_table() -> None:
    html = STATIC_HTML.read_text()

    assert 'tableMode: "review"' in html
    assert 'localStorage.getItem("erw-table-mode") || "review"' in html
    assert 'state.tableMode === "pivot"' in html


def test_verifier_exposes_pivot_as_opt_in_table_mode() -> None:
    html = STATIC_HTML.read_text()

    assert 'id="btn-review-table"' in html
    assert 'id="btn-pivot-view"' in html
    assert 'Pivot' in html


def test_verifier_has_mobile_stacked_panel_layout() -> None:
    html = STATIC_HTML.read_text()

    assert "@media (max-width: 760px)" in html
    assert "flex-direction: column" in html
    assert "min-width: 520px" in html

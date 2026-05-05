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


def test_verifier_uses_explicit_annotation_actions() -> None:
    html = STATIC_HTML.read_text()

    assert "annotation-actions" in html
    assert 'data-action="verify"' in html
    assert 'data-action="flag"' in html
    assert 'data-action="clear"' in html
    assert "wireAnnotationActions" in html
    assert "Click to verify" not in html


def test_verifier_surfaces_annotation_save_feedback() -> None:
    html = STATIC_HTML.read_text()

    assert 'id="save-status"' in html
    assert "setSaveStatus" in html
    assert "saveAnnotation" in html
    assert "clearAnnotation" in html
    assert "Failed to save annotation" in html

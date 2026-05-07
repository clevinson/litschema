from __future__ import annotations

from pathlib import Path


STATIC_HTML = Path("src/litschema/webapp/static/index.html")


def test_verifier_defaults_to_review_table_without_extra_header_controls() -> None:
    html = STATIC_HTML.read_text()

    assert 'tableMode: "review"' in html
    assert 'state.tableMode = "review"' in html
    assert 'id="btn-review-table"' not in html
    assert 'id="btn-pivot-view"' not in html
    assert ">Pivot<" not in html
    assert 'id="btn-advanced"' not in html
    assert 'id="btn-json-view"' not in html
    assert 'id="confidence-display"' not in html
    assert 'id="panel-right-meta"' not in html


def test_verifier_has_mobile_stacked_panel_layout() -> None:
    html = STATIC_HTML.read_text()

    assert "@media (max-width: 760px)" in html
    assert "flex-direction: column" in html
    assert "min-width: 520px" in html


def test_verifier_uses_selected_field_actions() -> None:
    html = STATIC_HTML.read_text()

    assert "selected-field-bar" in html
    assert 'id="selected-field-label"' in html
    assert 'id="selected-field-value"' in html
    assert 'id="source-evidence-overlay"' in html
    assert 'id="source-evidence-reasoning"' in html
    assert 'id="source-evidence-range"' in html
    assert 'id="btn-source-evidence-prev"' in html
    assert 'id="btn-source-evidence-next"' in html
    assert 'id="btn-selected-verify"' in html
    assert 'id="btn-selected-edit"' in html
    assert 'id="btn-selected-clear"' in html
    assert 'aria-label="Verify selected field"' in html
    assert 'aria-label="Edit selected field"' in html
    assert 'aria-label="Clear selected field review"' in html
    assert 'data-action="verify"' in html
    assert 'data-action="edit"' in html
    assert 'data-action="clear"' in html
    assert "wireSelectedFieldActions" in html
    assert "Click to verify" not in html


def test_verifier_edits_in_selected_field_inspector() -> None:
    html = STATIC_HTML.read_text()

    assert 'id="selected-field-edit-form"' in html
    assert 'id="selected-edit-correct"' in html
    assert 'id="selected-edit-note"' in html
    assert 'id="btn-selected-save-edit"' in html
    assert 'id="btn-selected-cancel-edit"' in html
    assert "setInspectorEditMode" in html
    assert "saveSelectedFieldEdit" in html
    assert "showFlagDialog" not in html
    assert "flag-dialog" not in html


def test_verifier_table_uses_compact_evidence_badges() -> None:
    html = STATIC_HTML.read_text()

    assert "buildEvidenceBadge" in html
    assert "evidence-badge" in html
    assert "sourceSummaryForPath" in html
    assert "selectedSourceRanges" in html
    assert "reasoning-tooltip-row" not in html


def test_verifier_keeps_transient_feedback_out_of_review_header() -> None:
    html = STATIC_HTML.read_text()

    assert 'id="save-status"' not in html
    assert 'id="bulk-status"' not in html
    assert "btn-undo-bulk" not in html
    assert "setSaveStatus" in html
    assert "saveAnnotation" in html
    assert "clearAnnotation" in html
    assert "Failed to save annotation" in html


def test_verifier_exposes_bulk_review_actions() -> None:
    html = STATIC_HTML.read_text()

    assert 'id="btn-verify-article"' in html
    assert 'aria-label="Verify all unreviewed cited fields"' in html
    assert "bulk-verify-btn" in html
    assert "section-review-toggle" in html
    assert 'data-section-action="${action}"' in html
    assert '"Verify unreviewed cited fields in this section"' in html
    assert '"Clear verified fields in this section"' in html
    assert "Verify remaining" not in html
    assert "Verify Remaining" not in html


def test_verifier_bulk_review_is_reversible_and_field_level() -> None:
    html = STATIC_HTML.read_text()

    assert "collectReviewablePaths" in html
    assert "bulkVerifyPaths" in html
    assert "clearVerifiedScope" in html
    assert "undoBulkBatch" not in html
    assert "bulk_section" in html
    assert "bulk_article" in html
    assert "batch_id" in html


def test_verifier_action_column_uses_compact_status() -> None:
    html = STATIC_HTML.read_text()

    assert ".ext-table colgroup .col-status { width: 84px; }" in html
    assert '<col style="width:84px">' in html
    assert "buildFieldStatus" in html
    assert "status-verified" in html
    assert "status-flagged" in html
    assert "status-cell" in html
    assert "line-height: 1" in html
    assert "margin: 0 auto" in html
    assert "toggleFieldVerification" in html


def test_verifier_bulk_review_normalizes_primitive_array_reasoning() -> None:
    html = STATIC_HTML.read_text()

    assert "reviewableAnnotationPaths" in html
    assert "value.map((_, idx) => `${path}[${idx}]`)" in html
    assert ".flatMap(([path]) => reviewableAnnotationPaths(path))" in html


def test_verifier_section_headers_keep_status_and_bulk_action_together() -> None:
    html = STATIC_HTML.read_text()

    assert "tv-heading-actions" in html
    assert "bulkActionHtml(basePath, \"section\")" in html
    assert "sectionReviewState" in html
    assert "reviewState.complete" in html
    assert "clearVerifiedScope" in html
    assert "section-toggle-icon-hover" in html
    assert 'const disabled = count === 0 ? " disabled" : "";' not in html
    assert "bulk-section-actions" not in html
    assert "tv-toggle" not in html
    assert "tv-heading.collapsed" not in html
    assert "aria-expanded" not in html


def test_verifier_normalizes_legacy_reasoning_paths() -> None:
    html = STATIC_HTML.read_text()

    assert "normalizeReasoningPath" in html
    assert '.experimental_scale";' in html
    assert '.trial_type";' in html
    assert "normalizeReasoningPath(p)" in html


def test_verifier_scopes_review_navigation_to_current_article() -> None:
    html = STATIC_HTML.read_text()

    assert 'id="review-progress"' in html
    assert 'id="btn-next-unreviewed"' in html
    assert 'id="btn-next-flagged"' not in html
    assert "selectNextReviewPath" in html
    assert "articleOptionLabel" in html
    assert "article.confidence" not in html
    assert "filter-group" not in html
    assert "queue-summary" not in html
    assert 'id="tags-display"' not in html


def test_verifier_shows_explicit_no_citation_state() -> None:
    html = STATIC_HTML.read_text()

    assert "No citation" in html
    assert "source-missing" in html


def test_verifier_uses_explicit_no_citation_acceptance() -> None:
    html = STATIC_HTML.read_text()

    assert "selectedFieldHasCitation" in html
    assert "Accept selected value without a source citation" in html
    assert "accepted_no_citation" in html
    assert "selectedVerifyExtra" in html


def test_verifier_docks_selected_field_editor_below_review_table() -> None:
    html = STATIC_HTML.read_text()

    assert 'id="panel-right"' in html
    assert html.index('id="panel-right"') < html.index('id="selected-field-bar"')
    assert ".selected-field-bar" in html
    assert "max-height: 38vh" in html


def test_verifier_moves_source_reasoning_to_left_overlay() -> None:
    html = STATIC_HTML.read_text()

    assert "source-evidence-overlay" in html
    assert "updateSourceEvidenceOverlay" in html
    assert "focusSelectedSource" in html
    assert "selectedReasoning" in html
    assert 'id="selected-field-reasoning"' not in html
    assert 'id="selected-field-source"' not in html

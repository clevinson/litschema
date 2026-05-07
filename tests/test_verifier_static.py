from __future__ import annotations

from pathlib import Path


STATIC_HTML = Path("src/litschema/webapp/static/index.html")


def test_verifier_uses_litschema_verify_branding() -> None:
    html = STATIC_HTML.read_text()

    assert "<title>litschema verify</title>" in html
    assert "<h1>litschema verify</h1>" in html
    assert "brand-script" not in html
    assert "ERW Extraction Verifier" not in html


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


def test_verifier_uses_source_overlay_without_selected_field_box() -> None:
    html = STATIC_HTML.read_text()

    assert "selected-field-bar" not in html
    assert 'id="selected-field-label"' not in html
    assert 'id="selected-field-value"' not in html
    assert 'id="btn-selected-edit"' not in html
    assert 'data-action="edit"' not in html
    assert 'id="source-evidence-overlay"' in html
    assert 'id="source-evidence-reasoning"' in html
    assert 'id="source-evidence-index"' in html
    assert 'id="source-evidence-lines"' in html
    assert 'id="btn-source-evidence-prev"' in html
    assert 'id="btn-source-evidence-next"' in html
    assert 'id="btn-selected-verify"' not in html
    assert 'id="btn-selected-clear"' not in html
    assert 'aria-label="Verify selected field"' not in html
    assert 'aria-label="Clear selected field review"' not in html
    assert 'data-action="verify"' in html
    assert 'data-action="clear"' in html
    assert "wireSelectedFieldActions" in html
    assert "Click to verify" not in html


def test_verifier_edits_in_source_pane_modal() -> None:
    html = STATIC_HTML.read_text()

    assert 'class="panel panel-right"' in html
    assert 'class="panel panel-right"' in html and html.index('class="panel panel-right"') < html.index('id="source-edit-overlay"')
    assert 'id="source-edit-overlay"' in html
    assert 'id="source-edit-correct"' in html
    assert 'id="source-edit-note"' in html
    assert 'id="btn-source-edit-save"' in html
    assert ">Save<" in html
    assert ">Save Edit<" not in html
    assert "openFieldEditModal" in html
    assert "closeFieldEditModal" in html
    assert "displayOriginalFieldValueForEdit" in html
    assert "Extracted value" in html
    assert "AI value" not in html
    assert "saveSelectedFieldEdit" in html
    assert "selected-field-edit-form" not in html
    assert "showFlagDialog" not in html
    assert "flag-dialog" not in html


def test_verifier_uses_unicode_pencil_for_edit_actions() -> None:
    html = STATIC_HTML.read_text()

    assert 'class="icon-svg edit-icon"' not in html
    assert 'aria-label="Edit selected field"' not in html
    assert "&#9998;" in html
    assert "row-edit-action" in html
    assert 'title="Edit value">&#9998;</button>' in html


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


def test_verifier_uses_orcid_connect_flow() -> None:
    html = STATIC_HTML.read_text()

    assert 'id="reviewer-id"' in html
    assert 'type="hidden"' in html
    assert 'id="btn-orcid-connect"' in html
    assert ">ORCID</button>" in html
    assert 'id="orcid-modal"' in html
    assert 'id="orcid-input"' in html
    assert 'id="btn-orcid-lookup"' not in html
    assert 'id="btn-orcid-save"' in html
    assert "saveOrcidProfile" in html
    assert "lookupOrcidProfile" not in html
    assert "/api/orcid/" in html
    assert "Disconnect" in html
    assert html.index('id="btn-orcid-cancel"') < html.index('id="btn-orcid-save"')


def test_verifier_exposes_bulk_review_actions() -> None:
    html = STATIC_HTML.read_text()

    assert 'id="btn-verify-article"' in html
    assert 'aria-label="Verify all unreviewed cited fields"' in html
    assert "bulk-verify-btn" in html
    assert "section-review-toggle" in html
    assert 'data-section-action="${action}"' in html
    assert '"Verify unreviewed cited fields in this section"' in html
    assert '"Clear verified fields in this section"' in html
    assert "hover-clear-ready" in html
    assert "suppressClearHoverSections" in html
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
    assert ".ext-table td.status-cell" in html
    assert "line-height: 1" in html
    assert "margin: 0 auto" in html
    assert "suppressClearHoverPaths" in html
    assert "status-icon-hover" in html
    assert "row-edit-action" in html
    assert "row-clear-edit-action" in html
    assert "grid-template-columns: 22px 18px" in html
    assert ".ext-table tr:hover .row-clear-edit-action" in html
    assert "displayFieldValueForPath" in html
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
    assert "section-complete.hover-clear-ready:hover" in html
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
    assert '<strong>${counts.reviewed}/${counts.total}</strong> audited' in html
    assert "reviewed${flagText}" not in html
    assert " flagged</span>" not in html.lower()
    assert " flagged`" not in html.lower()
    assert "edited" in html.lower()
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
    assert "accepted_no_citation" in html
    assert "selectedVerifyExtra" in html


def test_verifier_docks_field_editor_over_review_table() -> None:
    html = STATIC_HTML.read_text()

    assert 'id="panel-right"' in html
    assert html.index('id="panel-right"') < html.index('id="source-edit-overlay"')
    assert ".selected-field-bar" not in html
    assert ".panel-right" in html
    assert "position: relative" in html


def test_verifier_moves_source_reasoning_to_left_overlay() -> None:
    html = STATIC_HTML.read_text()

    assert "source-evidence-overlay" in html
    assert "updateSourceEvidenceOverlay" in html
    assert "focusSelectedSource" in html
    assert "selectedReasoning" in html
    assert 'id="selected-field-reasoning"' not in html
    assert 'id="selected-field-source"' not in html

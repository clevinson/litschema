from __future__ import annotations

from pathlib import Path

STATIC_HTML = Path("src/litschema/webapp/static/index.html")


def test_verifier_uses_litschema_verify_branding() -> None:
    html = STATIC_HTML.read_text()

    assert "<title>litschema verify</title>" in html
    assert "<h1>litschema verify</h1>" in html
    assert "brand-script" not in html
    assert "ERW Extraction Verifier" not in html


def test_verifier_pdf_button_treats_127_0_0_1_as_local() -> None:
    html = STATIC_HTML.read_text()

    assert 'location.hostname === "127.0.0.1"' in html
    assert '!location.origin.includes("localhost")' not in html


def test_verifier_defaults_to_review_table_with_mode_switcher() -> None:
    html = STATIC_HTML.read_text()

    assert 'viewMode: "review"' in html
    assert 'overviewMode: "table"' in html
    assert 'id="btn-review-table"' not in html
    assert 'id="btn-pivot-view"' not in html
    assert ">Pivot<" not in html
    assert 'id="btn-advanced"' not in html
    assert 'id="btn-json-view"' not in html
    assert 'id="confidence-display"' not in html
    assert 'id="panel-right-meta"' not in html
    assert 'id="view-mode-review"' in html
    assert ">Audit</button>" in html
    assert 'id="view-mode-overview"' in html
    assert 'data-view-mode="review"' in html
    assert 'data-view-mode="overview"' in html
    assert 'data-view-mode="json"' not in html
    assert 'id="view-mode-json"' not in html
    assert 'id="overview-mode-table"' in html
    assert 'id="overview-mode-json"' in html
    assert 'data-overview-mode="table"' in html
    assert 'data-overview-mode="json"' in html
    assert "setViewMode" in html
    assert "setOverviewMode" in html
    assert "initialViewMode" in html
    assert "initialOverviewMode" in html
    assert "syncViewControls" in html


def test_verifier_restores_read_only_overview_and_json_modes() -> None:
    html = STATIC_HTML.read_text()

    assert "renderReviewTable" in html
    assert "renderOverviewView" in html
    assert "renderJsonView" in html
    assert "renderExtractionPanel" in html
    assert "state.viewMode === \"overview\"" in html
    assert "state.overviewMode === \"json\"" in html
    assert "buildOverviewHorizontalTable" in html
    assert "buildOverviewValueCell" in html
    assert "json-tree" in html
    assert "json-toggle" in html
    assert "Overview" in html
    assert "JSON" in html


def test_verifier_overview_and_json_use_effective_post_edit_values() -> None:
    html = STATIC_HTML.read_text()

    assert "effectiveExtraction" in html
    assert "applyCorrectedValue" in html
    assert "if (!isOverridden(ann)) continue;" in html
    assert "removeValueAtPath" in html
    assert "renderOverviewView(effectiveExtraction())" in html
    assert "renderJsonView(effectiveExtraction())" in html


def test_verifier_moves_identity_and_queue_controls_into_review_header() -> None:
    html = STATIC_HTML.read_text()

    toolbar = html[html.index('<div class="toolbar">'):html.index('<div class="orcid-modal-backdrop"')]
    assert 'id="review-identity-controls"' not in toolbar
    assert 'id="view-mode-json"' not in toolbar
    assert 'id="review-identity-controls"' in html
    assert html.index('id="extraction-panel-title"') < html.index('id="review-identity-controls"')
    assert 'id="review-progress"' in html
    assert 'id="btn-prev-unreviewed"' in html
    assert 'id="btn-next-unreviewed"' in html
    assert ">Previous<" in html
    assert ">Next<" in html
    assert ">Previous Field<" not in html
    assert ">Next Field<" not in html
    assert ">Next Unreviewed<" not in html
    assert "selectAdjacentReviewPath" in html
    assert "review-queue-actions" in html


def test_verifier_json_is_overview_submode_with_code_styling() -> None:
    html = STATIC_HTML.read_text()

    assert "overview-mode-toggle" in html
    assert "syncOverviewModeControls" in html
    assert "json-code-view" in html
    assert "json-token-key" in html
    assert "json-token-string" in html
    assert "json-token-number" in html
    assert "json-token-boolean" in html
    assert "json-token-null" in html
    assert 'const open = " open";' in html


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
    assert 'id="source-evidence-value"' in html
    assert 'id="source-evidence-value-label"' in html
    assert 'id="source-evidence-value-text"' in html
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


def test_verifier_edits_inline_in_value_cell() -> None:
    html = STATIC_HTML.read_text()

    assert 'id="source-edit-overlay"' not in html
    assert 'id="source-edit-correct"' not in html
    assert 'id="source-edit-note"' not in html
    assert 'id="btn-source-edit-save"' not in html
    assert "openInlineEdit" in html
    assert "cancelInlineEdit" in html
    assert "saveInlineEdit" in html
    assert "inline-edit-input" in html
    assert "inline-edit-select" in html
    assert "buildEnumEditSelect" in html
    assert "schemaFieldForPath" in html
    assert 'fetchJson("/api/schema/fields")' in html
    assert ".inline-edit-select {" in html
    assert "padding: 5px 30px 5px 10px" in html
    assert "text-overflow: ellipsis" in html
    assert "-webkit-appearance: none" in html
    assert "background-position: right 10px center" in html
    assert "inline-edit-save" in html
    assert "inline-edit-cancel" in html
    assert "displayOriginalFieldValueForEdit" not in html
    assert "Corrected value" not in html
    assert "Extracted value" not in html
    assert "AI value" not in html
    assert "saveSelectedFieldEdit" not in html
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

    assert 'id="btn-verify-article"' not in html
    assert 'id="btn-clear-article"' not in html
    assert 'aria-label="Verify all unreviewed cited fields"' not in html
    assert 'aria-label="Clear verified fields"' not in html
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
    assert "bulk_article" not in html
    assert "batch_id" in html


def test_verifier_action_column_uses_compact_status() -> None:
    html = STATIC_HTML.read_text()

    assert ".ext-table colgroup .col-status { width: 84px; }" in html
    assert '<col style="width:84px">' in html
    assert "buildFieldStatus" in html
    assert "status-verified" in html
    assert "status-flagged" in html
    assert ".field-status.status-empty:hover .status-icon-main" in html
    assert ".field-status.status-empty:hover .status-icon-hover" in html
    assert ".field-status.status-verified:hover" in html
    assert 'const hoverIcon = status === "verified" ? "&#10005;" : "&#10003;"' in html
    assert "state.annotations[path] = entry" in html
    assert "renderReviewState()" in html
    assert "status-cell" in html
    assert ".ext-table td.status-cell" in html
    assert "line-height: 1" in html
    assert "margin: 0 auto" in html
    assert "suppressClearHoverPaths" in html
    assert "status-icon-hover" in html
    assert "row-edit-action" in html
    assert "row-clear-edit-action" in html
    assert "Revert edited value" in html
    assert "&#8634;" in html
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


def test_verifier_scopes_review_navigation_to_current_article() -> None:
    html = STATIC_HTML.read_text()

    assert 'id="review-progress"' in html
    assert 'id="btn-next-unreviewed"' in html
    assert 'id="btn-next-flagged"' not in html
    assert "selectNextReviewPath" in html
    assert '<strong>${counts.reviewed}/${counts.total}</strong> fields audited' in html
    assert "tv-badges" not in html
    assert "tv-badge-audit" not in html
    assert "tv-badge-edited" not in html
    assert "auditBadgesHtml" not in html
    assert "countFieldsUnderPath" not in html
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


def test_accepting_an_uncited_value_is_plain_verification() -> None:
    """Version 2 has no tag for it, and none is needed.

    Version 1 stamped `source: accepted_no_citation` when a reviewer accepted a
    value the agent had not cited. Version 2's entry holds only `override` and
    `note`, so that tag is unrepresentable — and unnecessary: whether a field
    carried evidence is already answerable from the reasoning artifact, which
    is immutable, rather than from a flag copied into the review at click time.
    """
    html = STATIC_HTML.read_text()

    assert "selectedVerifyExtra" in html
    assert "accepted_no_citation" not in html
    assert "selectedFieldHasCitation" not in html


def test_verifier_edits_values_in_review_table_without_docked_modal() -> None:
    html = STATIC_HTML.read_text()

    assert 'id="panel-right"' in html
    assert 'id="source-edit-overlay"' not in html
    assert "inline-edit-form" in html
    assert "editing-value-cell" in html
    assert ".selected-field-bar" not in html
    assert ".panel-right" in html
    assert "position: relative" in html


def test_bib_header_has_provenance_badge_and_edit_affordance() -> None:
    html = STATIC_HTML.read_text()

    assert 'id="bib-badge"' in html
    assert 'id="bib-edit-btn"' in html
    assert 'id="bib-edit-form"' in html
    assert 'id="bib-edit-cancel"' in html
    assert "PROVENANCE_BADGES" in html
    badge_map = html[html.index("PROVENANCE_BADGES") : html.index("};", html.index("PROVENANCE_BADGES"))]
    assert "legacy" not in badge_map  # retired provenance values carry no badge
    assert "openalex" not in badge_map
    assert '"/api/bibliography/"' in html or "`/api/bibliography/" in html
    assert "lastBibMeta" in html
    assert "bibArticleId" in html
    # Lock model affordances: generic DOI pill, unlock control, per-article sync.
    assert "✓ from DOI" in html
    assert "verified via" not in html
    assert 'id="bib-sync-btn"' in html
    assert "/sync" in html
    assert "Unlock to edit" in html
    assert "Replace your manual edits" in html  # confirm() guards the destructive direction
    # Race guard: responses apply by the id captured at request time, and
    # the header only re-renders when that article is still current.
    assert "applyBibBlock(id," in html
    assert "articleId === state.currentId" in html
    # The article-change handler discards stale fetch batches too.
    assert "if (id !== state.currentId) return;" in html


def test_bib_header_title_first_layout_with_corporate_author() -> None:
    html = STATIC_HTML.read_text()

    # corporate_author is editable and rendered when no personal authors exist
    assert 'name="corporate_author"' in html
    assert "Organization" in html
    assert 'placeholder="Acme Institute"' in html
    assert "meta.corporate_author" in html
    assert "article.corporate_author" in html
    # journal input keeps its name but is labelled "Published in"
    assert 'Published in <input name="journal"' in html
    # Save/Cancel sit on their own full-width row
    assert "flex-basis: 100%" in html


def test_verifier_surfaces_a_corrupt_review_file() -> None:
    """Corrupt review state must be visible, never rendered as "no reviews"."""
    html = STATIC_HTML.read_text()

    assert 'id="review-error-warning"' in html
    assert "state.reviewError = payload?.review_error || null" in html
    assert "renderReviewErrorBanner" in html
    # Staleness is superseded by run binding and must be gone entirely.
    assert "baseStale" not in html
    assert "base_stale" not in html


def test_verifier_reads_and_writes_reviews_against_an_explicit_run() -> None:
    html = STATIC_HTML.read_text()

    assert "function activeRunId(" in html
    assert "function annotationsUrl(" in html
    # Every annotation URL is built through the run-aware helper.
    assert "/api/annotations/${id}`" not in html


def test_annotation_mutations_capture_the_article_id() -> None:
    html = STATIC_HTML.read_text()

    # Same race rule as the bib handlers: a response landing after the user
    # navigated away must not mutate the new article's state.
    save = html[html.index("async function saveAnnotation") :]
    save = save[: save.index("\n}\n")]
    clear = html[html.index("async function clearAnnotation") :]
    clear = clear[: clear.index("\n}\n")]
    for handler in (save, clear):
        assert "const id = state.currentId;" in handler
        assert "id !== state.currentId" in handler


def test_verifier_renders_placeholder_for_unextracted_articles() -> None:
    html = STATIC_HTML.read_text()

    assert "No litschema extraction has been run yet" in html
    assert "/extract-article" in html
    assert "renderNoExtractionPlaceholder" in html
    assert "has_extraction === false" in html



def test_verifier_index_served_by_app() -> None:
    from fastapi.testclient import TestClient

    from litschema.webapp.app import app

    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'id="bib-badge"' in resp.text


def test_verifier_moves_source_reasoning_to_left_overlay() -> None:
    html = STATIC_HTML.read_text()

    assert "source-evidence-overlay" in html
    assert "updateSourceEvidenceOverlay" in html
    assert "focusSelectedSource" in html
    assert "selectedReasoning" in html
    assert "selectedFieldValueHtml" in html
    assert "selectedFieldContextLabel" in html
    assert "selectedFieldValueLabel" in html
    assert 'valueBox.style.display = "inline-flex"' in html
    assert "source-cycle-control" in html
    assert "source-cycle-counter" in html
    assert "source-cycle-btn" in html
    assert "source-evidence-lines" in html
    assert 'cycle.style.display = ranges.length < 2 ? "none" : "inline-flex";' in html
    assert 'id="selected-field-reasoning"' not in html
    assert 'id="selected-field-source"' not in html
    assert 'class="review-action-btn" id="btn-source-evidence-prev"' not in html
    assert 'class="review-action-btn" id="btn-source-evidence-next"' not in html


def test_verifier_surfaces_overall_extraction_confidence() -> None:
    html = STATIC_HTML.read_text()

    # Chip sits next to review-progress in the extraction panel header,
    # hidden until reasoning supplies a top-level confidence.
    assert 'id="confidence-chip"' in html
    assert html.index('id="review-progress"') < html.index('id="confidence-chip"')
    assert "updateConfidenceChip" in html
    assert "model confidence" in html
    assert "confidence_reasoning" in html
    # Subtle banding: colored dot indicator, text stays muted.
    assert "confidenceBand" in html
    assert ".confidence-chip" in html
    assert ".confidence-low::before { background: var(--red); }" in html
    assert ".confidence-mid::before { background: var(--yellow); }" in html
    assert ".confidence-high::before { background: var(--green); }" in html


def test_verifier_surfaces_per_field_confidence_in_evidence_overlay() -> None:
    html = STATIC_HTML.read_text()

    assert 'id="source-evidence-confidence"' in html
    assert html.index('id="source-evidence-value"') < html.index('id="source-evidence-confidence"')
    assert "selectedConfidence" in html
    assert ".source-evidence-confidence" in html
    assert "typeof entry.confidence" in html


def test_inline_edit_has_typed_inputs_and_remove_affordance() -> None:
    html = STATIC_HTML.read_text()

    assert "buildTypedEditControl" in html
    assert "inline-edit-number" in html
    assert "inline-edit-boolean" in html
    assert "inline-edit-remove" in html
    assert 'op: "remove"' in html
    assert "schemaField.kind" in html or "schemaField?.kind" in html
    assert "(removed)" in html
    assert "removeInlineEdit" in html


# ── routes (ka84) ────────────────────────────────────────────────────────────


def test_verifier_exposes_overview_and_document_routes() -> None:
    html = STATIC_HTML.read_text()

    assert 'id="overview-route"' in html
    assert "function parseRoute(" in html
    assert "function applyRoute(" in html
    assert '"#/doc/"' in html or "#/doc/${encodeURIComponent(articleId)}" in html
    # Deep links must survive reload and the back button.
    assert 'window.addEventListener("hashchange"' in html
    assert "await applyRoute();" in html


def test_navigation_goes_through_the_route_not_around_it() -> None:
    """One path through the app: dropdown, deep link, and back all route."""
    html = STATIC_HTML.read_text()

    assert "if (e.target.value) routeToDoc(e.target.value);" in html
    assert "routeToDoc(state.filteredArticles[nextIdx].article_id);" in html
    # The old direct-dispatch path must be gone.
    assert 'dispatchEvent(new Event("change"))' not in html


def test_overview_lists_unextracted_articles_and_flags_unreadable_reviews() -> None:
    """The overview is the work queue, so it must show what still has no run."""
    html = STATIC_HTML.read_text()

    assert "not extracted" in html
    assert "review unreadable" in html
    assert "const noRun = !a.active_run_id;" in html
    # An unknown deep link is recoverable, never a dead end.
    assert "No document" in html


def test_reasoning_resolves_through_ancestors() -> None:
    """A row-level citation is evidence for the cells in that row."""
    html = STATIC_HTML.read_text()

    assert "function reasoningFor(" in html
    assert "inheritedFrom" in html
    # Every read goes through the resolver, not the raw index.
    body = html[html.index("function reasoningFor("):]
    assert "state.reasoningByPath[path]" in body  # the exact-match lookup inside it
    # Three raw accesses, all inside the index build and the resolver itself:
    # every other read site goes through reasoningFor().
    assert html.count("state.reasoningByPath[") == 3


def test_render_tokens_derive_from_v2_state_not_a_status_key() -> None:
    """`status` was a version-1 entry key; reading it renders everything unreviewed."""
    html = STATIC_HTML.read_text()

    assert "const statusToken = (ann)" in html
    assert "statusToken(ann)" in html
    # The version-1 key must not be read back anywhere.
    assert "ann.status" not in html
    assert "ann?.status" not in html
    # Verification is an empty entry: no version-1 `source` tag rides along.
    assert "accepted_no_citation" not in html

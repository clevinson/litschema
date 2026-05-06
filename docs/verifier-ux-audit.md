# Verifier UX Audit

## Current Goal

The verifier should optimize for field-by-field review: select a field, inspect
the cited source line, verify or flag, and move on. Dense comparison views are
useful, but they should not interfere with editing semantics.

## Findings

- The previous default table rendered some uniform arrays as horizontal pivot
  tables. That was useful for scanning repeated objects, but it made the default
  editing mode inconsistent: some clicks selected rows, some selected cells, and
  row-level annotation could imply multiple child-field annotations.
- On narrow screens, side-by-side panels squeezed extraction tables until values
  rendered one character per line. This made the app unusable on phone-sized
  viewports and also exposed that the table needed a minimum readable width.
- The normal field table was the most reliable review surface. Its source links,
  row selection, reasoning highlight, and annotation controls map cleanly to a
  single extraction path.
- The single annotation cycle button was efficient for the original author but
  too implicit for external reviewers. It also hid network write failures, so a
  reviewer could believe a field was saved when the write did not persist.

## Current Design

- The default table mode is **Review**, which renders nested field tables with
  stable one-field-per-row semantics.
- The former horizontal rendering is still available as **Pivot**, but it is an
  explicit opt-in mode.
- The JSON tree remains available for raw inspection.
- The article queue exposes All, Needs Review, Flagged, and Complete filters,
  with progress counts in the toolbar and article selector.
- Field review uses explicit Verify, Flag, and Clear actions rather than a
  hidden click cycle.
- Review mode supports reversible bulk verification at section and article
  scope. Bulk actions write field-level review events, preserve existing flags,
  skip uncited fields, and offer an undo action for the latest batch.
- Section headers keep status badges and actionable bulk review controls
  together. Completed sections omit inactive bulk actions so the heading stays
  focused on useful reviewer decisions.
- Annotation writes surface saving, saved, cleared, and failed states in the
  toolbar. Failed writes preserve the previous visible annotation state.
- Canceling a flag dialog closes the dialog without mutating the field back to
  verified.
- Mobile layout stacks source and extraction panels vertically and lets
  extraction tables scroll horizontally instead of crushing columns.
- A blank inline favicon removes the only fresh-load console error seen during
  browser testing.

## Follow-Up Ideas

- Add keyboard shortcuts for verify, flag, next cited field, and next article.
- Add a compact “needs review” filter inside the extraction panel.
- Add a selected-field review bar so row status remains visible while actions
  are consolidated away from every table row.
- Show an explicit muted `No citation` state for uncited fields.
- If section collapse returns, use a left-side disclosure icon that does not
  shift heading text alignment.
- Consider an explicit side drawer for flag editing if inline dialogs continue
  to feel cramped in nested tables.
- Add schema-aware correction inputs for enums, numbers, booleans, and remove /
  unknown states.

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

## Changes In This Branch

- The default table mode is now **Review**, which renders nested field tables
  with stable one-field-per-row semantics.
- The former horizontal rendering is still available as **Pivot**, but it is an
  explicit opt-in mode.
- The JSON tree remains available for raw inspection.
- Mobile layout now stacks source and extraction panels vertically and lets
  extraction tables scroll horizontally instead of crushing columns.
- A blank inline favicon removes the only fresh-load console error seen during
  browser testing.

## Follow-Up Ideas

- Add keyboard shortcuts for verify, flag, next cited field, and next article.
- Add a compact “needs review” filter inside the extraction panel.
- Persist collapsed sections per article rather than globally.
- Consider an explicit side drawer for flag editing if inline dialogs continue
  to feel cramped in nested tables.

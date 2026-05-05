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

## Changes In This Branch

- The default table mode is now **Review**, which renders nested field tables
  with stable one-field-per-row semantics.
- The former horizontal rendering is still available as **Pivot**, but it is an
  explicit opt-in mode.
- The JSON tree remains available for raw inspection.
- Field review now uses explicit Verify, Flag, and Clear actions rather than a
  hidden click cycle.
- Annotation writes now surface saving, saved, cleared, and failed states in the
  toolbar. Failed writes preserve the previous visible annotation state.
- Canceling a flag dialog now closes the dialog without mutating the field back
  to verified.
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
- Add schema-aware correction inputs for enums, numbers, booleans, and remove /
  unknown states.

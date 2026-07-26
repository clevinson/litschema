# Capability: verifier

Status: partially current.

## Implementation status

Live today: `litschema verify` serving a single-page app with an article
dropdown, the `?filter=` queue expression, the Audit/Overview toggle for one
article's extraction, markdown and PDF panes, review editing against the
version-1 model, and ORCID lookup. Its read API is the `/api/...` surface named
under API ownership below.

Pending: the route architecture. There is no hash routing at all today — no
`#/`, `#/doc/{id}`, or `#/runs`, and therefore no dataset summary, no
progress-metric aggregation, and no run or refinement visibility. Deep links,
encoded queue state, and the schema-error/review-error null-out contract are
part of that pending work. Tracked by `ka84`, blocked on `tdv3` and `2gd1`.
Live refinement metrics stay null until a ledger exists.

`litschema verify` is the loopback-only human review application. It consumes
active runs and run-bound reviews but does not own their storage or lifecycle.
Source metadata is owned by `specs/source-metadata/spec.md`.

## Launch and distribution

`litschema verify [--port/-p 8000]` binds `127.0.0.1` and opens one browser
window. There is no public-bind flag. Project configuration is injected through
application state; invalid article and run IDs return 404 rather than escaping
the store.

The frontend has no framework and no build step. The current static monolith is
split into native ES modules. Third-party JavaScript, components, fonts, and
styles previously loaded from CDNs are pinned, vendored with license/source
records, included in distributions, and served locally. Core summary, document,
review, and run views work without network access. Explicit ORCID lookup may
remain an optional outbound action and must fail without breaking offline
review.

## Hash routes

One application shell exposes three route-level pages:

| route | purpose |
|---|---|
| `#/` | dataset summary and work queue |
| `#/doc/{article-id}` | one document's active-run review |
| `#/runs` | minimal run and refinement visibility |

Routes are deep-linkable and survive reload. Filter, sort, and view state use
fragment query parameters and travel from the summary to a document route.
Next/previous follows that encoded queue. A direct document link without queue
state falls back to article-ID order. If a later filter excludes the open
article, the document remains open and next/previous enters the new queue.
Unknown routes render a recoverable not-found view.

### Dataset summary

The summary lists every assembled article, including articles with no active
run. It reports source metadata, active run ID, active schema hash, extraction
and reasoning availability, effective review progress, override count, and
whether the article needs refinement attention. Metrics are schema-derived; no
ERW field names are hard-coded.

### Progress metrics

`specs/reviews/spec.md` owns effective state for a path. The verifier API owns
aggregation. It interprets fields with the exact schema bytes associated with
the displayed active run, using the historical resolution contract in the
reviews spec. It never substitutes the current project schema for an older run.
If that schema is unavailable, the API sets `schema_error` and makes field
counts, progress, completion, and typed editor metadata `null`.

For a valid active run with a resolved schema, it returns:

- `field_paths`: canonical leaf paths in the raw active extraction plus the
  leaves contributed by `add` overrides, excluding every slot marked
  `identifier: true`; containers are not leaves. Omitted slots a reviewer has
  not supplied never enter the denominator, so revealing them with the
  show-all-fields toggle does not change progress;
- `n_fields = len(field_paths)`;
- `n_verified`: paths controlled by exact or ancestor verification without an
  override;
- `n_overridden`: paths controlled by an exact or terminal ancestor
  replace/remove override;
- `n_reviewed = n_verified + n_overridden`;
- `n_unreviewed = n_fields - n_reviewed`;
- `review_progress = n_reviewed / n_fields` when `n_fields > 0`, otherwise
  `1.0` for a valid zero-leaf extraction;
- `is_complete = true` only when a valid active run exists and
  `n_reviewed == n_fields`.

A note does not affect counts. A parent entry counts each raw descendant leaf
once. A terminal container override counts the raw leaves under that container;
replacement-only leaves do not change the denominator. Invalid review paths or
a corrupt review file set `review_error` and make all review counts, progress,
and completion `null`; the API never reports them as zero. An article without a
valid active run reports `n_fields = 0`, review counts `0`, progress `0.0`, and
`is_complete = false`.

Live refinement metrics come only from the sole nonterminal ledger owned by
`specs/refinement/spec.md`. When none exists, live refinement metrics are null.
A completed ledger is displayed only when its refinement ID is explicitly
selected; the verifier never chooses one by timestamp or directory order:

- `eligible_total`, `excluded_total`, and `added_after_baseline` use ledger
  scope;
- `candidate_ready`, `reconciled`, and `activated` count eligible entries in
  the corresponding recorded state;
- `cleanup_remaining` counts abandoned candidates not yet `trashed`;
- `current_schema_coverage = activated / eligible_total`, or `1.0` when the
  eligible set is empty;
- `refinement_complete` is the ledger's completion predicate, not a frontend
  inference.

An eligible article has `needs_refinement_attention` when its ledger entry lacks
a valid candidate, resolved/omitted reconciliation, or active accepted run, or
when it owns a pending proposal or cleanup error. Excluded and later-added
articles display their scope status but do not enter the denominator.

### Document review

The document route shows article metadata, prepared text/PDF, active extraction,
reasoning evidence, and review controls. It displays the active run ID and
schema identity prominently. Stored entries and effective inherited review
state are distinguishable. Replace/remove overrides show both raw and effective
values; notes do not change state.

Writes identify the displayed run explicitly. If another process changes
`active-run.json`, the page does not silently retarget a pending edit: it
requires reload or explicit acknowledgement. Articles without an active run
retain metadata/PDF access and show a clear extraction placeholder.

#### Supplying omitted values

The default view shows only what the extraction contains. Omitted fields are
not review state and do not clutter the reviewer's default surface. A "show all
fields" toggle reveals every schema-defined slot the extraction omitted,
derived from the schema field metadata the route already loads.

An array whose items the reviewer may extend offers an explicit add control.
Adding an entity opens a focused form over the item class rather than inline
tree editing, so a reviewer fills a labelled set of slots and the client can
enforce required slots before submitting. The resulting write is an `add`
override under `specs/reviews/spec.md`, appended past the raw basis.

Added values render as human-origin wherever a raw value would otherwise
appear, so a reviewer can always see which values no agent produced.

### Runs and refinement visibility

`#/runs` shows live and trashed runs, active selection, schema hash,
creation time, model, reviewed/corrupt state, and the sole
nonterminal refinement ledger's phase, scoped coverage, exclusions, pending
proposals, and cleanup count. A completed ledger appears only after explicit ID
selection. The page does not infer ledger selection, phase, or completion.

The page is visibility-oriented. List, activate, trash, restore, purge, and
reviewed-run confirmation remain `litschema runs` operations. The frontend
must not add an unprotected mutation path or imply that destructive actions
succeeded.

## Queue filter trust boundary

The local power-user queue filter may evaluate JavaScript against article
summaries. It is not a sandbox. A filter typed locally may run immediately. A
filter loaded from a URL is displayed but never evaluated during navigation;
the user must explicitly confirm its first execution. Core navigation and
review do not depend on the filter.

## API ownership

The target read surface retains `GET /api/articles`, `/api/markdown/{id}`,
`/api/pdf/{id}`, `/api/schema/fields`, and optional ORCID lookup. Extraction and
reasoning reads accept an explicit run ID; run and refinement summary endpoints
serve `#/runs`. Review endpoints follow `specs/reviews/spec.md` and always carry
a run ID. After a review write, the document and summary use server-recomputed
effective state. Route entry and explicit refresh reread disk state so CLI run
changes appear without restarting the server. Run mutation endpoints are out of
scope. Server handlers call Python APIs in process and never shell out to CLI
commands.

## Invariants

- The server binds loopback only.
- Core UI assets and behavior are local and offline.
- All assembled articles remain visible, including those without active runs.
- Each document edit is bound to the run displayed when the edit began.
- Stored and effective review state are not conflated.
- The runs page is read-only visibility; CLI protections own mutation.
- Route state is deep-linkable and recoverable.
- Traversal-shaped IDs fail as 404s.

## Test obligations

Implementation coverage must replace brittle source-substring assertions with:

- structural checks for the application shell, native module graph, pinned
  local assets and licenses, packaged-wheel inclusion, semantic landmarks,
  labels, and route containers;
- browser behavior on `#/`, `#/doc/{id}`, and `#/runs`, including direct load,
  fragment query state, filtered next/previous, exclusion of the open article,
  navigation, back/forward, and reload;
- exact active-run schema selection, unavailable-schema errors, and review
  metric formulas for no-run, zero-leaf, verified, overridden, parent-covered,
  terminal-container, invalid-path, and corrupt-review cases;
- ledger-derived eligibility, exclusions, later additions, candidate,
  reconciliation, activation, cleanup, coverage, completion, and attention
  metrics;
- document selection, raw/effective values, inherited parent coverage,
  replace/remove overrides, notes, and no-active-run placeholders;
- server-recomputed summaries after review writes, explicit refresh after CLI
  file changes, and stale displayed-run protection when active selection changes
  concurrently;
- live/inactive/trashed run visibility without mutation controls;
- offline startup with external network blocked, zero core external requests,
  and graceful optional ORCID failure;
- parity for document loading, typed filters, keyboard navigation, view modes,
  bibliography editing, review round trips, evidence navigation, PDF/markdown
  views, theme, and URL persistence;
- active-run-schema-derived typed editors, refusal to fall back to the current
  schema, and accessibility-oriented DOM checks;
- independent API contract tests for IDs, active and explicit run reads, review
  writes, and absence of run mutation endpoints;
- loopback CLI wiring and concise launch failures.

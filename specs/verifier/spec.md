# Capability: verifier

Status: partially current.

## Implementation status

Live today: `litschema verify` serving a single-page app with an article
dropdown, the `?filter=` queue expression, the Audit/Overview toggle for one
article's extraction, markdown and PDF panes, review editing against the
version-1 model, and ORCID lookup. Its read API is the `/api/...` surface named
under API ownership below.

Live today: both routes, the dataset overview with progress aggregation, the
document review against an explicit active run, deep links that survive reload
and the back button, and explicit surfacing of a corrupt review file.

Pending: any UI for supplying omitted values. The `add` op works end to end
through the API; the document view exposes no affordance for it. Tracked in
kata `ncw4`, which holds the requirements.

Browser coverage lives in `tests/browser_verify_flow.py`, which drives the real
click path and asserts both what lands in `review.json` and what the page
renders. It runs against a copy of a fixture project in a temp directory,
serving it itself, so it never touches a real one. It is not in the pytest
suite because playwright is not a project dependency.

Every behavioural requirement below is pinned there. `tests/test_verifier_static.py`
asserts only that removed surfaces stay removed: a substring in index.html
cannot detect a control that renders but does nothing, which is how a v1 status
key, a parse-time dead zone, and a `?view=review` routing bug all shipped past
a green suite.

`litschema verify` is the loopback-only human review application. It consumes
active runs and run-bound reviews but does not own their storage or lifecycle.
Source metadata is owned by `specs/bib-metadata/spec.md`.

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

One application shell exposes two route-level pages:

| route | purpose |
|---|---|
| `#/` | dataset summary and work queue |
| `#/doc/{article-id}` | one document's active-run review |

The hash-route shell is also where future run-level visibility will hang — a
route showing an article's runs and their states once articles can have more
than one. That surface is developed on the `feat/multirun` branch and is not
specified here.

Each route states where the user is and offers a marked way out. A document
shows a breadcrumb back to the overview and a persistent control returning to
it, so leaving never depends on the browser's back button. Controls scoped to a
document — the article selector, previous/next, and the view-mode toggle — are
hidden on the overview rather than shown inert, since a visible control implies
a context the user is not in.

Provenance is reported where it can be acted on. The document view names the
model that produced the extraction being reviewed — enough context while
weighing one value. Effort and extraction time are comparative: they answer
whether a document is unlike its neighbours, which is a question about the
whole set, so they appear on the overview where documents sit side by side. The
run identifier is opaque by contract and so identifies without informing; it
stays available for the run-level commands that take it, and is not
foregrounded anywhere.

No word names two things. The per-document render toggle switches how one
document's *data* is displayed and is labelled accordingly; "overview" names
the dataset route and nothing else. A control labelled for the route but wired
to something else is worse than a missing control, because it silently does the
wrong thing.

Routes are deep-linkable and survive reload. Filter, sort, and view state use
fragment query parameters and travel from the summary to a document route.
Next/previous follows that encoded queue. A direct document link without queue
state falls back to article-ID order. If a later filter excludes the open
article, the document remains open and next/previous enters the new queue.
Unknown routes render a recoverable not-found view.

### Dataset summary

The summary lists every assembled article, including articles with no active
run. It reports source metadata, what produced the active run (model, effort,
extraction time), active schema hash, extraction and reasoning availability,
effective review progress, and override count. Reporting provenance per row is
what makes an inconsistent extraction visible: one document run by a different
model, at a different effort, or long apart from the rest shows up by
comparison, which no single document view can reveal. Extraction time is its
own column so dates align and can be scanned; counts are right-aligned so
magnitudes compare at a glance.

An article whose active run produced no reviewable field is reported as having
nothing extracted, not as complete, and does not count toward the completed
tally. Completion by arithmetic over an empty set is true but reads as audited
work, which is the opposite of what it means.
Metrics are schema-derived; no ERW field names are hard-coded.

### Progress metrics

`specs/reviews/spec.md` owns effective state for a path. The verifier API owns
aggregation. It interprets fields with the schema whose hash the displayed
active run records; when the current project schema's bytes no longer match
that hash, the API sets `schema_error` and makes field counts, progress,
completion, and typed editor metadata `null` rather than silently aggregating
against the wrong schema.

For a valid active run with a resolved schema, it returns:

- `field_paths`: canonical leaf paths in the raw active extraction plus the
  leaves contributed by `add` overrides, excluding every slot marked
  `identifier: true`; containers are not leaves. Slots the extraction omitted
  and no reviewer has supplied never enter the denominator;
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

#### Feedback

A successful review needs no message: the field control moves between
unreviewed, verified, and edited, and narrating that in the header is chatter.
A failure is the opposite — it has no other signal, so it is stated in words
and stays until the next action. Writing failures nowhere is how a rejected
edit can look identical to a saved one.

The same rule governs bulk actions. Everything a bulk verification succeeds at
is already on screen: the controls it changed turn verified, and clearing
reverts them. A field it deliberately left alone shows that its evidence is
missing in its own row, permanently and beside the value the decision concerns
— which is both more durable and better placed than a count that disappears.
Only failures are stated, in the same place a single failure is stated.

#### Verification affordances

A verified control is armed to clear on the next click, and shows that by
swapping its check for a clear icon under the cursor. Arming is suppressed for
the control the pointer is on at the moment it becomes verified, until the
pointer leaves it, so the click that verified a field cannot immediately undo
it.

Suppression follows the pointer, not the write. A bulk action leaves the
pointer on the section control, having never touched the fields it verified,
so those fields stay armed and accept their next click. Suppressing them
instead would make each one silently swallow a genuine click and appear
unresponsive.

Bulk verification covers the unreviewed leaves in scope that have evidence
behind them, resolving evidence through ancestors under
`specs/extraction/spec.md`. It never overwrites an existing override: a value a
human already corrected is not re-verified by a section-wide action.

#### Supplying omitted values

The `add` override defined by `specs/reviews/spec.md` works end to end through
the annotation API: a client may append past the raw basis, and added leaves
enter the review denominator. The verifier exposes no affordance for it — no
show-all-fields toggle, no array add control, and no distinct rendering for
human-supplied values.

That UI is deliberately unspecified here rather than specified-and-unbuilt.
Its requirements, including why added values must render distinctly from
uncited extracted ones, are held in kata `ncw4` and return to this spec when
the affordance ships.

## Queue filter trust boundary

The local power-user queue filter may evaluate JavaScript against article
summaries. It is not a sandbox. A filter typed locally may run immediately. A
filter loaded from a URL is displayed but never evaluated during navigation;
the user must explicitly confirm its first execution. Core navigation and
review do not depend on the filter.

## Settings and project policy

Reviewer identity is a property of the person, not of the document on screen,
so it lives in a settings dialog reachable from either route rather than in a
per-document header. It is entered inline there: collecting one value should
not open a dialog on top of a dialog. A connected identity displays as a name
beside its identifier, with an explicit control to change it that returns to
the input without discarding the current identity until a new one is confirmed.
Registry lookup is a convenience, not a gate — an unreachable registry records
the identifier as entered rather than blocking the reviewer.

`require_reviewer` is project policy: when set, every review must name a
reviewer. Its wording states what is required and whom it binds — everyone
auditing extractions in the project, not only people on the machine that set
it — because a policy read as a local preference will be set with the wrong
expectations. It is stored in `litschema.yaml` and enforced at the write endpoint,
so it binds every caller — scripts and agents included — rather than being a
rule the browser politely follows. Writing it is the one place the verifier
mutates project configuration; the write preserves unknown keys, and clearing
the policy removes the key rather than recording a false value.

Backfilling attribution onto previously anonymous reviews never reassigns an
entry that already names someone. Whether the offer carries a warning follows
the same signal used elsewhere: outside a Git repository the project is
presumed local and its anonymous reviews the reviewer's own; inside one they
may be a collaborator's, and the dialog says so with a count before proceeding,
because the file cannot distinguish afterwards.

## Extractor explanations

The reasoning artifact's overall confidence and its accompanying explanation
are shown together, the explanation behind a visible affordance rather than a
bare tooltip — an explanation nobody knows is there is not an explanation. This
is the only place a run states why it extracted little or nothing, which is
exactly when a reviewer most needs it.

## API ownership

The target read surface retains `GET /api/articles`, `/api/markdown/{id}`,
`/api/pdf/{id}`, `/api/schema/fields`, and optional ORCID lookup. Extraction and
reasoning reads accept an explicit run ID. Review endpoints follow
`specs/reviews/spec.md` and always carry a run ID. Project settings are read and written at `/api/settings`; attribution
backfill posts to its own endpoint. After a review write, the document and
summary use server-recomputed effective state. Route entry and explicit refresh reread disk state so CLI run
changes appear without restarting the server. Run mutation endpoints are out of
scope. Server handlers call Python APIs in process and never shell out to CLI
commands.

## Invariants

- The server binds loopback only.
- Core UI assets and behavior are local and offline.
- All assembled articles remain visible, including those without active runs.
- Each document edit is bound to the run displayed when the edit began.
- Stored and effective review state are not conflated.
- Route state is deep-linkable and recoverable.
- Traversal-shaped IDs fail as 404s.

## Test obligations

Implementation coverage must replace brittle source-substring assertions with:

- structural checks for the application shell, native module graph, pinned
  local assets and licenses, packaged-wheel inclusion, semantic landmarks,
  labels, and route containers;
- browser behavior on `#/` and `#/doc/{id}`, including direct load, fragment
  query state, filtered next/previous, exclusion of the open article,
  navigation, back/forward, and reload;
- a marked exit from every document route, breadcrumb linking, and hiding of
  document-scoped controls on the overview;
- displayed run provenance (model, effort, extraction time) with the opaque
  identifier available but not foregrounded, and its absence for an
  unextracted article;
- the absence of any label naming both a route and a view mode;
- silence on successful saves and a visible, persistent message on failure;
- server-side refusal of an unattributed review under `require_reviewer`,
  preservation of unknown config keys across a policy write, and removal rather
  than falsification when the policy is cleared;
- backfill touching only unattributed entries, and warning inside a repository;
- the extractor explanation surfacing behind its own affordance, including for
  a run that extracted nothing;
- silence from a bulk action that succeeds, and a stated failure when one does
  not;
- clear-arming suppressed for a single verification's own control and not for
  fields written by a bulk action, which accept their next click directly;
- bulk verification of a section whose evidence is cited only on an ancestor,
  and preservation of existing overrides within it;
- exact active-run schema selection, unavailable-schema errors, and review
  metric formulas for no-run, zero-leaf, verified, overridden, parent-covered,
  terminal-container, invalid-path, and corrupt-review cases;
- document selection, raw/effective values, inherited parent coverage,
  replace/remove overrides, notes, and no-active-run placeholders;
- server-recomputed summaries after review writes, explicit refresh after CLI
  file changes, and stale displayed-run protection when active selection changes
  concurrently;
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

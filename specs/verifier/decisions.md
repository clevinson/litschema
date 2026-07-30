# Decisions: verifier

Append-only. Newer entries supersede older ones.

## 2026-07-07 — Spec backfilled as-built

**Context:** this capability shipped before the specs/ convention existed;
its behavior was documented only in code, tests, and skill text. A
three-lens audit of the full surface inventoried it.

**Decision:** the spec documents the capability exactly as built at audit
time, including known deviations, which are flagged inline and tracked in
`specs/improvements.md` rather than silently normalized. Future behavior
changes update the spec in the same PR, per `specs/README.md`.


## 2026-07-14 — Native-module hash routes consume first-class runs

**Context:** the single static file and CDN dependencies made the local-first
verifier brittle and hard to test. The earlier extraction-hash model also
treated run history as deferred.

**Decision:** keep a framework-free frontend but split it into native ES
modules with vendored assets. The application exposes `#/`, `#/doc/{id}`, and
`#/runs`. It reads explicit immutable runs and run-bound reviews. The runs page
is visibility-only; lifecycle mutation remains protected CLI work. Structural
and browser behavior tests replace static substring pins.

**Rejected:** a frontend framework for the MVP; CDN-required core behavior;
hash-only implicit runs; destructive run controls in the verifier.


## 2026-07-14 — Progress uses raw leaves and ledger scope

**Context:** entry counts could not represent parent coverage, container
overrides, corrupt review state, or refinement exclusions.

**Decision:** review progress counts non-identifier raw extraction leaves and
classifies each by its effective controlling review entry. Corrupt or invalid
review state produces unavailable metrics, not zero. Refinement progress and
completion come only from the authoritative ledger; excluded and later-added
articles do not enter current-schema coverage.

**Rejected:** counting stored review entries; counting replacement-only leaves;
frontend inference of refinement scope or completion; reporting corrupt review
as unreviewed.


## 2026-07-26 — Two routes, and one path through the app

**Context:** the verifier was a single page whose only navigation was a
dropdown that dispatched a change event. There was no way to link to a
document, no way back to a corpus-level view, and no answer to "what is left
to review" without opening articles one at a time.

**Decision:** `#/` is the dataset overview and `#/doc/<article-id>` is one
document. Both are deep-linkable and survive reload. Every way of moving
between documents — dropdown, prev/next, a filter that excludes the open
article, a pasted link, the back button — sets the hash and lets `applyRoute`
load the document. One path, so navigation cannot diverge from what the URL
says.

The overview lists articles with no active run rather than hiding them: that
is exactly the work someone still has to do, and hiding it would make the
queue look shorter than it is. A corrupt review file shows as "review
unreadable" with its counts blanked, never as zero — zero reads as "nothing
reviewed yet", a materially more reassuring claim than "we cannot tell".

**Rejected:** keeping the welcome splash, which occupied the position where
corpus state belongs; and auto-selecting the first article on load, which
skipped the overview entirely and made the corpus view unreachable without a
filter that matched nothing.


## 2026-07-26 — Navigation, naming, and what feedback is worth saying

**Context:** a usability pass against Nielsen's heuristics found the document
route had no marked way back to the overview. Worse, the only control labelled
"Overview" on that route was the per-document render toggle, so clicking it
expecting to navigate silently re-rendered the extraction panel instead. The
word named three things: the dataset route, the view mode, and its table/JSON
sub-modes. Separately, `setSaveStatus` and `setBulkStatus` both guarded on
elements that did not exist, so every save message — including every failure —
was computed and discarded.

**Decision:** the render toggle is "Data", renamed in the label and in the code
behind it so the two cannot drift; "overview" names the route alone. Every
document carries a breadcrumb and a persistent exit to the overview.
Document-scoped controls hide on the overview instead of rendering inert. The
document states which run it is reviewing.

On feedback, the earlier decision to keep transient chatter out of the header
was right and is kept: a successful save is already shown by the control
changing state. Only failures are written, and they persist rather than fading,
since a failure the user does not notice is indistinguishable from a success.

**Rejected:** relying on the browser back button as the exit, which is not a
designed affordance and does not survive a deep link opened in a new tab;
disabling rather than hiding document controls on the overview, which still
implies a document is open; and restoring "Saving…/Saved" messages, which
narrate what the control already shows.


## 2026-07-26 — Settings, and a policy the server actually enforces

**Context:** ORCID connection sat in the per-document review header, though who
you are does not change per document. Separately, a project may want every
review attributed, and there was no way to express that.

**Decision:** identity and project policy live in a settings dialog reachable
from either route. `require_reviewer` is stored in `litschema.yaml` and
enforced at the write endpoint. Enforcing server-side is the whole point: a
checkbox only the browser honours is bypassed by `curl` and by every agent, and
would be the same theatre as a gate that records nothing. Storing it in config
rather than browser storage follows from what it is — a statement about the
project, shared through the repository, not a preference of one machine.

This is the first time the verifier writes project configuration, which widens
a surface previously described as read-only for project state. The write is
narrow and preserves unknown keys, and clearing the policy deletes the key
rather than writing `false`.

Backfill attributes only entries that name nobody. Inside a Git repository it
warns first, with a count, because anonymous entries may be a collaborator's
and the file cannot tell afterwards who wrote them — the same reasoning that
stops canonicalization absorbing a differently attributed entry.

**Rejected:** a browser-only preference, which cannot bind a script; a required
ORCID gate before any review, rejected earlier for taxing the solo case; and
unconditional backfill, which in a shared project silently claims someone
else's work.


## 2026-07-26 — Bulk actions report failures only, like every other action

**Context:** bulk verification printed a summary — verified, skipped, later
split into verified, left-uncited, and failed. Reviewing it against what the
screen already shows, almost all of it was restatement. Verified fields turn
their controls verified. Cleared fields revert. A field left alone for lack of
evidence shows "No citation" in its own row, permanently, next to the value in
question.

**Decision:** bulk actions say nothing when they succeed, and state failures in
the same slot a single failed save uses. This makes one rule cover every
action: the control is the feedback, words are for failure. The second status
element, its function, and the batch identifier that only ever grouped a
message are all removed.

**Rejected:** keeping a success tally on the argument that bulk actions are too
large to verify by eye — the counts restate per-control state that is already
visible, and the one genuinely invisible thing, why a field was passed over,
belongs in that field's row rather than in a message that vanishes.

## 2026-07-30 — Unbuilt affordances leave the spec; their requirements move to the issue

**Context:** § Supplying omitted values specified a show-all-fields toggle, an
array add control, and distinct rendering for human-supplied values. None of it
was built. The `add` op behind it does work end to end through the annotation
API, so the spec read as though the capability shipped and only a detail was
missing. A spec that describes unbuilt UI cannot be used to tell whether the
product does what it claims — which is the one job it has on a release line.

**Decision:** the 0.1.0 verifier spec describes only implemented behaviour. The
section states plainly that the `add` op is API-only and that no affordance
exists, and points at kata `ncw4`, which now holds the requirements verbatim.
They return to the spec when the affordance ships. The progress-metric clause
that referenced the toggle was rewritten to describe the denominator without
it.

`specs/reviews/spec.md` keeps its human-origin claim, because that one is true:
an `add` op IS the record — no other op can produce a value the extraction
never had. What did not exist was carrying the distinction to consumers, so its
cross-reference now names the verifier rendering (`ncw4`) and the export audit
sidecar (`bmwn`) as unbuilt rather than asserting export already does it.

**Why the human-origin clause is called out by name in `ncw4`:** it is the
clause most likely to be lost in a move. The evidence column has two states, a
line range or "No citation". An added value has no citation and none is
possible, so without distinct rendering it is indistinguishable from an
extracted value the agent failed to cite — and those are opposites. An uncited
model value is the least trustworthy thing in the table; a human-supplied one
is the most. Shipping the add control without the marking is the defect;
neither alone harms anyone, since no user can currently create an added value.

**Rejected:** keeping the section and marking it Pending, which is what it
already was — the Pending line did not stop the section reading as a contract.
Also rejected: deleting the requirements outright, which would have lost the
reasoning above along with them.

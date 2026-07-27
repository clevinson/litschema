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

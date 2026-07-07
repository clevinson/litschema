# Decisions: reviews

Append-only. Newer entries supersede older ones.

## 2026-06-11 — review.json replaces the append-only event log

**Context:** review state lived in `reviews.jsonl`, an append-only event log
(save = append, clear = append a `cleared` marker). Reading current state
meant replaying the log; git diffs showed noise, not state; and the file
grew without bound.

**Decision:** one `review.json` per article whose content IS the current
verification state: `{version, base_extraction_sha256?, fields: {path ->
entry}}`. Writes are atomic, keys sorted, empty files deleted. The webapp
API keeps its historical field names and maps at the endpoint boundary, so
the frontend contract is unchanged.

**Rationale:** state-as-file makes git the audit log — a diff of review.json
is exactly "what changed in the review" — and reading is trivial.

**Rejected:** replaying the event log at read time (complexity without a
consumer); converting old logs (see the no-legacy entry below).

## 2026-06-11 — One review per field, total

**Context:** the first review.json draft kept a list of entries per field
(one per reviewer), with per-reviewer views and author-scoped clearing.

**Decision:** at most ONE entry per field path. Any save replaces whatever
is there, regardless of author; `author` on the entry is git-diff
attribution. Clearing drops the entry (not an attributable action).
Multi-reviewer disagreement is resolved where it is visible: in PR diffs of
review.json.

**Rationale:** the review workflow runs through git anyway; an in-app
multi-reviewer model duplicated what PRs already do, with UI complexity
(whose view am I seeing?) and no consumer for the stacked opinions.

**Rejected:** per-reviewer entry stacks (the deleted draft); recording
`cleared` tombstones (state file, not event log).

## 2026-06-11 — Reviews stamp the extraction they reviewed

**Context:** a review of `experiments[0].ph` silently misattaches if the
article is re-extracted and the experiments reorder — same path, different
meaning.

**Decision:** non-empty review.json writes carry `base_extraction_sha256`,
the hash of `agent-extraction.json` at write time. The annotations API
reports `base_stale: true` on mismatch; the verifier warns. Stale reviews
are served, not discarded — a human decides what still applies.

**Rejected:** blocking review writes on stale bases (reviewers often want to
re-verify right after re-extraction); per-field hashes (cost without
precision — reordering is the failure mode, and it invalidates wholesale).

## 2026-07-07 — No reviews.jsonl handling at all

**Context:** the branch originally set leftover `reviews.jsonl` logs aside
as `.bak` on first read (unconverted — the owner confirmed all existing logs
were dummy data). Post-#15/#17, the framework's alpha policy is explicit: no
legacy-format awareness; domain repos clean up their own files. The erw-lit
migration deleted every `reviews.jsonl` at the source.

**Decision:** all `reviews.jsonl` handling is removed — no lazy rename, no
`.bak`, no `reviews_legacy` path on `ArticleFiles`. A stray `reviews.jsonl`
is an unknown file the framework neither reads nor touches.

**Rationale:** the set-aside guarded a state that no longer exists anywhere;
keeping it meant carrying vocabulary ("legacy", ".bak") the specs forbid.
Renaming user files as a side effect of a GET was also a write the reader
never asked for.

**Rejected:** keeping the rename as a safety net (a special case with no
remaining trigger); converting old logs (throwaway data, alpha policy).

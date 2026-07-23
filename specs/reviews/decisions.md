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

## 2026-07-07 — Staleness stamps move onto each entry

**Context:** the stamp was file-level, recomputed on every write. An
adversarial review reproduced the consequence: review a field, re-extract
(warning on), verify one unrelated field — the write re-stamped the file
with the new hash and silently disarmed the warning for the entries actually
written against the old extraction. A save while the extraction file was
absent likewise erased the stamp permanently.

**Decision:** each entry carries `base_extraction_sha256` from ITS write
time; `base_stale` is true when any entry's stamp mismatches the current
extraction. Older entries keep their stamps, so saves cannot disarm the
warning for entries they did not touch, and the warning self-heals as stale
fields are re-reviewed or cleared.

**Rejected:** preserving the file-level stamp across writes (the warning
would then never clear, and fresh post-re-extraction reviews would be
wrongly flagged stale); blocking writes while stale (reviewers re-verify
immediately after re-extraction — that is the healing path).

## 2026-07-07 — Corrupt review.json refuses writes instead of being destroyed

**Context:** reads treat an unreadable review.json as empty and leave it in
place — but the write paths built on that same lenient read: a PUT rebuilt
the file from the empty map (destroying the evidence), and a DELETE removed
the file entirely via the empty-means-absent rule.

**Decision:** write paths read strictly: an unreadable file (bad JSON, bad
encoding, wrong shape) raises, and the API answers 409 telling the user to
fix or remove the file by hand. Reads stay lenient.

**Rejected:** quarantine-and-continue (renaming a user's file as a side
effect of a write is the same overreach in a different costume).

## 2026-07-07 — Canonical paths only strip the leading dot

**Context:** `canonical_review_path` also rewrote dotted-numeric segments to
bracket form (`.experiments.0.ph` → `experiments[0].ph`) — a leftover from
the event-log era. The current frontend always sends bracket-form paths, so
the rewrite's only remaining effect was a bug: a dict key that happens to be
digits (`yields.2023`) was misrouted to `yields[2023]`, orphaning the review.

**Decision:** canonicalization is `lstrip(".")`, nothing else. Keys are also
canonicalized on read, so hand-edited dotted keys round-trip through upsert
and delete instead of DELETE reporting success while removing nothing.

**Rejected:** shape-aware normalization against the extraction (complexity
serving only hand-authored path styles the frontend never produces).


## 2026-07-14 — Run-bound path overlays supersede signals and hash staleness

**Context:** immutable extraction runs make an extraction hash stamp a second,
weaker run identity. The MVP also does not need reviewer stacks or a separate
flag state; Git and pull requests already record attribution and disagreement.

**Decision:** `review.json` lives inside its run and stores at most one entry per
exact path. Entry presence without an override means verified; an explicit
replace or remove means overridden; absence means unreviewed unless an ancestor
covers the path. Notes are independent. Parent coverage is stored as a compact
canonical frontier. Reconciliation transfers only deterministic unchanged
state; ambiguous LLM-proposed mappings require user confirmation.

This supersedes the 2026-06-11 file-level article location, `signal` vocabulary,
extraction-hash binding, and the 2026-07-07 per-entry staleness stamps. It
preserves the 2026-06-11 one-review-per-field decision.

**Rejected:** retaining `base_stale` beside first-class run IDs; storing
multiple reviewers in-app; auto-accepting array mappings; expanding parent
coverage into redundant leaf entries.


## 2026-07-14 — Conservative reconstruction and explicit container semantics

**Context:** review migration was ambiguous when historical schema commits were
missing, arrays nested, overrides targeted containers, or review files were
corrupt. Subtree unreview also lacked a precise deletion and compaction rule.

**Decision:** source schemas resolve only from bytes matching the run's schema
hash, using the recorded commit, Git history, or the exact current file. No
entry transfers automatically when those bytes are unavailable. Container
overrides migrate only under explicit structural and equality gates. Array
identity resolves recursively at every boundary. Element removal uses a
non-splicing null tombstone. Subtree unreview removes all target descendants,
expands only verifying ancestor coverage, and never splits a container
override. Ambiguous proposals persist in the refinement ledger before
confirmation. Corrupt reviews remain explicit and lifecycle-protected.

**Rejected:** trusting commit labels without rehashing; primitive-type guesses
without the source schema; positional nested-array mapping; splicing element
removals; treating corrupt review as empty; implicit proposal confirmation.

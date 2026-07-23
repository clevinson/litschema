# Decisions: article-store

Append-only. Newer entries supersede older ones.

## 2026-07-07 — Spec backfilled as-built

**Context:** this capability shipped before the specs/ convention existed;
its behavior was documented only in code, tests, and skill text. A
three-lens audit of the full surface inventoried it.

**Decision:** the spec documents the capability exactly as built at audit
time, including known deviations, which are flagged inline and tracked in
`specs/improvements.md` rather than silently normalized. Future behavior
changes update the spec in the same PR, per `specs/README.md`.


## 2026-07-14 — Immutable per-article runs and active selection

**Context:** article-root extraction files were overwritten in place, so
lineage, rollback, review binding, and schema upgrades had no stable unit.

**Decision:** every extraction attempt is published under
`extraction-runs/<run-id>/` with immutable extraction, reasoning, and metadata;
only its run-bound review may change. `active-run.json` selects one live run per
article. Trash is reversible, purge is explicit, active runs are protected, and
reviewed runs require confirmation.

**Rejected:** mutable article-root outputs; extraction hashes as implicit runs;
schema copies inside runs; destructive verifier controls.


## 2026-07-14 — Purge preview parity and complete settings capture

**Context:** a preview that omitted the deletion command's reviewed-run filter
could not prove what purge would delete. The run contract also allowed callers
to omit effective model defaults.

**Decision:** `--dry-run` accepts the same `--confirm-reviewed` flag and uses
the same candidate predicate as `--purge`. Reviewed and corrupt-review runs are
excluded without confirmation and included with it. Filesystem changes after a
preview require another preview. Run settings use canonical JSON and capture all
effective behavior-affecting values and input hashes; a model run with
incomplete capture cannot publish.

**Rejected:** advisory previews with different filtering; treating corrupt
reviews as empty; best-effort model settings.


## 2026-07-14 — Purge parity is snapshot parity

**Context:** requiring a prior preview receipt would add state and alter the
approved `--dry-run`/`--purge` grammar.

**Decision:** both modes evaluate the same candidate predicate and confirmation
filter. A preview is optional and side-effect-free. For the same filesystem
snapshot and arguments, its candidate and exclusion sets equal purge's
immediate pre-delete evaluation. Settings use RFC 8785 and hash every prepared
text, context, instruction, tool, template, and other model input.

This supersedes the prior entry's requirement to repeat a preview after
filesystem change; purge re-evaluation, not a receipt, is authoritative.

**Rejected:** preview receipts or tokens; deletion from a cached candidate set;
partial input hashing.

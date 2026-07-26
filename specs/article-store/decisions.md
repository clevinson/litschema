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


## 2026-07-24 — MVP build order: list/activate now, trash/restore/purge deferred

**Context:** the full `runs` command group was speced as one unit, but a
v0.1.0 MVP only needs a working read path — verifier and export resolve every
article through `active-run.json`, which requires a way to list and activate
runs. Trash/restore/purge have no read-path dependency, and are also the
highest-risk commands to rush: destructive by design, with reviewed-run
protection and dry-run/purge parity rules that are easy to get wrong under
time pressure.

**Decision:** stage implementation. `runs list` and `runs activate` land
first and are required for 0.1.0. `runs trash`, `runs restore`, and `runs
purge` are deferred to a follow-up change. The contract in the spec is
unconditional once they ship — no partial purge grammar, no unconfirmed
reviewed-run deletion, no shortcut on dry-run/purge candidate parity.

**Rejected:** cutting trash/restore/purge from the spec (they remain correct,
just not yet built); shipping a simplified or best-effort purge for 0.1.0 to
save time.


## 2026-07-26 — run.json records reproduction and attribution, nothing else

**Context:** the original run contract required "every effective
behavior-affecting model parameter, including provider defaults," and failed
publication when a model ran but capture was incomplete. Investigation showed
that is unsatisfiable for the only extraction path that exists. A Claude Code
skill cannot observe its own sampling parameters; the environment exposes the
harness version and reasoning effort but no model identifier; the model is not
even a session constant, since a user can switch models mid-run. Roborev solves
the same problem by declaring the model in configuration and passing it to the
agent, and backfills token usage from a separate log rather than capturing it
inline. The record also carried redundancy: hashes keyed `*_sha256` holding
`sha256:`-prefixed values, a Git commit that reconciliation already treated as
a non-authoritative hint, a `tool_contract` hash duplicating the schema hash,
an `instructions` hash over a prompt the framework does not compose, and a
`lineage.kind` derivable from the parent's schema hash.

**Decision:** the record separates reproduction from attribution.
`schema_hash` and `inputs` are computed by the publisher from files it reads
itself, and publication fails if any cannot be computed. `agent` states what
the caller ran, is recorded without verification, and omits what it cannot
observe rather than inventing it — a caller that cannot name its model still
publishes. Hashes carry the algorithm in the value only. `inputs` covers
prepared text, domain context, and the conducting skill; the tool contract is
the schema and the composed prompt is not ours to hash. Schema identity is the
digest alone: a schema is found later by searching for its bytes in the working
tree or Git history, which works identically outside a repository. Runs record
no relationship to other runs; the refinement ledger owns that when reruns
exist.

**Rejected:** a `provenance: declared|measured` discriminator, which answered
no question once every run is declared; parsing Claude Code's session
transcript to recover the model, which depends on an undocumented internal
format; a `schema_dirty` flag, whose warning belongs in `doctor`/`status`
rather than stamped into every artifact; and retaining `lineage` for a release
in which no workflow can create a non-initial run.


## 2026-07-26 — 0.1.0 ships publish-activates and no runs CLI

**Context:** the 2026-07-24 build-order entry kept `runs list`/`activate` in
0.1.0 as the load-bearing read path. Splitting the release into a tight MVP
and a separate multirun line showed even that was more surface than the MVP
needs: with one meaningful run per article, there is never a choice to make,
so a selection command is a UI for a situation that cannot occur.

**Decision:** 0.1.0 ships the full run-shaped format — layout, `run.json`,
`active-run.json` — with a single-run write path: publishing a complete
non-error run atomically activates it, and that is the only activation.
Re-extraction publishes and activates a new run; prior runs and their
run-bound reviews stay inert on disk. The whole `runs` command group
(`list`/`activate`/`trash`/`restore`/`purge`) moves to the multirun branch,
targeting 0.2.0, with its contract unchanged. This supersedes the 2026-07-24
entry's build order while keeping its purge-rigor requirements intact.

**Rejected:** shipping `runs list`/`activate` in 0.1.0 (surface without a
use case); shipping the old article-root layout in 0.1.0 (would force the
one format migration the alpha policy exists to avoid); auto-trashing
superseded runs (destructive behavior without lifecycle commands to inspect
or undo it).


## 2026-07-26 — `runs list`/`activate` return to 0.1.0

**Context:** the same-day entry above cut the whole `runs` group from 0.1.0,
reasoning that with one meaningful run per article there is never a choice to
make. The first real corpus run disproved it within the hour. Two agents
extracted one paper concurrently and both runs were valid but materially
different — 45 measurements versus 5 — and the weaker one won the active
pointer purely by finishing seventy seconds later. Publish-activates offered
no way back, and the better run sat on disk unreachable.

The race came from a dispatch bug, but the gap it exposed does not depend on
one: any re-extraction that turns out worse than what it replaced is
permanent, because a superseded run remains on disk with nothing able to point
at it again.

**Decision:** `runs list` and `runs activate` ship in 0.1.0. Activation is
strict — it refuses unpublished, error-marker, and traversal-shaped run IDs,
and every refusal leaves the pointer unchanged. Listing is tolerant, showing a
run with an unreadable `run.json` rather than hiding it. Deletion stays out:
`trash`, `restore`, and `purge` remain multirun work, so 0.1.0 can select
among runs but never destroy one.

**Rejected:** shipping `activate` without `list`, which would require reading
run directories by hand to learn the ID to pass; and auto-selecting the "best"
run by heuristic such as measurement count, which would substitute a guess for
the human judgment this exists to enable.

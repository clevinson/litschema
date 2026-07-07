# Decisions — source metadata

Append-only. Newer entries supersede older ones; nothing is rewritten.

## 2026-06-10 — Bibliography lives in a provenance-tagged block, not a LinkML schema

**Context:** grey literature (no DOIs) joins journal articles as a target
corpus; a title can now come from several origins with different trust levels.
**Decision:** one `source_metadata` block inside the manifest, tagged with
`metadata_source`; a small fixed convention, deliberately outside the LinkML
schema machinery. Top-level manifest keys are identity, never bibliography.
**Rejected:** modelling bibliography in the extraction schema (conflates what
a document IS with what it SAYS); keeping loose top-level bib keys (no
provenance, no render-mode signal).

## 2026-07-05 — Retire the `.meta.yaml` sidecar

**Context:** the sidecar was the batch path for hand-authored intake metadata.
**Decision:** removed. No realistic human authors per-file YAML: small corpora
are better served by agent backfill + header edits; bulk metadata arrives as a
spreadsheet the agent transcribes into CLI calls. Its one virtue (carrying
filename-keyed data through id-minting) is covered by `original_filename` in
the manifest plus post-assembly matching.
**Rejected:** keeping it as machine interchange (redundant once a CLI write
surface exists — an agent that can write YAML can call a CLI more easily).

## 2026-07-05 — Retire `articles.csv`; harvest is manifest-driven

**Context:** harvest iterated a user-authored DOI registry CSV; its row-only
fallback stamped machine writes `manual`, permanently self-locking articles
against enrichment, and the CSV was an undocumented setup prerequisite.
**Decision:** harvest enriches every assembled article whose manifest carries
a DOI. The registry file, the row-only write path (and with it the self-lock
bug), `author_citation`, and row-supplied `open_access` are deleted. DOIs
enter manifests via agent backfill, header edits, or `meta set`.
**Rejected:** patching the fallback's provenance (a new `csv` value) — the
path itself was redundant once DOIs live in manifests. Problems should
disappear, not be patched.

## 2026-07-05 — Provenance vocabulary = actual writers only

**Context:** `PROVENANCE_VALUES` declared `crossref` and `doi` registry-
attribution values no writer ever stamped.
**Decision:** the vocabulary contains exactly the origins real writers stamp.
Speculative values invite drift (same disease as the sidecar).
**Rejected:** per-registry attribution (openalex vs crossref) — no code
consumes it; the badge is generic; re-adding a value later is one line.

## 2026-07-05 — The 3-state lock model (`doi | auto | manual`)

**Context:** four values (`openalex/filename/manual/agent`) encoded
distinctions no behavior used; the owner pushed to collapse toward a bool
("locked from DOI" vs not).
**Decision:** three stored states, two UI states. `filename` + `agent`
collapse into `auto` (nothing treated them differently). `manual` stays
distinct from `auto` for exactly one reason: batch enrichment must be able to
skip human-edited records — otherwise re-running harvest after a hand-fix
silently stomps the fix with the same wrong registry data the human corrected.
Editable is derived (`!= "doi"`); `EDITABLE_SOURCES` deleted. The
author-of-the-values rule assigns the tag (agent inferred → `auto`; human
authored → `manual` — even when an agent transcribes a human's spreadsheet).
**Rejected:** a pure bool (loses the machine-rights bit; see stomp scenario);
badging the three states distinctly (see next entry).

## 2026-07-05 — Badge minimalism: label the exception, never the default

**Context:** should the header distinguish "from DOI" vs "from LLM" vs
"manual"?
**Decision:** only `doi` earns a pill ("✓ from DOI" — generic, no vendor
name). `auto` vs `manual` is never badged: in a grey-lit corpus a "from LLM"
chip would be on everything (wallpaper), the absent pill already means "not
externally verified", and you don't put caution stickers on the intended
default. The distinction is available on demand (`meta show`).
**Rejected:** three-way badges; vendor-named pills ("via OpenAlex").

## 2026-07-05 — `litschema meta` is the one programmatic write surface

**Context:** agents and scripts had no legitimate write path (hand-editing
JSON bypasses every invariant); the never-clobber rule existed only as skill
prose.
**Decision:** `meta show/set/sync`. Strictness lives in the CLI (required
caller-asserted `--source auto|manual`, validated fields, the `can_overwrite`
guard in code); looseness lives in the agent layer (LLMs interpret arbitrary
user spreadsheets ad hoc and emit canonical CLI calls). The webapp calls the
same library functions in-process — the CLI is a peer caller, never the
implementation.
**Rejected:** a rigid bulk-import file format (brittle against real-world
exports; the emitted CLI calls are the replayable record instead); asserting
`doi` via `meta set` (registry provenance is earned, not claimed).

## 2026-07-05 — `meta sync --all` supersedes `harvest`; scope decides consent

**Context:** "harvest" named a CSV-era operation that no longer exists; batch
and per-article registry fetches are one concept.
**Decision:** one verb — sync from the DOI registries. Per-article sync
(button / `meta sync <id>`) is explicit consent and may overwrite anything,
including `manual`. Batch (`--all`) is a sweep and never touches `manual`.
Legacy `litschema harvest` remains for its CrossRef-supplement and
entity-resolution legs (the explore store consumes those registries), with
help text pointing at the new verb.
**Rejected:** renaming harvest wholesale (its extra legs have real consumers);
letting batch overwrite unlocked-but-edited records (the stomp scenario).

## 2026-07-05 — The block is the DOI's single home

**Context:** the DOI lived twice (identity level + block), requiring a
mirroring rule to prevent drift — the classic sign there should be one copy.
**Decision:** the block is canonical. The top-level `doi` is a read-only
legacy fallback for pre-block manifests (nothing writes it; inert once a block
has a DOI). `meta sync --doi` passes the DOI straight into the fetch and is
manifest-atomic: a registry miss records nothing, and the error points at
`meta set --source manual --doi ...` as the deliberate escape hatch.
**Rejected:** two slots + mirroring (drift machinery for a self-inflicted
problem); recording `--doi` before the fetch (provenance puzzle on failure).

## 2026-07-05 — Specs live in this repo

**Context:** design docs previously lived in the external erw-research repo.
**Decision:** framework capabilities carry their specs in the framework's own
repo (`specs/`), updated in the same PR as behavior changes. This folder's
conventions: `specs/README.md`.

## 2026-07-05 — No legacy-format awareness; migrations belong to the domain repo

**Context:** the single-DOI-home decision (above) kept a read-time fallback to
the legacy top-level `doi` for pre-block manifests, so unmigrated corpora
could be enriched without a migration step. That fallback bred the
DOI-resurrection bug, was patched with a subtler conditional, and required a
paragraph of explanation — the lifecycle of a wart.
**Decision:** the fallback is removed; litschema reads DOIs from the block,
period. This supersedes the legacy-fallback portion of the single-DOI-home
entry. More broadly (alpha policy, now in specs/README.md): until a versioned
release exists, the framework carries no backwards compatibility or
migration code — format changes land clean, and existing corpora update
their data in their own repos (for erw-lit: loop `meta set --source auto
--doi`, then `meta sync --all`).
**Rejected:** keeping the narrowed pre-block-only fallback (still legacy
awareness, still a special case to explain and test); an in-framework
`migrate` command (same objection, more surface).

## 2026-07-07 — `meta set --sync`: registry-first enrichment, one guarded command

**Context:** the agent contract was two commands — `meta set --source auto
<fields> --doi X`, then `meta sync <id>` — with different consent semantics.
A review pass caught the hazard (an agent syncing after a guard refusal would
clobber human edits; patched with skill instructions), and the happy path was
wasteful: the registry immediately replaced everything the agent had just
transcribed.

**Decision:** `meta set` gains `--sync`, which REQUIRES `--doi` and FORBIDS
every other field option and `--clear`. It records the DOI under the caller's
`--source` tag (guarded like any set) and immediately attempts the registry
lock. Success → block replaced with registry values, `doi`. Registry failure →
the DOI stays recorded, unlocked, retryable by per-article sync or the sweep.
Guard refusal → nothing runs. The agent contract becomes registry-first:
title-page transcription happens only as an explicit fallback (no DOI, or the
sync half failed).

**Rationale:** one guard verdict covers both halves, so agent-supplied consent
escalation is unrepresentable rather than instructed away; nothing is ever
written that a successful sync would immediately destroy; and the happy path
skips hand-transcription entirely — cheaper and less error-prone.

**Rejected:** allowing fallback fields alongside `--sync` (dead-on-arrival
writes, and the half-found-fields clobber question this entry exists to kill);
spelling it `set --from-doi <doi>` (hides the record-then-attempt two-phase
and muddles what `--source` tags when the registry fails); making
`meta sync --doi` record the DOI on a registry miss (breaks sync's
nothing-on-failure atomicity).

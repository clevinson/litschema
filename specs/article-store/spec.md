# Capability: article store

Status: approved target.

The on-disk source of truth is one directory per document under
`data/papers/<article-id>/`. This spec owns article identity, immutable
extraction runs, active-run selection, and the run CLI lifecycle. Extraction
contents are defined by `specs/extraction/spec.md`; review entries and
reconciliation are defined by `specs/reviews/spec.md`.

## Layout

```text
data/papers/<article-id>/
  article-metadata.json
  <article-id>.pdf
  article.md
  active-run.json
  extraction-runs/
    <run-id>/
      agent-extraction.json
      agent-reasoning.json
      run.json
      review.json
    .trash/
      <run-id>/
        ...same four run artifacts...
```

`ArticleFiles` is the sole article-id-to-path chokepoint. Article IDs and run
IDs are single path components; empty values, `.`, `..`, `/`, and `\` are
invalid. A run ID is framework-generated, opaque, path-safe, and unique within
its article. Consumers must not derive meaning from its text.

Article-root `agent-extraction.json`, `agent-reasoning.json`, and `review.json`
are not canonical. Pre-release corpora are rewritten into the run layout by
their owning repository; the framework does not read both layouts.

## Run boundary and immutability

A published run directory is a complete extraction attempt. The extraction,
reasoning, and `run.json` payload never change after publication. `review.json`
is the only mutable file inside a run because it records later human review of
that immutable payload. Writes to `review.json` remain atomic.

An attempt is prepared outside its final run path and published atomically only
after its required artifacts are present. Failed extraction attempts may be
published with the extraction error marker defined by the extraction spec, but
they cannot become active. Partial directories are never runs.

`run.json` has this required shape:

```json
{
  "version": 1,
  "run_id": "01J2Q4Y7Y9K0M3T6W8X1Z5A9BC",
  "article_id": "beerling-2024",
  "created_at": "2026-07-14T21:20:00Z",
  "schema_sha256": "sha256:…",
  "schema_git_commit": "0123456789abcdef0123456789abcdef01234567",
  "schema_dirty": false,
  "provider": "openai",
  "model": "model-name",
  "settings": {
    "temperature": 0,
    "prepared_text_sha256": "sha256:…",
    "domain_context_sha256": "sha256:…",
    "instructions_sha256": "sha256:…",
    "tool_contract_sha256": "sha256:…"
  },
  "lineage": {
    "kind": "initial",
    "parent_run_id": null
  }
}
```

`schema_sha256` is mandatory and hashes the exact configured schema file bytes.
`schema_git_commit` is the full commit containing those bytes when one exists;
otherwise it is `null` and `schema_dirty` is true. Provider and model keys are mandatory and may be `null` only for a run that did
not invoke a model. `settings` uses RFC 8785 JSON Canonicalization Scheme bytes. Strings retain
their Unicode code points; numbers follow the scheme's finite JSON-number rules;
NaN, infinity, duplicate keys, and non-JSON values are rejected. It records
every effective behavior-affecting model parameter, including provider
defaults, plus SHA-256 hashes for prepared article text, domain context,
composed extraction instructions/prompt, tool contract, templates, and any
other model input not already identified by `schema_sha256`. It excludes
secrets, timestamps, request IDs, and transport metadata. Publication fails
when a model ran but the publisher cannot capture the complete effective
setting and input set.

`lineage.kind` is `initial`, `same_schema`, or `schema_upgrade`.
`parent_run_id` is null only for `initial`; otherwise it names the prior run
from which the attempt was requested. The schema-identity rules in `specs/project-config/spec.md` determine which
non-initial kind applies. `specs/refinement/spec.md` owns when each kind is
created.

## Active selection

`active-run.json` is the article-level selection:

```json
{"run_id": "01J2Q4Y7Y9K0M3T6W8X1Z5A9BC"}
```

The file is written atomically. Absence means that the article has no active
extraction. Its target must be a complete, non-error, non-trashed run under the
same article. A broken pointer is an integrity error; consumers must not guess
another run. Activation changes only this pointer and never mutates either run.

Verifier and export consumers resolve each article independently. A corpus may
therefore be temporarily mixed during a resumable refinement, but the
refinement workflow is not complete until every eligible article selects a run
using the current schema hash.

## Run CLI

The command group is `litschema runs`:

| command | contract |
|---|---|
| `runs list [<article-id>] [--trash]` | List run ID, active/reviewed/trashed state, schema hash, timestamp, model, and lineage. |
| `runs activate <article-id> <run-id>` | Atomically select a complete live run. |
| `runs trash <article-id> <run-id> [--confirm-reviewed]` | Move an inactive run to `.trash/`. |
| `runs restore <article-id> <run-id>` | Move a trashed run back to the live run namespace. |
| `runs purge [<article-id> [<run-id>]] --dry-run [--confirm-reviewed]` | List the exact deletion candidate set under the supplied scope and confirmation flags, plus excluded protected runs. |
| `runs purge [<article-id> [<run-id>]] --purge [--confirm-reviewed]` | Permanently delete the candidate set produced by the same predicate. |

`--dry-run` and `--purge` are mutually exclusive and one is required. Purge
operates only on `.trash/`; live runs are never purge candidates. An active run
cannot be trashed or purged. A reviewed run is one whose valid `review.json` has at least one field entry.
A corrupt or unreadable review file has protected `corrupt` review state and is
treated as reviewed for lifecycle commands. Trashing or purging either state
requires `--confirm-reviewed`; this confirmation does not bypass active-run
protection.

Dry-run and deletion use the same scope, trash-only rule, review-state parser,
and `--confirm-reviewed` filter. Without confirmation, reviewed and corrupt
runs appear as excluded and are absent from the candidate set. With
confirmation, both enter the candidate set. Dry-run is a side-effect-free evaluation, not an authorization receipt, and
purge does not require a prior preview. Given the same filesystem snapshot and
arguments, both modes produce the same candidate and exclusion sets. Purge
re-evaluates that predicate immediately before deletion.
Restore fails rather than replacing an existing live run ID.

## Manifest and intake

`article-metadata.json` owns article identity and source metadata only. Identity
keys are `id`, `filename`, `original_filename`, `file_sha256`, `added_at`, and
`open_access`. It does not duplicate active selection or extraction-run
provenance. Writes shallow-merge non-null top-level values, default `id` from
the directory, and atomically replace the file.

`litschema assemble` remains offline. It slugifies the PDF filename stem,
uses `article` for an empty slug, treats identical bytes as an idempotent
re-drop, and gives different bytes that collide a short content-hash suffix.
Each successful PDF moves to `<article-id>/<article-id>.pdf`, receives a
manifest, and seeds automatic title metadata. Re-drops move to
`papers-inbox/.processed/`. A bad PDF is counted and left in the inbox while
the batch continues.

Stats are `inbox_pdfs`, `assembled`, `already_assembled`, and `errors`. Per-file
errors do not abort the batch; interruption exits 130 and preserves resumable
work. The manifest, canonical PDF, and prepared text stay at article root
because they belong to the article, not a run.

## Text preparation

`litschema prepare-text <article-id> | --all` converts PDFs to `article.md`
offline. Exactly one of an ID or `--all` is required. Existing markdown is
skipped unless `--force` is used. `--inbox-dir` and `--output-dir` retain their
current override behavior.

PDF resolution checks the manifest filename under the article directory, then
the inbox. Batch mode also discovers inbox PDFs without manifests. Stats are
`total`, `converted`, `skipped`, `empty`, `missing`, and `errors`; output under
100 characters is `empty` but remains written.

## Invariants

- WHEN an article or run ID is resolved, THEN the guarded path chokepoint
  rejects traversal-shaped input.
- WHEN a run is published, THEN its extraction, reasoning, and metadata are
  complete and thereafter immutable.
- WHEN a review changes, THEN the run payload and active pointer do not.
- WHEN activation succeeds, THEN `active-run.json` names one complete live run
  from the same article.
- WHEN an active run is targeted by trash or purge, THEN the command fails.
- WHEN a reviewed run is targeted by trash or purge without explicit
  confirmation, THEN the command fails.
- WHEN the same PDF bytes are assembled twice, THEN no duplicate article is
  created.

## Test obligations

Implementation coverage must pin:

- the complete live and trashed layouts and rejection of article-root run
  artifacts;
- guarded article and run IDs;
- atomic run publication, review writes, and active-pointer replacement;
- immutable extraction, reasoning, and metadata after publication;
- required run metadata, RFC 8785 settings, complete effective parameters and
  model-input hashes, rejection of incomplete capture, honest null provenance,
  schema hash determinism, and
  all three lineage kinds;
- activation of valid runs and rejection of missing, partial, error, foreign,
  or trashed runs;
- list output for active, inactive, reviewed, and trashed runs;
- active-run protection; valid-reviewed and corrupt-review confirmation;
  restore collisions; dry-run/deletion candidate parity with and without
  confirmation; state-change refusal; and permanent purge only from trash;
- missing active selection as a normal unextracted state and broken selection
  as an integrity failure;
- assemble idempotence, collision handling, offline operation, and atomic
  manifests.

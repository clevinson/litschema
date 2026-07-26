# Capability: article store

Status: partially current.

The on-disk source of truth is one directory per document under
`data/papers/<article-id>/`. This spec owns article identity, immutable
extraction runs, active-run selection, and the run CLI lifecycle. Extraction
contents are defined by `specs/extraction/spec.md`; review entries and
reconciliation are defined by `specs/reviews/spec.md`.

## Implementation status

Live today: the article directory and its `article-metadata.json` manifest, the
`ArticleFiles` path chokepoint and ID guards, `assemble`, and `prepare-text`.

Pending — everything run-shaped. Extraction, reasoning, and review files
currently sit at the article root and are overwritten in place; there is no
`extraction-runs/`, no `run.json`, and no `active-run.json`. The Layout, Run
boundary, and Active selection sections below are the 0.1.0 target, tracked by
`tdv3`, whose write path is publish-activates.

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
  "created_at": "2026-07-26T18:04:11Z",

  "schema_hash": "sha256:9f2a…",

  "inputs": {
    "prepared_text": "sha256:c41d…",
    "domain_context": "sha256:7be0…",
    "skill": "sha256:1a88…"
  },

  "agent": {
    "harness": "claude-code",
    "harness_version": "2.1.219",
    "provider": "anthropic",
    "model": "claude-opus-5",
    "effort": "high"
  }
}
```

Every hash is `<algorithm>:<hex>`. The algorithm lives in the value, never in
the key, so a key never contradicts what it holds.

### Reproduction versus attribution

The record separates what the framework controls from what it can only report.

`schema_hash` and `inputs` are **reproduction**. They hash bytes the publisher
reads off disk itself: the configured schema file, the article's prepared text,
the domain context, and the skill or program that conducted the extraction.
Publication fails if any of them cannot be computed — an unhashable input means
the run cannot state what it was run against, which is the one claim this file
exists to make.

`agent` is **attribution**. It names what produced the extraction and is
recorded as requested, not as confirmed by a provider. An agent harness cannot
observe its own sampling parameters, and a model identifier may be resolved
further downstream than the caller can see, so these values are honest about
intent rather than measurement. `harness`, `harness_version`, and `effort` come
from the execution environment when it exposes them. An optional `settings`
object carries sampling parameters when a caller genuinely has them, such as a
direct provider API call; it uses RFC 8785 JSON Canonicalization Scheme bytes,
rejects NaN, infinity, duplicate keys, and non-JSON values, and excludes
secrets, request IDs, and transport metadata. It is absent rather than empty
when nothing is observable. `agent` is `null` for a run that invoked no model.

A run records no relationship to any other run. It states what it was, not what
it came from. Nothing in this release creates a run derived from another one;
when that workflow exists, `specs/refinement/spec.md` owns the mapping between
source and candidate runs, and a parent reference may be added here then.

## Active selection

`active-run.json` is the article-level selection:

```json
{"run_id": "01J2Q4Y7Y9K0M3T6W8X1Z5A9BC"}
```

The file is written atomically. Absence means that the article has no active
extraction. Its target must be a complete, non-error run under the same
article. A broken pointer is an integrity error; consumers must not guess
another run. The only activation is the publisher's: publishing a complete
non-error run atomically activates it, and activation changes only this
pointer, never a run.

Verifier and export consumers resolve each article independently.

## Toward multiple runs

The run-per-directory layout exists so a future release can hold several runs
per article — reruns after a schema change, side-by-side candidates, trash and
restore — without changing this format. That behavior, and the CLI that
manages it, is developed on the `feat/multirun` branch and is deliberately not
specified here. In this release the only lifecycle is: publish activates, and
superseded runs stay inert on disk.

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
- WHEN the same PDF bytes are assembled twice, THEN no duplicate article is
  created.
- WHEN an input hash cannot be computed, THEN publication fails.
- WHEN agent attribution is unavailable, THEN publication still succeeds and
  the record omits what it cannot observe rather than inventing it.

## Test obligations

Implementation coverage must pin:

- the complete run layout and rejection of article-root run artifacts;
- guarded article and run IDs;
- atomic run publication, review writes, and active-pointer replacement;
- immutable extraction, reasoning, and metadata after publication;
- required run metadata; deterministic schema and input hashing independent of
  the working directory; `<algorithm>:<hex>` hash formatting; publication
  failure when any input hash cannot be computed; publication success when only
  agent attribution is unavailable; absent rather than empty `settings`; RFC
  8785 canonicalization when `settings` is present; and `agent: null` for a run
  that invoked no model;
- publish-activates: a successful publish replaces the active pointer, an
  error-marker publish does not, and a re-extraction leaves the prior run
  directory intact and unmodified;
- missing active selection as a normal unextracted state and broken selection
  as an integrity failure;
- assemble idempotence, collision handling, offline operation, and atomic
  manifests.

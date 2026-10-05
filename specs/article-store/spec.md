# Capability: article store

Status: partially current.

The on-disk source of truth is one directory per document under
`data/papers/<article-id>/`. This spec owns article identity, immutable
extraction runs, and active-run selection. Extraction contents are defined by
`specs/extraction/spec.md`; review entries are defined by
`specs/reviews/spec.md`. The run lifecycle beyond `list` and `activate` —
trash, restore, purge — belongs to the deferred multirun work and is not
specified here.

## Implementation status

Live today: the article directory and its `article-metadata.json` manifest, the
`ArticleFiles` path chokepoint and ID guards, `assemble`, `prepare-text`, the
run layout (`extraction-runs/<run-id>/`, `run.json`, `active-run.json`), and
the publish-activates write path — `agent record-extraction` validates the
staged artifacts, computes the reproduction hashes, publishes atomically, and
activates complete non-error runs. Every consumer (verifier, export, validate,
status) resolves articles through the active run.

Live today also: `runs list` and `runs activate`.

Pending: `review.json` placement. The layout below shows it inside the run
directory, but the version-1 review model still lives at the article root; it
moves into the run with reviews v2 (`2gd1`).

## Layout

```text
data/papers/<article-id>/
  article-metadata.json
  <article-id>.pdf
  article.md
  figures/
  prepared-text.json
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
  },

  "litschema": {
    "version": "0.1.1",
    "source": "release"
  },

  "conversion": {
    "version": 1,
    "tool": "pymupdf4llm",
    "tool_version": "1.28.2",
    "pymupdf_version": "1.28.2",
    "options": {"use_ocr": false, "header": false, "footer": false, "…": "…"},
    "pdf_sha256": "sha256:5e0a…",
    "text_sha256": "sha256:c41d…",
    "figures_sha256": "sha256:88b3…",
    "litschema_version": "0.1.2",
    "created_at": "2026-07-26T17:58:02+00:00"
  }
}
```

`conversion` is optional. The publisher copies it from the article's
`prepared-text.json` (see Text preparation), dropping the `figures` list and
adding `figures_sha256`: the SHA-256 of the UTF-8 lines `<name>:<sha256>\n`,
one per figure, sorted by name. An article with no `prepared-text.json`
publishes without the block. When the record exists, its `text_sha256` must
equal `inputs.prepared_text`, or publication fails: `article.md` was edited, or
something rewrote it without writing a record.

Every hash is `<algorithm>:<hex>`. The algorithm lives in the value, never in
the key, so a key never contradicts what it holds.

`litschema` records the version that published the run and how it was
installed: `release` (a package index), `git` (with a `commit` key naming the
code), or `local` (a path on disk, possibly with uncommitted edits). The
publisher reads both from the installed package metadata. Runs published
before 0.1.1 lack the block and remain valid.

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
another run. Activation changes only this pointer, never a run.

Publishing a complete non-error run activates it, so the newest successful
extraction is active by default. `runs activate` reselects an earlier run when
that default is wrong — a re-extraction that turned out worse than what it
replaced is otherwise unrecoverable, because a superseded run stays on disk
but nothing can point at it again.

Verifier and export consumers resolve each article independently.

## Run CLI

| command | contract |
|---|---|
| `runs list [<article-id>]` | List each run's ID, timestamp, model, schema hash, and active/error/reviewed state. Without an article, list every article's runs. |
| `runs activate <article-id> <run-id>` | Atomically select a published, complete, non-error run. |

Activation refuses a run that is not published under this article, an
error-marker run, and a traversal-shaped ID. Every refusal leaves the active
pointer unchanged. Reselecting the already-active run succeeds unchanged.
Neither command mutates a run.

Listing is tolerant where selection is strict: an unreadable `run.json` still
lists, with its unknown fields blank, so a damaged run remains visible to the
person who has to deal with it.

## Toward multiple runs

Deleting runs — trash, restore, and purge — is deliberately absent. A
superseded run stays on disk, inert but selectable, and nothing in this
release removes one. That lifecycle, along with reprocessing a corpus after a
schema change, is developed on the `feat/multirun` branch and is not specified
here.

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
work. The manifest, canonical PDF, prepared text, figures, and conversion record stay
at article root because they belong to the article, not a run.

## Text preparation

`litschema prepare-text <article-id> | --all` converts PDFs to `article.md`
offline. Exactly one of an ID or `--all` is required. Existing markdown is
skipped unless `--force` is used. `--inbox-dir` and `--output-dir` retain their
current override behavior.

PDF resolution checks the manifest filename under the article directory, then
the canonical `<article-id>.pdf`, then the inbox. Batch mode also discovers
inbox PDFs without manifests. Stats are `total`, `converted`, `skipped`,
`empty`, `missing`, and `errors`; output under 100 characters is `empty` but
remains written.

Conversion calls `pymupdf4llm.to_markdown` with `use_ocr=False`,
`header=False`, `footer=False`, `write_images=True`, `image_format="png"`, and
`dpi=150`. OCR is off: a scanned PDF converts to little or no text and counts
as `empty`. Post-processing then:

- drops every image whose content hash occurs 3 or more times in the document
  (logos, page furniture) and every image under 150 px wide or 100 px tall,
  deleting the file and blanking its markdown line (the line stays, empty);
- rewrites each kept image ref to `![](figures/<name>)`;
- strips `<mark>` and `</mark>` (MuPDF flags shaded form fields as highlights).

Kept images go to `<article-id>/figures/`. A rerun with `--force` replaces the
directory; a conversion that keeps no images leaves none.

Each conversion writes `<article-id>/prepared-text.json` atomically, after
`article.md`:

```json
{
  "version": 1,
  "tool": "pymupdf4llm",
  "tool_version": "1.28.2",
  "pymupdf_version": "1.28.2",
  "options": {
    "use_ocr": false, "header": false, "footer": false, "write_images": true,
    "image_format": "png", "dpi": 150,
    "drop_figure_repeats_at": 3, "min_figure_width_px": 150, "min_figure_height_px": 100
  },
  "pdf_sha256": "sha256:…",
  "text_sha256": "sha256:…",
  "figures": [{"name": "smith-2024.pdf-0003-02.png", "sha256": "sha256:…"}],
  "litschema_version": "0.1.2",
  "created_at": "2026-07-26T17:58:02+00:00"
}
```

`text_sha256` hashes the `article.md` bytes as written, the same bytes
`inputs.prepared_text` hashes at publication. The record holds no text from the
paper, so projects commit it; `article.md` and `figures/` stay ignored and
regenerate from the PDF.

With `--output-dir DIR`, the markdown goes to `DIR/<article-id>.md`, figures to
`DIR/<article-id>-figures/` with refs `![](<article-id>-figures/<name>)`, and
the record to `DIR/<article-id>.prepared-text.json`.

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
- WHEN `prepared-text.json` exists and its `text_sha256` differs from the
  hash of `article.md`, THEN publication fails.
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
- `runs activate` reselection, refusal of unknown/error/traversal run IDs with
  an unchanged pointer, and mutation of neither run;
- `runs list` active/error/reviewed marking, model and schema reporting, and
  tolerance of an unreadable `run.json`;
- missing active selection as a normal unextracted state and broken selection
  as an integrity failure;
- assemble idempotence, collision handling, offline operation, and atomic
  manifests;
- prepare-text on a real PDF: recorded options, repeated and small images
  dropped, refs rewritten, `<mark>` stripped, record hashes, `--force`
  replacing `figures/`, flat-mode paths, and the canonical-PDF fallback;
- the `conversion` block copied into `run.json`, its absence without a record,
  and refusal on a text hash mismatch.

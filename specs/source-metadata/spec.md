# Capability: source metadata

Status: current.

Provenance-locked bibliographic metadata — **what a document IS** (title,
authors, venue, DOI), as distinct from what it SAYS (the schema-driven
extraction). Introduced by PR #15 (`feat/source-metadata`).

## Data model

Each article's `data/papers/<id>/article-metadata.json` manifest has two
layers. Extraction, reasoning, and review belong to the selected immutable run
(`specs/article-store/spec.md`):

| data layer | location or keys | writer |
|---|---|---|
| identity | `id`, `filename`, `original_filename`, `file_sha256`, `added_at`, `open_access` | assemble, registry sync (`open_access` only) |
| source metadata | the `source_metadata` block (below) | see "Writers" |
| domain extraction | active run's `agent-extraction.json` | the extraction agent |
| review overlay | active run's `review.json` | the verifier or review CLI |

The `source_metadata` block holds only the fields in `SOURCE_FIELDS`
(`title, authors, corporate_author, year, journal, doi, publisher, url,
abstract`) plus the `metadata_source` provenance tag. Bibliography lives ONLY
in the block — top-level manifest keys are identity, never bibliography. The
block is a fixed manifest convention, deliberately not a LinkML schema.

**The DOI has a single home: the block.** Nothing reads or writes a
top-level manifest `doi` — a block without a DOI means the article has no
DOI. (Alpha policy, `specs/README.md`: no legacy-format awareness in the
framework.)

## The lock model

`metadata_source` has exactly three values (`PROVENANCE_VALUES` in
`src/litschema/source_metadata.py`):

| value | meaning | header rendering | machine rights |
|---|---|---|---|
| `doi` | fetched from the DOI registries | LOCKED: "✓ from DOI" pill + unlock (🔓) affordance | refreshable by sync |
| `auto` | machine-seeded: filename prettify, agent title-page read | editable (✎ pencil), no badge | batch enrichment may overwrite |
| `manual` | a human touched it | editable (✎ pencil), no badge | machines may NOT overwrite without explicit consent |

- Editable is **derived**: `metadata_source != "doi"`. There is no separate
  editable flag in storage.
- `auto` and `manual` render identically. The distinction exists solely so
  machines know what is sacred; it is surfaced only on demand (`meta show`).
- **The author-of-the-values rule** picks the tag: the agent *inferred* the
  values from the document → `auto`; a human *authored* the values (header
  form, dictated fix, their own spreadsheet transcribed by an agent) →
  `manual`; a registry supplied them → `doi`. The question is never "who
  performed the write" but "who authored the values".

## User surface

**CLI** (`litschema meta`, a peer caller of the same library the webapp uses):

- `meta show <id>` — print the block as JSON.
- `meta set <id> --source auto|manual [field options] [--clear FIELD]...
  [--force]` — per-field merge; comma-split authors; int-coerced year; DOIs
  are validated and normalized (junk is rejected, so the sync affordance is
  never offered for an unsyncable value). An explicit empty-string value
  clears a field; `--clear` combined with a value for the same field is an
  error. `--source` is required and caller-asserted; `doi` cannot be
  asserted.
- `meta set <id> --source auto|manual --doi 10.x/y --sync` — record the DOI
  (guarded, tagged by `--source`) and immediately attempt the registry lock,
  in one command. `--sync` takes ONLY `--doi`: registry values replace the
  whole block, so fallback values belong in a separate `meta set` (passing
  any other field or `--clear` with `--sync` is an error). On registry
  failure the DOI stays recorded under the caller's tag — unlocked,
  retryable by per-article sync or the batch sweep — and the command says
  so. A guard refusal runs nothing: one verdict covers the write and the
  sync.
- `meta sync <id> [--doi 10.x/y] [--email ...]` — explicit per-article
  registry sync. Uses the block's DOI, or `--doi` when given (pass-through;
  on a registry miss NOTHING is recorded — no manifest change, no cache
  marker — and the error points at `meta set` as the escape hatch).
  Overwrites any state (REPLACE semantics: a `doi` block contains only
  registry-supplied values); locks to `doi`.
- `meta sync --all [--refresh] [--email ...]` — THE batch enrichment
  surface: enriches every assembled article with a DOI. Never touches
  `manual`; `--refresh` re-fetches past cached responses and `not_found`
  markers. Transient registry failures are counted (`errors`) and never
  cached, so affected articles stay retryable.

**HTTP API** (verify webapp; in-process library calls, never the CLI):

- `GET /api/bibliography/{id}` — the block + derived `editable`.
- `PUT /api/bibliography/{id}` — partial update of `SOURCE_FIELDS`; `null`
  or an empty string clears a field; DOIs validated and normalized; stamps
  `manual`. 400 unknown fields / bad year / bad DOI; 404 unknown article.
- `POST /api/bibliography/{id}/sync` — explicit sync; 404 unknown article,
  400 no DOI, 502 registry failure; on success returns the locked block.

**Verifier header:** title-first layout; ✓ pill only for `doi`; pencil on
editable records; 🔓 unlock on locked records (revealing the edit form —
saving stamps `manual`); "⟳ from DOI" sync button on editable records that
have a DOI, with a `confirm()` only when the sync would overwrite `manual`.

**Pipeline writers:** `assemble` seeds `{title}` from the PDF filename
(`auto`). The extraction agent backfills bibliography read off the document
(`auto` — see agent contract). Registry sync writes registry data (`doi`).

**Agent contract** (for bundled skills, e.g. extract-article) is
registry-first: if a DOI is printed on the document, run
`meta set <id> --source auto --doi <doi> --sync` — one guarded command that
records the DOI and attempts the lock; nothing is transcribed that the
registry would immediately replace. Transcribe bibliography off the title
page (`meta set <id> --source auto ...`) only when the document has no DOI
or the sync half failed (the recorded DOI stays retryable by the sweep).
The guard covers everything: on a refusal the agent writes nothing and never
syncs — per-article sync's overwrite-anything consent belongs to humans. The
bundled extract-article skill implements this contract.

A hand-edited block missing `metadata_source` reads as `manual` — the
protective default: machines will not touch it.

## Invariants

- **Never-clobber.** WHEN a write carries `--source auto` AND the block is
  `manual` or `doi`, THEN the write is refused (CLI exit 1) unless `--force`.
  WHEN a write carries `--source manual`, THEN it always succeeds — a human
  outranks every machine. (`can_overwrite` in `source_metadata.py`.)
- **Consent by scope.** WHEN batch enrichment (`meta sync --all`)
  encounters a `manual` block, THEN it skips the article. WHEN per-article
  sync is invoked, THEN it may overwrite any state — invoking it IS the
  consent.
- **`meta sync` is atomic.** WHEN a `meta sync` registry lookup fails or
  returns an unusable record, THEN the sync writes nothing at all — no
  manifest change, no cache marker — and any `--doi` passed to `meta sync` is
  NOT recorded. (The batch sweep caches a `not_found` marker for true 404s
  only. `meta set --doi ... --sync` differs by design: the guarded DOI write
  lands FIRST and survives a failed lookup — that persistence is the point of
  the flag; the sync half itself still writes nothing on failure.)
- **Auto-first enrichment.** Every article gets its best free metadata with
  zero user effort (filename seed → agent backfill → registry upgrade); human
  attention is spent only on corrections, and only those corrections are
  protected.
- **Atomic manifest writes.** All manifest writes go through
  `write_article_metadata` (same-directory tmp + rename); a crash never leaves
  a torn manifest.
- **Unresolvable DOIs stay retryable.** WHEN a DOI is not in the registry,
  THEN no provenance is written for it — a later run can still enrich the
  article (no self-lock).
- **The server never shells out.** Webapp endpoints call the Python library
  in-process.

## Migration (legacy corpora)

litschema reads only the block; pre-block manifests render as empty editable
`auto` records until migrated. Migration is the domain repo's job (alpha
policy): loop `litschema meta set <id> --source auto --doi <top-level value>`
(an agent or a small script), then run `litschema meta sync --all` to lock
everything the registry resolves. Legacy top-level keys are inert junk the
domain repo may prune at leisure.

## Test obligations

Implementation coverage must pin that manifest source-metadata writes do not
create extraction provenance, modify run artifacts, or change active selection;
source metadata remains unchanged when active runs switch; and verifier headers
read the same manifest block on every route.

## Code map

`src/litschema/source_metadata.py` (model + guard) ·
`src/litschema/ingest/openalex_harvest.py` (batch sweep, `sync_article`) ·
`src/litschema/ingest/article_assembly.py` (seeding) ·
`src/litschema/webapp/app.py` (endpoints) ·
the verifier's static native ES modules (header) ·
`src/litschema/cli.py` (`meta` sub-app). Tests: `test_source_metadata.py`,
`test_harvest_sources.py`, `test_meta_cli.py`, `test_webapp_app.py`,
`test_verifier_static.py`, `test_assemble.py`.

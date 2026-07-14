# Capability: article store

The on-disk source of truth: one directory per document under
`data/papers/<article-id>/`, plus the offline intake (`assemble`) and text
preparation (`prepare-text`) that populate it. Documented as-built from the
2026-07-07 audit; the store predates the specs convention.

## Layout

```
<article_store_dir>/<article-id>/     # default data/papers/
  article-metadata.json               # the manifest (identity + source metadata)
  <article-id>.pdf                    # canonical PDF, named after the id
  article.md                          # prepared full text
  agent-extraction.json               # what the document SAYS (specs/extraction)
  agent-reasoning.json                # evidence for the extraction (specs/extraction)
  review.json                         # human review state (specs/reviews)
```

`ArticleFiles` (`src/litschema/articles.py`) is the one place these paths are
defined; everything else asks it. `article_files(cfg, id)` is the single
chokepoint for id → path joins and raises `InvalidArticleIdError` for ids
that are empty, `.`, `..`, or contain `/` or `\` — ids arrive from CLI args
and URL segments, so the guard is load-bearing (the webapp maps the error to
HTTP 404).

## The manifest

`article-metadata.json` has two layers (the `source_metadata` block is
`specs/source-metadata/spec.md`; identity is this spec):

| identity key | writer |
|---|---|
| `id` | assemble (and defaulted on every manifest write) |
| `filename` | assemble — always `<id>.pdf` |
| `original_filename` | assemble — the inbox name the PDF arrived with |
| `file_sha256` | assemble — full-file SHA-256 |
| `added_at` | assemble — ISO-8601 UTC |
| `open_access` | registry sync only |
| `extraction` | `agent record-extraction` (specs/extraction) |

Writes go through `write_article_metadata`: shallow merge (None values
ignored — top-level keys cannot be deleted; nested dicts are replaced
wholesale), `id` defaulted from the directory name, atomic same-directory
tmp + `os.replace`. Known deviation: `prepare-text`'s fallback manifest
uses a raw write (improvements backlog).

## Intake: `litschema assemble`

Offline by construction — no DOI, no registry, no network (pinned:
`test_assemble_needs_no_doi_or_network`).

- **Id derivation**: slugify the PDF filename stem (`[^a-zA-Z0-9]+` → `-`,
  lowercased, trimmed; empty → `article`). Only `[a-z0-9-]` survives, so an
  id is a single path component by construction.
- **Collision resolution by content**: free slug → take it. Slug taken by
  the same `file_sha256` → `already_assembled` (idempotent re-drop). Slug
  taken by different content → suffix `-<sha256[:6]>`.
- **Per PDF**: move inbox PDF → `<store>/<id>/<id>.pdf`; write the minimal
  identity manifest (no bibliographic keys); seed the source-metadata block
  `{title: <prettified filename>, metadata_source: "auto"}`. Re-drops are
  archived to `<inbox>/.processed/`.
- **Stats**: `{inbox_pdfs, assembled, already_assembled, errors}`. A failing
  PDF is counted and left in the inbox; the run continues. Exit 0 even with
  per-PDF errors; exit 130 on interrupt ("progress has been saved" — rerun
  resumes); exit 2 without a project.

## Text preparation: `litschema prepare-text <id> | --all`

Converts PDFs to `article.md` with pymupdf4llm (CPU-only, offline).

- Positional id XOR `--all` (neither or both → exit 2). `--force` rebuilds
  existing markdown; otherwise existing output is `skipped` (idempotent).
  `--inbox-dir` / `--output-dir` override locations (`--output-dir` writes
  flat `<dir>/<id>.md` instead of per-article files).
- PDF resolution: the manifest `filename` under the article dir first, then
  the inbox. In `--all` mode, inbox PDFs with no manifest are also picked up.
- Stats: `{total, converted, skipped, empty, missing, errors}`. `empty`
  means the conversion produced under 100 characters (the file is still
  written; the extract-article skill treats it as unusable). The command
  currently exits 0 regardless of error counts (improvements backlog).

## Invariants

- **Single path chokepoint.** WHEN any surface resolves an article id to a
  path, THEN it goes through `article_files`, and traversal-shaped ids raise
  `InvalidArticleIdError` (webapp: 404). (`test_article_files.py`)
- **Ids are content-stable.** WHEN the same PDF bytes are dropped twice
  (same or different filename mapping to the same slug), THEN the second
  drop is `already_assembled` — never a duplicate article. WHEN different
  content collides on a slug, THEN the newcomer gets a content-hash suffix.
  (`test_assemble.py`)
- **Offline intake.** WHEN `assemble` or `prepare-text` runs, THEN no
  network access occurs. (`test_assemble.py`)
- **Atomic manifests.** WHEN a manifest is written via
  `write_article_metadata`, THEN a crash never leaves a torn file and no
  `*.tmp` survives. (`test_article_files.py`)
- **Failures don't abort batches.** WHEN one PDF fails intake or
  conversion, THEN it is counted and the loop continues; interrupted runs
  resume where they left off.

## Code map

`src/litschema/articles.py` (layout, guard, manifest IO) ·
`src/litschema/ingest/article_assembly.py` (assemble) ·
`src/litschema/ingest/pdf_to_markdown.py` (prepare-text) ·
`src/litschema/cli.py` (verbs). Tests: `test_article_files.py`,
`test_assemble.py`, `test_article_layout_consumers.py`.

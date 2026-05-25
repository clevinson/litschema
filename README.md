# litschema

Schema-driven extraction and verification for scientific literature.

`litschema` is a local-first toolkit for turning papers into structured,
schema-valid JSON with source-linked reasoning and human review. It is built
around [LinkML](https://linkml.io) schemas, agent-readable extraction skills, a verification webapp,
and a DuckDB/MCP exploration layer.

The source of truth is an article store on disk:

```text
data/papers/<article-id>/
  article-metadata.json
  <article-id>.pdf
  article.md
  agent-extraction.json
  agent-reasoning.json
  reviews.jsonl
```

## Local Install

From this repo:

```bash
uv sync
uv run litschema status
uv run pytest
```

Against a sibling data repo:

```bash
cd ../erw-lit-ie
uv run --project ../litschema litschema status
uv run --project ../litschema litschema validate
uv run --project ../litschema litschema verify
```

## Core Commands

```bash
litschema status                 # count metadata, markdown, extractions, reviews
litschema assemble               # DOI rows + papers-inbox PDFs -> article folders
litschema prepare-text <id>      # lower-level PDF -> markdown helper for one article
litschema prepare-text --all     # prepare markdown for every known article
litschema validate               # validate per-article extraction JSON
litschema verify --port 8000     # launch local review webapp
litschema mcp                    # expose DuckDB-backed exploration tools
litschema skills install         # install agent slash-command skills
```

Extraction is intentionally agent-mediated. Install the bundled skills globally
with `litschema skills install`, or into one project with
`litschema skills install --local`, then run `/litschema-assemble` or
`/extract-article <article-id>` inside an agent CLI from a configured project
directory. New projects use `data/sources/articles.csv` as the article registry;
users can fill only the `doi` column or drop PDFs into `papers-inbox/` and let
`litschema assemble` populate the remaining metadata and canonical PDFs. The
`/extract-article` skill prepares per-article markdown when needed before
running extraction.

## Project Layout

- `src/litschema/` — package code and CLI
- `skills/` — agent instructions for extraction and validation
- `tests/` — framework tests and small project fixtures
- `pyproject.toml` — package metadata and dependencies

The framework is still being separated from the ERW reference project. The
current public target is a small open-access agriculture/ERW demo that proves:
DOI or article input -> markdown -> extraction -> verification -> local query.

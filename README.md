# litschema

Schema-driven extraction and verification for scientific literature.

`litschema` is a local-first toolkit for turning papers into structured,
schema-valid JSON with source-linked reasoning and human review. It is built
around LinkML schemas, agent-readable extraction skills, a verification webapp,
and a DuckDB/MCP exploration layer.

The source of truth is an article store on disk:

```text
data/papers/<article-id>/
  article-metadata.json
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
litschema convert                # PDFs -> data/papers/<id>/article.md
litschema validate               # validate per-article extraction JSON
litschema verify                 # launch local review webapp
litschema mcp                    # expose DuckDB-backed exploration tools
litschema skills install         # install agent slash-command skills
```

Extraction is intentionally agent-mediated. Install the bundled skill, then run
`/extract-article <article-id-or-doi>` inside an agent CLI from a configured
project directory.

## Project Layout

- `src/litschema/` — package code and CLI
- `skills/` — agent instructions for extraction and validation
- `tests/` — framework tests and small project fixtures
- `pyproject.toml` — package metadata and dependencies

The framework is still being separated from the ERW reference project. The
current public target is a small open-access agriculture/ERW demo that proves:
DOI or article input -> markdown -> extraction -> verification -> local query.

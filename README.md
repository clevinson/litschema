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
litschema assemble               # move papers-inbox PDFs -> per-article folders
litschema prepare-text <id>      # lower-level PDF -> markdown helper for one article
litschema prepare-text --all     # prepare markdown for every known article
litschema validate               # validate per-article extraction JSON
litschema verify --port 8000     # launch local review webapp
litschema mcp                    # expose DuckDB-backed exploration tools
litschema skills install         # install agent slash-command skills
```

Onboarding is local-PDF-first: drop PDFs into `papers-inbox/` and run
`litschema assemble`. Assembly is offline — it derives a stable `article_id`
from each PDF's filename, moves the PDF into `data/papers/{article_id}/`, and
writes a minimal `article-metadata.json` manifest. No DOI, bibliography file, or
network access is required to reach extraction.

Extraction is intentionally agent-mediated. Install the bundled skills globally
with `litschema skills install`, or into one project with
`litschema skills install --local`, then run `/litschema-assemble` or
`/extract-article <article-id>` inside an agent CLI from a configured project
directory. The `/extract-article` skill prepares per-article markdown when
needed before running extraction, and bibliographic fields are filled into the
manifest by extraction.

Optional bibliographic enrichment lives in a separate `litschema harvest`
command, which queries OpenAlex/CrossRef for every assembled article whose
manifest carries a DOI (captured during extraction, or edited in the verify
header). There is no registry file to author, and articles with human-edited
metadata are never overwritten. It is not part of the core PDF-first flow.

## Project Layout

- `src/litschema/` — package code and CLI
- `skills/` — agent instructions for extraction and validation
- `tests/` — framework tests and small project fixtures
- `pyproject.toml` — package metadata and dependencies

The framework is still being separated from the ERW reference project. The
current public target is a small open-access agriculture/ERW demo that proves:
PDFs -> markdown -> extraction -> verification -> local query.

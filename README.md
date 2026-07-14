# litschema

Schema-driven extraction and verification for document collections.

`litschema` is a local-first toolkit for turning a folder of PDFs into
structured, schema-valid JSON with line-cited reasoning, human review, and a
queryable database. It is built around [LinkML](https://linkml.io) schemas,
agent-executed extraction skills, a review webapp, and a DuckDB/MCP
exploration layer. Everything runs on your machine; the only network calls
are optional DOI-registry lookups and the verifier's ORCID name resolution.

## The flow

```text
litschema init my-review        # scaffold a project (no questions asked)
  → drop PDFs in papers-inbox/
  → /litschema-onboard          # agent: schema drafting, intake, pilot, batch
  → litschema verify            # you: review what was extracted
  → litschema export            # the reviewed data, ready for analysis
```

The source of truth is an article store on disk — one directory per
document, everything in git-friendly JSON:

```text
data/papers/<article-id>/
  article-metadata.json    # identity + bibliographic metadata (provenance-locked)
  <article-id>.pdf
  article.md               # prepared full text
  agent-extraction.json    # what the document SAYS (schema-valid)
  agent-reasoning.json     # why — per-field evidence with line citations
  review.json              # human verdicts: verify / flag / override
```

## Install

```bash
uv sync
uv run litschema status
uv run pytest
```

Against a sibling data repo:

```bash
cd ../my-review
uv run --project ../litschema litschema status
```

## Commands

```bash
litschema init <dir>             # scaffold a project; installs agent skills locally
litschema status                 # counts: inbox, manifests, text, extractions, reviews
litschema doctor                 # diagnose environment + skill installation
litschema assemble               # papers-inbox PDFs -> per-article folders (offline)
litschema prepare-text <id>|--all  # PDF -> article.md (offline)
litschema meta show <id>         # print source metadata (what the document IS)
litschema meta set <id> ...      # write it (--source auto|manual; --sync locks from DOI)
litschema meta sync <id>|--all   # fetch + lock metadata from the DOI registry
litschema validate [target]      # validate extractions against the schema (closed-world)
litschema verify [--port 8000]   # local review webapp (loopback only)
litschema export [-f jsonl|csv]  # the reviewed data as flat files (pandas/R/jq-ready)
litschema mcp                    # build the DuckDB store and serve it over MCP (experimental)
litschema skills install         # install the agent skills globally
litschema agent ...              # deterministic steps the extraction skill calls
```

## How it works

**Intake is offline and content-addressed.** `assemble` derives a stable
article id from each PDF's filename (content-hash suffix on collisions),
moves the PDF into the store, and writes a minimal manifest. No DOI,
bibliography file, or network access is needed to reach extraction — and
re-dropping the same PDF is a no-op.

**Extraction is agent-executed, framework-checked.** `init` installs the
bundled skills into `.claude/skills/`; run `/litschema-onboard` in your
agent CLI for the guided first run (it interviews you to draft the LinkML
schema, runs intake, pilots one article, then batches the rest), or
`/extract-article <id>` directly. The agent extracts only from the prepared
text, writes the extraction and a line-cited reasoning file, and loops until
both validate — closed-world, so nothing the schema doesn't define gets in.

**Bibliographic metadata is provenance-locked.** When a document shows a
DOI, extraction records it and locks the metadata from the registry in one
guarded command (`meta set --source auto --doi ... --sync`); a post-batch
`meta sync --all` sweep retries transient failures. Human edits (`manual`)
are never overwritten by machines — per-article sync (or the verifier's
"⟳ from DOI" button) is the explicit-consent exception. Documents without a
DOI flow through the whole pipeline unchanged.

**Review is field-by-field and git-native.** `litschema verify` shows each
extracted value beside its cited source lines and confidence; you verify,
flag, or override with typed editors. One review per field lives in
`review.json` — diffs of that file are the audit log, and reviews know which
extraction they were written against (re-extraction raises a staleness
warning until stale fields are re-reviewed).

**Use the reviewed truth.** `litschema export` writes the review-applied
extractions as JSONL or CSV for pandas, R, or jq; `litschema mcp`
(experimental) derives a DuckDB database from the schema and serves it
read-only over MCP: `run_sql`, `describe_schema`, `get_linkml_schema`. Both
surfaces produce the same records — overrides applied, error markers
skipped.

## Project layout

- `src/litschema/` — package code and CLI
- `specs/` — capability specs (current truth) and decision logs — start at
  `specs/README.md`
- `skills/` — the agent-facing extraction and onboarding instructions
- `tests/` — framework tests and small project fixtures

## Status

Pre-release alpha. Formats change without migration paths
(`specs/README.md` § Alpha status); the improvements backlog lives in
`specs/improvements.md`. The MVP target: PDFs → text → extraction →
review → local SQL, demonstrated end to end on a small open-access demo
project.

# litschema

**Turn a folder of PDFs into a dataset you can defend.**

Extraction gets you structured data. `litschema` gets you structured data where
every value carries the lines it came from, a record of which model produced
it, and a human's verdict on whether it's right — because in a systematic
review or meta-analysis, "the model said so" is not a citation.

Everything runs on your machine. The only network calls are optional DOI
lookups and the verifier's ORCID name resolution.

## What you get

For each document, three artifacts that stay in step:

```text
data/papers/<article-id>/
  article-metadata.json                  identity + bibliographic block
  <article-id>.pdf
  article.md                             prepared full text
  active-run.json                        which extraction is current
  extraction-runs/<run-id>/
    agent-extraction.json                what the document SAYS (schema-valid)
    agent-reasoning.json                 why — per-field evidence, line-cited
    run.json                             inputs hashed, model recorded
    review.json                          your verdicts on this run
```

Plain JSON on disk, one directory per document, diffable in git. A run is
immutable once published: its extraction, reasoning, and `run.json` never
change, so a review written against it stays meaningful forever. Re-extracting
creates a new run rather than overwriting the old one.

## Alpha Software

**litschema is early software. Extracted data may need regenerating
when updating litschema versions.**

Each release will document breaking changes in the [CHANGELOG.md](./CHANGELOG.md).

## Specs

The [specs](specs/README.md) describe what is currently implemented; anything
deferred says so and names where it is tracked.

## The flow

```bash
litschema init my-project       # scaffold a project
                                # drop PDFs into papers-inbox/
/litschema-onboard              # agent: drafts your schema, extracts, pilots
litschema verify                # you: check what was extracted
litschema export                # the reviewed data, ready for analysis
```

`/litschema-onboard` is a bundled agent skill, installed into `.claude/skills/`
by `init`. It interviews you to draft a LinkML schema from your own papers,
runs intake, extracts one article as a pilot so you can course-correct, then
batches the rest.

## Install

No PyPI release yet — clone and run from the checkout:

```bash
git clone https://github.com/clevinson/litschema && cd litschema
uv sync
uv run litschema --help
```

Against a project in a sibling directory:

```bash
cd ../my-review
uv run --project ../litschema litschema status
```

Agent skills resolve the CLI the way you would: a project dev override, then
`uv run litschema`, then bare `litschema`. To pin them to a checkout, write the
command to `.litschema/dev-cli`. Because that file executes whatever it
contains, an agent will ask before using it, and records your approval in your
own config rather than in the project — a repository cannot approve itself.

## Commands

```bash
litschema init <dir>               scaffold a project; installs agent skills locally
litschema doctor                   diagnose config, schema, and skill installation
litschema status                   counts: inbox, articles, runs, reviews
litschema assemble                 papers-inbox PDFs -> per-article folders (offline)
litschema prepare-text <id>|--all  PDF -> article.md (offline)
litschema meta show|set|sync <id>  bibliographic metadata, provenance-tagged
litschema validate [target]        validate extractions against the schema
litschema runs list|activate       inspect published runs; choose the active one
litschema verify [--port 8000]     local review webapp (loopback only)
litschema export [-f jsonl|csv]    reviewed data as flat files (pandas/R/jq-ready)
litschema mcp                      DuckDB store served over MCP (experimental)
litschema skills install           install the agent skills globally
litschema agent ...                deterministic steps the extraction skill calls
```

There is no `litschema extract`: extraction is judgment work, so it runs as an
agent skill (`/extract-article <id>`) with the framework checking the output.
The verb exists only to say so.

## How it works

**Intake is offline and content-addressed.** `assemble` derives a stable
article id from each PDF's filename, moves the PDF into the store, and writes a
minimal manifest. No DOI, bibliography file, or network access is needed to
reach extraction, and re-dropping the same PDF is a no-op.

**Extraction is agent-executed, framework-checked.** The agent reads only the
prepared text, writes an extraction plus a line-cited reasoning file, and loops
until both validate. Validation is closed-world — nothing the schema doesn't
define gets in — and citations must resolve to real lines in the prepared text,
so a reference to a line that doesn't exist fails rather than shipping.

**Runs are immutable and provenance-bearing.** Publishing records the SHA-256
of every input — prepared text, domain context, and the skill that conducted
the extraction — alongside the schema hash and what produced it. Reproduction
data is computed by the publisher; attribution is recorded as asserted, since
an agent cannot verify its own model. Nothing is overwritten.

**Bibliographic metadata is provenance-locked.** Values fetched from a DOI
registry are marked and locked; machine-written values may be upgraded but
human edits are never overwritten without explicit consent. Documents with no
DOI flow through unchanged.

**Review is field-by-field and git-native.** `litschema verify` shows every
extracted value beside its cited source lines, with the model and effort that
produced it. You verify a value, correct it, or remove it — one entry per
field, stored inside the run it reviews. Diffs of `review.json` are the audit
log. Because a run's payload can never change, a review never goes stale.

**Use the reviewed truth.** `export` writes the review-applied extractions as
JSONL or CSV for pandas, R, or jq. `mcp` (experimental) derives a DuckDB
database from your schema and serves it read-only. Both apply overrides and
skip error markers, so they agree.

## Project layout

- `src/litschema/` — package code and CLI
- `specs/` — capability specs and decision logs; start at `specs/README.md`
- `skills/` — the agent-facing extraction and onboarding instructions
- `tests/` — framework tests and small project fixtures

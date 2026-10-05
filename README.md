# litschema

[![PyPI](https://img.shields.io/pypi/v/litschema)](https://pypi.org/project/litschema/)
[![Docs](https://readthedocs.org/projects/litschema/badge/?version=latest)](https://litschema.readthedocs.io/)

**Turn a folder of PDFs into a dataset you can defend.**

![Reviewing a paper in litschema: cited lines highlighted in the text, extracted values with the grader's confidence](https://raw.githubusercontent.com/clevinson/litschema/main/docs/assets/review.gif)

Extraction gets you structured data. `litschema` gets you structured data where
every value carries the lines it came from, how it was derived, a record of
which model produced it, an independent grader's estimate that it's correct,
and a human's verdict. In a systematic review or meta-analysis, "the model said
so" is not a citation.

You define the schema in [LinkML](https://linkml.io). Runs are immutable and
record the hash of every input. Bibliographic metadata fetched by DOI is
marked with its source and locked. Documentation:
[litschema.readthedocs.io](https://litschema.readthedocs.io/).

Everything runs on your machine. Models run through your own Claude Code
install. The only other network calls are optional DOI lookups and the
verifier's ORCID name resolution.

## What you get

For each document, three artifacts that stay in step:

```text
data/papers/<article-id>/
  article-metadata.json                  identity + bibliographic block
  <article-id>.pdf
  article.md                             prepared full text
  prepared-text.json                     how the PDF was converted, hashed
  figures/                               images from the PDF
  active-run.json                        which extraction is current
  extraction-runs/<run-id>/
    agent-extraction.json                what the document SAYS (schema-valid)
    agent-reasoning.json                 why — per-field evidence, line-cited
    run.json                             inputs hashed, model recorded
    grades/<grade-id>.json               grader's confidence per value
    review.json                          your verdicts on this run
```

Plain JSON on disk, one directory per document, diffable in git. The PDF,
`article.md`, and extracted figures are gitignored by default, since most
papers can't be redistributed; `prepare-text` regenerates the text from the
PDF. A run is
immutable once published: its extraction, reasoning, and `run.json` never
change, so a review written against it stays meaningful forever. Re-extracting
creates a new run rather than overwriting the old one.

![The overview: status, flags, and review progress per paper](https://raw.githubusercontent.com/clevinson/litschema/main/docs/assets/overview.png)

## Alpha Software

**litschema is early software. Extracted data may need regenerating
when updating litschema versions.**

One limit qualifies the line-level citations promised above: PDF conversion
collapses some tables onto a single line, so a citation into a table can name
the table but not the row. This matters most for measurement-heavy schemas.

Each release documents its breaking changes and known limits in the
[CHANGELOG.md](https://github.com/clevinson/litschema/blob/main/CHANGELOG.md).

## Specs

The [specs](https://github.com/clevinson/litschema/blob/main/specs/README.md) describe what is currently implemented; anything
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

```bash
uv tool install litschema      # or: pip install litschema
litschema --version
```

`init` pins each project to the version that created it (`litschema_version`
in `litschema.yaml`), and commands refuse to run under any other. To move a
project to a new release, install it and edit the pin.

To try an unreleased tag or work on litschema itself:

```bash
uv tool install "litschema @ git+https://github.com/clevinson/litschema@v0.1.1" --force
uv tool install --editable path/to/litschema --force   # edits take effect immediately
```

## Commands

```bash
litschema init <dir>               scaffold a project; installs agent skills locally
litschema doctor                   diagnose config, schema, and skill installation
litschema status                   counts: inbox, articles, runs, reviews
litschema assemble                 papers-inbox PDFs -> per-article folders (offline)
litschema prepare-text <id>|--all  PDF -> article.md (offline)
litschema meta show|set|sync <id>  bibliographic metadata, provenance-tagged
litschema validate [target]        validate extractions against the schema
litschema grade <id>|--all         score each value against its cited lines
litschema runs list|activate       inspect published runs; choose the active one
litschema verify [--port 8000]     local review webapp (loopback only)
litschema export [-f jsonl|csv]    reviewed data as flat files (pandas/R/jq-ready)
litschema mcp                      DuckDB store served over MCP (experimental)
litschema skills install           install the agent skills globally
litschema agent ...                deterministic steps the extraction skill calls
```

Extraction runs as an agent skill (`/extract-article <id>`), with the
framework checking the output. A headless `litschema extract` is planned.

## How it works

**Intake is offline and content-addressed.** `assemble` derives a stable
article id from each PDF's filename, moves the PDF into the store, and writes a
minimal manifest. No DOI, bibliography file, or network access is needed to
reach extraction, and re-dropping the same PDF is a no-op.

**Extraction is agent-executed, framework-checked.** The agent reads only the
prepared text and its figures. It writes an extraction plus a reasoning file
that gives, for each value, the cited lines, a basis (stated, converted,
normalized, calculated, inferred, or assumed), and a note on how it got the
value. It loops until both validate. Validation is closed-world — nothing the schema doesn't
define gets in — and citations must resolve to real lines in the prepared text,
so a reference to a line that doesn't exist fails rather than shipping.

**Grading is independent.** `litschema grade` gives each value, the
extractor's basis and note, and the cited lines to a separate model, which
returns the probability that the value is correct and a one-line issue when
it's below 0.9. The app sorts flagged values to the top. In an 18-paper pilot,
85% of stated values scored high, while 29% of inferred values scored low.

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

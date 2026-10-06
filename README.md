# litschema

[![PyPI](https://img.shields.io/pypi/v/litschema)](https://pypi.org/project/litschema/)
[![Docs](https://readthedocs.org/projects/litschema/badge/?version=latest)](https://litschema.readthedocs.io/)

**Turn a folder of PDFs into a dataset you can defend.**

![Reviewing a paper in litschema: cited lines highlighted in the text, extracted values with the grader's confidence](https://raw.githubusercontent.com/clevinson/litschema/main/docs/assets/review.gif)

litschema extracts structured data from scientific papers into a
[LinkML](https://linkml.io) schema you write. Every value comes with:

- the lines of the paper it came from;
- how it was derived (stated, converted, normalized, calculated, inferred, or
  assumed);
- the model and inputs that produced it, hashed;
- a second model's probability that it's correct;
- your verdict, once you've reviewed it.

It runs on your machine. Models run through your own Claude Code install; the
only other network calls are optional DOI lookups and ORCID name lookups in
the review app. Docs: [litschema.readthedocs.io](https://litschema.readthedocs.io/).

## What you get

One folder per paper:

```text
data/papers/<article-id>/
  <article-id>.pdf
  article-metadata.json                  identity and bibliographic metadata
  article.md                             prepared text
  prepared-text.json                     how the PDF was converted, hashed
  figures/                               images from the PDF
  active-run.json                        which run is current
  extraction-runs/<run-id>/
    agent-extraction.json                the values, valid against your schema
    agent-reasoning.json                 per value: cited lines, basis, note
    run.json                             input hashes and the model
    grades/<grade-id>.json               the grader's confidence per value
    review.json                          your verdicts
```

It's plain JSON, so you can diff it in git. The default `.gitignore` leaves
out the PDF, `article.md`, and figures, since most papers can't be
redistributed; `prepare-text` rebuilds them from the PDF. A published run
never changes, so a review of it stays valid. Re-extracting adds a new run
beside the old one.

![The overview: status, flags, and review progress per paper](https://raw.githubusercontent.com/clevinson/litschema/main/docs/assets/overview.png)

## Alpha software

**litschema is early software. You may need to regenerate extracted data when
you update it.**

Tables that a PDF stores as images arrive as figures, so a value from one cites
the figure rather than a row.

The [changelog](https://github.com/clevinson/litschema/blob/main/CHANGELOG.md)
lists each release's breaking changes and known limits.

## Specs

The [specs](https://github.com/clevinson/litschema/blob/main/specs/README.md)
describe what's implemented now. Anything deferred says so and links to where
it's tracked.

## The flow

```bash
litschema init my-project       # scaffold a project
                                # copy PDFs into papers-inbox/
/litschema-onboard              # agent: drafts your schema, pilots, extracts
litschema grade --all           # a second model scores every value
litschema verify                # you: review what was extracted
litschema export                # values with your corrections
```

`init` installs the `/litschema-onboard` skill into `.claude/skills/`. It
drafts a LinkML schema with you from your own papers, converts the PDFs,
extracts one paper as a pilot so you can adjust the schema, then extracts the
rest.

## Install

```bash
uv tool install litschema      # or: pip install litschema
litschema --version
```

`init` pins each project to the installed version (`litschema_version` in
`litschema.yaml`), and commands refuse to run under any other. To move a
project to another version, install it, edit the pin, and run
`litschema skills install --local --force`.

To try an unreleased commit or work on litschema itself:

```bash
uv tool install "litschema @ git+https://github.com/clevinson/litschema@main" --force
uv tool install --editable path/to/litschema --force   # edits apply immediately
```

## Commands

```bash
litschema init <dir>               scaffold a project; installs agent skills locally
litschema doctor                   check config, schema, and skill installation
litschema status                   counts: inbox, articles, runs, reviews
litschema assemble                 papers-inbox PDFs -> per-article folders (offline)
litschema prepare-text <id>|--all  PDF -> article.md and figures (offline)
litschema meta show|set|sync <id>  bibliographic metadata, provenance-tagged
litschema validate [target]        validate extractions against the schema
litschema grade <id>|--all         score each value against its cited lines
litschema runs list|activate       list published runs; choose the active one
litschema verify [--port 8000]     local review app (loopback only)
litschema export [-f jsonl|csv]    values with corrections, plus an audit file
litschema mcp                      DuckDB store served over MCP (experimental)
litschema skills install           install the agent skills
litschema agent ...                steps the extraction skill calls
```

Extraction runs as an agent skill (`/extract-article <id>`), and litschema
checks what the agent writes. A headless `litschema extract` is planned.

## How it works

**Intake is offline.** `assemble` derives an article id from each PDF's
filename, moves the PDF into the store, and writes a minimal manifest. You
need no DOI, bibliography file, or network access to reach extraction, and
dropping the same PDF twice does nothing.

**The agent extracts; litschema checks.** The agent reads only the prepared
text and its figures. It writes the values and a reasoning file that gives, for
each value, the cited lines, a basis, and a note on how it got the value, and
it loops until both validate. Validation is closed-world: litschema rejects any
field the schema doesn't define and any citation to a line that doesn't exist.

**A second model grades.** `litschema grade` gives a separate model each value,
the extractor's basis and note, and the cited lines. It returns the
probability that the value is correct, with a one-line issue below 0.9. The
review app puts flagged values first. In an 18-paper pilot, 85% of stated
values scored 0.9 or higher; 29% of inferred values scored below 0.6.

**Runs record their inputs.** Publishing a run records the SHA-256 of the
prepared text, the domain context, the extraction skill, and the schema, plus
the litschema version and the conversion settings. The model name is recorded
as the agent reports it.

**DOI metadata is locked.** Bibliographic fields fetched from a DOI registry
are marked with their source and locked. Machine-written values can be
upgraded, and litschema never overwrites your edits without asking. Papers
without a DOI work the same way.

**Review is per field and lives in git.** `litschema verify` shows each value
beside its cited lines. You verify, correct, or remove it, and each action
writes one entry to the run's `review.json`. The diff of that file is the
audit log.

**Export with provenance.** `export` writes every value with your
corrections applied, as JSONL or CSV, including values nobody has reviewed yet.
`--audit-output` writes one record per paper beside it: the run, model, DOI,
schema hash, how many fields you reviewed, the grader's flags, and your review
entries. `mcp` (experimental) loads them into a
DuckDB database built from your schema and serves it read-only. Both skip
runs that failed extraction, so they agree.

## Project layout

- `src/litschema/`: package code and CLI
- `specs/`: capability specs and decision logs; start at `specs/README.md`
- `skills/`: the extraction and onboarding instructions for agents
- `tests/`: framework tests and small project fixtures

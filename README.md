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

It runs on your machine, through the coding agents you already have (Claude
Code or Codex), paid by your own subscription or API key.

> **Alpha.** File formats can change before 1.0. The
> [changelog](https://github.com/clevinson/litschema/blob/main/CHANGELOG.md)
> lists each release's breaking changes.

## Quick start

```bash
uv tool install litschema
litschema init my-review && cd my-review
# copy PDFs into papers-inbox/, open the folder in your coding agent,
# and run the litschema skill
litschema grade --all        # a second model scores every value
litschema verify             # review in your browser
litschema export -f csv -o data.csv --audit-output audit.jsonl
```

The `litschema` skill designs a schema with you from your own papers, extracts
one paper as a pilot so you can adjust it, then extracts the rest. Run it again
any time to add papers or pick up where you left off. The
[quickstart](https://litschema.readthedocs.io/en/latest/quickstart/) walks
through each step.

## What you get

One folder per paper, in plain JSON you can diff in git:

```text
data/papers/<article-id>/
  article-metadata.json        identity and bibliographic metadata
  prepared-text.json           how the PDF was converted, hashed
  extraction-runs/<run-id>/
    agent-extraction.json      the values, valid against your schema
    agent-reasoning.json       per value: cited lines, basis, note
    run.json                   input hashes and the model
    grades/<grade-id>.json     the grader's confidence per value
    review.json                your verdicts
```

Published runs never change, so a review stays valid; re-extracting adds a new
run beside the old one. PDFs and the text converted from them stay out of git.

![The overview: status, flags, and review progress per paper](https://raw.githubusercontent.com/clevinson/litschema/main/docs/assets/overview.png)

## How it works

- **The agent extracts; litschema checks.** Validation rejects fields your
  schema doesn't define and citations to lines that don't exist.
- **A second model grades** each value against its cited lines, and the review
  app shows flagged values first. You can pin the grader to a specific harness
  and model. In an 18-paper pilot, 85% of stated values scored 0.9 or higher
  and 29% of inferred values scored below 0.6.
- **You review in a local app.** Each verify, correction, or removal is one
  entry in `review.json`, so the git diff is the audit log.
- **Export** writes the values with your corrections, plus one provenance
  record per paper: DOI, run, model, review status, and grade flags.

## Documentation

[litschema.readthedocs.io](https://litschema.readthedocs.io/) has the
[quickstart](https://litschema.readthedocs.io/en/latest/quickstart/),
[concepts](https://litschema.readthedocs.io/en/latest/concepts/),
[reviewing](https://litschema.readthedocs.io/en/latest/reviewing/),
[file formats](https://litschema.readthedocs.io/en/latest/file-formats/), and
the [CLI reference](https://litschema.readthedocs.io/en/latest/cli/). The
[specs](https://github.com/clevinson/litschema/blob/main/specs/README.md) are
the contract for what's implemented.

## Development

```bash
uv tool install --editable path/to/litschema --force
```

Each project pins the litschema version it runs with (`litschema_version` in
`litschema.yaml`). To move it, install the version you want, edit the pin, and
run `litschema skills install --project --force`.

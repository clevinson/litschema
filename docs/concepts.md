# Concepts

## One folder per paper

```text
data/papers/<article-id>/
  <article-id>.pdf
  article-metadata.json        title, authors, DOI; provenance-tagged
  article.md                   prepared text, one line per paragraph
  prepared-text.json           how the PDF was converted, with hashes
  figures/                     images pulled from the PDF
  active-run.json              which run is current
  extraction-runs/<run-id>/
    agent-extraction.json      the values (valid against your schema)
    agent-reasoning.json       per value: cited lines, basis, note
    run.json                   input hashes, model, litschema version
    grades/<grade-id>.json     the grader's confidence per value
    review.json                your verdicts
```

It's all plain JSON, so you can diff it in git. You can commit everything
except the PDFs, text, and figures, which the default `.gitignore` excludes.
See [What goes in git](git.md).

## Runs never change

Re-extracting a paper creates a new run beside the old one; nothing gets
overwritten. `run.json` records the SHA-256 of the prepared text, the domain
context, the prompt (skill), and the schema, plus the model, effort, and
litschema version that produced the run. Publishing refuses if `article.md` no
longer matches the conversion record. A review belongs to one run, so it can't
go stale.

## How each value was extracted

For each value, the extractor writes the lines it cites and a `basis`:

| basis | meaning |
|---|---|
| `stated` | the text says it |
| `converted` | a unit or format conversion (6°52′ N to 6.87) |
| `normalized` | mapped onto a schema term ("sandy loam" to an enum) |
| `calculated` | computed from stated numbers |
| `inferred` | follows from the text, but the text doesn't say it |
| `assumed` | a default the paper doesn't support |

Any basis other than `stated` needs a one-line `note` saying how the extractor
got the value.

## Grading

`litschema grade` gives each value and its evidence to a separate model, which
returns the probability that the value is correct. That's a score for the
value; the grader doesn't rate its own judgment. The app turns the probability
into bands:

| band | confidence |
|---|---|
| high | ≥ 0.9 |
| check | 0.6 to 0.9 |
| low | < 0.6 |
| can't verify | no score |

Values below 0.9 carry a one-line `issue`. In an 18-paper pilot, 85% of
`stated` values scored high and none scored low, while 29% of `inferred` values
scored low. Grades sit beside the run and never change the extraction.

## Metadata

Bibliographic fields fetched from a DOI registry are marked with their source
and locked. Machine-written values can be upgraded; human edits are never
overwritten without consent. Papers without a DOI work the same way.

## Schemas

You define the extraction schema in LinkML YAML, and it marks its root class
with `tree_root: true`. Validation is closed-world: litschema rejects any field
the schema doesn't define. `litschema mcp` (experimental) builds a DuckDB
database from the schema and the reviewed data and serves it read-only over
MCP.

## Known limits

Tables that a PDF stores as images arrive as figures, so a value from one cites
the figure rather than a row. The
[changelog](https://github.com/clevinson/litschema/blob/main/CHANGELOG.md)
lists the rest for each release.

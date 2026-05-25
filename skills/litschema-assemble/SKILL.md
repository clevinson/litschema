---
name: litschema-assemble
description: "Use when preparing a litschema project's article inputs before schema building or extraction, including DOI rows in articles.csv or PDFs in papers-inbox."
context: fork
allowed-tools: Bash, Read
---

# litschema Assemble

Prepare article inputs for a litschema project using deterministic CLI commands.

## Setup Gate

Verify you are in a litschema project by checking for `litschema.yaml` in the
current directory or a parent directory. If it is missing, stop and ask the user
to point you to the project folder or run `litschema init <project-directory>`.

Select the command runner:

1. Try `uv run litschema --help`.
2. If that exits 0, use `uv run litschema`.
3. Otherwise try `litschema --help`.
4. If that exits 0, use `litschema`.
5. If neither works, stop and tell the user litschema is unavailable in this shell.

Treat the selected command as `LITSCHEMA` below, but substitute the actual
command text. Do not run `$LITSCHEMA` literally.

## Assembly

Run:

```bash
LITSCHEMA assemble
```

This command owns the deterministic intake work:

- reads and updates `data/sources/articles.csv`
- scans `papers-inbox/*.pdf`
- detects DOI strings from PDFs without running full markdown conversion
- harvests bibliographic metadata for valid DOI rows
- writes metadata-only article folders for rows without a DOI when `article_id`
  and enough curated metadata are present in `articles.csv`
- creates canonical article folders under `data/papers/{article_id}/`
- writes `article-metadata.json` and canonical PDFs when possible

Extraction uses `data/papers/{article_id}/article.md`; `/extract-article`
prepares that markdown for the requested article when needed. Do not run
project-wide text preparation from this skill.

Do not hand-edit `articles.csv` for fields that `litschema assemble` can fill.
DOI-less rows are valid for theses, reports, blog posts, and grey literature.
For those rows, ensure `articles.csv` has at least `article_id`, `title`, `year`,
and `publisher` when known. Only ask the user for help when the command reports
PDFs without DOI strings, rows without `article_id`, or rows that still lack
enough metadata for schema building.

## Finish

Report:

- how many inbox PDFs were found
- how many PDFs were assembled
- how many DOI rows were harvested
- any PDFs still missing DOI values
- any DOI-less rows that need manual `article_id` or metadata fields
- whether the article registry is ready for `/extract-article`

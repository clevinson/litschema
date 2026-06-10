---
name: litschema-assemble
description: "Use when preparing a litschema project's article inputs before extraction, by moving PDFs from papers-inbox into per-article folders under data/papers."
context: fork
allowed-tools: Bash, Read
---

# litschema Assemble

Move dropped PDFs into per-article folders using a single deterministic CLI
command. Assembly is offline: it does not look up DOIs or fetch bibliographic
metadata.

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

- scans `papers-inbox/*.pdf`
- derives a stable `article_id` from each PDF filename (sanitized to a slug;
  colliding names get a short content-hash suffix)
- creates `data/papers/{article_id}/` and moves the PDF to
  `data/papers/{article_id}/{article_id}.pdf`
- writes a minimal `article-metadata.json` manifest (`id`, `filename`,
  `original_filename`, `file_sha256`, `added_at`)
- leaves the inbox empty after a successful run

The `article_id` comes from the filename, so the user controls it by naming the
PDF before dropping it in (e.g. `Smith 2024 enhanced weathering.pdf` →
`smith-2024-enhanced-weathering`). Bibliographic fields (title, authors, year)
are filled in later by extraction; they are not part of assembly.

Extraction uses `data/papers/{article_id}/article.md`; `/extract-article`
prepares that markdown for the requested article when needed. Do not run
project-wide text preparation from this skill.

## Finish

Report:

- how many inbox PDFs were found
- how many were assembled, and their new `article_id`s
- how many were already assembled (duplicate re-drops)
- any PDFs that failed and remain in the inbox
- that the project is ready for `/extract-article <article-id>`

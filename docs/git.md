# What goes in git

A litschema project is meant to live in a git repository. `init` writes a
`.gitignore` that keeps the papers out and everything you made in.

**Committed:**

- `litschema.yaml`, your schema, `domain_context.md`, and `.claude/skills/`
- per paper: `article-metadata.json`, `prepared-text.json`, `active-run.json`
- per run: the extraction, reasoning, `run.json`, grades, and `review.json`

**Kept local:**

- PDFs, in `papers-inbox/` and `data/papers/`
- `article.md` and `figures/`, which `litschema prepare-text` rebuilds from the
  PDF
- `.litschema/`, the cache that `mcp` and the agent's schema files use

Most papers can't be redistributed, so the repository stays shareable. A
collaborator adds their own copies of the PDFs and runs
`litschema prepare-text --all`. `prepared-text.json` records the hashes of the
PDF and the text, so you can both check you're reading the same thing.

Before you make the repository public, keep in mind that extracted values,
the extractor's notes, and the grader's issues can quote short passages from
the papers.

# Quickstart

Litschema requires Python 3.13+, [uv](https://docs.astral.sh/uv/), and a
coding agent set up with your subscription or an API key.

## Supported coding agents

| Coding agent | Schema design and extraction | Grading |
| --- | --- | --- |
| [Claude Code](https://claude.com/claude-code) | yes | yes |
| [Codex](https://developers.openai.com/codex) | yes | yes |

Schema design and extraction run as skills in Claude Code or Codex, in the
terminal or the desktop app. Grading runs the `claude` or `codex` command, so
it must be on your PATH even if you work in a desktop app. You can grade with
a different coding agent than the one that extracted.

## Install

```bash
uv tool install litschema
litschema --version
```

## Create a project

```bash
litschema init my-review
cd my-review
```

`init` writes a starter schema and installs the skills for each coding agent
it finds (Claude Code, Codex). To choose the agents yourself, pass `--agent`;
see [coding agents](cli.md#coding-agents).

Copy your PDFs into `papers-inbox/`.

## Draft a schema and extract

Open the project in Claude Code or Codex and run the `litschema` skill:
`/litschema` in Claude Code, `$litschema` in Codex. Asking it to "set up
litschema" works too.

It reads a few of your papers, designs a LinkML schema with you, prepares the
text of each PDF, extracts one paper as a pilot so you can adjust the schema,
and then extracts the rest. Run it again to add papers; it picks up where the
project left off. To extract one paper by hand, ask for the
`extract-article` skill with the article id.

## Grade

```bash
litschema grade --all
```

A second model scores each value against its cited lines, once per paper,
through Claude Code or Codex. To choose the grader's harness and model, set
them in `litschema.yaml`:

```yaml
models:
  grade:
    harness: codex
    model: gpt-6-astra
```

`--harness` and `--model` override that setting for one run. The grader bills
the way that coding agent does: your subscription, or an API key or gateway
set in your shell. `grade` says which before it starts.

## Review

```bash
litschema verify
```

This opens the review app at `http://127.0.0.1:8000`. Start with the papers
that have the most flags. See [Reviewing](reviewing.md).

## Export

```bash
litschema export -f csv -o data.csv --audit-output audit.jsonl
```

The export applies your corrections and drops removed values. It writes JSONL
by default, or CSV for pandas or R. It includes values you haven't reviewed.
`audit.jsonl` has one record per paper: run, model, DOI, review status
(`complete`, `partial`, or `unreviewed`), grade flags, and your review entries.
Join it to the data on `article_id`.

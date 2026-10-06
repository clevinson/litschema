# Quickstart

You need Python 3.13+, [uv](https://docs.astral.sh/uv/), and
[Claude Code](https://claude.com/claude-code) logged in to your account.

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

`init` writes `litschema.yaml`, a starter schema, and the agent skills into
`.claude/skills/`. It also pins the project to the installed litschema version;
commands refuse to run under any other version until you edit the pin.

Copy your PDFs into `papers-inbox/`.

## Draft a schema and extract

Open Claude Code in the project and run the onboarding skill:

```text
/litschema-onboard
```

It reads a few of your papers, drafts a LinkML schema with you, converts the
PDFs to text, extracts one paper as a pilot so you can adjust the schema, and
then extracts the rest. To extract one paper by hand, run
`/extract-article <article-id>`.

## Grade

```bash
litschema grade --all
```

The grader is a second model that scores each value against its cited lines.
It runs once per paper through a coding-agent harness you already have
installed (Claude Code or Codex today). You can pin the grader to a specific
harness and model in `litschema.yaml`:

```yaml
models:
  grade:
    harness: codex
    model: gpt-6-astra
```

`--harness` and `--model` override the pin for one run.

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

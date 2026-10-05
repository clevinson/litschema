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

The grader is a separate `claude -p` call per paper. It scores each value
against its cited lines. Sonnet costs about $0.20 a paper;
`--model claude-haiku-4-5` costs less.

## Review

```bash
litschema verify
```

This opens the review app at `http://127.0.0.1:8000`. Start with the papers
that have the most flags. See [Reviewing](reviewing.md).

## Export

```bash
litschema export -f csv -o reviewed.csv
```

The export applies your corrections and drops removed values. It writes JSONL
by default, or CSV for pandas or R.

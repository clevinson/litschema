# Quickstart

You need Python 3.13+, [uv](https://docs.astral.sh/uv/), and a coding agent
set up with your subscription or an API key.

## Supported coding agents

| Coding agent | Onboarding and extraction | Grading |
| --- | --- | --- |
| [Claude Code](https://claude.com/claude-code) | yes | yes (the default) |
| [Codex](https://developers.openai.com/codex) | yes, piloted on one paper | yes |
| [pi](https://pi.dev) | coming soon | coming soon |

Onboarding and extraction run as skills in the agent you work in, CLI or
desktop app. Grading calls the agent's CLI, so install the CLI even if you work
in the app. The grader doesn't have to be the agent you extract with.

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
`.claude/skills/` (Claude Code) and `.agents/skills/` (Codex). It also pins the project to the installed litschema version;
commands refuse to run under any other version until you edit the pin.

Copy your PDFs into `papers-inbox/`.

## Draft a schema and extract

Open the project folder in your agent and run the onboarding skill:
`/litschema-onboard` in Claude Code, `$litschema-onboard` in Codex. Asking it
to "set up litschema" works too.

It reads a few of your papers, drafts a LinkML schema with you, converts the
PDFs to text, extracts one paper as a pilot so you can adjust the schema, and
then extracts the rest. To extract one paper by hand, ask for the
`extract-article` skill with the article id.

Codex blocks network access by default, so DOI lookups fail inside it. Run `litschema meta sync --all` from your own terminal afterwards,
or allow network for the session.

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
litschema export -f csv -o data.csv --audit-output audit.jsonl
```

The export applies your corrections and drops removed values. It writes JSONL
by default, or CSV for pandas or R. It includes values you haven't reviewed.
`audit.jsonl` has one record per paper: run, model, DOI, review status
(`complete`, `partial`, or `unreviewed`), grade flags, and your review entries.
Join it to the data on `article_id`.

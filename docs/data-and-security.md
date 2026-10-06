# Data and security

litschema has no server and no account. Your project folder holds the PDFs,
prepared text, extractions, grades, and reviews, and nothing in it leaves your
machine except as described below.

## What goes to a model

Both model calls go through your own Claude Code login, under your account's
data settings.

**Extraction** runs in your Claude Code session (`/extract-article`). The agent
reads `domain_context.md`, the generated schema files, the paper's
`article.md`, and any figures it opens. The skill lets it read and write files
and run shell commands in the project.

**Grading** (`litschema grade`) runs `claude -p` once per run, from the
article's folder. The prompt holds each extracted value, its basis and note,
the slot's description from your schema, and the cited lines with two lines of
context either side. The grader:

- has the Read tool and nothing else, limited to the article folder;
- loads no MCP servers and ignores your user-level Claude Code settings;
- saves no session;
- runs with `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, and
  `ANTHROPIC_BASE_URL` removed, so it uses the logged-in account. You can't
  grade through an API key or a gateway yet.

## Other network calls

- `litschema meta sync` sends a DOI to OpenAlex, plus your email if you pass
  `--email`.
- The review app sends an ORCID iD to the public ORCID API when you enter one,
  to show the reviewer's name.

The review app bundles its scripts, fonts, and icons, so opening it fetches
nothing.

## The review app

`litschema verify` listens on 127.0.0.1 only and has no login. Anyone with a
shell on your machine can reach it. Don't forward its port to a network.

## PDFs are untrusted input

The extraction agent reads the paper's text and can run shell commands in your
project. A PDF can hide text written as instructions to a model, which is
prompt injection. litschema limits what a bad paper can do to the data:

- Validation rejects fields your schema doesn't define and citations to lines
  that don't exist.
- The grader is read-only and judges each value against the lines it cites.
- The formatted view sanitizes HTML in the prepared text.

litschema doesn't sandbox the extraction agent. For papers from sources you
don't trust, run extraction in a container or VM, or keep Claude Code's
permission prompts on. Keep the project in git so any change outside
`data/papers/` shows up in the diff.

## What goes in git

The default `.gitignore` leaves out PDFs, `article.md`, and figures, since most
papers can't be redistributed. You commit extractions, reasoning, `run.json`,
grades, reviews, and `prepared-text.json`, which holds hashes and converter
settings. Extracted values, the extractor's notes, and the grader's issues can
quote short passages of the paper; check that before you publish the
repository.

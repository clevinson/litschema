# litschema — Agent Instructions

## What this is

Schema-driven, agentic extraction of structured data from scientific PDFs.
LinkML-native, local-first, with bundled agent skills (`skills/`). Pre-release
alpha (`specs/README.md` — no backwards compatibility until a versioned
release ships).

## Project structure

- `src/litschema/` — the package; CLI entrypoint is `litschema.cli:app`
- `tests/` — pytest suite (`testpaths = ["tests"]`)
- `specs/` — normative capability contracts; see `specs/README.md` for the
  convention. **Read a capability's `spec.md` before changing its surface,
  and update the spec in the same change if behavior moves.**
- `skills/` — bundled agent skills (`extract-article`, `litschema-onboard`)
  installed into user projects via `litschema skills install`

## Commands

Always prefix with `uv run`.

```bash
uv run pytest                 # full suite
uv run ruff check .           # lint
uv run litschema --help       # CLI surface: prepare-text, assemble, extract,
                               # validate, verify, mcp, export, status,
                               # doctor, init, skills, agent, meta
```

`specs/project-config/spec.md` owns which spec is the normative source for
each CLI verb — check its ownership table before assuming where a verb's
contract lives.

## Best practices

- Always use pytest, never unittest; prefer functional-style tests with
  `@pytest.mark.parametrize` over class-based suites.
- Do not "fix" a failing test by weakening its assertions. Find the real
  cause, or ask if it's ambiguous.
- Avoid mock-heavy tests for anything with real file/CLI behavior to verify —
  this project relies on tests actually exercising the filesystem/CLI paths
  they claim to cover.
- Favor failing fast and explicit errors over silent fallbacks; avoid
  try/except blocks that could mask a real bug.
- Alpha policy: no compatibility shims, no migrations, no dual code paths for
  an old and new format. Format changes land clean — see
  `specs/README.md` § Alpha status.

## Git & PR conventions

- **Commit messages: one line, no body.** Subject only.
- **No AI-attribution byline** (e.g. `Co-Authored-By: Claude`) on commits or
  PRs.
- **No "Generated with ..." AI-tool footer** on PR descriptions.
- PR descriptions: a one-line summary, the key changes, and a brief test
  plan. Don't pad them.

## kata issue tracker

This repo shares one kata project with `erw-meta-analysis`. Tag every issue
`area:litschema`. Run `kata quickstart` for the full agent contract; the short
version:

- Search before creating: `kata search "<keywords>" --agent`.
- Prefer updating existing issues over duplicates.
- Close only verified work: `kata close <ref> --done --message "<scope + verification>" --commit <sha>`.
- If work is incomplete, label `needs-review` and comment what remains.

# Capability: onboarding

Status: current.

Onboarding takes a first-time user from an empty directory and local PDFs to an
extracted, verifiable collection. It is local-PDF-first and is distinct from
later refinement.

## Implementation status

Everything below is live: `litschema init`, `skills install`, and the
`litschema` skill conductor end to end, publishing each extraction as an
active run through `agent record-extraction`.

## First-run path

```text
litschema init <dir>
  → place PDFs in papers-inbox/
  → litschema skill
  → litschema verify
```

A DOI may improve source metadata later; it is never an intake prerequisite.

## `litschema init`

Init creates `litschema.yaml`, `domain_context.md`, the one current
`schema/extraction.yaml`, `data/papers/`, `papers-inbox/`, ignore entries, and
project-local agent skills unless `--no-skills` is given. The draft schema has
one minimal local `tree_root: true` class.

Init and `skills install --project` set the project up for each coding agent
whose config directory exists: `$CLAUDE_CONFIG_DIR` or `~/.claude` for Claude
Code, `$CODEX_HOME`, `~/.codex` or `~/.agents` for Codex. `--agent claude-code`,
`--agent codex` or `--agent all` overrides detection; when no agent is found and
none is given, the command exits 2 and asks for `--agent`. Skills go to
`.claude/skills/` for Claude Code and `.agents/skills/` for Codex, and are
gitignored. For Codex, init also writes `.codex/config.toml` with network
access on so DOI lookups work; an existing `.codex/config.toml` without it is
left alone with a warning.

Init asks no questions and is scriptable. It refuses a file target, refuses any
directory already containing `litschema.yaml`, and refuses a nonempty
non-project directory unless `--force` is given. `--force` permits creation
alongside existing files but never overwrites them. Existing projects are
managed through config edits and `skills install --project --force`, not re-init.

Templates may be copied as starting material. Onboarding does not configure
parallel schema versions or import a framework base schema.

## `litschema` skill conductor

The project-local skill owns the first run and every later request. This is a
first-time user's first contact with the tool, so the conductor's default
surface is narrow: one question per message, no framework vocabulary, and no
narration of setup or internals. Checks that pass are silent. When the user
names commands or files, the conductor answers in those terms.

The conductor routes by the user's request first and project state second:

- A loose request ("get started") resumes at the first unfinished phase below.
- A specific task that fits the order runs directly; a missing prerequisite is
  named in one line and offered first.
- A task that departs from the order gets one message stating what litschema
  is built to do, the concrete consequence, and any narrower alternative, then
  one confirming question. On confirmation the conductor proceeds without
  raising it again. It asks why only when the answer would change the action.
- A request that breaks an integrity rule is declined with the supported
  route: no hand-edits to published runs (corrections are review overrides),
  no publishing an extraction that failed validation, no subagent publishing
  or model the conductor didn't choose, and no invented values or citations.

The conductor states consequences as facts and does not use persuasive
language.

0. **Silent pre-check:** confirm `litschema.yaml` exists, then run
   `litschema status` (see Running the CLI). A pass is silent. A missing
   config, a missing CLI (exit 127) or a version mismatch (exit 3) is the only
   setup condition the user hears about.
1. **Welcome:** open with a short plain-language welcome plus the count of
   papers found, then branch on that count and skim representative PDFs.
2. **Schema drafting:** interview for fields one question at a time, offer an
   existing structure (JSON Schema, spreadsheet, codebook) as a starting point,
   write the single current schema and domain context silently, validate
   silently, and confirm the field list with the user.
3. **Intake:** run offline `assemble` and `prepare-text --all`.
4. **Pilot:** extract one skimmed article, publish and activate its run, and
   offer to open the verifier. Revising the schema here returns to drafting;
   re-extracting publishes a new run and activates it, and the earlier run
   stays on disk.
5. **Batch:** extract every article with no active run, or whose active run is
   an error marker, retrying a failed article once before recording it. The
   conductor publishes each run itself with the model it dispatched, so
   subagents stage and validate only.
6. **Finish:** run the post-extraction metadata sweep, validation, and status;
   offer `litschema grade --all` when runs have no grades; hand off to
   `litschema verify`.

Extraction mechanics belong to `specs/extraction/spec.md`. Run layout and
activation belong to `specs/article-store/spec.md`. Review behavior belongs to
`specs/reviews/spec.md`.

## Running the CLI

Both bundled skills run the `litschema` on PATH and nothing else. Their first
command loads the project (`litschema status`), so a version mismatch surfaces
before any work: onboarding runs it before its first message, and
`extract-article` in its setup gate. Exit 127 means litschema is not installed;
the skill tells the user to run `uv tool install litschema`. Exit 3 means the
project's pin disagrees with the installed litschema or its skills; the skill
stops and relays the message verbatim. A skill never edits `litschema.yaml`,
reinstalls litschema, or reinstalls skills to clear a mismatch, since which
version a project runs is the user's decision.

`skills install` stamps each copied skill with the installing version. See
`specs/project-config/spec.md` for the pin contract.

## Onboarding versus refinement

Onboarding establishes a project and its first active runs. Changing an
established schema and reprocessing a reviewed corpus is a future, separate
workflow (refinement, planned for 0.2.0); the `litschema` skill must not grow
into it.

## Source metadata

Assemble seeds automatic filename metadata. Extraction uses the bib-metadata
CLI for registry-first DOI enrichment or title-page fallback. A post-batch
`meta sync --all` retries transient registry failures. Skills never edit the
manifest directly.

## Interruption and rerun

Onboarding is resumable, and the skill is the entry point for every later
session: it reads `litschema status` and starts at the first unfinished phase
(schema, prepare, pilot, the rest, grading, handoff). Existing intake artifacts
remain, complete published runs remain immutable, active selections remain
valid, and incomplete staging does not appear as a run. Rerunning skips
articles with an active run and retries missing or error-only articles. A
schema change after review is a departure from the order: the conductor says
that every run becomes stale and that re-extracted runs start without the
existing reviews, which stay on the old runs, and proceeds if the user
confirms. It does not create a same-schema rerun unless the user asks.

## Invariants

- PDFs enter through `papers-inbox/`.
- The `litschema` skill remains the conductor, for the first run and reruns.
- Init is offline, noninteractive, create-only, and never re-initializes. It
  sets up the coding agents whose config folders exist, or those named with
  `--agent`.
- The project has one current schema; Git stores its history.
- First successful extractions become immutable runs with per-article active
  selection.
- Refinement is not folded into onboarding: the conductor never carries
  reviews between runs.
- The user's request decides what the conductor does, except where an
  integrity rule applies.
- Metadata writes use deterministic CLI guards.
- Interrupted work is resumable without mutating completed runs.

## Test obligations

Implementation coverage must pin:

- init refusal and create-only behavior, including `--force`;
- exact scaffold paths, one current schema, local skills, and copied-template
  behavior without a framework base import;
- offline assemble and prepare-text;
- silent pre-check: missing-config stop, `litschema status` before the welcome
  message, and a stop that relays exit 127 or 3 unchanged;
- request routing: loose requests resume, out-of-order requests get one notice
  and proceed on confirmation, and integrity rules hold when the user insists;
- conductor voice constraints: one question per message, no framework
  vocabulary in user-facing text, and no narration of passing checks;
- empty-project stop behavior;
- representative-document schema drafting and approval gate;
- one-article pilot publication and activation;
- batch creation and activation of runs;
- skip of articles with an active run and retry of missing/error attempts;
- interruption before and after publication;
- bib-metadata CLI use and post-batch sync placement;
- handoff to the verifier;
- absence of refinement behavior from the onboarding conductor.

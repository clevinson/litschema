# Capability: onboarding

Status: approved target.

Onboarding takes a first-time user from an empty directory and local PDFs to an
extracted, verifiable collection. It is local-PDF-first and is distinct from
later refinement.

## First-run path

```text
litschema init <dir>
  → place PDFs in papers-inbox/
  → /litschema-onboard
  → litschema verify
```

A DOI may improve source metadata later; it is never an intake prerequisite.

## `litschema init`

Init creates `litschema.yaml`, `domain_context.md`, the one current
`schema/extraction.yaml`, `data/papers/`, `papers-inbox/`, ignore entries, and
project-local agent skills unless `--no-skills` is given. The draft schema has
one minimal local `tree_root: true` class.

Init asks no questions and is scriptable. It refuses a file target, refuses any
directory already containing `litschema.yaml`, and refuses a nonempty
non-project directory unless `--force` is given. `--force` permits creation
alongside existing files but never overwrites them. Existing projects are
managed through config edits and `skills install --local --force`, not re-init.

Templates may be copied as starting material. Onboarding does not configure
parallel schema versions or import a framework base schema.

## `/litschema-onboard` conductor

The project-local skill owns the first run:

1. **Setup:** resolve the project and CLI, run `status` and `doctor`, and stop
   when there is no inbox or assembled work.
2. **Schema drafting:** interview for fields, inspect two or three user-selected
   representative PDFs, edit the single current schema and domain context,
   prepare runtime schema context, and obtain user approval.
3. **Intake:** run offline `assemble` and `prepare-text --all`.
4. **Pilot:** extract one representative article as an `initial` run, validate
   it, activate it, and have the user inspect it in the verifier.
5. **Batch:** extract remaining eligible articles into `initial` runs and
   activate each successful first run. Existing articles with an active run
   using the current schema are skipped.
6. **Finish:** run the post-extraction metadata sweep, validation, and status;
   hand off to `litschema verify`.

Extraction mechanics belong to `specs/extraction/spec.md`. Run layout and
activation belong to `specs/article-store/spec.md`. Review behavior belongs to
`specs/reviews/spec.md`.

## Onboarding versus refinement

Onboarding establishes a project and its first active runs.
`/litschema-refine` changes an established schema or domain context, pilots a
subset, creates lineage children for the full corpus, reconciles existing
reviews, activates the accepted runs, and cleans up abandoned runs. It is
defined only by `specs/refinement/spec.md`. The onboarding skill must not absorb
or restate that lifecycle.

## Source metadata

Assemble seeds automatic filename metadata. Extraction uses the source-metadata
CLI for registry-first DOI enrichment or title-page fallback. A post-batch
`meta sync --all` retries transient registry failures. Skills never edit the
manifest directly.

## Interruption and rerun

Onboarding is resumable. Existing intake artifacts remain, complete published
runs remain immutable, active selections remain valid, and incomplete staging
does not appear as a run. Rerunning skips accepted active current-schema work
and retries missing or error-only articles. It does not create a same-schema
rerun unless the user explicitly requests that separate workflow.

## Invariants

- PDFs enter through `papers-inbox/`.
- `/litschema-onboard` remains the first-run conductor.
- Init is offline, noninteractive, create-only, and never re-initializes.
- The project has one current schema; Git stores its history.
- First successful extractions become immutable initial runs with per-article
  active selection.
- Refinement is not folded into onboarding.
- Metadata writes use deterministic CLI guards.
- Interrupted work is resumable without mutating completed runs.

## Test obligations

Implementation coverage must pin:

- init refusal and create-only behavior, including `--force`;
- exact scaffold paths, one current schema, local skills, and copied-template
  behavior without a framework base import;
- offline assemble and prepare-text;
- setup/doctor failure and empty-project stop behavior;
- representative-document schema drafting and approval gate;
- one-article pilot publication and activation;
- batch creation and activation of initial runs;
- skip of active current-schema articles and retry of missing/error attempts;
- interruption before and after publication;
- source-metadata CLI use and post-batch sync placement;
- handoff to all three verifier routes;
- absence of refinement behavior from the onboarding conductor.

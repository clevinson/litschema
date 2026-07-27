# Capability: onboarding

Status: partially current.

Onboarding takes a first-time user from an empty directory and local PDFs to an
extracted, verifiable collection. It is local-PDF-first and is distinct from
later refinement.

## Implementation status

Live today: `litschema init`, `skills install`, and the `/litschema-onboard`
conductor end to end, writing extractions to the article-root layout.

Pending: run-shaped extraction output. Steps 4 and 5 below publish `initial`
runs and activate them; today they write `agent-extraction.json` at the article
root and there is no activation step. Tracked by `tdv3`; the conductor's
user-facing flow does not otherwise change.

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

The project-local skill owns the first run. This is a first-time user's first
contact with the tool, so the conductor's surface is deliberately narrow: one
question per message, no framework vocabulary, and no narration of setup or
internals. Checks that pass are silent.

0. **Silent pre-check:** confirm `litschema.yaml` exists using file reads
   alone. Do not run `status`, `doctor`, or resolve the CLI yet — none of it is
   needed to count or skim PDFs, and none of it reaches the user. A missing
   config is the one setup condition the user hears about.
1. **Welcome:** open with a short plain-language welcome plus the count of
   papers found, then branch on that count and skim representative PDFs.
2. **Schema drafting:** interview for fields one question at a time, offer an
   existing structure (JSON Schema, spreadsheet, codebook) as a starting point,
   write the single current schema and domain context silently, validate
   silently, and confirm the field list with the user.
3. **Intake:** run offline `assemble` and `prepare-text --all`.
4. **Pilot:** extract one skimmed article as an `initial` run, validate it,
   activate it, and offer to open the verifier. Revising the schema here
   returns to drafting.
5. **Batch:** extract remaining eligible articles into `initial` runs and
   activate each successful first run, retrying a failed article once before
   recording it. Existing articles with an active run using the current schema
   are skipped.
6. **Finish:** run the post-extraction metadata sweep, validation, and status;
   hand off to `litschema verify`.

Extraction mechanics belong to `specs/extraction/spec.md`. Run layout and
activation belong to `specs/article-store/spec.md`. Review behavior belongs to
`specs/reviews/spec.md`.

## Approving the CLI dev override

`.litschema/dev-cli` names a development command that agents will execute, so
it requires the user's approval. Approval is recorded as the SHA-256 of the
approved file's exact content in `.litschema/dev-cli-approved`, which lives
under the gitignored runtime directory and therefore stays machine-local.

Approval must be verifiable state rather than a claim carried in a prompt.
A batch conductor cannot approve on the user's behalf and cannot pass approval
down as an assertion: text asserting consent is indistinguishable from text
fabricating it, so an agent that accepts one accepts both. Recording the hash
lets every dispatched subagent confirm approval itself, which is what allows a
batch to run without stalling on each article. Editing `dev-cli` changes its
hash and silently revokes the old approval. `doctor` reports the current
state and, when unapproved, the command that records it.

## Onboarding versus refinement

Onboarding establishes a project and its first active runs. Changing an
established schema and reprocessing a reviewed corpus is a future, separate
workflow (refinement, developed on `feat/multirun`); the onboarding skill must
not grow into it.

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
- silent pre-check: missing-config stop, and no `status`/`doctor`/CLI
  resolution before the welcome message;
- dev-override approval: matching hash used silently, missing or stale hash
  prompting the user, recording after confirmation, and revocation when the
  override file changes;
- conductor voice constraints: one question per message, no framework
  vocabulary in user-facing text, and no narration of passing checks;
- empty-project stop behavior;
- representative-document schema drafting and approval gate;
- one-article pilot publication and activation;
- batch creation and activation of initial runs;
- skip of active current-schema articles and retry of missing/error attempts;
- interruption before and after publication;
- source-metadata CLI use and post-batch sync placement;
- handoff to the verifier;
- absence of refinement behavior from the onboarding conductor.

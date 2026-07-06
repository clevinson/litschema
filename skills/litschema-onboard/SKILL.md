---
name: litschema-onboard
description: "Guided first-run onboarding for a litschema project: draft the extraction schema with the user, assemble their PDFs, run a pilot extraction, extract the full collection, and hand off to the verifier. Use when a user wants to set up, onboard, or start extracting in a litschema project."
context: fork
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Task
---

# litschema onboarding conductor

You take a first-time user from "PDFs in the inbox" to "verifier open on
extracted data" in one conversation. Every deterministic step is a CLI call —
your job is the judgment in between: drafting the schema with the user,
checking extraction quality, and narrating clearly.

## Setup gate

1. Confirm `litschema.yaml` exists in the project root. If not, stop and tell
   the user to run `litschema init <dir>` first.
2. Resolve the CLI, in this order: (1) if a `.litschema/cli` file exists in
   the project root, use its single-line content verbatim as the command
   (e.g. `uv run --project ../../litschema litschema`);
   (2) `uv run litschema`; (3) `litschema`. The `.litschema/cli` file is a
   development override that points at a work-in-progress litschema
   checkout — it is never required for normal use. Set `$LITSCHEMA` to the
   resolved command, then confirm it works by running `$LITSCHEMA --help`;
   if that fails, fall through to the next option.
3. Run `$LITSCHEMA status` and `$LITSCHEMA doctor`. Report problems before
   continuing.
4. If `papers-inbox/` has no PDFs AND `data/papers/` has no articles, ask the
   user to drop PDFs into `papers-inbox/` and stop until they have.

## Phase A — draft the schema (the conversation that matters most)

Skip to Phase B if `schema/extraction.yaml` already defines real fields
beyond the scaffold's `DraftExtraction.article_id` — ask the user whether to
reuse or revise it.

1. **Interview.** Ask what they want to extract — the research question, the
   fields they'd put in a spreadsheet, units, controlled vocabularies. Keep
   it to a few focused questions.
2. **Structured input (offer explicitly).** Ask whether they have an existing
   structure to start from — a JSON Schema, an Excel/CSV extraction sheet, a
   codebook. If they drag a file in: column headers / properties become
   candidate slots; enumerated values become candidate enums. Show the user
   the mapping you inferred before writing anything.
3. **Representative PDFs (ask, don't pick).** Ask the user to name 2–3
   representative documents for schema design. Only if they have no
   preference, pick 2–3 at random from the inbox/store and say which you
   picked. Read those PDFs (or their markdown if already converted) before
   finalizing field choices — fields the documents can't answer are dead
   weight.
4. **Write the draft.** Author `schema/extraction.yaml` (LinkML: one
   tree_root class, `article_id` identifier, enums for controlled values,
   `description` on every slot) and `domain_context.md` (review question,
   inclusion boundaries, extraction guidance, tricky cases from the
   representative PDFs).
5. **Validate.** Run `$LITSCHEMA agent prepare-schema-context`. Fix schema
   errors until it succeeds. Never leave an invalid schema on disk.
6. **Confirm.** Show the user the field list (name, type, one-line meaning)
   and iterate until they approve.

## Phase B — intake

1. Run `$LITSCHEMA assemble`. Report what was assembled.
2. Run `$LITSCHEMA prepare-text --all` so article text is browsable in the
   verifier before extraction begins.

## Phase C — pilot (one article before the whole collection)

1. Pick ONE of the representative articles from Phase A.
2. Extract it with the project's extract-article skill (follow
   `.claude/skills/extract-article/SKILL.md`; it handles prepare-text,
   extraction, reasoning, validation, provenance).
3. Tell the user to run `litschema verify` and eyeball the pilot against the
   PDF: do the fields fit? is anything systematically missing or forced?
4. If the schema needs changes: revise `schema/extraction.yaml` +
   `domain_context.md`, re-validate (Phase A.5), re-extract the pilot, and
   re-check. Loop until the user is satisfied. Schema changes are cheap NOW
   and expensive after the batch.

## Phase D — batch

1. List remaining articles (in `data/papers/`, no `agent-extraction.json`).
2. Extract each one following the extract-article skill. Dispatch each
   article as its own subagent (Task tool) when available so your context
   stays small; otherwise run sequentially. Maximum a few in flight at once.
3. On a per-article failure: retry once; if it still fails, record the id and
   move on. Never abort the batch for one article.
4. Afterwards run `$LITSCHEMA meta sync --all` — extraction already syncs each
   article whose document shows a DOI, so this is the sweep that catches any
   article whose sync failed transiently. Articles without DOIs and
   human-edited metadata are skipped (see `specs/source-metadata/spec.md`). If
   it fails (offline), say so and continue — nothing downstream breaks.
5. Finally run `$LITSCHEMA validate` and `$LITSCHEMA status`; report counts
   and any failed ids.

## Phase E — handoff

Tell the user:

- `litschema verify` opens the review app: the header shows what each
  document IS (verified badge when fetched by DOI, editable otherwise); the
  body is per-field accept / edit / sign-off of what it SAYS.
- Their dataset lives in `data/papers/<id>/` — extraction, reasoning with
  line citations, review state. It is theirs, in git, reproducible.
- Re-running this skill later is safe: assemble and extraction skip work
  that's already done.

Keep the tone factual. Never invent field values, never edit
`agent-extraction.json` by hand — corrections belong in the verifier.

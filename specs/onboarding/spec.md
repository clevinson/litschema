# Capability: onboarding

Taking a first-time user from an empty directory and a folder of PDFs to an
extracted, verifiable collection — with an agent conducting the judgment steps
and the CLI owning every deterministic one. Introduced by PR #17
(`feat/onboard-flow`).

Onboarding is **local-PDF-first**: no registry file, no bibliography authoring,
no network access on the intake path. A DOI, if a document has one, improves
metadata later — it is never a prerequisite.

## The path

```
litschema init <dir>          # scaffold (offline, no questions)
  → drop PDFs in papers-inbox/
  → /litschema-onboard        # agent: schema drafting, intake, pilot, batch
  → litschema verify          # human: review what was extracted
```

## `litschema init`

Scaffolds a complete project: `litschema.yaml`, `domain_context.md`, a draft
`schema/extraction.yaml` (one `DraftExtraction` tree-root class with an
`article_id` identifier — deliberately minimal; the real schema is drafted
conversationally during onboarding), `data/papers/`, `papers-inbox/`,
`.gitignore` entries for PDFs and runtime dirs, and the bundled agent skills
copied project-locally into `.claude/skills/` (`--no-skills` opts out).

Refusals, in order:

- WHEN the target exists and is not a directory, THEN exit 2.
- WHEN the target contains `litschema.yaml`, THEN exit 2 — **always**;
  `--force` does not override. There is no re-init: an existing project is
  managed by editing `litschema.yaml` directly and by
  `litschema skills install --local --force` for skill refresh.
- WHEN the target is a non-empty directory without a config and `--force` was
  not given, THEN exit 2. `--force` means "yes, initialize into this non-empty
  directory" (a fresh git repo with a README) — it never overwrites an
  existing file.

`init` asks no questions: bare `litschema init <dir>` is fully scriptable
(CI, agents, pipes). There is no document-type question and no
`document_profile` key — whether a document gets registry enrichment is
decided per article, from its data, at extraction time (see the lifecycle
below and `decisions.md`).

## The conductor (`litschema-onboard` skill)

One skill owns the whole first run; every deterministic step is a CLI call and
the agent's job is the judgment between them:

- **Setup gate** — verify the project, resolve the CLI (dev override →
  `uv run litschema` → `litschema`), run `status` + `doctor`, stop early if
  the inbox is empty.
- **Phase A: schema drafting** — the conversation that matters most.
  Interview for fields; offer to seed from an existing structure (JSON
  Schema, spreadsheet, codebook); read 2–3 user-named representative PDFs
  before finalizing; write `schema/extraction.yaml` + `domain_context.md`;
  validate with `agent prepare-schema-context`; iterate until approved.
- **Phase B: intake** — `assemble` (offline: stable id from filename, PDF
  moved to `data/papers/<id>/`, manifest written), then `prepare-text --all`.
- **Phase C: pilot** — extract ONE representative article, have the user
  eyeball it in the verifier, revise the schema while changes are cheap.
- **Phase D: batch** — extract the rest (subagent per article where
  available), then `meta sync --all` as the registry sweep, then `validate` +
  `status`.
- **Phase E: handoff** — point at `litschema verify` and the on-disk dataset.

Extraction mechanics belong to the `extract-article` skill; the conductor
never restates them.

## Metadata during onboarding

The full lock model is `specs/source-metadata/spec.md`; onboarding touches it
at these moments:

| moment | what happens | provenance |
|---|---|---|
| `init` | nothing — no metadata exists | — |
| `assemble` | block seeded `{title}` from the PDF filename | `auto` |
| extraction backfill | agent reads the title page, writes via `meta set <id> --source auto ...` (including `--doi` if printed on the document) | `auto` |
| post-extraction sync | ONLY IF a DOI was visible: `meta sync <id>` replaces the block with registry values | `doi` (locked) |
| post-batch sweep | `meta sync --all` catches articles whose per-article sync failed transiently | `doi` where it resolves |
| verifier edits | human corrections via the header form | `manual` (protected) |

Documents without DOIs simply never sync: their metadata is the agent's
title-page reading until a human touches it. Nothing downstream distinguishes
the two paths.

## Invariants

- **No re-init.** WHEN `init` targets a directory containing
  `litschema.yaml`, THEN it exits 2 and writes nothing, regardless of flags.
- **Init never overwrites.** WHEN `init` runs (including `--force`), THEN no
  existing file is modified — `.gitignore` entries are appended, everything
  else is create-only.
- **Scriptable init.** WHEN `init` runs without a TTY or flags, THEN it
  completes without prompting.
- **Offline intake.** WHEN `assemble` / `prepare-text` run, THEN no network
  access occurs; a project with zero DOIs reaches extraction untouched by any
  registry.
- **Bibliography flows through the CLI.** WHEN a skill backfills or enriches
  source metadata, THEN it does so via `meta set` / `meta sync` — never by
  editing `article-metadata.json` directly — so the never-clobber guard,
  DOI validation, and atomic writes always apply.
- **Sync follows extraction.** WHEN the conductor batch-syncs
  (`meta sync --all`), THEN it does so after the batch extraction — DOIs
  enter manifests via extraction backfill, so an intake-time sweep would be a
  no-op on a fresh project.
- **Safe re-runs.** WHEN onboarding runs on a partially-processed project,
  THEN `assemble` and extraction skip work that is already done.

## Future work

A **schema library**: `init --schema <ref>` seeding `schema/extraction.yaml`
by importing/extending a published LinkML base extraction class (standard
bases in the package, or an external schema by URL), instead of the built-in
draft scaffold. This is its own capability — deliberately NOT folded into
onboarding or revived as a "profile" (see `decisions.md`).

## Code map

`src/litschema/cli.py` (`init`, `status`, `doctor`, `skills install`) ·
`src/litschema/ingest/article_assembly.py` (`assemble`) ·
`skills/litschema-onboard/SKILL.md` (conductor) ·
`skills/extract-article/SKILL.md` (extraction + backfill contract). Tests:
`test_init_onboarding.py`, `test_skills_install.py`, `test_assemble.py`.

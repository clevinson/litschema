# Decisions: onboarding

Append-only. Newer entries supersede older ones.

## 2026-07-05 — Local-PDF-first onboarding; one conductor skill

**Context:** the original onboarding path required authoring a bibliography
registry before anything could be extracted, and the first-run experience was
scattered across README prose and individual commands.

**Decision:** onboarding starts from PDFs in `papers-inbox/` and nothing
else. `assemble` is offline (id from filename, manifest written, no DOI or
network required). One conductor skill (`litschema-onboard`) owns the first
run end to end — schema drafting, intake, pilot, batch, handoff — with every
deterministic step delegated to a CLI call and extraction mechanics delegated
to the `extract-article` skill.

**Rationale:** the sharpest onboarding friction was metadata ceremony before
value; a user's actual starting point is a folder of PDFs. Keeping judgment
in the agent and determinism in the CLI makes the flow reproducible and the
skill short.

**Rejected:** bibliography-file-driven intake (registry authoring before
extraction); separate skills per phase (context sprawl, no single narrative).

## 2026-07-06 — Disallow re-init

**Context:** `init --force` on an existing project re-ran scaffolding in
"preserve everything" mode: it changed nothing (every write is
existence-guarded, skill reinstall hardcoded `force=False`) while printing
next-steps output that could contradict the actual config.

**Decision:** `init` on a directory containing `litschema.yaml` exits 2,
always — `--force` does not override. `--force` is narrowed to "initialize
into a non-empty directory that is not yet a litschema project" and still
never overwrites a file. Existing projects are managed by editing
`litschema.yaml` and by `litschema skills install --local --force`.

**Rationale:** re-init bought nothing and could lie; every legitimate re-init
use had a better dedicated tool. Deleting the case also deleted two open bugs
(untruthful next-steps output; `--force` not forwarded to skill install).

**Rejected:** patching re-init to read the existing config and warn on
profile mismatch (keeps a special case alive to serve output text).

## 2026-07-06 — Delete `document_profile`; enrichment is data-driven

**Context:** init asked "what kind of documents?" and stored
`document_profile: journal_article | generic`. Its entire surface was one
hint line in init/status output and one conditional harvest step in the
onboard skill. It never touched schema scaffolding or pipeline behavior, and
after the source-metadata lock model landed, registry enrichment became a
per-article, data-driven decision (`meta set --doi` at extraction, then
`meta sync`).

**Decision:** the key, the init question, and the `--profile` flag are gone.
Whether a document gets registry enrichment is decided by whether a DOI is
found on it — never declared per project at init time.

**Rationale:** a project-level declaration is redundant with per-article data
and can mislead (a "generic" project with a few DOI'd journal articles would
skip enrichment those articles deserve). Bare `init` becomes zero-question
and fully scriptable; a config value that could be corrupt is gone.

**Rejected:** keeping the key as a pure UX hint (still a lying-output
surface); growing it into schema presets — that idea is real but is its own
future capability (a schema library: `init --schema <ref>` importing or
extending published LinkML base extraction classes), recorded in
`spec.md` § Future work rather than overloaded onto this key.

## 2026-07-06 — Batch registry sync runs after extraction, not at intake

**Context:** the onboard skill ran its batch metadata sync during intake
(immediately after `assemble`). On a fresh project no manifest has a DOI at
that point — DOIs enter manifests via extraction backfill (the agent reading
the title page) — so the intake-time sweep was a guaranteed no-op on the
primary path.

**Decision:** the per-article `meta sync <id>` at the end of each extraction
(when a DOI was visible on the document) is the primary sync moment.
`meta sync --all` runs once after the batch extraction as the sweep that
catches articles whose per-article sync failed transiently.

**Rationale:** sync placed where the data exists. The sweep stays useful for
re-runs and transient registry failures without pretending to serve the
first run.

**Rejected:** syncing at both intake and post-batch (a ceremonial no-op on
the path that matters, implying DOIs should exist before extraction).

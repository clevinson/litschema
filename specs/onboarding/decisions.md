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
after the bib-metadata lock model landed, registry enrichment became a
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

## 2026-07-07 — Extraction-time enrichment is `meta set --doi ... --sync` (supersedes the sync-placement entry's mechanism)

**Context:** the entry above named `meta sync <id>` as the per-extraction sync
moment. The contract was then consolidated: two commands with different
consent semantics invited agent error, and the happy path transcribed
bibliography the registry immediately replaced.

**Decision:** the extraction-time command is
`meta set <id> --source auto --doi <doi> --sync` — one guarded command that
records the DOI and attempts the registry lock; title-page transcription is
an explicit fallback (no DOI, or the sync half failed). The placement
decision above is unchanged: the post-batch `meta sync --all` sweep remains
the transient-failure net. Full rationale and rejected alternatives:
`specs/bib-metadata/decisions.md` (2026-07-07 entry).


## 2026-07-14 — Onboarding creates initial runs; refinement stays separate

**Context:** immutable runs and schema refinement add lifecycle steps that do
not belong in a first-run conductor.

**Decision:** `/litschema-onboard` still begins with `papers-inbox/`, drafts
the one current schema, pilots one article, and activates successful `initial`
runs. Established-project schema or domain-context changes use
`/litschema-refine`. Templates are copied; the earlier proposed schema-library
import mechanism is not part of the MVP.

**Rejected:** folding refinement into onboarding; overwriting extraction
outputs on rerun; reviving imported framework base schemas.


## 2026-07-26 — Dev-override approval is recorded state, not a relayed claim

**Context:** running the first real batch, every dispatched subagent stopped to
ask for approval of the `.litschema/dev-cli` override, and correctly refused
the conductor's assertion that the user had already approved it — naming it as
permission laundering. The batch could not proceed. Relaying the user's genuine
approval afterward still cost a round trip per agent, because consent arriving
as prose cannot be distinguished from consent invented as prose.

**Decision:** approval is the SHA-256 of the approved `dev-cli` content, stored
in `.litschema/dev-cli-approved`. Agents compare hashes themselves instead of
trusting a claim, so a conductor approves once and its subagents proceed
silently. Editing the override changes the hash and revokes approval
automatically. The file lives under the gitignored runtime directory, so
approval is machine-local and never travels to another user with the repo.

**Rejected:** passing approval down in the dispatch prompt, which cannot be
made correct because an agent that accepts asserted consent also accepts
fabricated consent; a project-config key, which would be committed and would
approve the override for everyone who clones; and emitting a pyproject.toml so
the override is unnecessary, which was tried and reverted (see kata qr3c — it
only helps post-publication and made `doctor` report false success).

## 2026-07-27 — Dev-override approval moves out of the checkout (supersedes the storage location above)

**Context:** the entry above stored approval in `.litschema/dev-cli-approved`
and argued it was safe because the runtime directory is gitignored, so approval
"never travels to another user with the repo." That reasoning does not hold.
`.gitignore` governs what *this* repository tracks; it has no say over what an
incoming repository already contains. Nothing stops a project from committing
both `.litschema/dev-cli` and a matching `.litschema/dev-cli-approved`, and on
a fresh clone the hashes agree — so the skills' own instruction ("use it
silently — they have approved this exact command before") hands a hostile
checkout silent arbitrary command execution on first run.

**Decision:** approval lives in the user's configuration, at
`${XDG_CONFIG_HOME:-$HOME/.config}/litschema/dev-cli-approved/<sha256 of the
real project path>`, holding the content hash. An in-project marker grants
nothing and is explicitly ignored; `doctor` reports one as ignored and offers
to have it deleted.

**What the original decision got right, and keeps:** approval must be
verifiable state rather than a relayed claim, because an agent that accepts
asserted consent also accepts fabricated consent. That was the correct response
to the threat it was built for — a peer agent laundering permission through a
dispatch prompt. It simply did not address a second threat: consent forged by
the repository itself. Keying by project path and content hash preserves the
batch property that motivated the original design, since every subagent can
still confirm approval on its own.

**Rejected:** keying by project name rather than resolved path, which would let
one approval cover any checkout sharing a directory name; and prompting per
agent, which is what the recorded-state design existed to eliminate.

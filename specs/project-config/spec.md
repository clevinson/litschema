# Capability: project config & CLI shell

How a litschema project is found and described (`litschema.yaml`), how the
extraction schema is resolved, and the conventions every CLI verb shares.
Documented as-built from the 2026-07-07 audit.

## Config discovery

`litschema.yaml` is found in this order (first hit wins):

1. An explicit path (`--config/-c` on the CLI).
2. The `LITSCHEMA_CONFIG` environment variable.
3. An upward walk from the current directory (every parent is checked).
4. An upward walk from the installed package's own directory — a fallback
   for scripts that `cd` elsewhere (flagged for removal: surprising in
   installed layouts; improvements backlog).

Failures raise `ConfigNotFoundError`; the CLI renders it and exits 2 with a
"run `litschema init`" hint when discovery (not an explicit path) failed.

## Config keys

All keys are optional; an empty file is a valid project. Every relative
path resolves against the config file's own directory.

| key | default | role |
|---|---|---|
| `project_root` | `.` | display root, git context, `.litschema/` runtime + cache dirs |
| `data_dir` | `data` | home of the explore registries (`authors.yaml`, `institutions.yaml`) |
| `schema_dir` | `schema` | where the extraction schema lives |
| `extraction_schema_file` | `extraction.yaml` | the schema file inside `schema_dir` |
| `article_store_dir` | `data/papers` | the article store (`specs/article-store`) |
| `paper_inbox_dir` | `papers-inbox` | intake drop zone |

Unknown keys are preserved on `cfg.raw` (escape hatch for domain repos).

Vestigial keys that still parse but have no consumer — scheduled for
removal, do not use: `references_dir`, `tracking_xlsx`, `static_site_dir`,
and `schema_root` (written by older `init` scaffolds; never read).

## Schema resolution

The extraction schema is `schema_dir/<extraction_schema_file>`. Resolution
loads it as a LinkML `SchemaView` and selects the root class: **exactly one
locally-defined class with `tree_root: true`** — imported classes never
count, so a base class from a library import must be subclassed (or
re-asserted) locally to become the root. Zero or multiple roots is an error.

Conventions the framework assumes of project schemas:

- one local `tree_root: true` class = the per-document extraction record;
- an `identifier: true` slot on it (any name; `article_id` by convention) —
  the explore store makes it the primary key and backfills it from the
  article directory name;
- enums for controlled vocabularies (drives the verifier's dropdown
  editors);
- scalar slot ranges drive explore column types; multivalued or
  class-ranged slots become JSON columns.

Validation everywhere is closed-world: unknown properties are rejected.

## CLI conventions

- Exit codes: **0** success, **1** operation/validation failure, **2**
  usage or configuration error, **130** interrupted (resumable).
- Verbs run in-process (no shelling out to sibling commands); the one
  exception is the legacy `harvest` pipeline (scheduled for removal).
- `--config/-c` (or `LITSCHEMA_CONFIG`) applies to every project-scoped
  verb.

| verb | needs a project? | spec |
|---|---|---|
| `init` | creates one | `specs/onboarding` |
| `status`, `doctor` | yes | below |
| `assemble`, `prepare-text` | yes | `specs/article-store` |
| `validate`, `agent *` | yes (except `agent validate-reasoning`) | `specs/extraction` |
| `meta show/set/sync` | yes | `specs/source-metadata` |
| `verify` | yes | `specs/verifier` |
| `mcp` | yes | `specs/explore` |
| `skills install` | no — standalone | `specs/onboarding` |
| `extract` | no | stub: exits 2 pointing at the agent skills |
| `harvest` | yes | legacy, superseded by `meta sync --all`; removal tracked in the improvements backlog |

**`status`** prints counts: schema presence, inbox PDFs, manifests,
prepared markdown, extractions, reasoning files, reviews (currently labeled
"annotations" — naming cleanup tracked). Always exit 0.

**`doctor`** checks Python ≥ 3.13, `uv` on PATH, the schema dir, litschema's
bundled skills (project-local `.claude/skills/` first, then global —
unrelated skills are not a green light), and an agent CLI on PATH. Exit 1
with a remediation list when anything fails; 0 otherwise.

## Invariants

- **Relative paths are config-relative.** WHEN litschema.yaml lives
  somewhere other than the cwd, THEN its relative paths still resolve
  against the file, not the invoker. (`test_smoke.py`)
- **One root class.** WHEN a project schema has zero or multiple local
  `tree_root` classes, THEN resolution fails loudly rather than guessing.
  (`test_schema_resolution.py`)
- **Usage errors are exit 2, never tracebacks.** WHEN a verb is invoked
  with a bad combination of flags, an unknown article, or no project, THEN
  it prints a one-line remedy and exits 2.
- **Doctor counts only litschema's skills.** WHEN unrelated skills live in
  the same directories, THEN doctor still reports litschema's as missing.
  (`test_init_onboarding.py`)

## Code map

`src/litschema/config.py` (discovery, keys) · `src/litschema/project.py`
(thin wrapper) · `src/litschema/schema_resolution.py` ·
`src/litschema/schema_validation.py` (closed-world validators, atomic JSON
writes) · `src/litschema/cli.py` (shell). Tests: `test_smoke.py`,
`test_schema_resolution.py`, `test_configured_schema_cli.py`.

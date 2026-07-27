# Capability: project config and CLI shell

Status: current.

This spec owns project discovery, the one current LinkML extraction schema,
schema identity, and conventions shared by CLI verbs. Run storage is owned by
`specs/article-store/spec.md`.

## Implementation status

Everything below is live: config discovery and precedence, config-relative
path resolution, the core key set, single-schema resolution requiring exactly
one local `tree_root: true` class, closed-world validation, the CLI exit-code
and `--config` conventions, schema identity hashing, `status`, and `doctor`.

## Config discovery and paths

`litschema.yaml` is found in this order: explicit `--config/-c`,
`LITSCHEMA_CONFIG`, an upward walk from the current directory, then the current
installed-package fallback walk. Relative paths resolve against the config
file, never the caller's working directory. Missing discovery exits 2 with an
`init` remedy; an invalid explicit path fails directly.

Core keys and defaults:

| key | default | role |
|---|---|---|
| `project_root` | `.` | Git context and `.litschema/` runtime files |
| `data_dir` | `data` | layout convention; not read directly |
| `schema_dir` | `schema` | schema directory |
| `extraction_schema_file` | `extraction.yaml` | the one current schema file |
| `article_store_dir` | `data/papers` | article store |
| `paper_inbox_dir` | `papers-inbox` | PDF intake |

Unknown keys are preserved for domain repositories. `references_dir`,
`tracking_xlsx`, and `static_site_dir` still parse but have no consumer and
must not be used; `init` no longer writes any of them. No config key may
select a schema version or maintain schema history.

## One current schema

`schema_dir/<extraction_schema_file>` is the project's only current LinkML
extraction schema. Resolution loads it with the LinkML Python API and requires
exactly one locally defined class with `tree_root: true`. Validation is
closed-world. The extraction schema imports no project or framework schema
files; the configured file is the complete schema identity. Templates may be
copied into that file as starting material.

Git is the schema and domain-context history. Runs record, but do not copy, the
current schema. Parallel versioned schema files, run-local schema files, and an
`extraction_class` override are not supported history mechanisms.

Schema identity is the SHA-256 digest of the configured schema file's exact
bytes, written as `sha256:<hex>`. The digest alone identifies the schema; a run
records nothing else about it. Content addressing means a schema is found later
by searching for its bytes, in the working tree or in Git history, so identity
works identically inside and outside a repository and no commit pointer can go
stale or lie.

Equal schema hashes define a same-schema rerun; unequal hashes define a schema
upgrade. The refinement workflow requires a committed schema checkpoint before
it can be declared complete — not because runs reference a commit, but because
an uncommitted schema may become unreconstructable once edited. `doctor` and
`status` surface an uncommitted current schema; runs do not carry that warning.

## CLI conventions

- Exit 0: success; 1: operation or validation failure; 2: usage or
  configuration error; 130: interrupted and resumable.
- Project-scoped verbs honor `--config/-c` and `LITSCHEMA_CONFIG`.
- Verbs call shared Python APIs in process rather than shelling out to sibling
  commands.
- Missing explicit file targets fail. A no-argument validation command may
  discover all configured outputs.

| verb | normative owner |
|---|---|
| `init`, `skills install` | `specs/onboarding` |
| `assemble`, `prepare-text`, `runs *` | `specs/article-store` |
| `validate`, `agent *` | `specs/extraction` |
| `meta *` | `specs/source-metadata` |
| `verify` | `specs/verifier` |
| `export`, `mcp` | `specs/explore` |

`status` reports schema presence plus inbox, article, prepared-text,
published-run, active-run, and current-schema-active counts, flags broken
active pointers, and exits 0. `doctor` checks Python and `uv`, schema resolution,
project-local then global litschema skills, and an agent CLI. It exits 1 with
remedies when a check fails. Neither command changes run selection.

## Invariants

- Relative paths are config-relative.
- Exactly one local `tree_root: true` class identifies the extraction root.
- One configured schema file is current; Git is its only history.
- Schema hashing is deterministic and independent of the working directory.
- Same-schema and schema-upgrade reruns follow hash equality, not filenames or
  timestamps.
- Usage errors are concise exit-2 failures, not tracebacks.

## Test obligations

Implementation coverage must pin:

- discovery precedence and config-relative paths;
- zero, one, and multiple local tree roots;
- closed-world validation and missing explicit-target failure;
- deterministic byte hashing independent of the working directory, and
  identity resolution inside a repository, outside one, and after the schema
  file is renamed;
- rejection of schema imports, parallel schema-history configuration, and
  run-local schemas;
- hash-based same-schema versus upgrade classification;
- common exit codes and project-scoped config flags;
- status counts across missing, active, and current-schema-active runs, and
  broken-pointer flagging;
- doctor failures for schema and skill resolution.

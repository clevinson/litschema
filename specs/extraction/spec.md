# Capability: extraction

The agent-mediated pipeline that turns a prepared document into schema-valid
structured data with cited evidence: runtime schema context, the two output
files, validation, and provenance recording. Extraction is deliberately
performed by an agent following the bundled `extract-article` skill — the
framework supplies deterministic tooling on both sides of the LLM step.
Documented as-built from the 2026-07-07 audit.

## Runtime schema context

`litschema agent prepare-schema-context` writes to
`<project_root>/.litschema/runtime/`:

- `extraction_schema.json` — JSON Schema generated in-process (LinkML
  `JsonSchemaGenerator`, no subprocess) from the project's extraction schema,
  top class = the unique locally-defined `tree_root: true` class
  (`specs/project-config/spec.md` § Schema resolution).
- `reasoning_schema.json` — generated from the BUNDLED
  `litschema/agent/reasoning.yaml` (root `ExtractionReasoning`); projects do
  not define reasoning schemas.

Both writes are atomic (same-directory tmp + replace). Agents read these
files instead of parsing LinkML.

## Output 1: `agent-extraction.json`

What the document SAYS, conforming to the project's extraction schema.

- Validation is **closed-world**: unknown properties are errors, so the
  extraction can never drift ahead of the schema silently.
- **Missing values are omitted keys** — never `null`, never empty arrays.
- **Error marker**: when a document cannot be extracted (missing/empty
  markdown), the agent writes `{"article_id": "<id>", "error": true,
  "reason": "..."}` instead. Every consumer treats a truthy `error` as
  "no extraction": validation skips it as valid, the verifier lists the
  article as unextracted, the explore store excludes it, and re-runs of the
  onboarding batch retry it.
- Bibliography is NOT extracted here — that is source-metadata backfill
  (`specs/source-metadata/spec.md` § Agent contract, registry-first).

## Output 2: `agent-reasoning.json`

WHY each value was extracted, with line-cited evidence. Validated against the
bundled schema (closed-world). Shape (`ExtractionReasoning`):

- `confidence` (optional, float 0.0–1.0) — overall extraction confidence;
  surfaced by the verifier as the article's confidence chip and queue filter
  field. Confidence lives ONLY here, never in the extraction.
- `confidence_reasoning` (optional) — one line on why.
- `fields` (required) — list of `ReasoningField`:
  - `path` (required) — jq-style with leading dot (`.experiments[0].ph`).
  - `source_lines` (required) — comma-separated markdown line refs,
    `L{n}` or `L{start}-L{end}` (convention, not schema-enforced).
  - `value` (optional) — the extracted value as text, for cross-reference.
  - `reasoning` (optional) — omitted when the cited lines speak for
    themselves.
  - `confidence` (optional, 0.0–1.0) — per-field, to flag weak support.

The one-entry-per-extracted-leaf rule is a skill-level promise, not
schema-enforced.

## Validation

- `litschema validate [target]` — no target validates every extraction in
  the store; a file or directory argument narrows it. Exit 0 iff everything
  is valid (error markers count as valid); exit 1 otherwise, with per-file
  error lists.
- `litschema agent validate-reasoning <file>` — validates one reasoning file
  against the bundled schema; needs no project. Exit 0 valid; exit 1
  usage/missing/invalid (first 10 errors printed).
- One LinkML validator instance is reused across files (startup cost paid
  once per run).

## Provenance: `litschema agent record-extraction <id>`

After both validations pass, the agent records extraction provenance into
the manifest's identity-layer `extraction` key:

| sub-key | value |
|---|---|
| `date` | command time, ISO-8601 UTC (always) |
| `provider` / `model` | only when `--provider` / `--model` are passed — never invented |
| `schema_commit` | `git rev-parse --short HEAD` in the project root (omitted when unavailable) |

Re-recording replaces the whole `extraction` dict (manifest merges are
shallow).

## The agent contract (bundled `extract-article` skill)

Setup gate (project check, CLI resolution — a `.litschema/cli` dev override
requires showing the user its content and confirmation before execution) →
`agent prepare-schema-context` → read runtime schemas → `prepare-text <id>`
→ extract from the markdown ONLY (never memory or other papers) → write
both outputs → loop `validate` + `agent validate-reasoning` until both exit
0 (max 3 attempts) → `agent record-extraction` → registry-first
bibliographic backfill (`specs/source-metadata/spec.md`).

## Invariants

- **Closed-world extractions.** WHEN an extraction carries a property the
  schema does not define, THEN validation fails.
  (`test_configured_schema_cli.py`)
- **Error markers are terminal-but-retryable.** WHEN `agent-extraction.json`
  has a truthy `error`, THEN validation passes it, the verifier and explore
  store treat the article as unextracted, and batch onboarding retries it.
- **Confidence lives in reasoning.** WHEN a project schema does not define
  confidence fields, THEN the extraction never carries them; the verifier
  reads confidence from `agent-reasoning.json` only.
- **Provenance is honest.** WHEN provider/model are not passed, THEN they
  are absent — `record-extraction` never invents them.
  (`test_assemble.py`)
- **Runtime context is atomic and in-process.** WHEN schema context is
  generated, THEN no subprocess runs and no torn JSON can be observed.
  (`test_agent_schema_context.py`)

## Code map

`src/litschema/agent/` (schema context, reasoning schema + validation) ·
`src/litschema/ingest/validate_extraction.py` (extraction validation) ·
`src/litschema/articles.py` (`record_extraction_provenance`) ·
`skills/extract-article/SKILL.md` (the agent-facing contract) ·
`src/litschema/cli.py` (verbs). Tests: `test_agent_schema_context.py`,
`test_configured_schema_cli.py`, `test_assemble.py`, `test_smoke.py`
(skill-contract pins).

# Capability: extraction

Status: partially current.

The agent-mediated pipeline turns prepared text into a complete immutable run:
schema-valid structured data, line-cited reasoning, and honest run provenance.
The framework supplies deterministic tools around the LLM step; the bundled
`extract-article` skill conducts it.

## Implementation status

Live today: `agent prepare-schema-context`, `agent validate-reasoning`, `agent
record-extraction`, `litschema validate`, the extraction and reasoning content
contracts, and the bundled `extract-article` skill that conducts the LLM step.

Pending: run publication. `record-extraction` records provenance into
`article-metadata.json`; there is no staged-then-published run directory and no
`run.json`, so the Run outputs framing below describes the target. Tracked by
`tdv3`.

`litschema extract` remains a deliberate stub that directs users to the bundled
skill — extraction requires an agent CLI, not a provider API key. Making it a
provider-native orchestrator is tracked separately by `e48h` and is explicitly
out of scope for v0.1.0.

## Runtime schema context

`litschema agent prepare-schema-context` writes atomic runtime artifacts under
`.litschema/runtime/`:

- `extraction_schema.json`, generated in process from the one current project
  schema and its unique local `tree_root: true` class;
- `reasoning_schema.json`, generated from the bundled reasoning schema.

Agents read these generated files rather than interpreting LinkML directly.

## Run outputs

A staged run contains `agent-extraction.json`, `agent-reasoning.json`, and
`run.json`. Publication and immutability are defined by the article-store spec.

### Extraction

`agent-extraction.json` records what the document says and conforms to the
current project schema.

- Validation is closed-world; unknown properties fail.
- Missing values are omitted, never represented by `null` or empty arrays.
- Bibliographic metadata is not extraction data.
- An unextractable document may contain
  `{"article_id":"<id>","error":true,"reason":"..."}`. The attempt may be
  retained as an inactive run for diagnosis, but it cannot be active and batch
  workflows retry the article.

### Reasoning

`agent-reasoning.json` records why values were extracted. It contains optional
overall `confidence` in 0.0–1.0, optional `confidence_reasoning`, and required
`fields`. Each field entry has canonical `path` and `source_lines`; it may carry
value text, concise reasoning, and 0.0–1.0 field confidence. Paths use bracket
indices and no leading dot, for example `experiments[0].ph`. Source lines use
`L<n>` or `L<start>-L<end>` ranges.

Confidence belongs only in reasoning. The project extraction schema does not
gain framework confidence fields.

## Validation

- `litschema validate [target]` validates extraction files. With no target it
  discovers every live run in the configured store; trash is excluded. A file
  or directory narrows the scope. It exits 0 only when every selected artifact
  is valid and exits 1 with per-file errors otherwise.
- `litschema agent validate-reasoning <file>` validates one reasoning artifact
  against the bundled schema without requiring a project. It exits 0 when valid
  and 1 for missing or invalid input, with bounded error output.
- A missing explicit target fails. Error markers are valid diagnostic
  artifacts, but they are not activatable extractions.
- Validator instances are reused within a command. Writes remain atomic and
  LinkML operations run in process.

## Run provenance and publication

After both artifacts validate, the deterministic publisher records the metadata
required by `specs/article-store/spec.md`: article and run IDs, timestamp,
schema hash and Git state, provider, model, settings, and lineage. Unknown
provider/model values remain null; callers never invent them.

`litschema agent record-extraction <article-id> --run-id <run-id>` finalizes a
staged attempt and publishes the directory atomically. It does not write
extraction provenance into `article-metadata.json`. Initial onboarding may
activate the first successful run. A same-schema rerun remains inactive until
the caller selects it. Refinement owns schema-upgrade activation.

## Agent contract

The bundled `extract-article` skill performs:

setup gate and CLI resolution (a `.litschema/dev-cli` override is shown to the
user and requires confirmation) → schema-context generation → prepared-text
check → extraction from that article's markdown only → write both staged
artifacts → validate both, with bounded repair attempts → record provenance and
publish → source-metadata enrichment through its own CLI.

The skill receives explicit lineage intent: `initial`, `same_schema`, or
`schema_upgrade`. It never overwrites a run, changes `active-run.json`
implicitly for a rerun, edits source metadata files directly, or imports facts
from another article.

## Invariants

- Unknown extraction properties fail closed-world validation.
- Published extraction, reasoning, and run metadata are immutable.
- Missing explicit targets fail.
- Error attempts stay inactive and retryable.
- Reasoning and reviews use one canonical path dialect.
- Confidence lives only in reasoning.
- Provenance records known values and explicit nulls without invention.
- Publication exposes either a complete run or no run.

## Test obligations

Implementation coverage must pin:

- in-process atomic runtime schema generation and unique-root selection;
- closed-world extraction validation, omitted missing values, and error-marker
  handling;
- no-argument live-run discovery, trash exclusion, and missing explicit-target
  failure;
- reasoning schema validation, confidence bounds, canonical paths, and
  extracted-leaf coverage;
- staged validation before publication and absence of partial runs;
- immutable published artifacts;
- honest provider/model/settings and schema provenance recording;
- initial, same-schema, and schema-upgrade lineage;
- no manifest provenance write and no implicit rerun activation;
- bounded skill repair, article-only evidence, deterministic CLI calls, and
  registry-first metadata backfill.

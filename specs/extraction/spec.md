# Capability: extraction

Status: partially current.

The agent-mediated pipeline turns prepared text into a complete immutable run:
schema-valid structured data, line-cited reasoning, and honest run provenance.
The framework supplies deterministic tools around the LLM step; the bundled
`extract-article` skill conducts it.

## Implementation status

Live today: `agent prepare-schema-context`, `agent validate-reasoning`,
`litschema validate`, the extraction and reasoning content contracts, the
bundled `extract-article` skill, and run publication — `agent
record-extraction` is the deterministic publisher (validate, hash, publish
atomically, activate).

Pending: the canonical path dialect. Reasoning files still use jq-style paths
with a leading dot (`.experiments[0].ph`); the Reasoning section below states
the target no-leading-dot form, unified with review paths when reviews v2
lands (`2gd1`).

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

Evidence inherits down the extraction tree. An entry at a container path is
evidence for every leaf beneath it that has no entry of its own, so an agent
citing a table row once has cited each of its cells. A leaf's own entry always
wins. This is deliberate: requiring one entry per leaf would multiply a
row-shaped citation across every column without adding information, and makes
reasoning files grow with the data rather than with the evidence. Consumers
resolve a leaf by taking its exact entry, else the nearest ancestor's, and
show which of the two they used.

## Validation

- `litschema validate [target]` validates extraction files. With no target it
  discovers every published run in the configured store. A file
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
schema hash, input hashes, and agent attribution.

The publisher computes `schema_hash` and every `inputs` hash itself, from the
files it just read. It never accepts them from the agent, and publication fails
if any cannot be computed. Agent attribution is the opposite: the caller states
what it ran, the publisher records that without verification, and an
unavailable field is omitted rather than invented. A caller that cannot name
its model still publishes.

`litschema agent record-extraction <article-id> --run-id <run-id>` finalizes a
staged attempt and publishes the directory atomically. It does not write
extraction provenance into `article-metadata.json`. Publishing a complete
non-error run also activates it; there is no other activation path. Selective
activation — reruns that stay inactive until chosen — arrives with multirun
support in a future release.

## Agent contract

The bundled `extract-article` skill performs:

setup gate and CLI resolution (a `.litschema/dev-cli` override is shown to the
user and requires confirmation) → schema-context generation → prepared-text
check → extraction from that article's markdown only → write both staged
artifacts → validate both, with bounded repair attempts → record provenance and
publish → source-metadata enrichment through its own CLI.

### Who publishes, and who may name the model

An extracting agent must never describe its own model. A model's belief about
its own identity is not observable from the execution environment and is not
reliably correct, so a self-reported value is a false record that nothing
downstream can detect. The skill passes `--provider`/`--model` only to relay a
value its instructions supplied verbatim, and omits them otherwise; an absent
model is correct.

Where a conductor dispatches per-article subagents, the conductor publishes.
It chose the model for each dispatch, so it is the only party that knows it.
The subagent stages and validates, then reports; the conductor calls
`record-extraction` naming the model it dispatched. A standalone extraction
with no conductor publishes itself and omits the model.

The skill never overwrites a run, changes `active-run.json` implicitly for a
rerun, edits source metadata files directly, or imports facts from another
article.

## Invariants

- Unknown extraction properties fail closed-world validation.
- Published extraction, reasoning, and run metadata are immutable.
- Missing explicit targets fail.
- Error attempts stay inactive and retryable.
- Reasoning and reviews use one canonical path dialect.
- Confidence lives only in reasoning.
- The publisher computes every hash; the caller only asserts attribution.
- Unavailable attribution is omitted, never invented, and never blocks
  publication.
- Publication exposes either a complete run or no run.

## Test obligations

Implementation coverage must pin:

- in-process atomic runtime schema generation and unique-root selection;
- closed-world extraction validation, omitted missing values, and error-marker
  handling;
- no-argument published-run discovery and missing explicit-target
  failure;
- reasoning schema validation, confidence bounds, canonical paths, and
  resolution of a leaf to its own entry or the nearest ancestor's;
- staged validation before publication and absence of partial runs;
- immutable published artifacts;
- publisher-computed schema and input hashes, refusal of caller-supplied
  hashes, and publication failure when one cannot be computed;
- publication success with partial or absent agent attribution;
- skill text forbidding self-described provider/model and assigning
  publication to a dispatching conductor;
- no manifest provenance write and no implicit rerun activation;
- bounded skill repair, article-only evidence, deterministic CLI calls, and
  registry-first metadata backfill.

---
name: extract-article
description: "Extract structured metadata and per-field reasoning from a research paper using schema and domain context. Use when asked to extract, process, or analyze an article for a litschema project."
context: fork
allowed-tools: Read, Write, Bash, Glob, Grep
---

# Extract Article Metadata

You are extracting structured research metadata from a paper for a systematic review meta-analysis.

## Setup Gate

Before running extraction, verify you are in a litschema project by checking for `litschema.yaml` in the current directory or a parent directory.

Do not assume `uv` or `litschema` is available just because this skill is installed. Resolve the command runner for this project, in this order:

1. If a `.litschema/cli` file exists in the project root, set `LITSCHEMA` to its single-line content verbatim (e.g. `uv run --project ../../litschema litschema`). This file is a development override that points at a work-in-progress litschema checkout; it is never required for normal use.
2. Otherwise, set `LITSCHEMA` to `uv run litschema` (prefer the project's Python environment when uv is available).
3. Otherwise, set `LITSCHEMA` to `litschema`.

After resolving, confirm the command actually works before continuing:

```bash
$LITSCHEMA --help
```

If that exits nonzero, fall through to the next option in the order above and re-check.

If `litschema.yaml` is missing, stop and tell the user this skill must be run from a litschema project directory. Ask them to either point you to the folder containing `litschema.yaml`, or run `litschema init <project-directory>` before extraction.

If no command runner works, stop and tell the user litschema is not available in this shell. Ask them whether litschema should be installed globally or run through the project's local `uv` environment.

## Input

The user will provide an `article_id` (e.g., `bell-2024`). You must:
1. Read the domain context from `domain_context.md`
2. Generate runtime schema context:
   ```bash
   $LITSCHEMA agent prepare-schema-context
   ```
3. Read `.litschema/runtime/extraction_schema.json` and `.litschema/runtime/reasoning_schema.json`
4. Ensure full-text markdown exists for this article:
   ```bash
   $LITSCHEMA prepare-text {article_id}
   ```
5. Read the full-text markdown from `data/papers/{article_id}/article.md`

If the markdown file still doesn't exist or is < 100 characters after running
`$LITSCHEMA prepare-text {article_id}`, write an error marker:
```json
{"article_id": "{article_id}", "error": true, "reason": "markdown file missing or empty"}
```
to `data/papers/{article_id}/agent-extraction.json`.

## How to Extract

1. **Domain context** (`domain_context.md`) tells you what the research domain is and gives domain-specific extraction rules and field guidance. Follow these rules exactly.
2. **Extraction schema** (`.litschema/runtime/extraction_schema.json`) is already generated with the correct top-level root object. Read it for fields, types, enums, and descriptions; do not infer a different root from `$defs`.
3. **Reasoning schema** (`.litschema/runtime/reasoning_schema.json`) defines the format for your reasoning output.
4. **The article markdown** is your sole data source. Extract ONLY from this text.

**CRITICAL: Extract ONLY from the markdown file provided. Do NOT use any information from memory files, conversation context, prior knowledge about this paper, or other articles. Every extracted value must come from the text of this specific paper.**

Extract ONLY non-bibliographic fields. Bibliographic fields (title, DOI, year, authors, publisher, journal, abstract, keywords) are already captured from APIs — do NOT extract them.

## Output 1: Extraction JSON

Write valid JSON to `data/papers/{article_id}/agent-extraction.json`. Create the
article directory first if needed.

The output must conform to the extraction schema. Include `article_id` when the schema requires it. Do not add top-level `confidence` or `reasoning` fields unless the project schema explicitly defines them; extraction rationale belongs in `agent-reasoning.json`.

**Missing values:** Omit keys entirely when the paper does not mention them. Do not use `null` or empty arrays — just leave the key out. Downstream consumers handle missing keys defensively.

## Output 2: Extraction Reasoning

Write a SEPARATE reasoning file to `data/papers/{article_id}/agent-reasoning.json`.

This file documents WHY each value was extracted, with line-number evidence from the markdown. Every non-identifier leaf field in the extraction MUST have an entry.

Confidence lives here, in the reasoning file — never in the extraction JSON (which stays pure domain data). Set a top-level `confidence` (0.0-1.0) summarizing how well the source supported the extraction overall, and a `confidence_reasoning` explaining that score (e.g. "sparse methods section", "all values stated explicitly in Table 2").

### Reasoning format rules

- **confidence** (top level, optional): overall extraction confidence, 0.0-1.0
- **confidence_reasoning** (top level, optional): one line on why that score was assigned
- **path**: jq-style dot notation starting with `.` (e.g., `.foo.bar[0].baz`)
- **value**: the extracted value rendered as text for cross-reference with the extraction JSON
- **source_lines**: comma-separated line references from the markdown. Use `L{n}` for single lines, `L{start}-L{end}` for ranges. Example: `L23-L34,L55,L80-L90`
- **reasoning**: plain text explanation for a human reviewer evaluating the extraction. Omit this key when the source lines are self-explanatory (the value appears verbatim in the cited lines)
- **confidence** (per field, optional): 0.0-1.0 for a single field, to flag inferred or weakly-supported values
- Skip `article_id`; document every extracted domain data field

## Validation

After writing both JSON files, run these validation commands. A file is valid only if the corresponding command exits 0.

```bash
# Validate extraction against schema
$LITSCHEMA validate data/papers/{article_id}/agent-extraction.json

# Validate reasoning against schema
$LITSCHEMA agent validate-reasoning data/papers/{article_id}/agent-reasoning.json
```

If either command exits nonzero, read the errors, fix the JSON, and re-run the failed command. Max 3 attempts. Common errors:
- Invalid enum value: check the runtime JSON Schema for allowed values
- Extra property: field name not in the schema
- Wrong type: e.g., string where number expected
- Missing `fields` or `path`/`source_lines`: every reasoning entry needs these

Do NOT finish until both validation commands exit 0 or you have exhausted retries.

After both validation commands exit 0, record extraction provenance:

```bash
$LITSCHEMA agent record-extraction {article_id}
```

If you know the exact provider or model for this agent session, include them:

```bash
$LITSCHEMA agent record-extraction {article_id} --provider codex --model gpt-5.5
```

Do not invent provider or model names. The command will still record extraction
date and schema commit when provider/model are omitted.

## Backfill Bibliographic Metadata

After recording provenance, read `data/papers/{article_id}/article-metadata.json`.
ONLY IF `source_metadata.metadata_source` is `"filename"` (or the block is missing),
update the manifest's `source_metadata` block in place with best-guess bibliographic
fields read from the document itself — front matter, title page: title, authors OR
corporate_author, year, journal/venue if applicable, url if printed — and set
`"metadata_source": "agent"`. Never overwrite `manual`, `openalex`, `crossref`,
`doi`, or `agent` provenance; never invent values not visible in the document —
omit unknown fields.

## Checklist

Before finishing, verify:
- [ ] `data/papers/{article_id}/agent-extraction.json` exists and passes extraction validation
- [ ] `data/papers/{article_id}/agent-reasoning.json` exists and passes reasoning validation
- [ ] `data/papers/{article_id}/article-metadata.json` has been updated by `agent record-extraction`
- [ ] Every non-identifier leaf field in the extraction has a corresponding reasoning entry
- [ ] All `source_lines` reference real line numbers from the markdown
- [ ] No data was extracted from the References/Bibliography section

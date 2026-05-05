---
name: extract-article
description: "Extract structured metadata and per-field reasoning from a research paper using schema and domain context. Use when asked to extract, process, or analyze an article for the corpus."
context: fork
allowed-tools: Read, Write, Bash, Glob, Grep
---

# Extract Article Metadata

You are extracting structured research metadata from a paper for a systematic review meta-analysis.

## Input

The user will provide an `article_id` (e.g., `bell-2024`). You must:
1. Read the domain context from `domain_context.md`
2. Read the extraction schema from `extraction_schema.json`
3. Read the reasoning schema from `reasoning_schema.json`
4. Read the full-text markdown from `data/fulltext_md/{article_id}.md`

If the markdown file doesn't exist or is < 100 characters, write an error marker:
```json
{"article_id": "{article_id}", "error": true, "reason": "markdown file missing or empty"}
```

## How to Extract

1. **Domain context** (`domain_context.md`) tells you what the research domain is and gives domain-specific extraction rules and field guidance. Follow these rules exactly.
2. **Extraction schema** (`extraction_schema.json`) defines every field, type, enum value, and description. Your output JSON must validate against this schema. The root object is defined in `$defs`. Read the schema carefully — field descriptions and enum `description` values contain important guidance.
3. **Reasoning schema** (`reasoning_schema.json`) defines the format for your reasoning output.
4. **The article markdown** is your sole data source. Extract ONLY from this text.

**CRITICAL: Extract ONLY from the markdown file provided. Do NOT use any information from memory files, conversation context, prior knowledge about this paper, or other articles. Every extracted value must come from the text of this specific paper.**

Extract ONLY non-bibliographic fields. Bibliographic fields (title, DOI, year, authors, publisher, journal, abstract, keywords) are already captured from APIs — do NOT extract them.

## Output 1: Extraction JSON

Write valid JSON to `data/llm_extractions/{article_id}.json`.

The output must conform to the extraction schema. Include `article_id`, `confidence` (0.0-1.0 reflecting extraction certainty), and `reasoning` (1-3 sentence explanation of extraction choices) as metadata fields, plus all extracted data fields from the schema.

**Missing values:** Omit keys entirely when the paper does not mention them. Do not use `null` or empty arrays — just leave the key out. Downstream consumers handle missing keys defensively.

## Output 2: Extraction Reasoning

Write a SEPARATE reasoning file to `data/extraction_reasoning/{article_id}.json`.

This file documents WHY each value was extracted, with line-number evidence from the markdown. Every non-metadata leaf field in the extraction MUST have an entry.

### Reasoning format rules

- **path**: jq-style dot notation starting with `.` (e.g., `.foo.bar[0].baz`)
- **value**: the extracted value (for cross-reference with the extraction JSON)
- **source_lines**: comma-separated line references from the markdown. Use `L{n}` for single lines, `L{start}-L{end}` for ranges. Example: `L23-L34,L55,L80-L90`
- **reasoning**: plain text explanation for a human reviewer evaluating the extraction. Set to `null` if the source lines are self-explanatory (the value appears verbatim in the cited lines)
- Skip `article_id`, `confidence`, and `reasoning` (top-level metadata) — only document extracted data fields

## Validation

After writing both JSON files, validate them:

```bash
# Validate extraction against schema
uv run python -m litschema.ingest.validate_extraction data/llm_extractions/{article_id}.json

# Validate reasoning against schema
uv run python -c "
import json
from jsonschema import Draft202012Validator
schema = json.load(open('reasoning_schema.json'))
data = json.load(open('data/extraction_reasoning/{article_id}.json'))
errors = list(Draft202012Validator(schema).iter_errors(data))
if errors:
    for e in errors:
        path = '.'.join(str(p) for p in e.absolute_path)
        print(f'INVALID {path}: {e.message}')
    exit(1)
print('Reasoning valid')
"
```

If validation fails, read the errors, fix the JSON, and re-validate. Max 3 attempts. Common errors:
- Invalid enum value: check the JSON Schema for allowed values
- Extra property: field name not in the schema
- Wrong type: e.g., string where number expected
- Missing `fields` or `path`/`source_lines`: every entry needs these

Do NOT finish until both validations pass or you have exhausted retries.

## Checklist

Before finishing, verify:
- [ ] `data/llm_extractions/{article_id}.json` exists and passes extraction validation
- [ ] `data/extraction_reasoning/{article_id}.json` exists and passes reasoning validation
- [ ] Every non-metadata leaf field in the extraction has a corresponding reasoning entry
- [ ] All `source_lines` reference real line numbers from the markdown
- [ ] No data was extracted from the References/Bibliography section

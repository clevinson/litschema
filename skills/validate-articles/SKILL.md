---
name: validate-articles
description: "Validate ERW article metadata, extractions, and reasoning against project schemas. Run after extraction to catch errors."
---

# Validate Article Store

Run validation across the ERW pipeline outputs and report issues.

## Setup Gate

Before validating, verify you are in a litschema project by checking for `litschema.yaml` in the current directory or a parent directory.

Do not assume `uv` or `litschema` is available just because this skill is installed. Choose the command runner for this project:

```bash
# Prefer project-local installs when uv is available
uv run litschema --help
```

If that exits 0, set `LITSCHEMA` to `uv run litschema` and `PYTHON` to `uv run python` for every command below. Otherwise try:

```bash
litschema --help
```

If that exits 0, set `LITSCHEMA` to `litschema` and `PYTHON` to `python3`.

If `litschema.yaml` is missing, stop and tell the user this skill must be run from a litschema project directory. Ask them to either point you to the folder containing `litschema.yaml`, or start the project onboarding/builder skill. The builder flow should run `litschema init` if needed, then ask for a file containing DOIs, PDFs, or bibliography records to initialize the article set.

If neither command runner works, stop and tell the user litschema is not available in this shell. Ask them whether litschema should be installed globally or run through the project's local `uv` environment.

## Steps

1. **Validate all extractions** against the configured LinkML extraction schema:

```bash
$LITSCHEMA validate data/papers/
```

2. **Validate all reasoning files** against the configured LinkML reasoning schema:

```bash
$LITSCHEMA agent validate-reasoning data/papers/
```

3. **Validate article metadata files** exist and are parseable:

```bash
$PYTHON -c "
import json
from pathlib import Path

valid = missing = invalid = 0
for paper_dir in sorted(Path('data/papers').iterdir()):
    if not paper_dir.is_dir():
        continue
    path = paper_dir / 'article-metadata.json'
    if not path.exists():
        missing += 1
        print(f'MISSING: {path}')
        continue
    try:
        data = json.loads(path.read_text())
    except Exception as e:
        invalid += 1
        print(f'INVALID: {path}: {e}')
        continue
    if not data.get('id'):
        invalid += 1
        print(f'INVALID: {path}: missing id')
    else:
        valid += 1
print(f'\nMetadata: {valid} valid, {missing} missing, {invalid} invalid')
"
```

4. **Report summary** of all validation results. If any step fails, list the specific files and errors.

5. **Check reasoning coverage** — for articles with reasoning files, report what percentage of extraction fields have corresponding reasoning entries:

```bash
$PYTHON -c "
import json
from pathlib import Path

paper_dir = Path('data/papers')
legacy_ext_dir = Path('data/llm_extractions')
legacy_reason_dir = Path('data/extraction_reasoning')

def count_leaves(obj, path=''):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from count_leaves(v, f'{path}.{k}' if path else k)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            yield from count_leaves(item, f'{path}[{i}]')
    else:
        if path not in ('article_id', 'confidence', 'reasoning'):
            yield path

reason_paths = sorted(paper_dir.glob('*/agent-reasoning.json'))
if not reason_paths:
    reason_paths = sorted(legacy_reason_dir.glob('*.json'))

for rf in reason_paths:
    aid = rf.parent.name if rf.name == 'agent-reasoning.json' else rf.stem
    ext_path = paper_dir / aid / 'agent-extraction.json'
    if not ext_path.exists():
        ext_path = legacy_ext_dir / f'{aid}.json'
    ext = json.loads(ext_path.read_text())
    reason = json.loads(rf.read_text())
    rpaths = set()
    for f in reason.get('fields', []):
        p = f['path']
        if p.startswith('.'): p = p[1:]
        rpaths.add(p)
    leaves = list(count_leaves(ext))
    covered = sum(1 for l in leaves if l in rpaths)
    pct = round(100 * covered / len(leaves)) if leaves else 0
    flag = ' <<<' if pct < 80 else ''
    print(f'{aid:40s} {covered:3d}/{len(leaves):3d} ({pct}%){flag}')
"
```

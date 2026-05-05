# litschema

Schema-driven extraction and verification for scientific literature.

`litschema` is a local-first toolkit for turning papers into structured,
schema-valid JSON with source-linked reasoning and human review. It is built
around LinkML schemas, agent-readable extraction skills, a verification webapp,
and a DuckDB/MCP exploration layer.

This repository is an early public scaffold. The current focus is a small
open-access agriculture demo:

```bash
litschema convert
# then in an agent CLI:
# /extract-article <article-id-or-doi>
litschema verify
litschema mcp
```

The framework is still being separated from the ERW reference project. Expect
file layout and command details to evolve while the public demo stabilizes.

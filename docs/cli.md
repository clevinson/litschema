# CLI

```text
litschema init <dir>               scaffold a project; installs agent skills locally
litschema doctor                   check config, schema, and skill installation
litschema status                   counts: inbox, articles, runs, reviews
litschema assemble                 papers-inbox PDFs -> per-article folders (offline)
litschema prepare-text <id>|--all  PDF -> article.md and figures (offline)
litschema meta show|set|sync <id>  bibliographic metadata, provenance-tagged
litschema validate [target]        validate extractions against the schema
litschema grade <id>|--all         score each value against its cited lines
litschema runs list|activate       list published runs; choose the active one
litschema verify [--port 8000]     local review app (loopback only)
litschema export [-f jsonl|csv]    values with corrections, plus an audit file
litschema mcp                      DuckDB store served over MCP (experimental)
litschema skills install           install the agent skills
litschema agent ...                deterministic steps the extraction skill calls
```

Run `litschema <command> --help` for the options.

Extraction runs as an agent skill (`extract-article`), and litschema
validates and publishes what the agent writes. A headless `litschema extract`
is planned.

## Exit codes

`0` success, `1` failure, `2` usage error, `3` the project's
`litschema_version` pin doesn't match the installed version.

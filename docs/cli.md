# CLI

```text
litschema init <dir>               scaffold a project and install its skills
litschema doctor                   check config, schema, and skill installation
litschema status                   counts: inbox, articles, runs, reviews
litschema assemble                 inbox PDFs into article folders (offline)
litschema prepare-text <id>|--all  PDF -> article.md and figures (offline)
litschema meta show|set|sync <id>  bibliographic metadata, provenance-tagged
litschema validate [target]        validate extractions against the schema
litschema grade <id>|--all         score each value against its cited lines
litschema runs list|activate       list published runs; choose the active one
litschema verify [--port 8000]     local review app (loopback only)
litschema export [-f jsonl|csv]    values with corrections, plus an audit file;
                                   refuses stale runs unless --allow-stale
litschema mcp                      DuckDB store served over MCP (experimental)
litschema skills install           install the agent skills
litschema agent ...                steps the extraction skill calls
```

Run `litschema <command> --help` for the options.

Extraction runs as the `extract-article` skill in Claude Code or Codex;
litschema validates and publishes what the skill writes. A headless
`litschema extract` is planned.

## Coding agents

`init` and `skills install --project` set up each coding agent whose config
folder exists: `~/.claude` (or `$CLAUDE_CONFIG_DIR`) for Claude Code, and
`~/.codex` (or `$CODEX_HOME`) or `~/.agents` for Codex. If neither exists, they
stop and ask for `--agent`. Pass `--agent claude-code`, `--agent codex` or
`--agent all` to choose.

Skills go where each agent looks: `.claude/skills/` for Claude Code,
`.agents/skills/` for Codex. For Codex, `init` also writes `.codex/config.toml`
allowing network access, so DOI lookups work inside Codex. `init` pins the
project to the installed litschema version; see Upgrading in the README.

## Exit codes

`0` success, `1` failure, `2` usage error, `3` the project's
`litschema_version` pin doesn't match the installed version.

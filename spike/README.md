# Spike: PDF rendering with source highlights

Exploratory only — nothing here is wired into the app. Measures whether
`source_lines` from agent-reasoning.json can be located in the PDF well enough
to overlay highlights. See kata `b85y`.

Run: `uv run python spike/locate_sources.py <project-dir> <article-id>`

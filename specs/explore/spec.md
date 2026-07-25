# Capability: explore and export

Status: partially current.

Export is the stable analysis surface. The experimental DuckDB/MCP projection
remains deliberately frozen. Both consume the article store; neither becomes an
authority for runs, reviews, or schema history.

## Implementation status

Live today: `litschema export --format jsonl|csv [--output PATH]` over the
article-root extractions with review overrides applied, plus the frozen DuckDB
store and the `litschema mcp` server and its three tools.

Pending: the view split. `--view all|audited` and `--audit-output` do not exist,
so there is no audited-data projection and no compact audit sidecar. Record
resolution below is written against per-article active runs, which do not exist
yet either. Tracked by `bmwn`, blocked on `tdv3` and `2gd1`.

## Record resolution

For each article, consumers resolve `active-run.json` and read extraction,
reasoning, metadata, and review from that one run. They never combine artifacts
from different runs. An article with no active run is skipped and counted. A
broken active pointer is an integrity error and fails the operation.

The review overlay is applied before projection under
`specs/reviews/spec.md`. Property and container removal omits the property.
Array-element removal writes a structural JSON `null` tombstone and never
splices the array. A whole-array replace establishes a new effective array and
index basis; otherwise indexes remain those of the raw active-run array. Raw
values remain in the immutable run artifact.

## Export views

`litschema export --view all|audited [--format jsonl|csv] [--output PATH]
[--audit-output PATH]` defaults to `--view all`.

### All-data

All-data contains every active-run extraction value after applying the review
overlay. Unreviewed values remain present. An element-level remove therefore
appears as `null` at its original index; a property remove is absent. Because
structural tombstones may violate the extraction schema's non-null contract,
all-data is an analysis projection rather than a replacement run artifact.

### Audited-data

Audited-data contains only effectively verified or overridden leaves. Ancestor
verification includes descendants; a terminal container override contributes
its complete effective replacement or removal. Necessary containers are
reconstructed.

Arrays use the same effective index basis as all-data. They retain their full
basis length: an unaudited element and a reviewed element removal both appear as
structural `null`. The compact audit sidecar distinguishes those cases. A partly
audited object item contains its audited descendants plus structural identity
slots.

The root `identifier: true` slot and the identifier slot of each included
class-valued array item are retained using their effective post-replace values.
The review contract rejects identifier removal, so export never reconstructs a
missing identity. Retained identifiers, ancestors, and null placeholders do not
become reviewed state. Audited output is not a schema-valid replacement
extraction.
Articles with neither an audited value nor an explicit remove decision are
omitted and counted. A remove-only article retains its root identifier in data
output and its remove decision in audit output.

## Compact audit output

`--audit-output PATH` writes JSONL independently of the data format. Each article included by the selected view has one compact record. Audited
remove-only articles are included:

```json
{
  "article_id": "beerling-2024",
  "run_id": "01J2Q4Y7Y9K0M3T6W8X1Z5A9BC",
  "schema_sha256": "sha256:…",
  "fields": {
    "experiments[0]": {},
    "experiments[0].ph": {
      "override": {"op": "replace", "value": 6.5}
    }
  }
}
```

`fields` is the canonical stored review frontier from
`specs/reviews/spec.md`. Export never expands parent coverage into redundant
descendant entries. Data output also never embeds per-leaf audit flags. The
run ID and schema hash make the sidecar reproducible against the local store and
Git history.

JSONL data records retain schema-root shape and sorted keys. CSV uses
schema-derived scalar columns and JSON strings for multivalued or class-valued
slots. A nested or multivalued audited value preserves placeholder positions as
literal JSON `null` inside that string, such as `[null,{"id":"b"}]`. An empty CSV cell means the top-level slot is absent; it never represents an
array placeholder. User replace values cannot be null, so a present top-level
scalar null cannot occur. Structural null is valid only inside serialized
arrays. The audit sidecar distinguishes unaudited absence from reviewed
removal. Repeated export against unchanged active selections and reviews is
byte-deterministic.

## DuckDB and MCP

`.litschema/explore.duckdb` is derived and disposable. The `articles` table
uses the all-data view: one active run per article, identifier backfilled,
schema scalar slots typed, and nested slots stored as JSON. Review provenance
is not added to DuckDB while the experimental freeze remains; audited analysis
uses export.

`litschema mcp [--rebuild] [--db-path PATH] [--transport stdio|http]
[--port 8765] [--max-rows 200]` builds or reuses the store, then serves:

- `run_sql(query)`, returning bounded TSV and engine errors as data;
- `describe_schema()`, returning tables, columns, counts, and samples;
- `get_linkml_schema()`, returning the current raw schema YAML.

Read-only enforcement belongs at the database connection, not query-text
filtering. Load summaries stay off stdout under stdio so MCP framing remains
valid. Schema-edit cache invalidation remains a separate deferred explore
concern; required schema provenance in `run.json` does not unfreeze it.

## Invariants

- Each record comes from exactly one article's active run.
- Missing active selection is counted; a broken pointer fails loudly.
- All-data applies overrides without dropping unreviewed values.
- Audited-data excludes unreviewed leaves and honors inherited coverage.
- Raw run artifacts remain unchanged and recoverable.
- Audit serialization is the compact canonical frontier, never expanded
  descendant state.
- Export is deterministic.
- DuckDB remains derived, read-only, and non-authoritative.

## Test obligations

Implementation coverage must pin:

- per-article active-run resolution and mixed run IDs across a corpus;
- skip/count behavior for no active run and failure for broken pointers;
- refusal to combine extraction, reasoning, or review from different runs;
- all-data property/container removal, whole-array replacement, element null
  tombstones, and stable non-splicing indexes;
- audited inclusion from exact and parent reviews, terminal container
  overrides, object reconstruction, shared array basis, unaudited-versus-remove
  nulls, and structural identity slots;
- omission of articles with no audited decisions and retention of remove-only
  articles;
- compact audit sidecars with run/schema provenance and no expanded leaves;
- deterministic JSONL and CSV, including literal JSON null placeholders, empty
  top-level cells, identifier replacement and removal refusal, audit-sidecar
  disambiguation, summaries, and repeated exports;
- schema-derived CSV/DuckDB shaping;
- read-only MCP rejection and separation of deferred DuckDB schema staleness
  from required run provenance.

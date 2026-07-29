# Decisions: project-config

Append-only. Newer entries supersede older ones.

## 2026-07-07 — Spec backfilled as-built

**Context:** this capability shipped before the specs/ convention existed;
its behavior was documented only in code, tests, and skill text. A
three-lens audit of the full surface inventoried it.

**Decision:** the spec documents the capability exactly as built at audit
time, including known deviations, which are flagged inline and tracked in
`specs/improvements.md` rather than silently normalized. Future behavior
changes update the spec in the same PR, per `specs/README.md`.


## 2026-07-14 — One current schema, byte identity, Git history

**Context:** first-class runs need deterministic schema identity without adding
a parallel schema-version store.

**Decision:** a project has one configured schema file and one local
`tree_root: true` class. Exact schema bytes define `schema_sha256`; a matching
full Git commit is recorded when available, otherwise the run records dirty
state. Equal hashes are same-schema lineage; unequal hashes are upgrades. Git
is the only schema history.

**Rejected:** `extraction_class` overrides, version-selected config, run-local
schema copies, and imported framework base schemas.


## 2026-07-14 — The configured schema file is the complete closure

**Context:** hashing only the root file cannot reconstruct historical induced
types if imported schema files change independently.

**Decision:** project extraction schemas contain no LinkML imports. The one
configured file is the complete extraction schema and its exact byte hash is
sufficient for run identity and historical reconstruction. Templates are copied
into that file.

**Rejected:** hashing a root file while allowing mutable imports; adding a
second schema-closure manifest.


## 2026-07-26 — doctor warns on slots that silently discard authored detail

**Context:** the first demo schema defined a rich `Treatment` class and a
multivalued `treatments` slot. Because `Treatment` declares an identifier,
LinkML defaulted the slot to reference-by-identifier and generated an array of
plain strings, so `practice_category`, `is_control`, `description`, and both
amendment-rate fields had nowhere to land. Extractions validated cleanly the
whole time. Five extraction agents independently rediscovered this and each
worked around it, which is the signal that documentation is not the fix.

**Decision:** `doctor` walks the schema from its tree root and reports any
multivalued class-range slot that resolves to identifier references while its
range class defines attributes beyond the identifier — naming the slot, the
attributes at risk, and the `inlined_as_list: true` remedy. The heuristic is
deliberately narrow: an identifier-only range class loses nothing, and an
explicitly inlined slot has already opted out, so neither warns.

**Rejected:** changing what LinkML generates, which would diverge from the
language the schema is written in; failing schema resolution outright, since
identifier references are legitimate when nothing is lost; and documenting the
trap only, which the five independent rediscoveries showed to be insufficient.

## 2026-07-29 — Multi-file schemas are permitted; identity is the byte closure (supersedes "The configured schema file is the complete closure")

**Context:** the 2026-07-14 entry above decided that project extraction schemas
contain no LinkML imports, and rejected "hashing a root file while allowing
mutable imports." The code had drifted from it in both directions: nothing
enforced the no-imports rule, `tests/fixtures/projects/organic_inherits`
imported and subclassed across files with two tests pinning that, and
`schema_hash` digested only the configured file — so editing an imported base
left run identity unchanged, which is exactly the failure the 2026-07-14 entry
was written to prevent.

**Decision:** multi-file schemas are permitted. Splitting a schema across files
is ordinary LinkML practice and worth preserving as an option, though not one
to reach for without reason. Schema identity is the SHA-256 over the byte
closure: the configured file plus every project file it transitively imports,
each contributing its name and its exact bytes, sorted by resolved path.
LinkML's own libraries (`linkml:...`) are excluded — they version with the
dependency, not with the project.

This answers the 2026-07-14 objection rather than ignoring it. That entry's
stated reason was that hashing only the root cannot reconstruct historical
induced types when imports change independently; a closure hash moves whenever
any contributing file moves, so the reconstruction property holds.

Scope stays narrow: no template composition mechanism, no cross-project schema
sharing, no `--template` flag, and no tooling that assumes more than one file.
Permitted, not promoted.

**Rejected:** hashing a *merged* schema (via `--merge-imports` or an equivalent
serialization). It hashes the semantic result, which is appealing — file
reorganisation that changes nothing would keep the hash stable. But the merged
form depends on the LinkML version, so a dependency upgrade could silently
change every historical run's hash and make every stored run read as "schema
mismatch". Bytes do not move when a dependency moves. For a provenance record,
over-sensitivity (a comment edit shifts the hash, prompting a re-check) is the
safe direction to fail; under-sensitivity is not.

**Rejected:** resolving imports ourselves. A hand-rolled walk was wrong twice
in one day — `with_suffix` replaced rather than appended, silently dropping a
`.yml` import out of the digest, and offering both `.yaml` and `.yml`
candidates let an unused sibling change identity. `SchemaView.imports_closure()`
already resolves imports correctly, including that LinkML appends `.yaml`
unconditionally, so `imports: [base.yml]` is not valid LinkML at all and fails
at resolution rather than yielding a confident wrong hash.

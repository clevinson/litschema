# Capability: reviews

Status: approved target.

A review is a compact, run-bound overlay on immutable extracted data. This spec
owns exact-path entries, effective review state, hierarchy, canonical storage,
corrupt-review behavior, and conservative transfer between runs. Git diffs and
pull requests own attribution and conflicting edits.

## Implementation status

None of this spec ships yet. A version-1 review model is live at the article
root (`review.json` beside the extraction) with a different entry shape —
`{author, signal: verified|flagged, timestamp, base_extraction_sha256?}` plus
optional `override_value`/`note`/`source`/`batch_id`, and an
extraction-hash staleness guard. Version 2 below replaces that model rather
than extending it: the legacy keys become invalid, verification becomes an
empty object, overrides move under an `override` key, and staleness is
superseded by run binding. Tracked by `2gd1`, which is blocked on `tdv3`
because reviews move inside the run directory.

## Stored model

Each run may contain `review.json`:

```json
{
  "version": 2,
  "fields": {
    "experiments[0]": {},
    "experiments[0].ph": {
      "override": {"op": "replace", "value": 6.5},
      "note": "table 2 corrects the prose"
    },
    "experiments[1].yield": {
      "override": {"op": "remove"}
    }
  }
}
```

There is at most one entry per exact path. Paths use property segments and
bracket indices with no leading dot, for example
`experiments[0].measurements[1].ph`. A path may name a container or leaf and
must resolve against the extraction in the same run.

An entry has optional `override`
(`{"op":"replace","value":...}` or `{"op":"remove"}`) and optional `note`.
An empty object means verified. A note may accompany verification or an
override and does not create another state. Git supplies author and time
history. Keys sort, writes replace atomically, and a file with no entries is
absent.

Legacy `signal`, `author`, `base_extraction_sha256`, `override_value`, and
`__remove__` fields are invalid in version 2. Pre-release data is rewritten by
its owning repository; runtime readers do not support both shapes.

## Effective state and overlay

| controlling entry | effective state |
|---|---|
| exact or nearest verifying ancestor, no override | verified |
| exact or nearest entry with replace/remove override | overridden |
| no exact or ancestor entry | unreviewed |

A more specific entry may refine a verifying ancestor. A replace/remove
override on an object or array container is terminal: descendant review entries
beneath that path are invalid. The override defines the complete effective
container or removes it.

Replace uses the supplied value after target-schema validation. A replace value
cannot be JSON `null`; omission uses remove, and `null` is reserved for
array-element tombstones. Remove is invalid on any LinkML `identifier: true`
slot. Other remove operations behave by target kind:

- object member or array-valued property: delete the property;
- object-valued property: delete the property and subtree;
- array element `items[i]`: replace that element with a structural JSON `null`
  tombstone; never splice or renumber the array;
- extraction root: reject the remove override.

A property inside an array item deletes only that property. Array-element
replace changes the value at the same index. A whole-array replace defines a new
array and its own indexes. Raw extracted values remain in the immutable run.

## Canonical hierarchy

A verifying parent covers descendants unless a more specific entry changes
state or carries a note. Canonical redundancy is exact:

- an entry is redundant only when it has no note or override and its nearest
  stored ancestor is also verification without an override;
- entries with a note or override are never redundant;
- an empty verification below a container override is invalid, not redundant;
- canonicalization removes redundant entries but never synthesizes a parent
  from independently reviewed siblings.

Saving parent verification removes only redundant descendant empty
verifications. It retains descendant overrides and notes. Reconciliation may
restore a source parent entry only when the source actually stored that parent
and every target descendant transfers safely; it does not infer parent intent
from complete leaf coverage.

Example:

```json
{
  "fields": {
    "experiments[0]": {},
    "experiments[0].ph": {
      "override": {"op": "replace", "value": 6.5}
    },
    "experiments[0].yield": {
      "note": "checked against supplement"
    }
  }
}
```

The parent verifies the subtree, `ph` is overridden, and `yield` stays verified
with a note. Another empty descendant verification would be redundant.

## Subtree unreview

Unreviewing path `p` means the entire `p` subtree becomes unreviewed:

1. remove entries at `p` and below it, including descendant overrides and
   notes;
2. if a verifying ancestor covers `p`, remove that ancestor and expand against
   the raw immutable extraction tree: at each segment from that ancestor to
   `p`, add verification at the highest sibling nodes not containing `p`;
3. retain pre-existing overrides and notes outside `p`; do not add an empty
   verification where a retained explicit entry already preserves coverage;
4. canonicalize using the exact redundancy rule.

This produces one unique minimal frontier. For
`{"groups":[{"x":1,"y":2},{"x":3}]}` with `groups` verified, unreviewing
`groups[0].x` stores verification at `groups[0].y` and `groups[1]`. Array
siblings retain raw indexes. It does not store separate verification for
`groups[1].x`.

For `{"a":{"x":1,"y":2},"b":3}` with `a` verified, unreviewing `a.x` replaces
`a` with `a.y` verification. Any entries at or below `a.x` are removed.

If the covering ancestor carries a note, the operation requires explicit
confirmation that the ancestor-scoped note will be discarded. If the covering
ancestor has a replace/remove override, subtree unreview is rejected because
the system cannot split that container decision without inventing sibling
overrides. The user must first edit or clear the container override.

## Run binding and corrupt files

`extraction-runs/<run-id>/review.json` reviews only that run. There is no
extraction-hash staleness mode. Switching active runs switches the overlay
consumers see without moving entries.

A valid file with at least one entry is `reviewed`. An unreadable, invalid-shape,
or invalid-path file is `corrupt`. Corrupt state is never treated as empty:

- review writes and deletes fail without changing the file;
- activating an inactive corrupt-review run fails until the file is repaired or
  deliberately removed;
- if an active run's review becomes corrupt, verifier and export surface an
  error instead of raw or unreviewed data;
- list and purge preview report `corrupt`;
- trash and purge treat `corrupt` as reviewed and require
  `--confirm-reviewed`.

## Reconciliation between runs

Reconciliation copies review state only when source meaning and target mapping
are proven. It resolves the historical source schema first, writes automatic
safe transfers, persists ambiguous proposals in the refinement ledger, applies
confirmed proposals, then canonicalizes.

### Historical source schema

The source run's mandatory `schema_sha256` is the identity anchor.
`schema_git_commit` and `schema_dirty` are provenance hints. Resolution tries,
in order:

1. if the recorded commit is reachable, find schema bytes in that commit whose
   SHA-256 equals `schema_sha256`, preferring the configured schema path;
2. search reachable Git history for schema-file bytes with the exact hash,
   including earlier paths after a rename;
3. use the current configured schema only when its exact bytes match the hash.

Every candidate is rehashed before LinkML loading. A mismatched recorded commit
is recorded as a provenance warning and does not authorize that schema.
`schema_dirty: true` or a null commit does not block reconstruction when an
exact-hash Git blob or current file exists.

If no exact bytes can be reconstructed, source-schema status is `unavailable`.
No review entry transfers automatically, including scalars, notes, container
reviews, or array reviews. A user may confirm a persisted proposal against the
raw source value and target schema; replace values must validate. Otherwise the
entry is omitted. The refinement ledger records `resolved` or `unavailable`
and the commit/blob source used when resolved.

### Scalars

A scalar entry transfers automatically only when source and target paths have
the same resolved LinkML scalar type, raw values are deeply equal with JSON type
preserved, and any replace value validates against the target field. A scalar
remove transfers under the same path/type/value conditions. Changed, missing,
coerced, or invalid values receive no entry.

### Object and array container overrides

Container verification follows the parent-coverage rule. Container overrides
transfer as a single terminal decision:

- object replace/remove requires the same resolved induced class/subtree
  signature and deeply equal raw source/target containers; replace also
  requires target validation;
- whole-array remove requires the same collection signature and count, complete
  recursive item identity, and deep equality after identity alignment;
- whole-array replace requires the same collection signature and count,
  complete recursive one-to-one identity, raw arrays deeply equal in the same
  order, and a replacement that validates against the target.

A reorder, structural change, count change, missing source schema, or validation
failure prevents automatic container-override transfer. The workflow may store
a proposal for user confirmation; otherwise it omits the override.

### Arrays and nested identity

Array-bound review transfer requires unchanged collection type and item count
plus a complete one-to-one identity mapping at every array boundary. Identity
precedence at each boundary is:

1. the item class's `identifier: true` slot, unique in both arrays;
2. for scalar arrays, the scalar value, unique in both arrays.

The workflow maps an outer element before considering any nested array inside
it. Each nested array then applies its own type/count/identity rules. Ambiguity
at an outer boundary blocks all automatic transfer below that element.
Position alone is never identity. Duplicate or missing identifiers, duplicate
scalar values, unkeyed object arrays, or incomplete matches are ambiguous.

An array-element replace/remove maps to the identified target element's index.
A transferred remove produces a null tombstone at that target index; it never
splices either array. Reordering is safe for element-bound reviews only when the
recursive mapping is complete.

### Proposals and confirmation

For `/litschema-refine`, an ambiguous mapping proposal is stored only in the
authoritative refinement ledger defined by `specs/refinement/spec.md`. It
contains source/target run IDs, paths, the complete mapping, and
`pending|confirmed|rejected`. It is not `review.json` state. Confirmation must
persist before transfer, and reuse requires identical run IDs and mapping.
Pending proposals block readiness. Rejection records omission.

A one-article same-schema rerun without a refinement ledger does not persist LLM
proposals. Ambiguous entries are omitted and the user reviews the target run
directly.

### Parent coverage and notes

Reconciliation evaluates leaves covered by a source parent. It transfers only
safe leaves. The source parent reappears on the target only when every target
descendant transfers safely; otherwise the safe leaves remain explicit. A note
follows its exact mapped node only when node identity is unambiguous. Review
state, notes, and identity are never inferred.

## User surface

Review endpoints are run-explicit:

- `GET /api/annotations/{article-id}/{run-id}` returns canonical stored fields
  and effective state, or explicit corrupt state;
- `PUT /api/annotations/{article-id}/{run-id}` upserts one path with optional
  override and note; no override means verify;
- `DELETE /api/annotations/{article-id}/{run-id}/{path}` unreviews the subtree
  and accepts the required note-discard confirmation.

Malformed paths, invalid replacements, terminal-override descendants, and
writes to trashed runs fail without changing review state.

## Invariants

- One entry exists per exact path.
- State derives from entry presence, override, and verifying ancestry.
- Container overrides are terminal.
- Canonicalization removes only redundant empty verification.
- Subtree unreview removes target descendants and preserves unaffected sibling
  state without splitting overrides.
- Corrupt review is explicit and lifecycle-protected.
- Historical schema resolution requires exact hash equality.
- Automatic reconciliation omits any unproven mapping.
- Proposal confirmation is durable before review transfer.
- Array-element removal preserves indexes with a null tombstone.

## Test obligations

Implementation coverage must pin:

- exact path parsing, duplicate rejection, run binding, atomic sorted writes,
  empty-file deletion, and legacy-field rejection;
- verified/overridden/unreviewed derivation; non-null replacement;
  identifier-remove refusal; replace/remove by target kind; terminal container
  overrides; and array tombstone index stability;
- exact canonical redundancy, parent save compaction, no parent synthesis from
  sibling coverage, raw-tree minimal frontier expansion, nested-array sibling
  selection, and stable raw indexes;
- subtree unreview for objects and nested arrays, descendant override/note
  removal, unaffected sibling preservation, note-discard confirmation, and
  rejection beneath container overrides;
- corrupt parse/shape/path states, write refusal, activation refusal, active
  consumer errors, lifecycle protection, and confirmed trash/purge;
- source schema lookup by recorded commit, renamed historical path, history
  hash, and current exact bytes; commit mismatch; unreachable commit;
  dirty/null-commit recovery; and unavailable-schema omission;
- unchanged scalar transfer and changed/type-coerced/invalid omission;
- object replace/remove and whole-array replace/remove safe and unsafe cases,
  including mandatory recursive identity for both array operations;
- recursive nested-array identity, outer ambiguity, safe reorder,
  duplicate/missing identity, and element replace/remove target-index mapping;
- persisted pending/confirmed/rejected proposals, decision reuse constraints,
  target validation, and one-article ambiguous omission;
- source-parent transfer, partial safe-leaf expansion, note mapping, and
  canonicalization.

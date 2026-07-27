# Capability: reviews

Status: partially current.

A review is a compact, run-bound overlay on immutable extracted data. This spec
owns exact-path entries, effective review state, hierarchy, canonical storage,
and corrupt-review behavior. Git diffs and pull requests own attribution and
conflicting edits.

## Implementation status

Live today: the stored model, effective state, canonical hierarchy, the `add`
op, subtree unreview, corrupt handling, and the run-explicit annotation API.
Version 1 is gone rather than migrated — its keys are rejected as corrupt.

Pending: the verifier frontend still speaks the version-1 vocabulary
(verified/flagged) and has not been rebuilt against these endpoints, so
in-browser review editing does not work until `ka84` lands. Every other
consumer — export, the explore store, progress aggregation — reads v2.

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
    },
    "experiments[4]": {
      "override": {"op": "add", "value": {"id": "E5", "ph": 7.1}},
      "note": "appendix B trial, missed by the agent"
    }
  }
}
```

There is at most one entry per exact path. Paths use property segments and
bracket indices with no leading dot, for example
`experiments[0].measurements[1].ph`. A path may name a container or leaf.
A `replace` or `remove` path must resolve against the extraction in the same
run; an `add` path must not, and is instead validated against the schema as
described below.

An entry has optional `override`
(`{"op":"replace","value":...}`, `{"op":"remove"}`, or
`{"op":"add","value":...}`) and optional `note`.
An empty object means verified. A note may accompany verification or an
override and does not create another state. Git supplies author and time
history. Keys sort, writes replace atomically, and a file with no entries is
absent.

Absence carries no review state. A field the extraction omitted is simply
absent: the model does not record that a human confirmed an omission, and
nothing writes `null` or an empty value into the extraction to represent one.
An omitted field becomes reviewable only when a human supplies it with `add`.

One entry per path also means one reviewer per path. Version 1 keyed entries by
author and so could hold competing reviews of the same field; version 2
deliberately does not. Two reviewers work in separate clones and reconcile by
merging `review.json`. Blind double-extraction with adjudication is a stated
non-goal for v1 (`specs/README.md` § Scope boundaries) and would require a
format change, not an additive one.

Legacy `signal`, `author`, `base_extraction_sha256`, `override_value`, and
`__remove__` fields are invalid in version 2. Pre-release data is rewritten by
its owning repository; runtime readers do not support both shapes.

## Effective state and overlay

| controlling entry | effective state |
|---|---|
| exact or nearest verifying ancestor, no override | verified |
| exact or nearest entry with replace/remove/add override | overridden |
| no exact or ancestor entry | unreviewed |

A more specific entry may refine a verifying ancestor. A replace/remove
override on an object or array container is terminal: descendant review entries
beneath that path are invalid. The override defines the complete effective
container or removes it. An `add` is likewise terminal at its path: the added
value is supplied whole, so descendant entries beneath it are invalid.

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

### Add

`add` supplies a value the extraction omitted. Its motivating case is a missing
array entity — the agent found four experiments and a human found a fifth in an
appendix. Structure is missed more often than a field on structure the agent
already found, because once the agent is reading an entity it fills that
entity's slots.

An add value cannot be JSON `null` and must validate against the slot or item
class the path names, exactly as replace does. A partially filled entity that
omits a required slot fails validation and is refused; the schema decides what
a complete entity is, not the reviewer.

Add is permitted at:

- an array element one position past the raw basis length, appending in order.
  Successive adds occupy successive indexes. Appended indexes live above the
  raw basis, so they never collide with tombstones or raw element indexes;
- a schema-defined property absent from its parent object, where the parent
  itself resolves.

Add is refused at a path that already resolves — that is a replace — at any
path under a terminal override, and at the extraction root. It never splices or
renumbers an array.

Because a human-supplied value has no line-cited reasoning behind it, an add is
recorded as human-origin and stays distinguishable from an agent value a human
merely confirmed. `specs/explore/spec.md` carries that distinction into export.

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
verifications. It retains descendant overrides and notes.

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
- if an active run's review becomes corrupt, verifier and export surface an
  error instead of raw or unreviewed data.

## Toward review transfer between runs

Because a review binds to one immutable run, rerunning an article will one day
need its reviews carried forward conservatively — copied only where the source
meaning and target mapping are proven, with everything unproven left for a
human. That reconciliation workflow is developed on the `feat/multirun` branch
and is deliberately not specified here; nothing in this release creates a
second run to reconcile against. Run-bound storage is what makes it possible
later without changing this format.

## User surface

Review endpoints are run-explicit:

- `GET /api/annotations/{article-id}/{run-id}` returns canonical stored fields
  and effective state, or explicit corrupt state;
- `PUT /api/annotations/{article-id}/{run-id}` upserts one path with optional
  override and note; no override means verify;
- `DELETE /api/annotations/{article-id}/{run-id}/{path}` unreviews the subtree
  and accepts the required note-discard confirmation.

Malformed paths, invalid replacements, invalid or misplaced adds,
terminal-override descendants, and writes to trashed runs fail without changing
review state.

## Invariants

- One entry exists per exact path.
- State derives from entry presence, override, and verifying ancestry.
- Container overrides are terminal.
- Canonicalization removes only redundant empty verification.
- Subtree unreview removes target descendants and preserves unaffected sibling
  state without splitting overrides.
- Corrupt review is explicit and lifecycle-protected.
- Array-element removal preserves indexes with a null tombstone.
- Absence is never review state; only an add makes an omitted field reviewable.
- Added values validate against the schema and stay identifiable as
  human-origin.

## Test obligations

Implementation coverage must pin:

- exact path parsing, duplicate rejection, run binding, atomic sorted writes,
  empty-file deletion, and legacy-field rejection;
- verified/overridden/unreviewed derivation; non-null replacement;
  identifier-remove refusal; replace/remove by target kind; terminal container
  overrides; and array tombstone index stability;
- add at an appended array index and at an absent object property; sequential
  appends; refusal at a resolving path, under a terminal override, at the
  extraction root, and for a value failing item-class or required-slot
  validation; non-collision of appended indexes with tombstones; and
  human-origin marking;
- exact canonical redundancy, parent save compaction, no parent synthesis from
  sibling coverage, raw-tree minimal frontier expansion, nested-array sibling
  selection, and stable raw indexes;
- subtree unreview for objects and nested arrays, descendant override/note
  removal, unaffected sibling preservation, note-discard confirmation, and
  rejection beneath container overrides;
- corrupt parse/shape/path states, write refusal, and active consumer errors.

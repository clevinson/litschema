# Release process

At the moment the release process is kept deliberately light. All releases prior to v1.0 are considered semi-stable. We reserve the right to break backwards compatiblity, but don't anticipate doing so without good reason :)

Prior to v1.0, each minor increment (major/minor/patch) MAY indicate a breaking change, or signfiicant feature addition, whereas patch increments will be used to indicate bug fixes / minor additions. The [CHANGELOG.md](./CHANGELOG.md) will be the canonical source of breaking changes for each version.

## Normal development

PRs land on `main` with **squash and merge**. The squash message is what shows
up in the next changelog draft, so write it as one line in Conventional Commits
form (`type(scope): summary`) describing the user-visible effect — not the
mechanics of the patch.

## Cutting a release

**1. Draft the changelog entry from the commits since the last tag.**

```bash
git log --oneline --no-merges $(git describe --tags --abbrev=0)..main
```

Move the `## [Unreleased]` heading down to a new `## [x.y.z] — YYYY-MM-DD`
section and write the entry from that log.

**Every major or minor entry opens with `### Breaking changes`, even when there are none** —
write "None." rather than omitting the heading. Not required for patch releases,
unless there is a breaking change. A format change belongs
here whether or not the version number implies one.

Then the Keep a Changelog headings as needed: `Added`, `Changed`, `Deprecated`,
`Removed`, `Fixed`, `Security` — plus `Known limits` where a gap is worth
stating outright rather than leaving someone to discover it.

**Write in lists, one bullet per change, and link the commit or PR that made
it inline.** Prefer the PR when a change arrived as one; use commits when a
release branch carried many features through a single merge, as 0.1.0 did. One
reference per bullet is the target — if a bullet needs three, it is probably
three bullets.

Inline full URLs are the common convention and the reason is portability: they
resolve wherever the file is read, including in an editor or on a package page.
The cost is that those lines run long, and no wrapping fixes it. Two
alternatives, if that becomes annoying:

- **Bare `#123` or a bare commit SHA.** GitHub autolinks both within the same
  repository, so lines stay short. They are inert everywhere else.
- **Reference-style definitions at the foot of the file.** Prose stays narrow
  and links still resolve anywhere, at the cost of a footer to keep in step —
  an unused or missing definition is easy to introduce and invisible until
  someone clicks.

What goes in: anything that changes what a user can do, what the tool produces,
or what it refuses. What stays out: internal refactors, test-only work,
dependency bumps with no behavioural effect, and anything implemented and then
reverted before the tag — the reader wants the delta between releases, not a
diary.

**Spec changes follow the same rule.** List a spec edit only when it changes
what the product does or admits. Correcting a spec to match code that never
moved is not a release-note item. Where a spec described unbuilt behaviour, put
it under `Known limits` rather than `Removed` — nothing a user relied on went
away, and the honest statement is "this does not exist," not "this was taken
out."

**2. Land the changelog, then bump the version.**

The changelog entry and the `version` in `pyproject.toml` go in one commit on
`main`:

```bash
git commit -am "chore(release): 0.2.0"
```

**3. Tag that commit.**

```bash
git tag -a v0.2.0 -m "v0.2.0"
git push origin main v0.2.0
```

Tag the release commit itself, so the tree at the tag contains the changelog
describing it. `.github/workflows/publish.yml` checks that the tag matches the
version in `pyproject.toml`, so keep them in step even while publishing is off.

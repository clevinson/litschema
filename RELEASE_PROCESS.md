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

What goes in the sections above: anything that changes what a user can do, what
the tool produces, or what it refuses.

Work with no user-visible effect — refactors, test and build infrastructure,
performance — goes under a final `Internal` heading rather than being dropped.
Keep it below the user-facing sections and say so in a line at the top of it,
so a reader skimming for what changed is never wading through it. The point is
that this project asks people to trust extracted data, and how it is tested is
part of that argument.

What still stays out: anything implemented and then reverted before the tag,
and pure churn — formatting passes, dependency bumps that changed nothing,
commits that only fix an earlier commit in the same release. The reader wants
the delta between releases, not a diary.

**Spec changes follow the same rule.** List a spec edit only when it changes
what the product does or admits. Correcting a spec to match code that never
moved is not a release-note item. Where a spec described unbuilt behaviour, put
it under `Known limits` rather than `Removed` — nothing a user relied on went
away, and the honest statement is "this does not exist," not "this was taken
out."

**2. Land the changelog.**

Commit the changelog entry on `main`, with `version` in `CITATION.cff` set to
the new version and `date-released` set to the release date:

```bash
git commit -am "chore(release): 0.2.0"
```

There is no version to bump in `pyproject.toml`. hatch-vcs takes the version
from the tag, so the tag in the next step is the version bump.

**3. Tag that commit.**

```bash
git tag -a v0.2.0 -m "v0.2.0"
git push origin main v0.2.0
```

Tag the release commit itself, so the tree at the tag contains the changelog
describing it.

**4. Publish.**

Run `.github/workflows/publish.yml` from the Actions tab, picking the tag (not
`main`) in the ref dropdown. Before uploading, it runs the tests, builds, checks
that the built version is the tag, and installs the wheel as a uv tool to run
`init`, `status`, and `doctor` in a fresh project. Pull requests run the same
install check.

PyPI never accepts a version twice. If a release turns out broken, yank it on
PyPI and ship the fix as the next patch release.

The workflow refuses to run from a branch: hatch-vcs would build a dev version
and the tag check would fail for a reason unrelated to the release.

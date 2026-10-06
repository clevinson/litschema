"""The installed litschema version, where it came from, and project pins.

A project pins the exact litschema version it runs with (``litschema_version``
in ``litschema.yaml``). Commands refuse to run under any other version, so
moving a project to a new release is a change someone makes on purpose.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from urllib.parse import unquote, urlparse

from .config import LitSchemaConfig

PIN_KEY = "litschema_version"
SKILL_STAMP_KEY = "litschema_version"
VERSION_MISMATCH_EXIT_CODE = 3

# Final releases and pre-releases; dev and local builds never reach PyPI.
_RELEASE_RE = re.compile(r"\d+(\.\d+)*((a|b|rc)\d+)?(\.post\d+)?")
_STAMP_RE = re.compile(rf"^{SKILL_STAMP_KEY}:\s*\"?([^\"\n]+?)\"?\s*$", re.MULTILINE)


def installed_version() -> str:
    return metadata.version("litschema")


@dataclass(frozen=True)
class InstallSource:
    """How this litschema was installed.

    ``release`` came from a package index, ``git`` from a git URL (``commit``
    names the code), and ``local`` from a path on disk, which may include
    uncommitted edits.
    """

    kind: str
    path: str | None = None
    commit: str | None = None

    def as_record(self) -> dict[str, str]:
        record = {"source": self.kind}
        if self.commit:
            record["commit"] = self.commit
        return record


def install_source() -> InstallSource:
    """Read PEP 610 ``direct_url.json``; its absence means an index install."""
    return parse_direct_url(metadata.distribution("litschema").read_text("direct_url.json"))


def parse_direct_url(raw: str | None) -> InstallSource:
    if not raw:
        return InstallSource("release")
    direct = json.loads(raw)
    if "vcs_info" in direct:
        return InstallSource("git", commit=direct["vcs_info"].get("commit_id"))
    url = urlparse(direct.get("url", ""))
    path = unquote(url.path) if url.scheme == "file" else None
    # Any other direct URL (a local wheel, a remote archive) can't be traced
    # back to a commit, so it counts as local.
    return InstallSource("local", path=path)


def version_line() -> str:
    source = install_source()
    line = f"litschema {installed_version()}"
    if source.kind == "local" and source.path:
        line += f" (local: {_home_relative(source.path)})"
    elif source.kind == "git" and source.commit:
        line += f" (git: {source.commit[:12]})"
    return line


def _home_relative(path: str) -> str:
    home = str(Path.home())
    return "~" + path[len(home) :] if path.startswith(home) else path


def is_release(version: str) -> bool:
    """True for a version PyPI could serve."""
    return _RELEASE_RE.fullmatch(version) is not None


def project_pin(cfg: LitSchemaConfig) -> str | None:
    value = cfg.raw.get(PIN_KEY)
    return str(value) if value is not None else None


def read_skill_stamp(skill_md: Path) -> str | None:
    text = skill_md.read_text()
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    match = _STAMP_RE.search(text[: end if end != -1 else len(text)])
    return match.group(1) if match else None


def stamp_skill(skill_md: Path, version: str) -> None:
    """Record the litschema version in a copied skill's frontmatter."""
    text = skill_md.read_text()
    line = f'{SKILL_STAMP_KEY}: "{version}"'
    if not text.startswith("---"):
        skill_md.write_text(f"---\n{line}\n---\n{text}")
        return
    end = text.find("\n---", 3)
    front, rest = text[:end], text[end:]
    front = _STAMP_RE.sub(line, front) if _STAMP_RE.search(front) else f"{front}\n{line}"
    skill_md.write_text(front + rest)


@dataclass(frozen=True)
class VersionCheck:
    """Outcome of comparing a project against the running litschema."""

    errors: list[str]
    warnings: list[str]


def check_project(cfg: LitSchemaConfig, skill_names: list[str]) -> VersionCheck:
    """Compare the running version and the project's copied skills with the pin."""
    running = installed_version()
    pin = project_pin(cfg)
    if pin is None:
        return VersionCheck(
            errors=[],
            warnings=[
                f"{cfg.config_path.name} has no {PIN_KEY}; add "
                f'`{PIN_KEY}: "{running}"` to pin this project to the version you run'
            ],
        )

    errors = []
    if running != pin:
        if is_release(pin):
            use_pin = f"  Use the pinned release:  uv tool install litschema=={pin} --force"
        else:
            use_pin = (
                f"  {pin} is a development build, not on PyPI; reinstall it from the "
                "checkout or commit it came from"
            )
        errors.append(
            f"this project is pinned to litschema {pin}; you're running {version_line()}\n"
            f"{use_pin}\n"
            f'  Or pin the project to {running}:  set {PIN_KEY}: "{running}" in '
            f"{cfg.config_path.name}, then run `litschema skills install --local --force`"
        )

    skills_dir = cfg.project_root / ".claude" / "skills"
    stale = []
    for name in skill_names:
        skill_md = skills_dir / name / "SKILL.md"
        # Symlinked installs track the package itself; only copies can drift.
        if (skills_dir / name).is_symlink() or not skill_md.is_file():
            continue
        if read_skill_stamp(skill_md) != pin:
            stale.append(name)
    if stale:
        errors.append(
            f"project skills ({', '.join(stale)}) don't match litschema {pin}; "
            "run `litschema skills install --local --force` from the project root"
        )
    return VersionCheck(errors=errors, warnings=[])

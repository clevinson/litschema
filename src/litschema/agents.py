"""The coding agents a project is set up for, and the files each one needs.

`init` records the choice as `agents:` in litschema.yaml; `skills install
--local` reads it back.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

AGENTS_KEY = "agents"

CODEX_CONFIG = """\
# Written by litschema init. Lets Codex reach the network in this project so
# DOI metadata lookups work. Delete it to keep Codex's offline sandbox.
[sandbox_workspace_write]
network_access = true
"""


@dataclass(frozen=True)
class Agent:
    name: str
    label: str
    skills_dir: Path
    command: str
    config_dir_env: str
    config_dir_default: str

    def detected(self) -> bool:
        config_dir = os.environ.get(self.config_dir_env) or Path.home() / self.config_dir_default
        return shutil.which(self.command) is not None or Path(config_dir).exists()


AGENTS = {
    "claude-code": Agent(
        "claude-code", "Claude Code", Path(".claude") / "skills", "claude",
        "CLAUDE_CONFIG_DIR", ".claude",
    ),
    "codex": Agent(
        "codex", "Codex", Path(".agents") / "skills", "codex", "CODEX_HOME", ".codex",
    ),
}
ALIASES = {"claude": "claude-code"}


class UnknownAgentError(ValueError):
    pass


def parse_agents(values: list[str]) -> list[str]:
    """Agent names from --agent values; `all` selects every agent."""
    chosen: list[str] = []
    for value in values:
        for part in value.split(","):
            name = ALIASES.get(part.strip().lower(), part.strip().lower())
            if not name:
                continue
            if name == "all":
                names = list(AGENTS)
            elif name in AGENTS:
                names = [name]
            else:
                raise UnknownAgentError(
                    f"unknown agent {part.strip()!r}; expected one of: {', '.join(AGENTS)}, all"
                )
            chosen += [n for n in names if n not in chosen]
    return chosen


def detected_agents() -> list[str]:
    return [name for name, agent in AGENTS.items() if agent.detected()]


def project_agents(raw: dict) -> list[str]:
    """The project's recorded agents; every agent for projects that predate the key."""
    value = raw.get(AGENTS_KEY)
    if not isinstance(value, list):
        return list(AGENTS)
    return [name for name in AGENTS if name in value]


def write_agent_config(project: Path, agents: list[str]) -> list[Path]:
    """Per-agent project config; existing files are left alone."""
    written = []
    if "codex" in agents:
        path = project / ".codex" / "config.toml"
        if not path.exists():
            path.parent.mkdir(exist_ok=True)
            path.write_text(CODEX_CONFIG)
            written.append(path)
    return written

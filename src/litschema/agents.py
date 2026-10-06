"""The coding agents litschema sets a project up for, and the files each one needs.

An agent is set up when its config directory exists, as roborev does:
`$CLAUDE_CONFIG_DIR` or `~/.claude` for Claude Code, `$CODEX_HOME` or `~/.codex`
for Codex. `~/.agents` also counts for Codex's project folder, `.agents/skills`,
since other agents read it too.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

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
    config_dir_env: str
    config_dir_default: str
    also_detected_by: tuple[str, ...] = ()

    def detected(self) -> bool:
        config_dir = os.environ.get(self.config_dir_env) or Path.home() / self.config_dir_default
        return Path(config_dir).is_dir() or any(
            (Path.home() / marker).is_dir() for marker in self.also_detected_by
        )


AGENTS = {
    "claude-code": Agent(
        "claude-code", "Claude Code", Path(".claude") / "skills", "CLAUDE_CONFIG_DIR", ".claude",
    ),
    "codex": Agent(
        "codex", "Codex", Path(".agents") / "skills", "CODEX_HOME", ".codex", (".agents",),
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


def agents_to_set_up(explicit: list[str] | None = None) -> list[str]:
    """--agent values, else the agents with a config directory, else all of them."""
    if explicit:
        return parse_agents(explicit)
    return detected_agents() or list(AGENTS)


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

from __future__ import annotations

import pytest

from litschema.runs import _agent_attribution


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, {}),
        (
            {"AI_AGENT": "claude-code_2-1-219_agent", "CLAUDE_EFFORT": "high"},
            {"harness": "claude-code", "harness_version": "2.1.219", "effort": "high"},
        ),
        ({"CODEX_VERSION": "0.154.0"}, {"harness": "codex", "harness_version": "0.154.0"}),
        # Codex launched from a Claude Code shell inherits its variables.
        (
            {"CODEX_VERSION": "0.154.0", "AI_AGENT": "claude-code_2-1-219_agent",
             "CLAUDE_EFFORT": "high"},
            {"harness": "codex", "harness_version": "0.154.0"},
        ),
    ],
)
def test_attribution_reads_the_harness_from_its_shell(monkeypatch, env, expected) -> None:
    for name in ("AI_AGENT", "CLAUDE_EFFORT", "CODEX_VERSION"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    assert _agent_attribution(None, None) == expected


def test_declared_provider_and_model_are_kept(monkeypatch) -> None:
    monkeypatch.setenv("CODEX_VERSION", "0.154.0")

    assert _agent_attribution("openai", "gpt-x") == {
        "harness": "codex", "harness_version": "0.154.0", "provider": "openai", "model": "gpt-x",
    }

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_detected_agents(monkeypatch):
    """Which agents the test machine has installed must not change what init sets up."""
    monkeypatch.setattr("litschema.agents.Agent.detected", lambda self: False)

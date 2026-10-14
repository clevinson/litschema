from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_detected_agents(monkeypatch):
    """Tests see every agent as installed, whatever the test machine has."""
    monkeypatch.setattr("litschema.agents.Agent.detected", lambda self: True)

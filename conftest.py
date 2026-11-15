"""Keep a launched AgentStack seat out of installer and launcher test fixtures."""
from __future__ import annotations

import os
import tempfile
import pytest

_patch = None


def pytest_configure(config):
    global _patch
    _patch = pytest.MonkeyPatch()
    prefixes = ("AGENTSTACK_", "CODEX_", "CLAUDE_CODE_")
    keys = {"AGENT_NAME", "PARENT_AGENT", "PROJECT_KEY", "TMUX", "TMUX_PANE",
            "CHILD_REGISTRATION_TOKEN", "MCP_AGENT_MAIL_TOKEN", "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY", "CLAUDECODE", "NVM_DIR"}
    for name in list(os.environ):
        if name.startswith(prefixes) or name in keys:
            _patch.delenv(name, raising=False)
    # Do this BEFORE collection: mail defaults expand HOME when imported.
    # Keep this regenerable fixture home with pytest's other run material.
    test_home = tempfile.mkdtemp(prefix="orrery-test-home-")
    _patch.setenv("HOME", test_home)


def pytest_unconfigure(config):
    global _patch
    if _patch is not None:
        _patch.undo()
        _patch = None

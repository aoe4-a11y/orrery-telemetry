"""Claude Code 2.1.308 composer footer regressions from captured real panes."""
from pathlib import Path

import pytest

from dashboard import server

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("name,expected", [("working", "work"), ("idle", "wait")])
def test_claude_2308_captured_pane_activity(name, expected):
    text = (FIXTURES / f"ORRERY-UP-4-pane-claude2308-{name}.txt").read_text()
    assert server._runtime_activity(text)[0] == expected
    assert server._parse_runtime(text)["act_state"] == expected


@pytest.mark.parametrize("footer", [
    "fixture | Sonnet 5 | ctx: 33% used",
    "? for shortcuts",
])
@pytest.mark.parametrize("working", [True, False])
def test_older_claude_composer_activity(footer, working):
    body = "✽ Stewing… (7s · ↓ 1.2k tokens)" if working else "⏺ Finished."
    text = f"{body}\n\n────────────────\n❯ \n────────────────\n{footer}\n"
    assert server._parse_runtime(text)["act_state"] == ("work" if working else "wait")


@pytest.mark.parametrize("working", [True, False])
def test_codex_composer_activity(working):
    body = "• Working (2s • esc to interrupt)" if working else "• Finished."
    text = f"{body}\n\n› Ask Codex to do anything\ngpt-5.6-terra medium · Context 70% left\n"
    assert server._parse_runtime(text)["act_state"] == ("work" if working else "wait")

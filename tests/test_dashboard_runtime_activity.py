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


def test_codex_captured_background_terminals_activity():
    text = (FIXTURES / "orrery-up-5-pane-codex-working-background.txt").read_text()
    assert server._runtime_activity(text)[0] == "work"
    parsed = server._parse_runtime(text)
    assert parsed["act_state"] == "work"
    assert parsed["work_secs"] == 4 * 3600 + 3 * 60 + 7
    assert parsed["work_disp"] == "4h03m"


@pytest.mark.parametrize("duration,seconds", [("2s", 2), ("03m 07s", 187), ("4h 03m 07s", 14587)])
@pytest.mark.parametrize("suffix", ["", " · 1 background terminal running", " · 2 background terminals running · /p…"])
def test_codex_active_duration_and_background_suffix(duration, seconds, suffix):
    text = (f"• Working ({duration} • esc to interrupt){suffix}\n"
            "› Ask Codex to do anything\nGPT-6.1-Sol high · ~/tools/examforge\n")
    parsed = server._parse_runtime(text)
    assert parsed["act_state"] == "work"
    assert parsed["work_secs"] == seconds


@pytest.mark.parametrize("body", [
    "The example says esc to interrupt while work is running.",
    "• The example says esc to interrupt; 2 background terminals running.",
    "The captured line was Working (4h 03m 07s • esc to interrupt) · 2 background terminals running.",
    "• Working (4h 03m 07s • esc to interrupt) · 2 background terminals running\n• Finished.",
])
def test_codex_interrupt_prose_and_finished_work_are_wait(body):
    text = body + "\n› Ask Codex to do anything\nGPT-6.1-Sol high · ~/tools/examforge\n"
    parsed = server._parse_runtime(text)
    assert parsed["act_state"] == "wait"
    assert parsed["work_secs"] is None

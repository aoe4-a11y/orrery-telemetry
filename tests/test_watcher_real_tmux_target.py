"""Read-only integration with an explicitly opted-in, task-owned tmux session."""
import os
from pathlib import Path
import re
import subprocess

import pytest


def test_watcher_pane_target_resolves_the_exact_owned_session_in_real_tmux():
    session = os.environ.get("ORRERY_TEST_OWN_TMUX_SESSION")
    if not session:
        pytest.skip("set ORRERY_TEST_OWN_TMUX_SESSION to the caller's own session")
    assert re.fullmatch(r"[A-Za-z0-9_-]+", session), "unsafe test session name"
    source = (Path(__file__).resolve().parents[1] / "hooks/watch_agent_mail_signals.sh").read_text()
    helper = re.search(r"^pane_target_for_session\(\) \{\n(?:.*\n)*?^\}\n",
                       source, re.MULTILINE)
    assert helper is not None
    formatted = subprocess.run(
        ["/bin/bash", "-c", helper.group(0) + '\npane_target_for_session "$1"', "fixture", session],
        text=True, capture_output=True, timeout=5, check=True,
    ).stdout.strip()
    assert formatted == f"={session}:"
    # No send-keys, session creation, or reads of any other seat's pane.
    identity = subprocess.run(
        ["tmux", "display-message", "-p", "-t", formatted, "#{session_name}"],
        text=True, capture_output=True, timeout=5,
    )
    assert identity.returncode == 0, identity.stderr
    assert identity.stdout.strip() == session
    captured = subprocess.run(
        ["tmux", "capture-pane", "-p", "-t", formatted],
        text=True, capture_output=True, timeout=5,
    )
    assert captured.returncode == 0, captured.stderr

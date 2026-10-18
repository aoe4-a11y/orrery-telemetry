"""A failed launch owns its new artifacts, never the existing seat identity.

No real tmux session, mail service, credential, or Codex home is used here.
Run with pytest or directly with Python's standard library.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPAWN = ROOT / "hooks/spawn_child.sh"
CLEANUP = ROOT / "hooks/cleanup-child-agent.sh"
NAME = "RestartFixture"
TOKEN = "fixture-only-token"


def executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o700)


class RestartIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def arrange(self, existing: bool) -> dict:
        runtime = self.base / "runtime"
        children = runtime / "child-agents"
        children.mkdir(parents=True)
        bindir = self.base / "bin"
        bindir.mkdir()
        work = self.base / "work"
        work.mkdir()
        token = runtime / f"agent_token_{NAME}"
        state = children / f"{NAME}.json"
        config = children / f"{NAME}.mcp.json"
        home = children / f"{NAME}.codex-home"
        managed = runtime / "managed_agents.txt"
        handoff = self.base / "handoff"
        if existing:
            token.write_text(TOKEN)
            token.chmod(0o600)
            state.write_text(json.dumps({
                "agent_name": NAME, "project_key": "/fixture/project",
                "registration_token": TOKEN,
            }))
            config.write_text("{}")
            home.mkdir()
            (home / "sentinel").write_text("existing seat data")
            managed.write_text(f"{NAME}\nOtherSeat\n")
            handoff = token
        else:
            managed.write_text("OtherSeat\n")
            handoff.write_text(TOKEN)
            handoff.chmod(0o600)
        executable(bindir / "sleep", "#!/bin/sh\nexit 0\n")
        executable(bindir / "codex", "#!/bin/sh\n"
                   "if [ \"${1:-}\" = --help ]; then "
                   "echo ' --ask-for-approval <POLICY>'; fi\nexit 1\n")
        executable(bindir / "tmux", '''#!/usr/bin/env python3
import os, pathlib, subprocess, sys
args = sys.argv[1:]
verb = args[0] if args else ''
with pathlib.Path(os.environ['FIXTURE_TMUX_LOG']).open('a') as log:
    log.write(verb + '\\n')
if verb == 'new-session':
    if os.environ.get('FIXTURE_EARLY_FAILURE') == '1':
        sys.exit(17)
    child_env = dict(os.environ)
    for i, arg in enumerate(args):
        if arg == '-e':
            key, value = args[i + 1].split('=', 1)
            child_env[key] = value
    assert 'cleanup-child-agent.sh' in args[-1]
    subprocess.run(['/bin/bash', os.environ['FIXTURE_CLEANUP']],
                   env=child_env, check=True)
    sys.exit(0)
if verb == 'has-session':
    sys.exit(1)
if verb == 'display-message':
    print('FixtureParent')
sys.exit(0)
''')
        # Only fixture-specific identity/transport values enter the subprocess.
        env = {
            # Inherit the actual home unchanged; all runtime/config paths below
            # are redirected, and no proxy or credential discovery is enabled.
            "HOME": os.environ["HOME"],
            "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
            "PARENT_AGENT": "FixtureParent", "PROJECT_KEY": "/fixture/project",
            "AGENTSTACK_PROJECT_KEY": "/fixture/project",
            "AGENTSTACK_RUNTIME_DIR": str(runtime),
            "AGENTSTACK_MANAGED_AGENTS_FILE": str(managed),
            "AGENTSTACK_HOOKS_DIR": str(ROOT / "hooks"),
            "AGENTSTACK_HOME": str(self.base / "agentstack"),
            "AGENTSTACK_LABEL_PREFIX": "org.agentstack.test.restart-identity",
            "AGENTSTACK_REGISTER_LIB": str(ROOT / "bin/lib/agentstack-register.sh"),
            "AGENTSTACK_MCP_PROXY": str(self.base / "absent-proxy"),
            "AGENTSTACK_CODEX_BIN": str(bindir / "codex"),
            "AGENTSTACK_TERMINAL": "none",
            "AGENTSTACK_MAIL_HTTP_BEARER_MODE": "disabled",
            "AGENTSTACK_MCP_URL": "http://127.0.0.1:1/mcp",
            "FIXTURE_CLEANUP": str(CLEANUP),
            "FIXTURE_TMUX_LOG": str(self.base / "tmux-verbs"),
        }
        return dict(env=env, work=work, token=token, state=state,
                    config=config, home=home, managed=managed, handoff=handoff)

    def failed_launch(self, seat: dict, early: bool = False) -> None:
        env = dict(seat["env"], FIXTURE_EARLY_FAILURE="1" if early else "0")
        result = subprocess.run([
            "/bin/bash", str(SPAWN), "--codex", "--model", "gpt-5.5",
            "--pre-registered", NAME, "--child-token-file", str(seat["handoff"]),
            "--embed-task", "fixture work", str(seat["work"]),
        ], env=env, cwd=seat["work"], capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        log = self.base / "tmux-verbs"
        self.assertTrue(log.is_file(), result.stdout + result.stderr)
        verbs = log.read_text().splitlines()
        self.assertIn("new-session", verbs, result.stderr)

    def assert_existing(self, seat: dict) -> None:
        self.assertEqual(seat["token"].read_text(), TOKEN)
        self.assertEqual(json.loads(seat["state"].read_text())["registration_token"], TOKEN)
        self.assertEqual(seat["config"].read_text(), "{}")
        self.assertEqual((seat["home"] / "sentinel").read_text(), "existing seat data")
        self.assertEqual(seat["managed"].read_text(), f"{NAME}\nOtherSeat\n")

    def test_child_exit_preserves_existing_identity(self) -> None:
        seat = self.arrange(True)
        self.failed_launch(seat)
        self.assert_existing(seat)

    def test_early_tmux_failure_preserves_existing_identity(self) -> None:
        seat = self.arrange(True)
        self.failed_launch(seat, early=True)
        self.assert_existing(seat)

    def test_fresh_child_failure_removes_new_identity(self) -> None:
        seat = self.arrange(False)
        self.failed_launch(seat)
        for key in ("token", "state", "config", "home", "handoff"):
            self.assertFalse(seat[key].exists(), key)
        self.assertNotIn(NAME, seat["managed"].read_text().splitlines())
        self.assertIn("OtherSeat", seat["managed"].read_text().splitlines())

    def test_new_token_rollback_preserves_existing_state_and_home(self) -> None:
        seat = self.arrange(True)
        seat["token"].unlink()
        seat["handoff"] = self.base / "handoff"
        seat["handoff"].write_text(TOKEN)
        seat["handoff"].chmod(0o600)
        self.failed_launch(seat)
        self.assertFalse(seat["token"].exists())
        self.assertTrue(seat["state"].is_file())
        self.assertTrue(seat["config"].is_file())
        self.assertTrue((seat["home"] / "sentinel").is_file())
        self.assertIn(NAME, seat["managed"].read_text().splitlines())

    def test_automatic_cleanup_preserves_existing_seat(self) -> None:
        seat = self.arrange(True)
        env = dict(seat["env"], AGENT_NAME=NAME, AGENTSTACK_PRESERVE_SEAT_IDENTITY="1")
        subprocess.run(["/bin/bash", str(CLEANUP)], env=env, check=True, timeout=10)
        self.assert_existing(seat)

    def test_explicit_admin_cleanup_remains_available(self) -> None:
        seat = self.arrange(True)
        env = dict(seat["env"], AGENT_NAME=NAME, AGENTSTACK_PRESERVE_SEAT_IDENTITY="1")
        subprocess.run(["/bin/bash", str(CLEANUP), NAME], env=env, check=True, timeout=10)
        for key in ("token", "state", "config", "home"):
            self.assertFalse(seat[key].exists(), key)

    def adoption_failure(self, existing: bool) -> None:
        text = SPAWN.read_text()
        match = re.search(r"adopt_child_token_file\(\) \{.*?<<'PY'\n(.*?)\nPY\n", text, re.S)
        self.assertIsNotNone(match)
        handoff, token, state = (self.base / name for name in ("handoff", "token", "state"))
        handoff.write_text(TOKEN)
        handoff.chmod(0o600)
        if existing:
            token.write_text(TOKEN)
            state.write_text("{}")
        original_unlink = Path.unlink

        def fail_handoff(path: Path, *args, **kwargs):
            if path == handoff:
                raise PermissionError("injected handoff unlink failure")
            return original_unlink(path, *args, **kwargs)

        argv = ["adopt", NAME, "/fixture/project", str(handoff), str(token), str(state), "true"]
        with patch.object(sys, "argv", argv), patch.object(Path, "unlink", fail_handoff):
            with self.assertRaises(PermissionError), contextlib.redirect_stdout(io.StringIO()):
                exec(compile(match.group(1), str(SPAWN), "exec"), {})
        self.assertTrue(handoff.is_file())
        self.assertEqual(token.exists(), existing)
        self.assertEqual(state.exists(), existing)

    def test_adoption_failure_keeps_existing_identity(self) -> None:
        self.adoption_failure(True)

    def test_adoption_failure_rolls_back_new_identity(self) -> None:
        self.adoption_failure(False)


if __name__ == "__main__":
    unittest.main()

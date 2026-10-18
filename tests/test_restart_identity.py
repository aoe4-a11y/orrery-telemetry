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
from user_home_isolation import isolated_user_environment


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hooks"))
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
        # Extracted Python probes run in this interpreter, including unittest.
        environment = patch.dict(os.environ, isolated_user_environment(self.base / "user-home"), clear=True)
        environment.start()
        self.addCleanup(environment.stop)

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
    # A real tmux child exits asynchronously after new-session returns. Store
    # its environment; failure tests below exercise the parent rollback.
    pathlib.Path(os.environ['FIXTURE_TMUX_LOG'] + '.env').write_text(__import__('json').dumps(child_env))
    sys.exit(0)
if verb == 'has-session':
    sys.exit(1)
if verb == 'display-message':
    print('FixtureParent')
sys.exit(0)
''')
        user_home = self.base / "user-home"
        user_home.mkdir(exist_ok=True)
        for child in (".codex", ".claude", ".config"):
            (user_home / child).mkdir(exist_ok=True)
        # Only fixture-specific identity/transport values enter the subprocess.
        env = {
            # All user configuration stays inside this fixture, including
            # when run directly via unittest rather than pytest/conftest.
            "HOME": str(user_home),
            "CODEX_HOME": str(user_home / ".codex"),
            "CLAUDE_CONFIG_DIR": str(user_home / ".claude"),
            "XDG_CONFIG_HOME": str(user_home / ".config"),
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

    def failed_launch(self, seat: dict, early: bool = False, require_tmux: bool = True) -> None:
        env = dict(seat["env"], FIXTURE_EARLY_FAILURE="1" if early else "0")
        args = [
            "/bin/bash", str(SPAWN), "--codex", "--model", "gpt-5.5",
            "--pre-registered", NAME,
        ]
        if seat["handoff"] is not None:
            args.extend(["--child-token-file", str(seat["handoff"])])
        args.extend(["--embed-task", "fixture work", str(seat["work"])])
        result = subprocess.run(args, env=env, cwd=seat["work"],
                                capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        if not require_tmux:
            return
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

    def enable_proxy(self, seat: dict) -> Path:
        source = self.base / "source-codex"
        source.mkdir()
        (source / "config.toml").write_text('model = "fixture"\n')
        (source / "sentinel").write_text("shared fixture remains")
        proxy = self.base / "bin/proxy"
        executable(proxy, "#!/bin/sh\nexit 0\n")
        seat["env"].update(CODEX_HOME=str(source), AGENTSTACK_MCP_PROXY=str(proxy),
                           AGENTSTACK_CLAUDE_JSON=str(self.base / "absent-claude-config"))
        return source

    def write_mcp_with_ownership(self, seat: dict) -> dict:
        match = re.search(r"^write_child_mcp_config\(\) \{.*?^\}", SPAWN.read_text(), re.S | re.M)
        self.assertIsNotNone(match)
        prelude = ('RUNTIME_DIR="$AGENTSTACK_RUNTIME_DIR"\n'
                   'PROJECT_KEY="$AGENTSTACK_PROJECT_KEY"\n'
                   'HTTP_BEARER_MODE=disabled\nMCP_URL=http://127.0.0.1:1/mcp\nMAIL_ENV=/fixture/missing.env\n')
        result = subprocess.run(["/bin/bash", "-c", prelude + match.group(0) +
                                 '\nwrite_child_mcp_config "$1" "$2" true\n',
                                 "fixture", NAME, str(seat["token"])],
                                env=seat["env"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_child_exit_preserves_existing_identity(self) -> None:
        seat = self.arrange(True)
        self.failed_launch(seat)
        self.assert_existing(seat)

    def test_early_tmux_failure_preserves_existing_identity(self) -> None:
        seat = self.arrange(True)
        self.failed_launch(seat, early=True)
        self.assert_existing(seat)

    def test_conflicting_handoff_keeps_existing_identity_bytes(self) -> None:
        seat = self.arrange(True)
        before = {key: seat[key].read_bytes() for key in ("token", "state")}
        seat["handoff"] = self.base / "different-handoff"
        seat["handoff"].write_text("different-fixture-only-token")
        seat["handoff"].chmod(0o600)
        self.failed_launch(seat, early=True, require_tmux=False)
        for key, value in before.items():
            self.assertEqual(seat[key].read_bytes(), value, key)
        self.assertTrue(seat["handoff"].is_file())
        self.assert_existing(seat)

    def test_matching_handoff_preserves_existing_state_metadata(self) -> None:
        seat = self.arrange(True)
        state = json.loads(seat["state"].read_text())
        state["fixture_metadata"] = "must remain byte-identical"
        seat["state"].write_text(json.dumps(state, indent=2) + "\n")
        before = seat["state"].read_bytes()
        self.failed_launch(seat, early=True)
        self.assertEqual(seat["state"].read_bytes(), before)

    def test_conflicting_handoff_keeps_state_only_identity(self) -> None:
        seat = self.arrange(True)
        seat["token"].unlink()
        before = seat["state"].read_bytes()
        seat["handoff"] = self.base / "different-handoff"
        seat["handoff"].write_text("different-fixture-only-token")
        seat["handoff"].chmod(0o600)
        self.failed_launch(seat, early=True, require_tmux=False)
        self.assertFalse(seat["token"].exists())
        self.assertEqual(seat["state"].read_bytes(), before)
        self.assertTrue(seat["handoff"].is_file())

    def test_managed_name_only_is_existing_identity(self) -> None:
        seat = self.arrange(False)
        before = f"{NAME}\nOtherSeat\n"
        seat["managed"].write_text(before)
        self.failed_launch(seat)
        self.assertEqual(seat["managed"].read_text(), before)

    def test_parent_trap_preserves_concurrent_identity_inodes(self) -> None:
        seat = self.arrange(False)
        tmux = self.base / "bin/tmux"
        code = tmux.read_text()
        original = "    if os.environ.get('FIXTURE_EARLY_FAILURE') == '1':\n        sys.exit(17)"
        replacement = """    if os.environ.get('FIXTURE_EARLY_FAILURE') == '1':
        runtime = pathlib.Path(os.environ['AGENTSTACK_RUNTIME_DIR'])
        paths = [runtime / 'agent_token_RestartFixture',
                 runtime / 'child-agents/RestartFixture.json']
        for path in paths:
            path.rename(path.with_name(path.name + '.old-inode'))
            path.write_text('concurrent-fixture-owner')
        sys.exit(17)"""
        self.assertIn(original, code)
        tmux.write_text(code.replace(original, replacement))
        self.failed_launch(seat, early=True)
        for key in ("token", "state"):
            self.assertTrue(seat[key].is_file(), key)
            self.assertEqual(seat[key].read_text(), "concurrent-fixture-owner")

    def test_parent_trap_preserves_unowned_home_and_config(self) -> None:
        seat = self.arrange(False)
        tmux = self.base / "bin/tmux"
        code = tmux.read_text()
        original = "    if os.environ.get('FIXTURE_EARLY_FAILURE') == '1':\n        sys.exit(17)"
        replacement = """    if os.environ.get('FIXTURE_EARLY_FAILURE') == '1':
        runtime = pathlib.Path(os.environ['AGENTSTACK_RUNTIME_DIR'])
        home = runtime / 'child-agents/RestartFixture.codex-home'
        config = runtime / 'child-agents/RestartFixture.mcp.json'
        assert not home.exists() and not config.exists()
        home.mkdir()
        (home / 'other-owner-session').write_text('concurrent fixture data')
        config.write_text('concurrent fixture config')
        sys.exit(17)"""
        self.assertIn(original, code)
        tmux.write_text(code.replace(original, replacement))
        self.failed_launch(seat, early=True)
        self.assertTrue((seat["home"] / "other-owner-session").is_file())
        self.assertEqual(seat["config"].read_text(), "concurrent fixture config")

    def test_parent_trap_removes_home_created_by_writer(self) -> None:
        seat = self.arrange(False)
        source = self.enable_proxy(seat)
        self.failed_launch(seat, early=True)
        self.assertFalse(seat["home"].exists())
        self.assertEqual((source / "sentinel").read_text(), "shared fixture remains")

    def test_parent_trap_preserves_replaced_writer_home(self) -> None:
        seat = self.arrange(False)
        self.enable_proxy(seat)
        tmux = self.base / "bin/tmux"
        original = "    if os.environ.get('FIXTURE_EARLY_FAILURE') == '1':\n        sys.exit(17)"
        replacement = """    if os.environ.get('FIXTURE_EARLY_FAILURE') == '1':
        home = pathlib.Path(os.environ['AGENTSTACK_RUNTIME_DIR']) / 'child-agents/RestartFixture.codex-home'
        assert home.exists()
        home.rename(home.with_name(home.name + '.old-inode'))
        home.mkdir()
        (home / 'other-owner-session').write_text('replacement fixture data')
        sys.exit(17)"""
        code = tmux.read_text()
        self.assertIn(original, code)
        tmux.write_text(code.replace(original, replacement))
        self.failed_launch(seat, early=True)
        self.assertEqual((seat["home"] / "other-owner-session").read_text(), "replacement fixture data")

    def test_existing_home_bytes_remain_unchanged_with_proxy(self) -> None:
        seat = self.arrange(True)
        self.enable_proxy(seat)
        config = seat["home"] / "config.toml"
        config.write_text("existing fixture config\n")
        self.failed_launch(seat, early=True)
        self.assertEqual(config.read_text(), "existing fixture config\n")
        self.assert_existing(seat)

    def test_automatic_cleanup_preserves_unowned_home_and_config(self) -> None:
        seat = self.arrange(False)
        tmux = self.base / "bin/tmux"
        original = "    child_env = dict(os.environ)"
        replacement = """    runtime = pathlib.Path(os.environ['AGENTSTACK_RUNTIME_DIR'])
    home = runtime / 'child-agents/RestartFixture.codex-home'
    home.mkdir()
    (home / 'other-owner-session').write_text('concurrent fixture data')
    (runtime / 'child-agents/RestartFixture.mcp.json').write_text('concurrent fixture config')
    child_env = dict(os.environ)"""
        code = tmux.read_text()
        self.assertIn(original, code)
        tmux.write_text(code.replace(original, replacement))
        self.failed_launch(seat)
        self.assertTrue((seat["home"] / "other-owner-session").is_file())
        self.assertEqual(seat["config"].read_text(), "concurrent fixture config")

    def test_mcp_writer_report_without_generation_cannot_authorize_cleanup(self) -> None:
        seat = self.arrange(True)
        self.enable_proxy(seat)
        seat["config"].unlink()
        ownership = self.write_mcp_with_ownership(seat)
        identity = seat["config"].stat()
        self.assertEqual(ownership["owned"], [[str(seat["config"]), identity.st_dev, identity.st_ino, "file"]])
        env = dict(seat["env"], AGENT_NAME=NAME,
                   AGENTSTACK_LAUNCH_AUTH_OWNERSHIP=json.dumps({"observed": []}),
                   AGENTSTACK_LAUNCH_ARTIFACT_OWNERSHIP=json.dumps(ownership))
        subprocess.run(["/bin/bash", str(CLEANUP)], env=env, check=True, timeout=10)
        self.assertTrue(seat["config"].exists())
        self.assertTrue((seat["home"] / "sentinel").is_file())

    def test_mcp_writer_does_not_claim_or_rewrite_existing_file(self) -> None:
        seat = self.arrange(True)
        self.enable_proxy(seat)
        before = seat["config"].read_bytes()
        ownership = self.write_mcp_with_ownership(seat)
        self.assertEqual(ownership["owned"], [])
        self.assertEqual(seat["config"].read_bytes(), before)

    def test_automatic_cleanup_preserves_replaced_writer_config(self) -> None:
        seat = self.arrange(True)
        self.enable_proxy(seat)
        seat["config"].unlink()
        ownership = self.write_mcp_with_ownership(seat)
        seat["config"].rename(seat["config"].with_name("old-config-inode"))
        seat["config"].write_text("replacement fixture config")
        env = dict(seat["env"], AGENT_NAME=NAME,
                   AGENTSTACK_LAUNCH_AUTH_OWNERSHIP=json.dumps({"observed": []}),
                   AGENTSTACK_LAUNCH_ARTIFACT_OWNERSHIP=json.dumps(ownership))
        subprocess.run(["/bin/bash", str(CLEANUP)], env=env, check=True, timeout=10)
        self.assertEqual(seat["config"].read_text(), "replacement fixture config")
        self.assertTrue(seat["token"].is_file())

    def test_early_failure_removes_original_new_identity(self) -> None:
        seat = self.arrange(False)
        self.failed_launch(seat, early=True)
        for key in ("token", "state", "config", "home"):
            self.assertFalse(seat[key].exists(), key)
        self.assertEqual(seat["managed"].read_text(), "OtherSeat\n")

    def test_state_fallback_failure_removes_only_restored_token(self) -> None:
        seat = self.arrange(True)
        seat["token"].unlink()
        seat["state"].chmod(0o600)
        before = seat["state"].read_bytes()
        seat["handoff"] = None
        self.failed_launch(seat, early=True)
        self.assertFalse(seat["token"].exists())
        self.assertEqual(seat["state"].read_bytes(), before)
        self.assertTrue((seat["home"] / "sentinel").is_file())

    def test_state_fallback_does_not_replace_an_existing_empty_token(self) -> None:
        seat = self.arrange(True)
        seat["token"].write_bytes(b"")
        seat["state"].chmod(0o600)
        before = seat["state"].read_bytes()
        seat["handoff"] = None
        self.failed_launch(seat, require_tmux=False)
        self.assertEqual(seat["token"].read_bytes(), b"")
        self.assertEqual(seat["state"].read_bytes(), before)

    def test_automatic_cleanup_preserves_concurrent_identity_inodes(self) -> None:
        seat = self.arrange(True)
        observed = [(str(seat[key]), seat[key].stat().st_dev,
                     seat[key].stat().st_ino) for key in ("token", "state")]
        for key in ("token", "state"):
            path = seat[key]
            path.rename(path.with_name(path.name + ".old-inode"))
            path.write_text("concurrent-fixture-owner")
        env = dict(seat["env"], AGENT_NAME=NAME,
                   AGENTSTACK_LAUNCH_AUTH_OWNERSHIP=json.dumps({"observed": observed}))
        subprocess.run(["/bin/bash", str(CLEANUP)], env=env, check=True, timeout=10)
        for key in ("token", "state"):
            self.assertEqual(seat[key].read_text(), "concurrent-fixture-owner")
        self.assertEqual(seat["managed"].read_text(), f"{NAME}\nOtherSeat\n")

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

    def test_explicit_name_without_generation_preserves_identity(self) -> None:
        seat = self.arrange(True)
        env = dict(seat["env"], AGENT_NAME=NAME, AGENTSTACK_PRESERVE_SEAT_IDENTITY="1",
                   AGENTSTACK_LAUNCH_AUTH_OWNERSHIP=json.dumps({
                       "observed": [(str(seat["token"]), -1, -1)],
                   }))
        subprocess.run(["/bin/bash", str(CLEANUP), NAME], env=env, check=True, timeout=10)
        self.assert_existing(seat)

    def adoption_failure(self, existing: bool) -> None:
        text = SPAWN.read_text()
        match = re.search(r"adopt_child_token_file\(\) \{.*?<<'PY'\n(.*?)\nPY\n", text, re.S)
        self.assertIsNotNone(match)
        runtime = self.base / "runtime"
        runtime.mkdir()
        children = runtime / "child-agents"
        children.mkdir()
        handoff = self.base / "handoff"
        token = runtime / f"agent_token_{NAME}"
        state = children / f"{NAME}.json"
        handoff.write_text(TOKEN)
        handoff.chmod(0o600)
        if existing:
            token.write_text(TOKEN)
            state.write_text(json.dumps({"registration_token": TOKEN,
                                         "agent_name": NAME, "project_key": "/fixture/project",
                                         "fixture_metadata": "retained"}))
        before = {p: p.read_bytes() for p in (token, state) if p.exists()}
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
        for path, payload in before.items():
            self.assertEqual(path.read_bytes(), payload)

    def test_adoption_failure_keeps_existing_identity(self) -> None:
        self.adoption_failure(True)

    def test_adoption_failure_rolls_back_new_identity(self) -> None:
        self.adoption_failure(False)

    def publication_failure(self, replace_token: bool) -> None:
        match = re.search(r"adopt_child_token_file\(\) \{.*?<<'PY'\n(.*?)\nPY\n",
                          SPAWN.read_text(), re.S)
        self.assertIsNotNone(match)
        runtime = self.base / "runtime"
        runtime.mkdir()
        children = runtime / "child-agents"
        children.mkdir()
        handoff = self.base / "handoff"
        token = runtime / f"agent_token_{NAME}"
        state = children / f"{NAME}.json"
        handoff.write_text(TOKEN)
        handoff.chmod(0o600)
        original_link = os.link

        def fail_state(source, destination):
            if destination == state:
                if replace_token:
                    token.unlink()
                    token.write_text("another-fixture-owner")
                raise PermissionError("injected state publication failure")
            return original_link(source, destination)

        argv = ["adopt", NAME, "/fixture/project", str(handoff), str(token), str(state), "true"]
        with patch.object(sys, "argv", argv), patch.object(os, "link", fail_state):
            with self.assertRaises(PermissionError), contextlib.redirect_stdout(io.StringIO()):
                exec(compile(match.group(1), str(SPAWN), "exec"), {})
        self.assertTrue(handoff.is_file())
        self.assertFalse(state.exists())
        self.assertEqual(token.exists(), replace_token)
        if replace_token:
            self.assertEqual(token.read_text(), "another-fixture-owner")
        self.assertEqual(list(self.base.rglob("*.tmp.*")), [])

    def test_state_publication_failure_rolls_back_new_token(self) -> None:
        self.publication_failure(False)

    def test_failed_publication_preserves_a_concurrent_token_owner(self) -> None:
        self.publication_failure(True)


if __name__ == "__main__":
    unittest.main()

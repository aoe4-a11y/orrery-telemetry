"""Exercise the real managed-doc writer against fake inherited config roots."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from user_home_isolation import isolated_user_environment


ROOT = Path(__file__).resolve().parents[1]


class UserHomeIsolationTests(unittest.TestCase):
    def test_inherited_codex_home_cannot_modify_external_agents_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            external = base / "external"
            external.mkdir()
            original = b"external user instructions\n"
            agents = external / "AGENTS.md"
            agents.write_bytes(original)
            inherited = base / "inherited-codex"
            inherited.mkdir()
            (inherited / "AGENTS.md").symlink_to(agents)
            ambient = dict(os.environ, CODEX_HOME=str(inherited))
            env = isolated_user_environment(base / "fixture-home", ambient)
            env.update({
                "AGENTSTACK_HOME": str(base / "fixture-install"),
                "AGENTSTACK_LABEL_PREFIX": "org.agentstack.test.user-home-isolation",
                "AGENTSTACK_TEMPLATE_HOME": str(ROOT),
                "AGENTSTACK_PROJECT_KEY": str(base / "fixture-project"),
            })
            result = subprocess.run(
                ["/bin/bash", str(ROOT / "bin/agentstack-codex-setup")],
                env=env, capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(agents.read_bytes(), original)
            self.assertTrue((inherited / "AGENTS.md").is_symlink())
            written = Path(env["CODEX_HOME"]) / "AGENTS.md"
            self.assertTrue(written.is_file())
            self.assertFalse(written.is_symlink())
            self.assertIn(str(base / "fixture-project"), written.read_text())
            for key in ("HOME", "CODEX_HOME", "CODEX_SHARED_CODEX_DIR",
                        "CLAUDE_HOME", "CLAUDE_CONFIG_DIR"):
                self.assertTrue(Path(env[key]).is_relative_to((base / "fixture-home").resolve()), key)

    def test_fixture_home_symlink_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            outside = base / "outside"
            outside.mkdir()
            home = base / "home"
            home.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                isolated_user_environment(home, {})

    def test_fixture_config_symlink_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            home, outside = base / "home", base / "outside"
            home.mkdir()
            outside.mkdir()
            (home / ".codex").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                isolated_user_environment(home, {})

    def test_ambient_identity_and_runtime_are_not_inherited(self):
        with tempfile.TemporaryDirectory() as temp:
            env = isolated_user_environment(Path(temp), {
                "PATH": "/fixture/bin", "AGENT_NAME": "AmbientSeat",
                "AGENTSTACK_RUNTIME_DIR": "/external/runtime",
                "CHILD_REGISTRATION_TOKEN": "fixture-only-token",
            })
            self.assertEqual(env["PATH"], "/fixture/bin")
            for key in ("AGENT_NAME", "AGENTSTACK_RUNTIME_DIR", "CHILD_REGISTRATION_TOKEN"):
                self.assertNotIn(key, env)


if __name__ == "__main__":
    unittest.main()

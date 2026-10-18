"""SEAT-RESTART-2: real launch/cleanup paths, synthetic identities and fake tmux."""
import json
import os
from pathlib import Path
import subprocess
import unittest

import test_restart_identity as fixture_module
from test_restart_identity import NAME, TOKEN, SPAWN, CLEANUP, executable


class RestartAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.RestartIdentityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_alias_of_canonical_handoff_is_not_consumed(self):
        seat = self.fixture.arrange(True)
        alias = self.fixture.base / 'runtime-alias'
        alias.symlink_to(seat['token'].parent, target_is_directory=True)
        seat['handoff'] = alias / seat['token'].name
        self.fixture.failed_launch(seat, early=True)
        self.fixture.assert_existing(seat)

    def test_automatic_cleanup_without_ownership_preserves_identity(self):
        seat = self.fixture.arrange(True)
        result = subprocess.run(['/bin/bash', str(CLEANUP)],
                                env={**seat['env'], 'AGENT_NAME': NAME},
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.fixture.assert_existing(seat)

    def test_each_preserve_condition_in_isolation(self):
        for only in ['token', 'state', 'config', 'home', 'managed']:
            with self.subTest(only=only):
                # Give every shape independent paths and independent synthetic identity.
                fixture = fixture_module.RestartIdentityTests(); fixture.setUp()
                try:
                    seat = fixture.arrange(True)
                    for key in ['token', 'state', 'config', 'home']:
                        if key != only:
                            if seat[key].is_dir():
                                (seat[key] / 'sentinel').unlink(); seat[key].rmdir()
                            else: seat[key].unlink()
                    if only != 'managed': seat['managed'].write_text('OtherSeat\n')
                    handoff = fixture.base / 'handoff-copy'
                    handoff.write_text(TOKEN); handoff.chmod(0o600); seat['handoff'] = handoff
                    before = seat[only].read_bytes() if only != 'home' else (seat['home']/'sentinel').read_bytes()
                    fixture.failed_launch(seat)
                    after = seat[only].read_bytes() if only != 'home' else (seat['home']/'sentinel').read_bytes()
                    self.assertEqual(before, after)
                finally: fixture.doCleanups()

    def test_standalone_fixture_home_does_not_inherit_live_home(self):
        seat = self.fixture.arrange(False)
        home = Path(seat['env']['HOME']).resolve()
        self.assertTrue(home.is_relative_to(self.fixture.base.resolve()), home)
        self.assertTrue(Path(seat['env']['CODEX_HOME']).is_relative_to(home))


if __name__ == '__main__':
    unittest.main()

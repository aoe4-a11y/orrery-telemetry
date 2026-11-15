"""The restart wrapper preserves a closed seat's identity in an isolated HOME."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RestartIdentityTest(unittest.TestCase):
    def test_closed_seat_reuses_identity_and_preserves_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / 'home'
            stack = home / '.agentstack'
            runtime = stack / 'runtime'
            hooks = stack / 'hooks'
            bin_dir = stack / 'bin'
            for directory in (runtime / 'child-agents', hooks, bin_dir, root / 'fake'):
                directory.mkdir(parents=True, exist_ok=True)
            def executable(path, contents):
                path.write_text(contents)
                path.chmod(0o755)
            executable(bin_dir / 'agentstack-memory-budget', '#!/bin/sh\nexit 0\n')
            executable(hooks / 'seat_lifecycle.py', 'import sys\nassert sys.argv[1] in ("held", "invalidate")\n')
            executable(hooks / 'spawn_child.sh', '#!/bin/bash\nprintf "%s\\n" "$@" > "$TRACE"\n')
            executable(root / 'fake/tmux', '#!/bin/sh\ncase "$1" in has-session) exit 1;; display-message) exit 0;; *) exit 90;; esac\n')
            executable(root / 'fake/sleep', '#!/bin/sh\nexit 0\n')
            token = runtime / 'agent_token_SunnyCurie'
            token.write_text('synthetic')
            state = runtime / 'child-agents/SunnyCurie.json'
            state.write_text(json.dumps({'agent_name': 'SunnyCurie', 'project_key': str(root)}))
            task = root / 'task.md'
            task.write_text('# Synthetic task\n')
            before = state.read_bytes(), token.read_bytes()
            trace = root / 'arguments'
            env = {'HOME': str(home), 'PATH': str(root / 'fake') + ':/usr/bin:/bin',
                   'AGENTSTACK_PROJECT_KEY': str(root), 'TRACE': str(trace)}
            result = subprocess.run(['/bin/bash', str(ROOT / 'bin/agentstack-restart-seat'),
                                     'SunnyCurie', str(task), 'test-model', 'high', str(root)],
                                    env=env, text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            args = trace.read_text().splitlines()
            self.assertEqual(args[args.index('--pre-registered') + 1], 'SunnyCurie')
            self.assertEqual(args[args.index('--child-token-file') + 1], str(token))
            self.assertEqual(args[args.index('--model') + 1], 'test-model')
            self.assertEqual(args[args.index('--effort') + 1], 'high')
            self.assertEqual((state.read_bytes(), token.read_bytes()), before)


if __name__ == '__main__':
    unittest.main()

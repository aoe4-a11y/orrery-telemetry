"""Offline CLI failures retain safe actionable metadata, never raw stderr."""
import errno
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard import managed_spawn
from integrations.dsh import cli_diagnostics as diag

ROOT = Path(__file__).resolve().parents[1]


class DiagnosticsTests(unittest.TestCase):
    def test_exception_details_are_not_serialized(self):
        secret = 'secret-provider-key private-prompt private-argv'
        for exc in (ValueError(secret), KeyError(secret), OSError(errno.EACCES, secret, secret),
                    subprocess.CalledProcessError(1, [secret], secret, secret),
                    subprocess.TimeoutExpired([secret], 1, secret, secret), SystemExit(secret)):
            line = diag.encode('init', exc)
            self.assertNotIn(secret, line)
            row = diag.parse(line, 'init')
            self.assertEqual(row['type'], type(exc).__name__)
            self.assertNotEqual(row['step'], 'unknown')
        self.assertIsNone(diag.parse(diag.encode('init', ValueError(secret)), 'run'))
        row['summary'] = secret
        self.assertIsNone(diag.parse(diag.PREFIX + json.dumps(row), 'init'))

    def test_real_cli_reports_stage_type_and_summary_without_private_path(self):
        with tempfile.TemporaryDirectory(prefix='dsh-cli-diag-') as tmp:
            result = subprocess.run([sys.executable, str(ROOT / 'integrations/dsh/launch.py'),
                                     'init', '--state', tmp + '/state', '--config', tmp + '/PRIVATE-config'],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(len(result.stderr.splitlines()), 1)
            self.assertNotIn(tmp, result.stderr)
            row = diag.parse(result.stderr, 'init')
            self.assertEqual(row['type'], 'FileNotFoundError')
            self.assertIn('ENOENT', row['summary'])

    def test_controller_retains_safe_cli_error_and_init_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'runner.log'
            stderr = 'raw-private-stderr\n' + diag.encode('init', ValueError('PRIVATE'))
            completed = subprocess.CompletedProcess([], 1, 'PRIVATE', stderr)
            with patch.object(managed_spawn, 'worker_environment', return_value={}), patch.object(
                    managed_spawn.subprocess, 'run', return_value=completed):
                run = managed_spawn.command_runner({}, log)
                with self.assertRaises(RuntimeError) as caught:
                    run(['python', '-I', '/product/launch.py', 'init'])
            self.assertEqual(caught.exception.managed_step, 'init')
            self.assertEqual(caught.exception.managed_reason, 'validation_failed')
            saved = json.loads((Path(tmp) / 'cli-last.json').read_text())
            self.assertEqual(saved['diagnostic']['type'], 'ValueError')
            self.assertNotIn('PRIVATE', json.dumps(saved))
            self.assertNotIn('raw-private', json.dumps(saved))

    def test_controller_timeout_keeps_step_without_subprocess_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(managed_spawn, 'worker_environment', return_value={}), patch.object(
                    managed_spawn.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['PRIVATE'], 1, 'PRIVATE', 'PRIVATE')):
                run = managed_spawn.command_runner({}, Path(tmp) / 'runner.log')
                with self.assertRaises(RuntimeError) as caught:
                    run(['python', '-I', '/product/launch.py', 'run'])
            self.assertEqual(caught.exception.managed_step, 'run')
            row = caught.exception.managed_diagnostic
            self.assertEqual(row['type'], 'TimeoutExpired')
            self.assertEqual(row['summary'], 'Subprocess failed (timeout)')
            self.assertNotIn('PRIVATE', json.dumps(row))

    def test_controller_worker_failure_keeps_original_exception_type(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            managed_spawn.save(root / 'manifest.json', {})
            managed_spawn.save(root / 'request.json', {'config_file': str(root / 'manifest.json'),
                'selected_mode': 'legacy', 'request': {'harness': 'dsh', 'parent': 'FixtureParent',
                'dir': tmp, 'allowed_paths': [], 'provider': 'strata', 'task': 'fixture', 'expected': []}})
            managed_spawn.save(root / 'status.json', {'phase': 'queued'})
            def prepare(**kwargs):
                kwargs['run'](['python', '-I', '/product/launch.py', 'init'])
            adapter = SimpleNamespace(prepare=prepare)
            source = {'project_key': str(root.resolve())}
            result = subprocess.CompletedProcess([], 1, '', diag.encode('init', ValueError('PRIVATE')))
            with patch.object(managed_spawn, 'trusted_selection', return_value=({}, source)), patch.object(
                    managed_spawn, 'worker_environment', return_value={}), patch.object(
                    managed_spawn.subprocess, 'run', return_value=result):
                run = managed_spawn.command_runner({}, root / 'runner.log')
                managed_spawn.run_job(root, adapter=adapter, run=run,
                    parent_call=lambda *a: {'name': 'FixtureParent'}, provider_loader=lambda *a, **k: [])
            failure = managed_spawn.read(root / 'worker-failure.json')
            self.assertEqual(failure['step'], 'init')
            self.assertEqual(failure['type'], 'ValueError')
            self.assertEqual(failure['summary'], 'Invalid run configuration or state')
            self.assertNotIn('PRIVATE', json.dumps(failure))


if __name__ == '__main__':
    unittest.main()

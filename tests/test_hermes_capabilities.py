"""Native effort declarations are data; catalog reads never execute Hermes."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import shutil
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard import managed_capabilities as capabilities
from dashboard import managed_catalog as catalog


class HermesCapabilities(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.template = {'hermes_source': str(self.source), 'profiles': {'deepseek': {}, 'strata': {}}}
        self.write('hermes_constants.py', 'raise RuntimeError("must never import")\nVALID_REASONING_EFFORTS = ("low", "medium", "high", "max", "ultra")\n')
        self.write('agent/reasoning_effort.py', 'OPENAI_COMPAT_WIRE_EFFORTS = ("none", "low", "medium", "high", "max")\n')
        self.write('plugins/model-providers/custom/__init__.py', '''raise RuntimeError("must never import")
class CustomProfile:
    def supported_reasoning_efforts(self, model):
        return OPENAI_COMPAT_WIRE_EFFORTS
    def default_reasoning_config(self, model=None):
        return {"enabled": True, "effort": "medium"}
''')

    def write(self, name, text):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def load(self, backend='deepseek'):
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('no process')), \
                patch.object(socket, 'socket', side_effect=AssertionError('no network')):
            return capabilities.load_effort_capability(self.template, harness='hermes', backend_id=backend, model='fixture-model')

    def test_source_not_saved_override_supplies_vocabulary_and_default(self):
        self.template['profiles']['deepseek']['reasoning_effort'] = 'low'
        expected = {'efforts': ['low', 'medium', 'high', 'max'], 'default_effort': 'medium', 'effort_source': 'harness'}
        self.assertEqual(self.load(), expected)
        self.assertEqual(self.load('strata'), expected)
        # A new upstream declaration is used directly, without copied product levels.
        self.write('hermes_constants.py', 'VALID_REASONING_EFFORTS = ("medium", "high")\n')
        self.assertEqual(self.load()['efforts'], ['medium', 'high'])
        self.assertEqual(self.load('missing'), capabilities.UNKNOWN)

    def test_unknown_or_changed_policy_never_reuses_known_values(self):
        self.assertEqual(self.load()['effort_source'], 'harness')
        self.write('plugins/model-providers/custom/__init__.py', '''class CustomProfile:
    def supported_reasoning_efforts(self, model):
        return OPENAI_COMPAT_WIRE_EFFORTS
    def default_reasoning_config(self, model=None):
        if model:
            return {"enabled": True, "effort": "high"}
        return None
''')
        self.assertEqual(self.load(), capabilities.UNKNOWN)
        self.write('hermes_constants.py', 'not valid python!')
        self.assertEqual(self.load(), capabilities.UNKNOWN)

    def test_standard_catalog_projects_hermes_only_on_its_model_harness_row(self):
        template = self.root / 'template.json'
        template.write_text(json.dumps(self.template))
        manifest = self.root / 'manifest.json'
        manifest.write_text(json.dumps({'enabled': True, 'harnesses': {},
            'backends': {'deepseek': {'model': 'fixture-model'}, 'strata': {'model': 'fixture-local'}}}))
        def selection(path, harness, backend, model):
            if harness != 'hermes':
                raise ValueError('runtime_not_prepared')
            return {'config_file': str(template)}
        with patch.object(catalog, '_thin_selection', side_effect=selection), patch.object(catalog.sys, 'platform', 'darwin'):
            rows = catalog.standard_catalog(manifest, mode='legacy')
        for row in rows:
            dsh, hermes = row['models'][0]['harnesses']
            self.assertIsNone(dsh['efforts'])
            self.assertEqual(hermes['efforts'], ['low', 'medium', 'high', 'max'])
            self.assertEqual(hermes['default_effort'], 'medium')
            self.assertEqual(hermes['effort_source'], 'harness')
        for harness in ('claude', 'codex', 'unknown'):
            self.assertEqual(capabilities.load_effort_capability(self.template, harness=harness, backend_id='deepseek', model='fixture-model'), capabilities.UNKNOWN)

    def test_fixed_native_source_is_read_without_imports_or_credentials(self):
        source = os.environ.get('ORRERY_HERMES_TEST_SOURCE')
        if not source:
            self.skipTest('Explicit installed dependency interpreter/source required')
        self.template['hermes_source'] = source
        self.assertEqual(self.load(), {'efforts': ['minimal', 'low', 'medium', 'high', 'xhigh', 'max'],
                                      'default_effort': 'medium', 'effort_source': 'harness'})

    def test_installed_dashboard_only_import_and_metadata_from_root_directory(self):
        installed = self.root / 'installed/dashboard'
        installed.mkdir(parents=True)
        repo = Path(__file__).resolve().parents[1]
        for name in ('managed_capabilities.py', 'managed_catalog.py', 'harness_helpers.py'):
            shutil.copyfile(repo / 'dashboard' / name, installed / name)
        self.template['hermes_source'] = os.environ.get('ORRERY_HERMES_TEST_SOURCE', str(self.source))
        expected = self.load()
        script = '''import json,sys
sys.path.insert(0,sys.argv[1])
def audit(event,args):
    if event in ('subprocess.Popen','socket.connect','socket.getaddrinfo'):
        raise AssertionError('No process, credential helper or network during catalog read')
sys.addaudithook(audit)
import managed_catalog
print(json.dumps(managed_catalog.load_effort_capability(json.loads(sys.argv[2]),
    harness='hermes',backend_id='deepseek',model='fixture-model')))
'''
        home = self.root / 'empty-home'
        home.mkdir()
        result = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(installed), json.dumps(self.template)],
            cwd='/', env={'HOME': str(home), 'PATH': os.defpath}, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), expected)


if __name__ == '__main__':
    unittest.main()

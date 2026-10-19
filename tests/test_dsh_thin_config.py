"""Thin generator: no upstream import, provider request or key retrieval."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('thin_dsh', ROOT / 'integrations/dsh/thin_config.py')
thin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(thin)


class ThinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.product = self.root / 'product'
        self.integration = self.product / 'integrations/dsh'
        self.integration.mkdir(parents=True)
        for plugin in ('orrery_tools.mjs', 'keychain_credentials.mjs'):
            # Static validation must not execute a plugin, even a broken one.
            (self.integration / plugin).write_text('throw new Error("MUST_NOT_IMPORT")')
        self.node = self.root / 'fixed-node'
        self.node.write_text('synthetic node; must not execute')
        self.node.chmod(0o700)
        self.runtime = self.root / 'generation/runtime'
        pins = thin.read(ROOT / 'integrations/dsh/runtime-pins.json')
        thin.save(self.integration / 'runtime-pins.json', pins)
        for pin in pins:
            thin.save(self.runtime / 'node_modules' / pin['name'] / 'package.json', {'version': pin['version']})
        entry = self.runtime / 'node_modules/@deepseek-ai/dsh/lib/bin.js'
        entry.parent.mkdir()
        entry.write_text('native CLI fixture')
        thin.save(self.runtime.parent / 'evidence/node-runtime.json', {
            'version': 'v24.3.0', 'execPath': str(self.node),
            'sha256': hashlib.sha256(self.node.read_bytes()).hexdigest()})
        source = self.runtime / 'node_modules/@deepseek-harness-tui/dsh-tui/lib/native.js'
        source.parent.mkdir()
        source.write_text('unmodified native fixture')
        native = self.runtime.parent / 'evidence/upstream-runtime.json'
        thin.save(native, {'variant': 'plain', 'source_patch': None,
            'files': [{'file': 'lib/native.js', 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}]})
        owner = self.runtime.parent / '.orrery-managed-install.json'
        thin.save(owner, {'harness': 'dsh', 'complete': True, 'variant': 'plain', 'thin_config_contract': 1,
            'details': {'node': str(self.node), 'runtime': str(self.runtime), 'runtime_receipt': str(native)}})
        backends = self.root / 'backends.json'
        thin.save(backends, {'backends': {'strata': {'base_url': 'https://strata.invalid', 'model': 'a',
            'keychain': {'service': 'fixture-service', 'account': 'fixture-account'},
            'model_definition': {'id': 'a', 'contextWindow': 131072}}}})
        self.template = self.root / 'template.json'
        thin.save(self.template, {'node': str(self.node), 'runtime': str(self.runtime),
            'generation_receipt': str(owner), 'backend_file': str(backends)})
        self.manifest = self.root / 'manifest.json'
        thin.save(self.manifest, {'enabled': True, 'backends': {'strata': {'model': 'a', 'models': ['a', 'b']}},
            'harnesses': {'dsh': {'config_file': str(self.template)}}})
        self.state = self.root / 'state'
        self.state.mkdir()
        prompt, instructions, mcp = [self.root / f for f in ('prompt.txt', 'instructions.md', 'mcp.json')]
        prompt.write_text('')
        instructions.write_text('shared rendered instructions')
        thin.save(mcp, {'mcpServers': {'orrery-mail': {'command': '/canonical/proxy', 'args': ['--stdio'],
            'env': {'AGENTSTACK_PROXY_PROGRAM': 'dsh'}}}})
        self.doc = dict(manifest_file=str(self.manifest), product_root=str(self.product), backend_id='strata',
            model='a', agent_name='ChildA', cwd=str(self.root), state_dir=str(self.state), runtime_dir=str(self.root),
            mcp_config=str(mcp), prompt_file=str(prompt), instructions_file=str(instructions), env={'AGENT_NAME': 'ChildA'},
            mcp_selection={'servers': {}, 'inherit': False, 'approved': {}, 'enabled_tools': {}})

    def rows(self, plan):
        return thin.read(Path(plan['config_dir']) / 'native.patch.json')

    def test_native_plan_omits_trial_policy_preserves_proxy_and_instructions(self):
        with patch('subprocess.run', side_effect=AssertionError('subprocess forbidden')):
            plan = thin.generate(self.doc)
        self.assertEqual(plan['argv'][:2], [str(self.node), str(self.runtime / 'node_modules/@deepseek-ai/dsh/lib/bin.js')])
        self.assertEqual(set(plan['env']), {'DSH_HOME', 'AGENTSTACK_LLM_KEY_FILES', 'AGENTSTACK_LLM_KEY_DEFINITIONS'})
        rows = self.rows(plan)
        self.assertFalse(any(row.get('disabled') for row in rows))
        self.assertIn('credentials', next(row for row in rows if row.get('id') == 'llm-deepseek')['inject'])
        text = json.dumps(rows)
        for absent in ('maxTokens', 'maxRetries', 'session_requests', 'scope_mode', 'managed_plugin', 'egress.mjs'):
            self.assertNotIn(absent, text)
        proxy = next(r for row in rows for r in row.get('insert', []) if r['id'] == 'orrery-mcp-orrery-mail')
        self.assertEqual(proxy['config']['command'], '/canonical/proxy')
        self.assertEqual(proxy['config']['env']['AGENTSTACK_PROXY_PROGRAM'], 'dsh')
        self.assertEqual((Path(plan['env']['DSH_HOME']) / 'AGENTS.md').read_text(), 'shared rendered instructions')
        self.assertNotIn('HOME', plan['env'])
        self.assertEqual(plan, thin.generate(self.doc))

    def test_model_helper_effort_and_exact_resume_are_projected(self):
        self.doc.update(model='b', helper_model='a', effort='high', resume_session_id='own-session')
        Path(self.doc['prompt_file']).write_text('literal `x` $(x)\nnext')
        plan = thin.generate(self.doc)
        rows = self.rows(plan)
        self.assertEqual(next(r for r in rows if r.get('id') == 'agent-default-model')['config']['model'], 'b')
        self.assertEqual(next(r for r in rows if r.get('id') == 'tool-subagent')['config']['agentOptions']['model'], 'a')
        self.assertEqual(plan['argv'][-4:], ['--resume', 'own-session', '--', 'literal `x` $(x)\nnext'])

    def test_unknown_model_helper_or_empty_resume_refused(self):
        for key, value, reason in [('model', 'unknown', 'model_mismatch'), ('helper_model', 'other/model', 'invalid_helper_model'),
                                   ('resume_session_id', '', 'invalid_resume_session_id')]:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, reason):
                thin.generate({**self.doc, key: value})

    def test_old_managed_generation_and_missing_key_plugin_are_not_ready(self):
        plugin = self.integration / 'keychain_credentials.mjs'
        plugin.unlink()
        with self.assertRaisesRegex(ValueError, 'credential_adapter_unavailable'):
            thin.validate_input(self.doc)
        plugin.write_text('synthetic file')
        template = thin.read(self.template)
        owner = thin.read(template['generation_receipt'])
        owner.pop('variant')
        thin.save(template['generation_receipt'], owner)
        with self.assertRaisesRegex(ValueError, 'plain_runtime_required'):
            thin.validate_input(self.doc)

    def test_selection_subset_is_read_only_and_package_node_changes_are_refused(self):
        subset = {k: self.doc[k] for k in ('manifest_file', 'product_root', 'backend_id', 'model')}
        self.assertEqual(thin.validate_input(subset)['node'], self.node)
        self.assertEqual(list(self.state.iterdir()), [])
        self.node.write_text('changed node')
        with self.assertRaisesRegex(ValueError, 'invalid_runtime'):
            thin.validate_input(subset)

    def test_unsupported_mcp_filters_refused_and_http_copied(self):
        for field in ('approved', 'enabled_tools'):
            self.doc['mcp_selection'][field] = {'server': ['tool']}
            with self.assertRaisesRegex(ValueError, 'unsupported_mcp_selection'):
                thin.generate(self.doc)
            self.doc['mcp_selection'][field] = {}
        thin.save(self.doc['mcp_config'], {'mcpServers': {'extra': {'type': 'http', 'url': 'http://127.0.0.1:1234/mcp'}}})
        plan = thin.generate(self.doc)
        row = next(r for block in self.rows(plan) for r in block.get('insert', []) if r['id'] == 'orrery-mcp-extra')
        self.assertEqual(row['config']['transport'], 'streamable-http')

    def test_mail_only_rejects_unknown_home_layer_instead_of_promising_no_inheritance(self):
        plan = thin.generate(self.doc)
        inherited = Path(plan['env']['DSH_HOME']) / 'cordis.patch.yml'
        inherited.write_text('- insert: [{name: arbitrary-plugin}]')
        with self.assertRaisesRegex(ValueError, 'inherited_mcp_conflict'):
            thin.generate(self.doc)

    def test_cli_failure_is_one_fixed_reason_without_input_content(self):
        Path(self.doc['prompt_file']).write_text('PRIVATE_PROMPT')
        self.doc['backend_id'] = 'PRIVATE_PROVIDER'
        source, target = self.root / 'input.json', self.root / 'plan.json'
        thin.save(source, self.doc)
        result = subprocess.run([sys.executable, str(ROOT / 'integrations/dsh/thin_config.py'),
                                 '--input', str(source), '--out', str(target)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, 'DSH_THIN_CONFIG_ERROR=unknown_backend\n')
        self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()

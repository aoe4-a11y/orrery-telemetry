"""Native hook adaptation with real common key guard and synthetic tool bodies."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import shlex
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from integrations.hermes import thin_guard as guard

ROOT = Path(__file__).resolve().parents[1]


class ThinGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.core = self.base / 'core'
        (self.core / 'hooks').mkdir(parents=True)
        for name in ('check-agent-registered.sh', 'check-file-reservation.sh'):
            (self.core / 'hooks' / name).write_text('#!/bin/sh\nexit 0\n')
        shutil.copyfile(ROOT / 'hooks/deny-llm-key-read.py', self.core / 'hooks/deny-llm-key-read.py')
        definitions = self.base / 'definitions.json'
        self.helper = self.base / 'key-helper'
        self.helper.write_text('#!/bin/sh\ntouch ' + str(self.base / 'helper-was-called') + '\n')
        self.helper.chmod(0o700)
        definitions.write_text(json.dumps({'backends': {'fixture': {'auth_command': [str(self.helper), '--fixture']}}}))
        self.enterContext(patch.dict(os.environ, {'HOME': str(self.base), 'PATH': os.defpath,
            'AGENTSTACK_HOME': str(self.core), 'AGENTSTACK_LLM_KEY_DEFINITIONS': str(definitions),
            'AGENTSTACK_NATIVE_SESSION_FILE': str(self.base / 'native-session.json')}, clear=True))
        self.enterContext(patch.object(guard, '_cwd', return_value=str(self.base)))

    def test_native_credential_tool_denied_before_real_helper_execution(self):
        command = str(self.helper) + ' --fixture'
        result = guard.before('terminal', {'command': command}, session_id='own-session')
        if result is None:
            subprocess.run([str(self.helper), '--fixture'], check=True)
        self.assertEqual(result['action'], 'block')
        self.assertFalse((self.base / 'helper-was-called').exists())
        self.assertNotIn(command, result['message'])

    def test_registration_veto_precedes_reservation_and_tool(self):
        (self.core / 'hooks/check-agent-registered.sh').write_text('echo unresolved >&2\nexit 2\n')
        (self.core / 'hooks/check-file-reservation.sh').write_text('touch ' + str(self.base / 'reservation-called') + '\n')
        result = guard.before('write_file', {'path': 'file.txt', 'content': 'never'})
        self.assertEqual(result, {'action': 'block', 'message': 'unresolved'})
        self.assertFalse((self.base / 'reservation-called').exists())
        self.assertFalse((self.base / 'file.txt').exists())

    def test_common_reservation_veto_blocks_all_patch_targets_before_writes(self):
        events = []
        def run(argv, **kwargs):
            payload = json.loads(kwargs['input'])
            events.append((Path(argv[-1]).name, payload))
            denied = Path(argv[-1]).name == 'check-file-reservation.sh' and payload['tool_input']['file_path'].endswith('/destination')
            return SimpleNamespace(returncode=2 if denied else 0, stderr='reservation conflict' if denied else '')
        with patch.object(guard.subprocess, 'run', side_effect=run):
            result = guard.before('patch', {'mode': 'patch', 'patch': '*** Move File: source -> destination\n'}, session_id='own-session')
        self.assertEqual(result['action'], 'block')
        checked = [payload['tool_input']['file_path'] for name, payload in events if name == 'check-file-reservation.sh']
        self.assertEqual(checked, [str(self.base / 'source'), str(self.base / 'destination')])
        self.assertTrue(all(payload['session_id'] == 'own-session' for _, payload in events))

    def test_non_veto_error_matches_normal_hook_contract(self):
        (self.core / 'hooks/check-agent-registered.sh').write_text('exit 1\n')
        self.assertIsNone(guard.before('terminal', {'command': 'echo harmless'}))

    def test_real_common_reservation_hook_missing_expired_conflict_and_allowed(self):
        from test_check_file_reservation import _Server, _mcp_result
        wrapper = self.core / 'hooks/check-file-reservation.sh'
        wrapper.write_text('exec /bin/bash ' + shlex.quote(str(ROOT / 'hooks/check-file-reservation.sh')) + '\n')
        runtime = self.base / 'runtime'
        runtime.mkdir()
        (runtime / 'agent_token_FixtureAgent').write_text('synthetic-owner-token')
        env = {'AGENT_NAME': 'FixtureAgent', 'AGENTSTACK_PROJECT_KEY': str(self.base),
               'AGENTSTACK_PROTECTED_ROOTS': str(self.base), 'AGENTSTACK_RUNTIME_DIR': str(runtime),
               'AGENTSTACK_HOOKS_DIR': str(self.core / 'hooks'), 'AGENTSTACK_PYTHON': sys.executable,
               'AGENTSTACK_MAIL_HTTP_BEARER_MODE': 'disabled', 'FILE_RESERVATION_RETRY_DELAY_SECONDS': '0'}
        for state in ('missing', 'expired', 'conflict', 'allowed'):
            response = json.loads(_mcp_result(1 if state in ('conflict', 'allowed') else 0))
            if state == 'conflict':
                response['result']['structuredContent']['conflict_check']['conflicts'] = [
                    {'agent': 'OtherAgent', 'path_pattern': 'native.txt'}]
            with self.subTest(state=state), _Server(lambda _: (200, json.dumps(response).encode())) as server:
                with patch.dict(os.environ, {**env, 'AGENTSTACK_MCP_URL': server.url}):
                    result = guard.before('write_file', {'path': 'native.txt', 'content': state}, session_id='own-session')
                target = self.base / 'native.txt'
                if result is None:
                    target.write_text(state)  # native handler is reached only after pre-tool approval
                self.assertEqual(result is None, state == 'allowed', result)
                self.assertEqual(target.exists(), state == 'allowed')
                self.assertTrue(server.requests)
        self.assertEqual((self.base / 'native.txt').read_text(), 'allowed')

    def test_registered_hook_timeout_is_not_reported_as_allow(self):
        with patch.object(guard.subprocess, 'run', side_effect=subprocess.TimeoutExpired('fixture', 60)):
            with self.assertRaises(subprocess.TimeoutExpired):
                guard.before('write_file', {'path': 'file.txt', 'content': 'never'})

    def test_native_base_cwd_and_relative_read_mapping(self):
        payload = next(guard.payloads('read_file', {'path': 'provider.json'}, cwd=str(self.base / 'changed'), session_id='s'))
        self.assertEqual(payload['tool_input']['file_path'], str(self.base / 'changed/provider.json'))
        self.assertEqual(payload['tool_name'], 'Read')

    def test_session_event_is_own_id_not_delegation_or_mru(self):
        context = ModuleType('agent.delegation_context')
        context.is_delegated_child_context = lambda: False
        with patch.dict(sys.modules, {'agent.delegation_context': context}):
            guard.session_started('own-exact-session')
            path = self.base / 'native-session.json'
            self.assertEqual(json.loads(path.read_text())['native_session_id'], 'own-exact-session')
            context.is_delegated_child_context = lambda: True
            guard.session_started('delegated-child')
            self.assertEqual(json.loads(path.read_text())['native_session_id'], 'own-exact-session')
            path.unlink()
            path.mkdir()
            context.is_delegated_child_context = lambda: False
            guard.session_started('not-persistable')  # optional metadata cannot kill startup

    def test_register_only_adds_native_hooks_no_preflight(self):
        hooks = {}
        guard.register(SimpleNamespace(register_hook=lambda name, fn: hooks.setdefault(name, fn)))
        self.assertEqual(set(hooks), {'pre_tool_call', 'on_session_start'})


if __name__ == '__main__':
    unittest.main()

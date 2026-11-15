"""Retained canonical seats must not need a one-shot handoff sidecar."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('up7_child_resume', ROOT / 'hooks/child_resume.py')
resume = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resume)


class RetainedRegistrationTest(unittest.TestCase):
    def test_legacy_owner_check_uses_existing_id_with_mocked_transport(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); runtime = root / 'runtime'; runtime.mkdir()
            states = runtime / 'child-agents'; states.mkdir()
            state = states / 'SunnyCurie.json'
            state.write_text(json.dumps({'agent_name': 'SunnyCurie', 'project_key': '/fixture',
                'registration_token': 'synthetic'})); state.chmod(0o600)
            token = runtime / 'agent_token_SunnyCurie'
            token.write_text('synthetic'); token.chmod(0o600)
            fake = root / 'sitecustomize.py'
            fake.write_text('''import http.client, json, os
class Response:
    def __init__(self, data): self.data = data
    def read(self): return json.dumps(self.data).encode()
class Connection:
    def __init__(self, *args, **kwargs): pass
    def request(self, method, path, body, headers):
        request = json.loads(body)
        if request['method'] == 'tools/list':
            result = {'tools': [{'name': 'register_agent', 'inputSchema': {'properties': {'existing_agent_id': {}}}}]}
        elif request['params']['name'] == 'whois':
            result = {'structuredContent': {'id': 11, 'name': 'SunnyCurie', 'program': os.getenv('TEST_PROGRAM','codex')}}
        else:
            arguments = request['params']['arguments']
            assert arguments['existing_agent_id'] == 11 and arguments['name'] == 'SunnyCurie'
            assert arguments['registration_token'] == 'synthetic'
            result = {'structuredContent': {'id': 12 if os.getenv('BAD_OWNER') else 11, 'name': 'SunnyCurie', 'program': os.getenv('TEST_PROGRAM','codex'), 'project_id': 1}}
        self.response = Response({'result': result})
    def getresponse(self): return self.response
    def close(self): pass
http.client.HTTPConnection = Connection
''')
            source = (ROOT / 'hooks/spawn_child.sh').read_text()
            start = source.index('authenticate_legacy_claude_child() {')
            end = source.index('\n# What the child\'s state says', start)
            script = 'legacy_http_bearer_enabled() { return 1; }\n' + source[start:end] + '\nauthenticate_legacy_claude_child SunnyCurie codex\n'
            env = {'HOME': str(root), 'PATH': '/usr/bin:/bin', 'PYTHONPATH': str(root),
                   'RUNTIME_DIR': str(runtime), 'CHILD_STATE_DIR': str(states),
                   'PROJECT_KEY': '/fixture', 'MCP_URL': 'http://127.0.0.1:1/mcp',
                   'AGENTSTACK_PYTHON': '/usr/bin/python3'}
            script = 'child_token_file_path() { printf "%s/agent_token_%s\\n" "$RUNTIME_DIR" "$1"; }\n' + script
            result = subprocess.run(['/bin/bash', '-c', script], env=env, text=True,
                                    capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), '11\tcodex')
            env['TEST_PROGRAM'] = 'codex-cli'
            alias = subprocess.run(['/bin/bash', '-c', script], env=env, text=True,
                                   capture_output=True, timeout=30)
            self.assertEqual(alias.returncode, 0, alias.stderr)
            self.assertEqual(alias.stdout.strip(), '11\tcodex-cli')
            env['BAD_OWNER'] = '1'
            wrong = subprocess.run(['/bin/bash', '-c', script], env=env, text=True,
                                   capture_output=True, timeout=30)
            self.assertNotEqual(wrong.returncode, 0)
            self.assertFalse(wrong.stdout.strip())

    def test_authenticated_legacy_codex_state_keeps_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            state = runtime / 'child-agents/SunnyCurie.json'; state.parent.mkdir()
            token = runtime / 'agent_token_SunnyCurie'
            token.write_text('synthetic'); token.chmod(0o600)
            state.write_text(json.dumps({'agent_name': 'SunnyCurie',
                'project_key': '/fixture', 'registration_token': 'synthetic'})); state.chmod(0o600)
            with self.assertRaises(resume.ResumeStateError):
                resume.stage_registration(runtime, 'SunnyCurie', project_key='/fixture',
                    program='codex', generation='c' * 32, legacy_agent_id=11)
            result = resume.stage_registration(runtime, 'SunnyCurie', project_key='/fixture',
                program='codex', generation='c' * 32, legacy_agent_id=11,
                verified_legacy_codex=True)
            self.assertEqual(result, token)
            self.assertEqual(json.loads(state.read_text())['agent_id'], 11)
            self.assertEqual(json.loads(state.read_text())['program'], 'codex')

    def test_authenticated_codex_cli_alias_keeps_its_program(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime=Path(temporary); state=runtime/'child-agents/SunnyCurie.json'; state.parent.mkdir()
            token=runtime/'agent_token_SunnyCurie'; token.write_text('synthetic'); token.chmod(0o600)
            state.write_text(json.dumps({'agent_name':'SunnyCurie','project_key':'/fixture',
                                         'registration_token':'synthetic'}));state.chmod(0o600)
            resume.stage_registration(runtime,'SunnyCurie',project_key='/fixture',program='codex-cli',
                generation='d'*32,legacy_agent_id=11,verified_legacy_codex=True)
            self.assertEqual(json.loads(state.read_text())['program'],'codex-cli')

    def test_formal_canonical_state_without_sidecar(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            state = runtime / 'child-agents/SunnyCurie.json'
            state.parent.mkdir()
            token = runtime / 'agent_token_SunnyCurie'
            token.write_text('synthetic'); token.chmod(0o600)
            state.write_text(json.dumps({'agent_id': 11, 'agent_name': 'SunnyCurie',
                'project_key': '/fixture', 'program': 'codex', 'registration_token': 'synthetic'}))
            state.chmod(0o600)
            staged = resume.stage_registration(runtime, 'SunnyCurie', project_key='/fixture',
                program='codex', generation='a' * 32, source=token,
                binding=token.with_name(token.name + '.binding.json'))
            self.assertEqual(staged, token)
            self.assertEqual(json.loads(state.read_text())['agent_id'], 11)

    def test_mismatch_external_handoff_and_dangling_sidecar_fail_closed(self):
        for case in ('mismatch', 'external', 'dangling'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                runtime = Path(temporary)
                state = runtime / 'child-agents/SunnyCurie.json'; state.parent.mkdir()
                token = runtime / 'agent_token_SunnyCurie'
                token.write_text('synthetic'); token.chmod(0o600)
                state.write_text(json.dumps({'agent_id': 11, 'agent_name': 'SunnyCurie',
                    'project_key': '/fixture', 'program': 'codex',
                    'registration_token': 'different' if case == 'mismatch' else 'synthetic'}))
                state.chmod(0o600)
                before = state.read_bytes(), token.read_bytes()
                source = token
                if case == 'external':
                    source = runtime / 'one-shot'; source.write_text('synthetic'); source.chmod(0o600)
                binding = source.with_name(source.name + '.binding.json')
                if case == 'dangling':
                    binding.symlink_to(runtime / 'missing')
                with self.assertRaises(resume.ResumeStateError):
                    resume.stage_registration(runtime, 'SunnyCurie', project_key='/fixture',
                        program='codex', generation='b' * 32, source=source, binding=binding)
                self.assertEqual((state.read_bytes(), token.read_bytes()), before)


if __name__ == '__main__':
    unittest.main()

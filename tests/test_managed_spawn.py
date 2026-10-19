"""Offline API/job boundaries; fake adapters never invoke a product or provider."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

from dashboard import managed_spawn as m


class Adapter:
    def __init__(self, job, *, broken=False, finalize_error=False):
        self.job, self.calls, self.tick = job, [], 0
        self.broken, self.finalize_error = broken, finalize_error
    def prepare(self, **kwargs):
        self.calls.append('prepare')
        self.kwargs = kwargs
        Path(kwargs['state']).mkdir()
    def start(self, state, *, run):
        self.calls.append('start')
        return SimpleNamespace(poll=lambda: 0)  # Wrapper already finished!
    def status(self, state):
        self.tick += 1
        if self.tick == 2:
            assert m.read(self.job / 'status.json')['state'] == 'pending'
        return {'agent_name': 'TestChild', 'runtime_attempt_id': 'runtime-generated',
                'ready': self.tick > 1 and not self.broken,
                'terminal': self.tick > 2, 'task_success': None, 'runtime_success': None}
    def finalize(self, state, *, parent_call, run):
        self.calls.append('finalize')
        if self.finalize_error:
            raise RuntimeError('no proof')
        return {'task_success': not self.broken, 'runtime_success': True}
    def clean(self, state, *, run):
        self.calls.append('clean')


class ManagedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root / 'source'; self.source.mkdir()
        (self.source / 'result.txt').write_text('original')
        self.backend = self.root / 'backend.json'
        m.save(self.backend, {'backends': {b: {'model': b + '-model', 'effort': 'low'} for b in m.PROVIDERS}})
        self.template = self.root / 'template.json'
        m.save(self.template, {'home': str(self.root / 'home'), 'project_key': str(self.root / 'project'),
                  'backend_file': str(self.backend), 'profiles': {b: {'model': b + '-model'} for b in m.PROVIDERS}})
        self.config = self.root / 'manifest.json'
        m.save(self.config, {'enabled': True, 'state_root': str(self.root / 'jobs'),
            'harnesses': {h: {'config_file': str(self.template), 'python': '/usr/bin/python3'} for h in m.HARNESSES}})
        self.providers = [{'id': b, 'efforts': ['off', 'low', 'high', 'max'],
            'models': [{'id': b + '-model', 'harnesses': [{'id': h, 'available': True, 'interactive': True, 'efforts': ['off', 'low', 'high', 'max']} for h in m.HARNESSES]}]}
            for b in m.PROVIDERS]
        self.spawn_calls = []
        def spawn(*args, **kwargs):
            self.spawn_calls.append((args, kwargs)); return SimpleNamespace(pid=1234)
        self.loader = lambda *a, **k: self.providers
        self.manager = m.Manager(self.config, provider_loader=self.loader, spawn=spawn)
    def payload(self, provider='strata', harness='dsh'):
        return {'attempt_id': str(uuid.uuid4()), 'provider': provider, 'harness': harness,
                'model': provider + '-model', 'parent': 'TestParent', 'task': 'write scoped result',
                'dir': str(self.source), 'allowed_paths': ['result.txt'],
                'expected': [{'path': 'result.txt', 'contains': 'done'}]}
    def parent_call(self, tool, args):
        self.assertEqual(tool, 'whois'); return {'name': args['name'], 'retired_at': None}
    def test_four_combinations_cleanup_and_wrapper_not_ready(self):
        for provider in m.PROVIDERS:
            for harness in m.HARNESSES:
                with self.subTest(provider=provider, harness=harness):
                    request = self.payload(provider, harness)
                    accepted = self.manager.submit(request)
                    self.assertEqual(accepted['state'], 'pending')
                    self.assertIsNone(accepted['cleanup_success'])
                    job = self.root / 'jobs' / request['attempt_id']
                    adapter = Adapter(job)
                    final = m.run_job(job, adapter=adapter, parent_call=self.parent_call,
                                      run=object(), sleep=lambda _: None, provider_loader=self.loader)
                    self.assertEqual(adapter.calls, ['prepare', 'start', 'finalize', 'clean'])
                    self.assertTrue(final['task_success']); self.assertTrue(final['runtime_success'])
                    self.assertTrue(final['finished']); self.assertEqual(final['phase'], 'cleaned')
                    self.assertTrue(final['cleanup_success'])
                    self.assertTrue(self.manager.lookup(request['attempt_id'])['cleanup_success'])
                    self.assertNotEqual(final['attempt_id'], final['runtime_attempt_id'])
                    self.assertEqual((job / 'work/result.txt').read_text(), 'original')
                    self.assertEqual((self.source / 'result.txt').read_text(), 'original')
    def test_retry_and_restart_reuse_job_not_identity(self):
        request = self.payload(); self.manager.submit(request)
        again = m.Manager(self.config, provider_loader=self.loader, spawn=lambda *a, **k: self.fail('second worker'))
        self.assertEqual(again.submit(request)['attempt_id'], request['attempt_id'])
        self.assertEqual(len(self.spawn_calls), 1)
        request['task'] = 'different'
        self.assertEqual(again.submit(request)['error_code'], 'attempt_conflict')
    def test_default_off_global_and_unavailable_do_not_spawn(self):
        self.assertEqual(m.catalog(None, selected_mode='legacy'), [])
        self.assertFalse(m.Manager(None).submit(self.payload())['ok'])
        global_manager = m.Manager(self.config, selected_mode='global', spawn=lambda *a, **k: self.fail('spawn'))
        self.assertEqual(global_manager.submit(self.payload())['error_code'], 'unsupported_mode')
        self.providers[1]['models'][0]['harnesses'][0]['available'] = False
        self.assertFalse(self.manager.submit(self.payload())['ok'])
        self.assertEqual(self.spawn_calls, [])

    def test_empty_catalog_rejects_before_worker_or_identity_creation(self):
        self.providers.clear()
        request = self.payload()
        result = self.manager.submit(request)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error_code'], 'managed_pair_unavailable')
        self.assertEqual(self.spawn_calls, [])
        self.assertFalse((self.root / 'jobs' / request['attempt_id']).exists())
    def test_client_cannot_supply_commands_scope_escape_or_context(self):
        for extra in ({'node': '/tmp/node'}, {'context': 2}, {'standalone': True},
                      {'allowed_paths': ['../outside']}, {'allowed_paths': ['.git/config']},
                      {'allowed_paths': ['*']}, {'expected': [{'path': 'outside', 'contains': 'x'}]}):
            request = self.payload(); request.update(extra)
            self.assertFalse(self.manager.submit(request)['ok'])
        self.assertEqual(self.spawn_calls, [])
    def test_worker_environment_never_inherits_keys_or_loaders(self):
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'dummy', 'NODE_OPTIONS': '--import evil',
                                     'CHILD_REGISTRATION_TOKEN': 'dummy'}):
            self.manager.submit(self.payload())
        env = self.spawn_calls[0][1]['env']
        for key in ('DEEPSEEK_API_KEY', 'NODE_OPTIONS', 'CHILD_REGISTRATION_TOKEN'):
            self.assertNotIn(key, env)
    def test_parent_mismatch_before_prepare(self):
        request = self.payload(); self.manager.submit(request)
        job = self.root / 'jobs' / request['attempt_id']; adapter = Adapter(job)
        final = m.run_job(job, adapter=adapter, parent_call=lambda *a: {'name': 'OtherParent'},
                          run=object(), provider_loader=self.loader)
        self.assertEqual(adapter.calls, []); self.assertFalse(final['task_success']) if final['task_success'] is not None else None
        self.assertEqual(final['state'], 'failed')
    def test_cleanup_failure_is_not_success_and_not_retried(self):
        request = self.payload(); self.manager.submit(request)
        job = self.root / 'jobs' / request['attempt_id']; adapter = Adapter(job, finalize_error=True)
        final = m.run_job(job, adapter=adapter, parent_call=self.parent_call,
                          run=object(), sleep=lambda _: None, provider_loader=self.loader)
        self.assertEqual(adapter.calls.count('finalize'), 1)
        self.assertNotIn('clean', adapter.calls)
        self.assertIsNone(final['runtime_success']); self.assertEqual(final['state'], 'failed')
        self.assertIsNone(final['cleanup_success'])
    def test_terminal_without_readiness_cannot_be_success(self):
        request = self.payload(); self.manager.submit(request)
        job = self.root / 'jobs' / request['attempt_id']; adapter = Adapter(job, broken=True)
        final = m.run_job(job, adapter=adapter, parent_call=self.parent_call,
                          run=object(), sleep=lambda _: None, provider_loader=self.loader)
        self.assertEqual(final['state'], 'failed'); self.assertFalse(final['task_success'])
    def test_stop_routes_same_name_to_persistent_job(self):
        request = self.payload(); self.manager.submit(request)
        job = self.root / 'jobs' / request['attempt_id']
        current = m.read(job / 'status.json'); current['name'] = 'TestChild'; m.save(job / 'status.json', current)
        self.assertTrue(self.manager.stop('TestChild')['pending'])
        self.assertTrue((job / 'stop-request.json').exists()); self.assertIsNone(self.manager.stop('NativeChild'))
    def test_disable_preserves_lookup_stop_and_same_attempt_without_new_worker(self):
        request = self.payload(); accepted = self.manager.submit(request)
        job = self.root / 'jobs' / request['attempt_id']
        status = m.read(job / 'status.json'); status['name'] = 'TestChild'; m.save(job / 'status.json', status)
        manifest = m.read(self.config); manifest['enabled'] = False; m.save(self.config, manifest)
        self.assertEqual(self.manager.lookup(request['attempt_id'])['attempt_id'], request['attempt_id'])
        self.assertEqual(self.manager.submit(request)['attempt_id'], request['attempt_id'])
        self.assertTrue(self.manager.stop('TestChild')['ok'])
        self.assertFalse(self.manager.submit(self.payload())['ok'])
        self.assertEqual(len(self.spawn_calls), 1)

    def test_selected_model_mismatch_before_worker(self):
        data = m.read(self.backend); data['backends']['strata']['model'] = 'other'; m.save(self.backend, data)
        self.assertEqual(self.manager.submit(self.payload())['error_code'], 'template_model_mismatch')
        self.assertEqual(self.spawn_calls, [])
    def test_effort_projection_changes_private_copy_only(self):
        for harness in m.HARNESSES:
            request = self.payload(harness=harness); request['effort'] = 'off'; self.manager.submit(request)
            job = self.root / 'jobs' / request['attempt_id']; adapter = Adapter(job)
            m.run_job(job, adapter=adapter, parent_call=self.parent_call, run=object(),
                      sleep=lambda _: None, provider_loader=self.loader)
            projected = m.read(job / 'run-template.json')
            if harness == 'dsh':
                self.assertEqual(m.read(projected['backend_file'])['backends']['strata']['effort'], 'off')
                self.assertEqual(m.read(self.backend)['backends']['strata']['effort'], 'low')
            else:
                self.assertEqual(projected['profiles']['strata']['reasoning_effort'], 'none')
                self.assertNotIn('reasoning_effort', m.read(self.template)['profiles']['strata'])



class ServerRoutingTests(unittest.TestCase):
    def setUp(self):
        from dashboard import server
        self.server = server
    def test_managed_dispatch_precedes_old_registration_path(self):
        response = {'ok': True, 'managed': True, 'pending': True, 'attempt_id': 'request'}
        manager = SimpleNamespace(submit=lambda payload: response)
        with patch.object(self.server, '_managed_spawn_manager', return_value=manager), \
             patch.object(self.server, '_spawn_request', side_effect=AssertionError('old path')):
            self.assertEqual(self.server.do_spawn({'provider': 'strata', 'harness': 'dsh'}), response)
    def test_native_harness_metadata_preserves_old_payload(self):
        for provider, harness in [('claude', 'claudecode'), ('codex', 'codex'), ('gemini', 'gemini')]:
            request = {'provider': provider, 'task': 'old task', 'parent': 'Parent'}
            with patch.object(self.server, '_spawn_unavailable_error', return_value=None), \
                 patch.object(self.server, '_spawn_request', side_effect=lambda p: (None, {'ok': False, 'snapshot': p})):
                old = self.server.do_spawn(request)
                new = self.server.do_spawn({**request, 'harness': harness, 'helper_model': 'same'})
                self.assertEqual(old, new)
        with patch.object(self.server, '_spawn_request', side_effect=AssertionError('fallback')):
            self.assertFalse(self.server.do_spawn({'provider': 'claude', 'harness': 'unknown'})['ok'])
    def test_catalog_same_consumer_off_on_off(self):
        import types
        module = types.ModuleType('dashboard.managed_catalog')
        module.load_catalog_inputs = lambda *a, **k: ({}, {}, True)
        added = [{'id': 'strata', 'managed': True}]
        module.catalog_providers = lambda *a, **k: added
        fake_models = SimpleNamespace(models=('sonnet',), source='fixture', error=None, overflow=())
        with patch.object(self.server.subprocess, 'run', return_value=SimpleNamespace(stdout='Bright\n\x1eCurie\n')), \
             patch.object(self.server, '_claude_catalog', return_value=fake_models), \
             patch.object(self.server, '_claude_default_model', return_value='sonnet'), \
             patch.object(self.server, '_spawn_scientist_statuses', return_value={}), \
             patch.object(self.server, '_portrait_file', return_value=None), \
             patch.object(self.server.codex_models, 'provider_catalog', return_value={'id': 'codex'}), \
             patch.dict('sys.modules', {'dashboard.managed_catalog': module}), \
             patch.dict('os.environ', {'AGENTSTACK_MANAGED_SPAWN_CONFIG': ''}):
            old = self.server.spawn_names_payload()
            with patch.dict('os.environ', {'AGENTSTACK_MANAGED_SPAWN_CONFIG': '/fixture/manifest'}):
                enabled = self.server.spawn_names_payload()
            off_again = self.server.spawn_names_payload()
        self.assertEqual(old, off_again)
        self.assertEqual(enabled['providers'], old['providers'] + added)
        for key in old.keys() - {'providers'}:
            self.assertEqual(old[key], enabled[key])

class ProfileBusyTests(unittest.TestCase):
    setUp = ManagedTests.setUp
    payload = ManagedTests.payload
    def set_hermes_interactive(self, value):
        for provider in self.providers:
            for entry in provider['models'][0]['harnesses']:
                if entry['id'] == 'hermes':
                    entry['interactive'] = value
    def test_hermes_same_profile_refused_but_other_backend_and_dsh_allowed(self):
        self.set_hermes_interactive(False)
        request = self.payload(harness='hermes'); self.assertTrue(self.manager.submit(request)['ok'])
        self.assertEqual(self.manager.submit(self.payload(harness='hermes'))['error_code'], 'profile_busy')
        self.assertTrue(self.manager.submit(self.payload(provider='deepseek', harness='hermes'))['ok'])
        self.assertTrue(self.manager.submit(self.payload(harness='dsh'))['ok'])
        self.assertEqual(self.manager.submit(request)['attempt_id'], request['attempt_id'])

    def test_interactive_hermes_attempts_share_profile_with_separate_jobs(self):
        requests = [self.payload(harness='hermes') for _ in range(2)]
        for request in requests:
            result = self.manager.submit(request)
            self.assertTrue(result['ok'], result)
            self.assertIs(result['capabilities']['interactive'], True)
            self.assertFalse(result['finished'])
        self.assertEqual(len(self.spawn_calls), 2)
        self.assertNotEqual(requests[0]['attempt_id'], requests[1]['attempt_id'])

    def test_mixed_legacy_and_interactive_profiles_are_refused_in_both_orders(self):
        for provider, first_interactive in (('strata', True), ('deepseek', False)):
            self.set_hermes_interactive(first_interactive)
            first = self.payload(provider=provider, harness='hermes')
            self.assertTrue(self.manager.submit(first)['ok'])
            self.set_hermes_interactive(not first_interactive)
            second = self.payload(provider=provider, harness='hermes')
            self.assertEqual(self.manager.submit(second)['error_code'], 'profile_busy')
            self.assertFalse((self.root / 'jobs' / second['attempt_id']).exists())
        self.assertEqual(len(self.spawn_calls), 2)

    def test_attempt_without_saved_overlay_capability_is_not_assumed_interactive(self):
        first = self.payload(harness='hermes'); self.assertTrue(self.manager.submit(first)['ok'])
        path = self.root / 'jobs' / first['attempt_id'] / 'status.json'
        old = m.read(path); old.pop('capabilities'); m.save(path, old)
        self.assertEqual(self.manager.submit(self.payload(harness='hermes'))['error_code'], 'profile_busy')
        self.assertEqual(len(self.spawn_calls), 1)

class ManagedHttpTests(unittest.TestCase):
    def test_post_202_and_uuid_lookup_share_existing_routes(self):
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer
        from dashboard import server
        aid = str(uuid.uuid4())
        accepted = {'ok': True, 'managed': True, 'attempt_id': aid, 'state': 'pending', 'pending': True}
        manager = SimpleNamespace(submit=lambda p: accepted, lookup=lambda value: {**accepted, 'attempt_id': value})
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
        try:
            with patch.object(server, '_managed_spawn_manager', return_value=manager):
                base = 'http://127.0.0.1:' + str(httpd.server_port)
                request = urllib.request.Request(base + '/api/spawn',
                    data=json.dumps({'provider': 'strata', 'harness': 'dsh'}).encode(),
                    headers={'Content-Type': 'application/json'}, method='POST')
                with urllib.request.urlopen(request) as response:
                    self.assertEqual(response.status, 202)
                    self.assertEqual(json.load(response)['attempt_id'], aid)
                with urllib.request.urlopen(base + '/api/spawn-status?attempt_id=' + aid) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.load(response)['attempt_id'], aid)
        finally:
            httpd.shutdown(); thread.join(); httpd.server_close()

class ParentContextTests(unittest.TestCase):
    def test_whois_uses_existing_context_without_parent_owner_or_inbox(self):
        calls = []
        core = SimpleNamespace(_project_key=lambda: '/synthetic/project',
            _runtime_agent_token=lambda *a: self.fail('must not read parent owner'),
            _mcp_call=lambda tool, args: (calls.append((tool, args)) or {'ok': True, 'data': {'name': args['agent_name']}}))
        connection = m.parent_connection(core, 'Parent')
        self.assertEqual(connection('whois', {'name': 'Child'}), {'name': 'Child'})
        self.assertEqual(calls[0][0], 'whois')
        self.assertNotIn('registration_token', calls[0][1])
        self.assertFalse(calls[0][1]['include_recent_commits'])
        with self.assertRaises(ValueError):
            connection('fetch_inbox', {})
        self.assertEqual(len(calls), 1)

class WorkerExitTests(unittest.TestCase):
    setUp = ManagedTests.setUp
    payload = ManagedTests.payload
    parent_call = ManagedTests.parent_call

    def test_failed_step_log_contains_stage_and_code_without_exception_values(self):
        request = self.payload(); self.manager.submit(request)
        job = self.root / 'jobs' / request['attempt_id']
        class FailedStep(Adapter):
            def prepare(self, **kwargs):
                error = RuntimeError('dummy-secret and private task body')
                error.managed_step = 'configure'
                error.managed_reason = 'profile_path_mismatch'
                raise error
        with self.assertLogs(m.LOG, level='ERROR') as captured:
            m.run_job(job, adapter=FailedStep(job), parent_call=self.parent_call,
                      run=object(), provider_loader=self.loader)
        message = '\n'.join(captured.output)
        self.assertIn('step=configure reason=profile_path_mismatch', message)
        self.assertNotIn('dummy-secret', message)
        self.assertEqual(m.read(job / 'worker-failure.json')['step'], 'configure')

    def test_explicit_unstarted_cleanup_closes_failure_without_reregistering(self):
        request = self.payload(harness='hermes'); self.manager.submit(request)
        job = self.root / 'jobs' / request['attempt_id']
        current = m.read(job / 'status.json')
        current.update(state='failed', phase='failed', task_success=False)
        m.save(job / 'status.json', current)
        calls = []
        adapter = SimpleNamespace(close_unstarted=lambda state, **kw:
            (calls.append(state) or {'runtime_success': True, 'cleaned': True}))
        with patch.object(m, '_product_module', return_value=adapter) as imported:
            result = m.finish_unstarted_job(job, run=object())
        imported.assert_called_once_with('integrations.hermes.managed_lifecycle')
        self.assertEqual(calls, [job / 'state'])
        self.assertFalse(result['task_success']); self.assertEqual(result['state'], 'failed')
        self.assertTrue(result['runtime_success']); self.assertTrue(result['cleanup_success'])
        self.assertTrue(result['finished'])
        self.assertEqual(result['phase'], 'cleaned_after_failure')

    def test_saved_status_without_cleanup_field_does_not_infer_from_runtime(self):
        request = self.payload(); self.manager.submit(request)
        path = self.root / 'jobs' / request['attempt_id'] / 'status.json'
        current = m.read(path)
        current.pop('cleanup_success')
        for fields, expected in (({'phase': 'running'}, None),
                                 ({'phase': 'cleaning'}, None),
                                 ({'phase': 'failed', 'error_phase': 'cleaning'}, False),
                                 ({'phase': 'cleaned'}, True),
                                 ({'phase': 'cleaned_after_failure', 'error_phase': 'cleaning'}, True)):
            m.save(path, {**current, 'runtime_success': True, **fields})
            self.assertIs(self.manager.lookup(request['attempt_id'])['cleanup_success'], expected)

    def test_recovery_clean_failure_preserves_runtime_proof_but_fails_cleanup(self):
        request = self.payload(); self.manager.submit(request)
        job = self.root / 'jobs' / request['attempt_id']
        class FailingRecovery(Adapter):
            def prepare(self, **kwargs):
                super().prepare(**kwargs)
                raise OSError('ordinary partial preparation failure')
            def clean(self, state, *, run):
                self.calls.append('clean')
                raise OSError('ordinary cleanup permission failure')
        adapter = FailingRecovery(job)
        result = m.run_job(job, adapter=adapter, parent_call=self.parent_call,
                           run=object(), sleep=lambda _: None, provider_loader=self.loader)
        self.assertTrue(result['runtime_success'])
        self.assertFalse(result['cleanup_success'])
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['phase'], 'cleanup_unconfirmed')
        self.assertEqual(result['error_phase'], 'cleaning')
        self.assertEqual(adapter.calls, ['prepare', 'finalize', 'clean'])

    def test_clean_failure_keeps_worker_exit_nonzero_even_with_task_runtime_proof(self):
        request = self.payload(); self.manager.submit(request)
        job = self.root / 'jobs' / request['attempt_id']
        class FailingClean(Adapter):
            def clean(self, state, *, run):
                self.calls.append('clean')
                raise OSError('ordinary cleanup permission failure')
        adapter = FailingClean(job)
        result = m.run_job(job, adapter=adapter, parent_call=self.parent_call,
                           run=object(), sleep=lambda _: None, provider_loader=self.loader)
        self.assertTrue(result['task_success'])
        self.assertTrue(result['runtime_success'])
        self.assertFalse(result['cleanup_success'])
        self.assertFalse(self.manager.lookup(request['attempt_id'])['cleanup_success'])
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['error_phase'], 'cleaning')
        self.assertEqual(result['error_code'], 'managed_attempt_failed')
        self.assertEqual(adapter.calls.count('finalize'), 1)
        with patch('sys.argv', ['managed_spawn.py', '--job', str(job)]):
            with patch.object(m, 'run_job', return_value=result):
                self.assertEqual(m.main(), 1)
            with patch.object(m, 'run_job', return_value={**result, 'state': 'ready', 'phase': 'cleaned'}):
                self.assertEqual(m.main(), 0)

class ManagedFinishedStopTests(unittest.TestCase):
    setUp = ManagedTests.setUp
    payload = ManagedTests.payload

    def test_finished_or_cleanup_unknown_names_never_reach_native_kill(self):
        from dashboard import server
        request = self.payload(); self.manager.submit(request)
        job = self.root / 'jobs' / request['attempt_id']
        for clean in (False, True):
            status = m.read(job / 'status.json')
            status.update(name='TestChild', finished=True, phase='cleaned' if clean else 'cleanup_unconfirmed',
                          runtime_success=True if clean else None)
            m.save(job / 'status.json', status)
            with patch.object(server, '_managed_spawn_manager', return_value=self.manager), \
                 patch.object(server, '_valid', side_effect=AssertionError('native fallback')):
                result = server.do_kill('TestChild')
            self.assertTrue(result['managed'])
            self.assertEqual(result['ok'], clean)
            if not clean:
                self.assertEqual(result['error_code'], 'managed_cleanup_unconfirmed')

class InteractiveControllerTests(unittest.TestCase):
    setUp = ManagedTests.setUp
    payload = ManagedTests.payload
    parent_call = ManagedTests.parent_call

    def test_blank_top_level_is_accepted_without_synthetic_parent(self):
        request = self.payload()
        for key in ('parent', 'task', 'allowed_paths', 'expected'):
            request.pop(key)
        accepted = self.manager.submit(request)
        self.assertTrue(accepted['ok'])
        self.assertIsNone(accepted['parent'])
        self.assertEqual(accepted['task_mode'], 'conversation')
        self.assertEqual(accepted['report_policy'], 'pane')
        self.assertEqual(accepted['task_evaluation'], 'not_applicable')
        job = self.root / 'jobs' / request['attempt_id']
        adapter = Adapter(job)
        final = m.run_job(job, adapter=adapter, parent_call=lambda *args: self.fail('synthetic whois'),
                          run=object(), sleep=lambda _: None, provider_loader=self.loader)
        self.assertIsNone(adapter.kwargs['parent'])
        self.assertEqual(adapter.kwargs['task']['prompt'], '')
        self.assertIsNone(final['task_success'])
        self.assertTrue(final['cleanup_success'])
        self.assertEqual(final['state'], 'ready')

    def test_report_does_not_close_runtime_and_idle_has_no_660_second_limit(self):
        request = self.payload(); self.manager.submit(request)
        job = self.root / 'jobs' / request['attempt_id']
        test = self
        class Continuing(Adapter):
            def status(self, state):
                self.tick += 1
                if self.tick >= 2:
                    test.assertNotIn('finalize', self.calls)
                if self.tick >= 3:
                    test.assertTrue(m.read(job / 'status.json')['task_success'])
                    test.assertFalse(m.read(job / 'status.json')['finished'])
                return {'ready': True, 'terminal': self.tick == 4, 'agent_name': 'TestChild',
                        'task_success': self.tick >= 2, 'activity': 'idle'}
        tick = iter([0, 10000, 20000, 30000, 40000])
        adapter = Continuing(job)
        result = m.run_job(job, adapter=adapter, parent_call=self.parent_call, run=object(),
                           sleep=lambda _: None, clock=lambda: next(tick), provider_loader=self.loader)
        self.assertEqual(adapter.tick, 4)
        self.assertEqual(adapter.calls.count('finalize'), 1)
        self.assertTrue(result['cleanup_success'])

    def test_mail_policy_and_explicit_standalone_are_not_contradictory(self):
        for values, code in (({'parent': None, 'standalone': False}, 'missing_parent'),
                             ({'standalone': True}, 'contradictory_parent'),
                             ({'parent': None, 'report_policy': 'mail'}, 'invalid_report_policy')):
            request = self.payload(); request.update(values)
            self.assertEqual(self.manager.submit(request)['error_code'], code)

    def test_effort_must_match_selected_harness(self):
        for provider in self.providers:
            for entry in provider['models'][0]['harnesses']:
                entry['efforts'] = ['off'] if entry['id'] == 'dsh' else None
        request = self.payload(); request['effort'] = 'off'
        self.assertTrue(self.manager.submit(request)['ok'])
        request = self.payload(harness='hermes'); request['effort'] = 'off'
        self.assertEqual(self.manager.submit(request)['error_code'], 'unsupported_effort')

class LegacyHermesModeTests(unittest.TestCase):
    setUp = ManagedTests.setUp
    payload = ManagedTests.payload
    parent_call = ManagedTests.parent_call
    def legacy_hermes(self):
        for provider in self.providers:
            for entry in provider['models'][0]['harnesses']:
                if entry['id'] == 'hermes': entry['interactive'] = False
    def test_old_assignment_gets_three_fields_and_conversation_is_rejected(self):
        self.legacy_hermes()
        request = self.payload(harness='hermes')
        self.assertTrue(self.manager.submit(request)['ok'])
        job = self.root / 'jobs' / request['attempt_id']; adapter = Adapter(job)
        m.run_job(job, adapter=adapter, parent_call=self.parent_call, run=object(),
                  sleep=lambda _: None, provider_loader=self.loader)
        self.assertEqual(set(adapter.kwargs['task']), {'prompt', 'allowed_paths', 'expected'})
        request = self.payload(harness='hermes')
        request.update(task_mode='conversation', expected=[])
        self.assertEqual(self.manager.submit(request)['error_code'], 'interactive_not_ready')
    def test_legacy_assignment_does_not_pretend_to_support_standalone_or_pane_reports(self):
        self.legacy_hermes()
        for values, code in (({'parent': None, 'standalone': True}, 'standalone_not_ready'),
                             ({'report_policy': 'pane'}, 'report_policy_not_ready')):
            request = self.payload(harness='hermes'); request.update(values)
            self.assertEqual(self.manager.submit(request)['error_code'], code)
    def test_mode_metadata_keeps_legacy_assignment_available(self):
        modes = m.task_modes(interactive=False, available=True)
        self.assertFalse(modes['conversation']['available'])
        self.assertEqual(modes['conversation']['reason'], 'interactive_not_ready')
        self.assertTrue(modes['assignment']['available'])
        self.assertTrue(modes['assignment']['requires_parent'])
        self.assertIs(modes['assignment']['requires_scope'], True)
        self.assertIs(modes['assignment']['requires_expected'], True)
        for mode in m.task_modes(interactive=True, available=True).values():
            self.assertIs(mode['requires_scope'], False)
            self.assertIs(mode['requires_expected'], False)

class OptionalAssignmentChecks(unittest.TestCase):
    setUp = ManagedTests.setUp
    payload = ManagedTests.payload
    def test_dsh_assignment_needs_only_a_prompt(self):
        request = self.payload(); request.update(task_mode='assignment', allowed_paths=[], expected=[])
        self.assertTrue(self.manager.submit(request)['ok'])
    def test_expected_without_scope_is_checked_in_the_private_workspace(self):
        request = self.payload(); request.update(task_mode='assignment', allowed_paths=[])
        self.assertTrue(self.manager.submit(request)['ok'])
        for path in ('../outside', '/absolute', '.git/config'):
            request = self.payload(); request.update(task_mode='assignment', allowed_paths=[],
                expected=[{'path': path, 'contains': 'done'}])
            self.assertFalse(self.manager.submit(request)['ok'])


if __name__ == '__main__':
    unittest.main()

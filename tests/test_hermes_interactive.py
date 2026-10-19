"""Continuing native turns and optional formal reports; no credentials/network."""
import json
import asyncio
from pathlib import Path
import sys
import os
import pty
import select
import shutil
import subprocess
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

ADAPTER = Path(__file__).resolve().parents[1] / 'integrations/hermes'
sys.path.insert(0, str(ADAPTER))
import completion
import interactive
from mail_lifecycle import read, save
import profile_projection
import task_spec
import test_hermes_managed as pilot
import runner
import mail_lifecycle
import mail_probe
import managed_lifecycle
import task_plugin
from dynamic_reservations import inventory


class InteractiveContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.work = self.state / 'work'
        self.work.mkdir()
        self.attempt = {'attempt_id': 'attempt', 'agent_name': 'FixtureChild',
                        'phase': 'run', 'started_at_ns': time.time_ns()}
        save(self.state / 'attempt.json', self.attempt)

    def tearDown(self):
        self.tmp.cleanup()

    def task(self, mode='assignment', policy='pane'):
        task = {'attempt_id': 'attempt', 'task_id': 'task', 'task_mode': mode, 'report_policy': policy,
                'report_to': None, 'worktree': str(self.work), 'interactive': True,
                'expected': [{'path': 'result.txt', 'contains': 'done'}] if mode == 'assignment' else []}
        save(self.state / 'task.json', task)
        return task

    def test_empty_conversation_and_parentless_policy(self):
        normalized = task_spec.normalize({})
        self.assertEqual(normalized['task_mode'], 'conversation')
        self.assertEqual(normalized['report_policy'], 'pane')
        self.assertEqual(normalized['prompt'], '')
        with self.assertRaises(ValueError):
            task_spec.normalize({'report_policy': 'mail'})
        self.task('conversation')
        result = completion.evaluate_task(self.state)
        self.assertIsNone(result['success'])
        self.assertEqual(result['evaluation'], 'not_applicable')
        self.assertEqual(result['applicable_checks'], [])

    def test_native_two_turns_report_snapshot_and_early_failure(self):
        self.task()
        state, work = self.state, self.work
        class Native:
            def chat(self, message):
                binding = read(state / 'activity.json')
                if message == 'early-failure':
                    return None
                work.joinpath('result.txt').write_text(message)
                with (state / 'audit.jsonl').open('a') as f:
                    for phase, extra in [('provider-request-start', {}),
                                         ('provider-usage', {'confirmed': True, 'terminal': True})]:
                        f.write(json.dumps({'attempt_id': 'attempt', 'task_id': binding['task_id'],
                            'turn_id': binding['turn_id'], 'phase': phase, 'seq': binding['turn_id'], **extra}) + '\n')
                self._last_turn_result = {'completed': True}
                return 'rendered'
        interactive.observe_chat(Native, state)
        runtime = Native()
        self.assertEqual(runtime.chat('done'), 'rendered')
        result = completion.evaluate_task(state)
        self.assertTrue(result['success'])
        self.assertEqual(len(result['applicable_checks']), 4)
        saved = (state / 'task-reports/task.json').read_bytes()
        self.assertEqual(runtime.chat('later edit'), 'rendered')
        self.assertEqual((state / 'task-reports/task.json').read_bytes(), saved)
        self.assertEqual(completion.evaluate_task(state), result)
        self.assertIsNone(read(state / 'activity.json')['task_id'])
        self.assertIsNone(runtime.chat('early-failure'))
        self.assertFalse(read(state / 'activity.json')['latest_turn']['completed'])
        self.assertFalse((state / 'runtime-exit.json').exists())

    def test_unknown_usage_never_becomes_task_success(self):
        self.task()
        (self.work / 'result.txt').write_text('done')
        (self.state / 'events.jsonl').write_text(json.dumps({'attempt_id': 'attempt', 'task_id': 'task',
            'phase': 'turn-end', 'reason_kind': 'completed'}) + '\n')
        (self.state / 'audit.jsonl').write_text(json.dumps({'attempt_id': 'attempt', 'task_id': 'task',
            'phase': 'provider-request-start', 'seq': 1}) + '\n')
        self.assertFalse(completion.evaluate_task(self.state)['success'])
        with (self.state / 'audit.jsonl').open('a') as stream:
            for confirmed in (True, False):
                stream.write(json.dumps({'attempt_id': 'attempt', 'task_id': 'task', 'phase': 'provider-usage',
                    'seq': 1, 'confirmed': confirmed, 'terminal': confirmed}) + '\n')
        self.assertFalse(completion.evaluate_task(self.state)['success'])

    def test_native_shortcuts_cannot_read_files_or_launch_shell_outside_tools(self):
        class Native:
            def process_command(self, text, **kwargs):
                return text
            def _chat_route_images(self, message, images):
                return message
        interactive.constrain_native_surface(Native, self.state)
        native = Native()
        self.assertTrue(native.handle_bang_shell('!cat outside'))
        self.assertFalse(native.handle_bang_shell('ordinary message'))
        self.assertTrue(native.process_command('/model other'))
        self.assertEqual(native.process_command('/status'), '/status')
        self.assertEqual(native._chat_expand_context_references('@outside'), ('@outside', None))
        self.assertEqual(native._expand_paste_references('[Pasted text #1: 1 lines → /outside]'),
                         '[Pasted text #1: 1 lines → /outside]')
        with self.assertRaises(ValueError):
            native._chat_route_images('attach', [self.state / 'outside.png'])

    def test_prompt_only_assignment_has_no_artifact_or_mail_requirement(self):
        value = task_spec.normalize({'task_mode': 'assignment', 'prompt': 'Explain the result.'})
        self.assertEqual(value['expected'], [])
        self.assertEqual(value['allowed_paths'], [])
        task = self.task()
        task['expected'] = []
        save(self.state / 'task.json', task)
        (self.state / 'events.jsonl').write_text(json.dumps({'attempt_id': 'attempt', 'task_id': 'task',
            'phase': 'turn-end', 'reason_kind': 'completed'}) + '\n')
        (self.state / 'audit.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in [
            {'attempt_id': 'attempt', 'task_id': 'task', 'phase': 'provider-request-start', 'seq': 1},
            {'attempt_id': 'attempt', 'task_id': 'task', 'phase': 'provider-usage', 'seq': 1, 'confirmed': True, 'terminal': True}]))
        result = completion.evaluate_task(self.state)
        self.assertTrue(result['success'])
        self.assertEqual(result['applicable_checks'], ['attempt_binding', 'completed_turn', 'provider_audit'])

    def test_provider_collision_registry_is_read_without_executing(self):
        source = self.state / 'source'
        (source / 'hermes_cli').mkdir(parents=True)
        registry = source / 'hermes_cli/auth.py'
        registry.write_text('raise RuntimeError("must not execute")\n'
                            '_REGISTRY_ROWS: tuple = (("deepseek", "DeepSeek"), ProviderConfig("anthropic", "Anthropic"))\n')
        for name in ('deepseek', 'Anthropic', 'openrouter'):
            with self.assertRaisesRegex(ValueError, 'collides'):
                profile_projection.validate_provider_name(name, source)
        self.assertEqual(profile_projection.validate_provider_name('deepseek-api', source), 'deepseek-api')
        registry.write_text('_REGISTRY_ROWS: tuple = unknown\n')
        with self.assertRaises(ValueError):
            profile_projection.validate_provider_name('deepseek-api', source)


class InteractiveLifecycle(unittest.TestCase):
    def setUp(self):
        self.fixture = pilot.PilotFixture('runTest')
        self.fixture.setUp()
        self.root = self.fixture.root
        self.config = runner.read(self.fixture.config_path)
        self.config['parent'] = None
        runner.save(self.fixture.config_path, self.config)
        self.state = self.root / 'chat'
        runner.initialize(self.fixture.config_path, self.state, 'strata', self.fixture.product.run,
                          file_task=True, task_spec={'task_mode': 'conversation'})
        mail_lifecycle.register(self.state, self.fixture.product.run, generate_config=False)
        runner.configure(self.state, self.fixture.product.run)
        self.config = read(self.state / 'run-config.json')
        save(self.state / 'mail-probe.json', {'ok': True, 'schema': True, 'backend': True,
            'agent_name': 'FixtureChild', 'tools': ['runtime_status', 'whois', 'fetch_inbox',
            'send_message', 'reserve_files', 'renew_reservations', 'release_reservations']})

    def tearDown(self):
        self.fixture.tearDown()

    def callbacks(self, expired=False):
        callbacks, calls = {}, []
        def call_mcp(server, tool, args, timeout=30):
            calls.append((server, tool, args))
            if tool == 'reserve_files':
                value = {'granted': [{'id': 17, 'owner': 'FixtureChild', 'path_pattern': args['paths'][0],
                    'expires_ts': (datetime.now(timezone.utc) + timedelta(seconds=-1 if expired else 1800)).isoformat()}]}
            elif tool == 'release_reservations':
                value = {'released': len(args['file_reservation_ids'])}
            else:
                raise AssertionError(tool)
            return {'ok': True, 'result': value}
        ctx = SimpleNamespace(register_hook=lambda name, cb: callbacks.update({name: cb}), call_mcp=call_mcp)
        with patch.dict('os.environ', {'HERMES_HOME': self.config['profile_home']}):
            task_plugin.install(ctx, self.state)
        return callbacks, calls

    def test_parentless_empty_pane_normal_mail_dynamic_write_and_scope(self):
        self.assertIsNone(read(self.state / 'task.json')['report_to'])
        self.assertEqual((self.state / 'task.md').read_text(), '')
        self.assertFalse((Path(self.config['worktree']) / 'trial-ok.txt').exists())
        self.assertNotIn('task_timeout_seconds', self.config)
        profile = read(runner.profile_config_path(self.config))
        self.assertEqual(profile['mcp_servers']['orrery_mail']['tools'], {'resources': False, 'prompts': False})
        self.assertFalse((self.state / 'message.json').exists())
        before, after = self.callbacks()[0].values()
        target = Path(self.config['worktree']) / 'new.txt'
        self.assertIsNone(before('read_file', {'path': str(target)}))
        self.assertIsNone(before('mcp__orrery_mail__fetch_inbox', {}))
        for _ in range(2):
            self.assertIsNone(before('mcp__orrery_mail__send_message', {'to': ['FixtureSibling'], 'body_md': 'arbitrary'}))
        self.assertEqual(before('write_file', {'path': str(self.root / 'outside')})['action'], 'block')
        self.assertIsNone(before('write_file', {'path': str(target)}, tool_call_id='write-1'))
        target.write_text('second input result')
        after('write_file', '{}', args={'path': str(target)}, status='ok', tool_call_id='write-1')
        self.assertEqual(inventory(self.state), ({17}, {17}))
        self.assertEqual(read(self.state / 'task.json')['reservation_receipts'], [])
        self.assertEqual(before('session_search', {'profile': 'other'})['action'], 'block')
        self.assertEqual(before('session_search', {'session_id': 'other/session-id'})['action'], 'block')

    def test_expired_receipt_denies_before_write_and_keeps_grant_for_cleanup(self):
        before = self.callbacks(expired=True)[0]['pre_tool_call']
        path = Path(self.config['worktree']) / 'expired.txt'
        self.assertEqual(before('write_file', {'path': str(path)}, tool_call_id='expired')['action'], 'block')
        self.assertFalse(path.exists())
        self.assertEqual(inventory(self.state), ({17}, set()))

    def test_shared_fixed_profile_has_distinct_attempt_config_and_no_owner_overwrite(self):
        first_config = runner.profile_config_path(self.config).read_bytes()
        second = self.root / 'second-chat'
        runner.initialize(self.fixture.config_path, second, 'strata', self.fixture.product.run,
                          file_task=True, task_spec={'task_mode': 'conversation'})
        mail_lifecycle.register(second, self.fixture.product.run, generate_config=False)
        # The first attempt is active: no retirement receipt is needed to reuse
        # its fixed profile, because its config/proxy files cannot be overwritten.
        runner.configure(second, self.fixture.product.run)
        other = read(second / 'run-config.json')
        self.assertEqual(other['profile_home'], self.config['profile_home'])
        self.assertNotEqual(other['runtime_config'], self.config['runtime_config'])
        self.assertEqual(runner.profile_config_path(self.config).read_bytes(), first_config)
        runner.check_configured(self.state)
        runner.check_configured(second)
        for config, state in [(self.config, self.state), (other, second)]:
            proxy = read(runner.profile_config_path(config))['mcp_servers']['orrery_mail']
            self.assertEqual(proxy['env']['AGENTSTACK_PROXY_TOKEN_FILE'], read(state / 'mail-identity.json')['token_file'])

    def test_collision_stops_before_configure_side_effects(self):
        state = self.root / 'collision'
        value = runner.read(self.fixture.config_path)
        value['profiles']['deepseek'] = {**value['profiles']['deepseek'], 'provider': 'deepseek'}
        runner.save(self.fixture.config_path, value)
        runner.initialize(self.fixture.config_path, state, 'deepseek', self.fixture.product.run,
                          file_task=True, task_spec={'task_mode': 'conversation'})
        mail_lifecycle.register(state, self.fixture.product.run, generate_config=False)
        with self.assertRaisesRegex(ValueError, 'collides'):
            runner.configure(state, self.fixture.product.run)
        self.assertFalse((state / 'mcp.json').exists())
        self.assertFalse((state / 'profile-write-intent.json').exists())

    def test_native_ready_requires_current_process_render_and_loaded_guard(self):
        self.assertTrue(managed_lifecycle.CAPABILITIES['interactive'])
        aid = read(self.state / 'attempt.json')['attempt_id']
        tid = read(self.state / 'task.json')['task_id']
        save(self.state / 'runtime-process.json', {'pid': 42})
        save(self.state / 'preflight-complete.json', {'attempt_id': aid, 'guard_loaded': True})
        events = self.state / 'events.jsonl'
        events.write_text(json.dumps({'attempt_id': aid, 'task_id': tid, 'phase': 'plugin-ready', 'process_id': 42}) + '\n')
        self.assertFalse(managed_lifecycle.status(self.state)['ready'])
        with events.open('a') as stream:
            stream.write(json.dumps({'attempt_id': aid, 'task_id': tid, 'phase': 'native-ready', 'process_id': 41}) + '\n')
        self.assertFalse(managed_lifecycle.status(self.state)['ready'])
        with events.open('a') as stream:
            stream.write(json.dumps({'attempt_id': aid, 'task_id': tid, 'phase': 'native-ready', 'process_id': 42}) + '\n')
        self.assertTrue(managed_lifecycle.status(self.state)['ready'])
        installed = self.root / 'installed'
        target = installed / 'integrations/hermes'
        target.mkdir(parents=True)
        for path in ADAPTER.glob('*.py'):
            shutil.copyfile(path, target / path.name)
        dashboard = installed / 'dashboard'
        dashboard.mkdir()
        code = '''import sys,importlib.util,json
from pathlib import Path
sys.path[:]=[sys.argv[1]]+[p for p in sys.path if 'site-packages' not in p]
assert str(Path.cwd())=='/'
spec=importlib.util.spec_from_file_location('installed_hermes_adapter',Path(sys.argv[1]).parent/'integrations/hermes/managed_lifecycle.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
result=module.status(sys.argv[2])
assert result['ready'] is True and result['terminal'] is False
assert result['task_success'] is None and result['task_evaluation']=='not_applicable'
assert result['capabilities']['interactive'] is True
print('installed-native-status-ok')
'''
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(dashboard), str(self.state)],
            cwd='/', env={'HOME': str(self.root / 'home'), 'PATH': '/usr/bin:/bin'}, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'installed-native-status-ok')

    def test_runtime_cleanup_empty_dynamic_and_unknown_reservation_inventory(self):
        state = self.state
        attempt = read(state / 'attempt.json')
        config = read(state / 'run-config.json')
        config['credential_mode'] = 'owned-once'
        save(state / 'run-config.json', config)
        save(state / 'diagnostic-scan.json', {'attempt_id': attempt['attempt_id'],
            'source': 'owned-process-prefix-scan', 'matches': 0, 'errors': 0})
        save(state / 'runtime-process.json', {'pid': 42, 'pgid': 42, 'agent_name': 'FixtureChild'})
        save(state / 'runtime-exit.json', {'group_absent': True, 'group_check': 'observed'})
        save(state / 'owned-pane.json', {'agent_name': 'FixtureChild', 'session': 'FixtureChild', 'socket_path': '/fixture/socket'})
        outer, releases = self, []
        class Session:
            async def list_tools(self):
                return SimpleNamespace(tools=[SimpleNamespace(name=n) for n in mail_probe.REQUIRED])
            async def call_tool(self, name, args):
                if name == 'runtime_status':
                    value = {'agent_name': 'FixtureChild', 'project_key': config['project_key'],
                        'program': 'claude-code', 'lineage': {'parent_agent': None}}
                elif name == 'whois':
                    value = {'name': 'FixtureChild', 'program': 'hermes'}
                else:
                    outer.assertEqual(name, 'release_reservations')
                    releases.append(args['file_reservation_ids'])
                    value = {'released': len(args['file_reservation_ids'])}
                return pilot.reply(value)
        def cli(argv, **kwargs):
            action = argv[3]
            if action == 'scan-diagnostics':
                from diagnostics import scan
                value = scan(state)
            elif action == 'release':
                value = {}
                asyncio.run(mail_probe.exercise(Session(), state, action, value))
            elif action == 'retire':
                value = mail_lifecycle.retire(state, self.fixture.product.run)
            elif action == 'confirm-retire':
                value = mail_lifecycle.confirm_retire(state, argv[argv.index('--input') + 1])
            elif action in ('complete', 'complete-runtime'):
                value = runner.evaluate(state, runtime=action == 'complete-runtime')
            elif action == 'clean':
                with patch('pane_entry.group_absent', return_value=True):
                    value = runner.clean(state, self.fixture.product.run)
            else:
                raise AssertionError(action)
            return subprocess.CompletedProcess(argv, 0, json.dumps({'result': value}))
        whois = lambda tool, args: {'name': 'FixtureChild', 'retired_at': datetime.now(timezone.utc).isoformat()}
        # No grant is a confirmed empty inventory; task evaluation stays N/A.
        outcome = managed_lifecycle.finalize(state, parent_call=whois, run=cli)
        self.assertTrue(outcome['runtime_success'])
        self.assertIsNone(outcome['task_success'])
        self.assertEqual(releases, [[]])
        # A late-discovered real grant must invalidate the prior empty release.
        grant = {'id': 79, 'owner': 'FixtureChild', 'path_pattern': 'new.txt',
                 'expires_ts': (datetime.now(timezone.utc) + timedelta(seconds=1800)).isoformat()}
        ledger = {'attempt_id': attempt['attempt_id'], 'agent_name': 'FixtureChild', 'source': 'product-bound-proxy',
                  'receipts': [grant], 'released_ids': [], 'pending_calls': []}
        save(state / 'reservation-ledger.json', ledger)
        self.assertFalse(completion.evaluate_runtime(state)['success'])
        outcome = managed_lifecycle.finalize(state, parent_call=whois, run=cli)
        self.assertTrue(outcome['runtime_success'])
        self.assertEqual(releases, [[], [79]])
        # An unanswered acquisition cannot be converted into a clean result.
        ledger['pending_calls'] = ['unanswered-rpc']
        save(state / 'reservation-ledger.json', ledger)
        self.assertIsNot(completion.evaluate_runtime(state)['success'], True)
        with self.assertRaises(ValueError):
            managed_lifecycle.finalize(state, parent_call=whois, run=cli)
        with self.assertRaises(ValueError):
            runner.clean(state, self.fixture.product.run)
        self.assertTrue(Path(read(state / 'mail-identity.json')['token_file']).exists())
        ledger['pending_calls'] = []
        save(state / 'reservation-ledger.json', ledger)
        managed_lifecycle.clean(state, run=cli)
        self.assertTrue(Path(config['profile_home']).is_dir())
        self.assertTrue((state / 'cleaned.json').is_file())
        self.assertFalse((state / 'mcp.json').exists())

    def test_owned_pty_keeps_two_inputs_and_native_seed_selector_interactive(self):
        source = os.environ.get('ORRERY_HERMES_TEST_SOURCE')
        if not source:
            self.skipTest('Explicit installed dependency interpreter/source required')
        # The native TTY selector is extracted from the pinned source without
        # importing the CLI/provider bootstrap. Input loop is a keyless fixture.
        script = self.root / 'tty_fixture.py'
        script.write_text('''import ast,os,sys
from pathlib import Path
tree=ast.parse((Path(sys.argv[1])/'cli.py').read_text())
node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_should_seed_interactive')
exec(compile(ast.Module(body=[node],type_ignores=[]),'pinned-selector','exec'))
assert _should_seed_interactive('initial',None,False,False)
print('READY '+str(os.getpid()),flush=True)
for index in range(2):
    value=input()
    print('TURN '+str(index)+' '+value+' '+str(os.getpid()),flush=True)
input()
''')
        supervisor = self.root / 'supervisor_fixture.py'
        supervisor.write_text('''import sys,signal
sys.path.insert(0,sys.argv[1])
import tty_runtime
def stop(*_): raise KeyboardInterrupt()
signal.signal(signal.SIGTERM,stop)
raise SystemExit(tty_runtime.run([sys.executable,'-B',sys.argv[2],sys.argv[3]],cwd=sys.argv[4],
    env={'PATH':'/usr/bin:/bin'},log=sys.argv[5],started=lambda child:None,deadline=20))
''')
        master, slave = pty.openpty()
        child = subprocess.Popen([sys.executable, '-B', str(supervisor), str(ADAPTER), str(script), source,
            str(self.root), str(self.root / 'tty.log')], stdin=slave, stdout=slave, stderr=subprocess.PIPE)
        os.close(slave)
        received = b''
        def until(marker):
            nonlocal received
            end = time.monotonic() + 12
            while marker not in received:
                if time.monotonic() >= end:
                    self.fail('PTY fixture did not reach ' + repr(marker))
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    received += os.read(master, 65536)
            return received
        try:
            until(b'READY ')
            os.write(master, b'first\r')
            until(b'TURN 0 first')
            self.assertIsNone(child.poll())
            os.write(master, b'second\r')
            until(b'TURN 1 second')
            self.assertIsNone(child.poll())
            os.write(master, b'exit\r')
            end = time.monotonic() + 12
            while child.poll() is None and time.monotonic() < end:
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    try:
                        received += os.read(master, 65536)
                    except OSError:
                        break
            self.assertEqual(child.wait(timeout=5), 0, child.stderr.read().decode())
            text = received.decode(errors='replace')
            pids = [line.split()[-1] for line in text.splitlines() if line.startswith('TURN ')]
            self.assertEqual(len(set(pids)), 1)
            self.assertIn(b'TURN 1 second', (self.root / 'tty.log').read_bytes())
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
            child.stderr.close()
            os.close(master)

    def test_owned_pane_real_pty_has_no_default_deadline_and_honors_explicit_trial_deadline(self):
        # The controller owns removal of a stale template deadline. This boundary
        # accepts its deadline-free run-config and preserves explicit CLI trials.
        idle = self.root / 'deadline_idle.py'
        idle.write_text("import os\nassert os.isatty(0) and os.isatty(1)\nprint('IDLE_READY',flush=True)\ninput()\n")
        supervisor = self.root / 'deadline_supervisor.py'
        supervisor.write_text('''import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import pane_entry,tty_runtime
original=tty_runtime.run
def fixture_child(command,**kwargs):
 assert Path(command[3]).name=='managed_entry.py'
 print('PTY_DEADLINE='+json.dumps(kwargs['deadline']),flush=True)
 return original([command[0],'-I','-B',sys.argv[3]],**kwargs)
tty_runtime.run=fixture_child
raise SystemExit(pane_entry.execute(Path(sys.argv[2])))
''')
        for label, deadline in (('unlimited', None), ('trial', 1)):
            with self.subTest(label=label):
                state = self.root / ('deadline-' + label)
                runner.initialize(self.fixture.config_path, state, 'strata', self.fixture.product.run,
                    file_task=True, task_spec={'task_mode': 'conversation'})
                mail_lifecycle.register(state, self.fixture.product.run, generate_config=False)
                runner.configure(state, self.fixture.product.run)
                config = read(state / 'run-config.json')
                self.assertNotIn('task_timeout_seconds', config)
                if deadline is not None:
                    config['task_timeout_seconds'] = deadline
                    save(state / 'run-config.json', config)
                save(state / 'start-intent.json', {'agent_name': 'FixtureChild'})
                master, slave = pty.openpty()
                child = subprocess.Popen([sys.executable, '-I', '-B', str(supervisor), str(ADAPTER), str(state), str(idle)],
                    stdin=slave, stdout=slave, stderr=slave, cwd='/', env=runner.base_env(config), start_new_session=True)
                os.close(slave)
                output = b''
                def drain(seconds, marker=None):
                    nonlocal output
                    end = time.monotonic() + seconds
                    while time.monotonic() < end and (marker is None or marker not in output):
                        if select.select([master], [], [], .05)[0]:
                            try:
                                data = os.read(master, 65536)
                            except OSError:
                                break
                            if not data:
                                break
                            output += data
                try:
                    drain(5, b'IDLE_READY')
                    self.assertIn(b'IDLE_READY', output)
                    self.assertIn(b'PTY_DEADLINE=' + json.dumps(deadline).encode(), output)
                    if deadline is None:
                        # Stay alive beyond the other case's explicit one-second
                        # deadline, then close through the same real input relay.
                        drain(1.25)
                        self.assertIsNone(child.poll())
                        self.assertFalse((state / 'runtime-exit.json').exists())
                        os.write(master, b'close\r')
                    drain(5)
                    code = child.wait(timeout=5)
                    self.assertTrue((state / 'runtime-exit.json').exists(), output.decode(errors='replace'))
                    receipt = read(state / 'runtime-exit.json')
                    self.assertTrue(receipt['group_absent'])
                    self.assertEqual(receipt['group_check'], 'observed')
                    self.assertEqual(receipt['stopped_by'], 'native-exit' if deadline is None else 'limit')
                    self.assertEqual(code, 0 if deadline is None else 1)
                    self.assertIn(b'IDLE_READY', (state / 'stdout.log').read_bytes())
                finally:
                    if child.poll() is None:
                        child.terminate()
                        try:
                            child.wait(timeout=8)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait()
                    os.close(master)

    def test_signal_permission_failure_is_not_accepted_for_a_live_owned_child(self):
        import signal
        import tty_runtime
        import pane_entry
        exited = SimpleNamespace(pid=42, poll=lambda: -signal.SIGHUP, wait=lambda **kwargs: -signal.SIGHUP)
        live = SimpleNamespace(pid=42, poll=lambda: None, wait=lambda **kwargs: self.fail('live EPERM was ignored'))
        with patch.object(tty_runtime.os, 'killpg', side_effect=PermissionError('denied')):
            with self.assertRaises(ProcessLookupError):
                tty_runtime.signal_owned_group(exited, signal.SIGTERM)
            pane_entry.terminate(exited)
            with self.assertRaises(PermissionError):
                tty_runtime.signal_owned_group(live, signal.SIGTERM)
            with self.assertRaises(PermissionError):
                pane_entry.terminate(live)

    def test_pinned_config_loader_and_guard_use_attempt_overlay_offline(self):
        source = os.environ.get('ORRERY_HERMES_TEST_SOURCE')
        python = os.environ.get('ORRERY_HERMES_TEST_PYTHON')
        if not source or not python:
            self.skipTest('Explicit installed dependency interpreter/source required')
        config = read(self.fixture.config_path)
        config['hermes_source'] = source
        self.fixture.install = Path(config['managed_root']) / 'installs' / __import__('hashlib').sha256(str(Path(source).resolve()).encode()).hexdigest()[:16]
        self.fixture.add_generation('installed-overlay')
        environment = Path(read(self.fixture.install / 'facts.json')['packages']['venv']['environment'])
        real_environment = Path(python).parent.parent
        (environment / 'pyvenv.cfg').write_bytes((real_environment / 'pyvenv.cfg').read_bytes())
        (environment / 'lib').mkdir()
        for path in (real_environment / 'lib').glob('python*'):
            (environment / 'lib' / path.name).mkdir()
            (environment / 'lib' / path.name / 'site-packages').symlink_to(path / 'site-packages', target_is_directory=True)
        config['worktree'] = str(self.root / 'overlay-work')
        save(self.fixture.config_path, config)
        state = self.root / 'installed-overlay'
        runner.initialize(self.fixture.config_path, state, 'strata', self.fixture.product.run,
                          file_task=True, task_spec={'task_mode': 'conversation'})
        mail_lifecycle.register(state, self.fixture.product.run, generate_config=False)
        runner.configure(state, self.fixture.product.run)
        save(state / 'mail-probe.json', read(self.state / 'mail-probe.json'))
        config = read(state / 'run-config.json')
        stable = (Path(config['profile_home']) / 'config.yaml').read_bytes()
        code = '''import json,sys,os
sys.path.insert(0,sys.argv[1])
from pathlib import Path
import managed_entry
state=Path(sys.argv[2])
config=json.loads((state/'run-config.json').read_text())
os.environ.update(HERMES_HOME=config['profile_home'],ORRERY_HERMES_STATE_ROOT=str(state),ORRERY_HERMES_ADAPTER_DIR=sys.argv[1])
def deny(name,args):
 if name in ('socket.connect','socket.getaddrinfo'): raise RuntimeError('offline-only fixture')
 if name=='subprocess.Popen':
  argv=list(args[1])[1:]
  if argv[:1]==['--no-optional-locks']: argv=argv[1:]
  readonly=bool(argv) and (argv[0] in ('rev-parse','describe','log','rev-list','show')
   or argv==['branch','--show-current'] or (argv[0]=='status' and '--porcelain' in argv)
   or (argv[0]=='tag' and '--list' in argv and '--merged' in argv))
  stamp=Path(config['hermes_source'])/'install-stamp.json'
  legacy=not stamp.exists() or json.loads(stamp.read_text()).get('source')=='git'
  if legacy and Path(str(args[0])).name=='git' and readonly: return
  raise RuntimeError('offline-only fixture')
sys.addaudithook(deny)
assert managed_entry.execute(state,check=True)==0
from hermes_cli.config import load_config,get_config_path
merged=load_config()
assert str(get_config_path())==config['runtime_config']
assert merged['mcp_servers']['orrery_mail']['env']['AGENTSTACK_PROXY_TOKEN_FILE']==str(state/'token-FixtureChild')
assert merged['auth']['adopt_external_logins'] is False
from tools import session_search_tool,skill_manager_tool
assert session_search_tool._resolve_profile_db(None) is None
assert session_search_tool._resolve_profile_db(config['profile_name']) is None
try: session_search_tool._resolve_profile_db('other')
except ValueError: pass
else: raise AssertionError('cross-profile database accepted')
assert skill_manager_tool._find_skill_in_other_profiles('missing')==[]
print('actual-loader-guard-overlay-ok')
'''
        result = subprocess.run([python, '-I', '-B', '-c', code, str(ADAPTER), str(state)],
                                cwd='/', env=runner.base_env(config), capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('actual-loader-guard-overlay-ok', result.stdout)
        self.assertEqual((Path(config['profile_home']) / 'config.yaml').read_bytes(), stable)
        self.assertTrue(read(state / 'preflight-complete.json')['guard_loaded'])
        marker = self.fixture.install / '.repair-incomplete'
        marker.write_text('explicit repair required')
        blocked = subprocess.run([python, '-I', '-B', '-c', code, str(ADAPTER), str(state)],
            cwd='/', env=runner.base_env(config), capture_output=True, text=True, timeout=30)
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn('dependencies require explicit operator repair', blocked.stderr)
        marker.unlink()
        sites = next((environment / 'lib').glob('python*/site-packages'))
        site_target = sites.readlink()
        sites.unlink()
        blocked = subprocess.run([python, '-I', '-B', '-c', code, str(ADAPTER), str(state)],
            cwd='/', env=runner.base_env(config), capture_output=True, text=True, timeout=30)
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn('dependencies require explicit operator repair', blocked.stderr)
        sites.symlink_to(site_target, target_is_directory=True)

    def test_pinned_native_cli_two_turns_raw_usage_and_reserved_write(self):
        source = os.environ.get('ORRERY_HERMES_TEST_SOURCE')
        python = os.environ.get('ORRERY_HERMES_TEST_PYTHON')
        if not source or not python:
            self.skipTest('Explicit installed dependency interpreter/source required')
        from hermes_native_fixture import run
        state, turns = run(self.fixture, ADAPTER, source, python)
        self.assertTrue(all(turn['latest_turn']['completed'] is True for turn in turns))
        self.assertNotEqual(turns[0]['turn_id'], turns[1]['turn_id'])
        self.assertIsNotNone(turns[0]['task_id'])
        self.assertIsNone(turns[1]['task_id'])
        self.assertTrue(completion.evaluate_task(state)['success'])
        report = state / 'task-reports' / (read(state / 'task.json')['task_id'] + '.json')
        frozen = report.read_bytes()
        config = read(state / 'run-config.json')
        self.assertEqual((Path(config['worktree']) / 'native-result.txt').read_text(), 'native-done')
        self.assertEqual(inventory(state), ({501}, {501}))
        audit = [json.loads(line) for line in (state / 'audit.jsonl').read_text().splitlines()]
        self.assertFalse([row for row in audit if row['phase'].startswith('blocked-')])
        starts = [row['seq'] for row in audit if row['phase'] == 'provider-request-start']
        usage = {row['seq']: row for row in audit if row['phase'] == 'provider-usage'}
        self.assertTrue(starts)
        self.assertTrue(all(usage[seq]['confirmed'] is True and usage[seq]['terminal'] is True for seq in starts))
        (Path(config['worktree']) / 'native-result.txt').write_text('later free edit')
        self.assertTrue(completion.evaluate_task(state)['success'])
        self.assertEqual(report.read_bytes(), frozen)
        self.assertTrue(read(state / 'runtime-exit.json')['group_absent'])
        self.assertEqual(read(state / 'runtime-exit.json')['group_check'], 'observed')
        self.assertEqual(read(state / 'diagnostic-scan.json')['matches'], 0)
        self.assertEqual(read(state / 'diagnostic-scan.json')['errors'], 0)

    def test_pinned_native_empty_conversation_opens_idle_and_accepts_later_input(self):
        source = os.environ.get('ORRERY_HERMES_TEST_SOURCE')
        python = os.environ.get('ORRERY_HERMES_TEST_PYTHON')
        if not source or not python:
            self.skipTest('Explicit installed dependency interpreter/source required')
        from hermes_native_fixture import run
        state, turns = run(self.fixture, ADAPTER, source, python, empty=True)
        self.assertEqual((state / 'task.md').read_text(), '')
        self.assertEqual(turns[0]['activity'], 'idle')
        self.assertNotIn('latest_turn', turns[0])
        self.assertEqual(len(turns), 3)
        self.assertTrue(all(row['latest_turn']['completed'] is True for row in turns[1:]))
        self.assertIsNone(completion.evaluate_task(state)['success'])
        self.assertEqual(completion.evaluate_task(state)['evaluation'], 'not_applicable')
        events = [json.loads(line) for line in (state / 'events.jsonl').read_text().splitlines()]
        self.assertEqual(len([row for row in events if row['phase'] == 'native-ready']), 1)
        self.assertFalse((state / 'task-reports').exists())

    def test_pinned_native_chat_completions_route_keeps_two_turns_and_raw_usage(self):
        source = os.environ.get('ORRERY_HERMES_TEST_SOURCE')
        python = os.environ.get('ORRERY_HERMES_TEST_PYTHON')
        if not source or not python:
            self.skipTest('Explicit installed dependency interpreter/source required')
        from hermes_native_fixture import run
        state, turns = run(self.fixture, ADAPTER, source, python, backend='deepseek', transport='chat_completions')
        self.assertTrue(all(row['latest_turn']['completed'] is True for row in turns))
        self.assertTrue(completion.evaluate_task(state)['success'])
        self.assertEqual(inventory(state), ({501}, {501}))
        self.assertTrue(read(state / 'runtime-exit.json')['group_absent'])


if __name__ == '__main__':
    unittest.main()

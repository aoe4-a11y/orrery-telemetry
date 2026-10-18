"""Whole-launcher adversarial tests: no real seat, service, home or tmux."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import test_restart_identity as fixtures

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'hooks'))
from seat_lifecycle import Seat, atomic_json, managed_update


FAKE_TMUX = r'''#!/usr/bin/env python3
import json, os, pathlib, signal, sys
args = sys.argv[1:]
verb = args[0]
base = pathlib.Path(os.environ['FIXTURE_TMUX_LOG'])
with base.open('a') as stream: stream.write(verb + '\n')
if verb == 'new-session':
    base.with_suffix('.prompt').unlink(missing_ok=True)
    env = dict(os.environ)
    for index, arg in enumerate(args):
        if arg == '-e':
            key, value = args[index + 1].split('=', 1)
            env[key] = value
    base.with_suffix('.env').write_text(json.dumps(env))
    if os.environ.get('FIXTURE_SIGNAL'):
        os.kill(os.getppid(), int(os.environ['FIXTURE_SIGNAL']))
        sys.exit(17)
    if os.environ.get('FIXTURE_EARLY_FAILURE') == '1': sys.exit(17)
elif verb == 'capture-pane':
    prompt = base.with_suffix('.prompt')
    print(prompt.read_text() if prompt.exists() else '? for shortcuts')
elif verb == 'send-keys' and '-l' in args:
    base.with_suffix('.prompt').write_text(args[args.index('-l') + 1])
elif verb == 'display-message': print('FixtureParent')
sys.exit(0)
'''


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RestartIdentityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.base = self.fixture.base

    def arrange(self, existing=False):
        seat = self.fixture.arrange(existing)
        self.fixture.enable_proxy(seat)
        fixtures.executable(self.base / 'bin/tmux', FAKE_TMUX)
        return seat

    def launch(self, seat, provider='codex', expect=0, extra_env=None):
        env = dict(seat['env'], **(extra_env or {}))
        fixtures.freeze_tmux_fixture(env)
        args = ['/bin/bash', str(fixtures.SPAWN), '--model', 'gpt-5.5' if provider == 'codex' else 'fable',
                '--pre-registered', fixtures.NAME, '--child-token-file', str(seat['handoff']),
                '--embed-task']
        if provider == 'codex': args.append('--codex')
        args += ['fixture-only lifecycle work', str(seat['work'])]
        result = subprocess.run(args, env=env, cwd=seat['work'], capture_output=True, text=True, timeout=25)
        if expect == 0: self.assertEqual(result.returncode, 0, result.stderr)
        else: self.assertEqual(result.returncode, expect, result.stderr)
        path = self.base / 'tmux-verbs.env'
        return json.loads(path.read_text()) if path.exists() else None

    def cleanup(self, env):
        result = subprocess.run(['/bin/bash', str(fixtures.CLEANUP)], env=env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_success_then_delayed_cleanup_removes_only_owned_for_each_provider(self):
        for provider in ('codex', 'claude'):
            with self.subTest(provider=provider):
                # Separate fixture/namespace, rather than reusing a spent launch.
                other = LifecycleTests(); other.setUp()
                try:
                    seat = other.arrange()
                    child_env = other.launch(seat, provider)
                    self.assertIn('AGENTSTACK_LAUNCH_JOURNAL', child_env)
                    self.assertTrue(seat['token'].exists())
                    other.cleanup(child_env)
                    for key in ('token', 'state', 'home', 'config'):
                        self.assertFalse(seat[key].exists(), key)
                    self.assertEqual(seat['managed'].read_text(), 'OtherSeat\n')
                finally: other.doCleanups()

    def test_delayed_old_cleanup_preserves_same_inode_successor(self):
        seat = self.arrange()
        old_env = self.launch(seat)
        old_inode = seat['token'].stat().st_ino
        seat['handoff'] = seat['token']
        owner = Seat(seat['token'].parent, fixtures.NAME)
        with owner.locked():
            owner.invalidate()
        new_env = self.launch(seat)
        self.assertEqual(old_inode, seat['token'].stat().st_ino)
        self.assertNotEqual(old_env['AGENTSTACK_LAUNCH_JOURNAL'], new_env['AGENTSTACK_LAUNCH_JOURNAL'])
        self.cleanup(old_env)
        self.assertEqual(seat['token'].read_text(), fixtures.TOKEN)
        self.cleanup(new_env)  # Existing identities are also preserved.
        self.assertEqual(seat['token'].read_text(), fixtures.TOKEN)

    def test_signal_cleanup_uses_writer_journal(self):
        for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=signum):
                other = LifecycleTests(); other.setUp()
                try:
                    seat = other.arrange()
                    other.launch(seat, expect=128 + signum, extra_env={'FIXTURE_SIGNAL': str(signum)})
                    for key in ('token', 'state', 'home', 'config'):
                        self.assertFalse(seat[key].exists(), key)
                finally: other.doCleanups()

    def test_partial_home_writer_failure_cleans_created_directory(self):
        seat = self.arrange()
        Path(seat['env']['CODEX_HOME'], 'config.toml').write_bytes(b'\xff')
        self.launch(seat, expect=0)
        child_env = json.loads((self.base / 'tmux-verbs.env').read_text())
        self.cleanup(child_env)
        self.assertFalse(seat['home'].exists())
        self.assertFalse(seat['token'].exists())

    def test_cleanup_rechecks_after_http_before_retirement_or_deletion(self):
        seat = self.arrange()
        child_env = self.launch(seat)
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append(request['params']['name'])
                if len(calls) == 1:
                    seat['token'].rename(seat['token'].with_suffix('.old'))
                    seat['token'].write_text('replacement fixture identity')
                self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            child_env['AGENTSTACK_MCP_URL'] = f'http://127.0.0.1:{server.server_port}/mcp'
            self.cleanup(child_env)
        finally:
            server.shutdown(); server.server_close(); thread.join()
        self.assertEqual(calls, ['release_file_reservations'])
        self.assertEqual(seat['token'].read_text(), 'replacement fixture identity')
        self.assertTrue(seat['state'].exists())

    def test_cross_project_adoption_refused_before_writes(self):
        seat = self.arrange(True)
        before = {key: seat[key].read_bytes() for key in ('token', 'state')}
        env = dict(seat['env'], PROJECT_KEY='/another/project')
        args = ['/bin/bash', str(fixtures.SPAWN), '--codex', '--model', 'gpt-5.5',
                '--pre-registered', fixtures.NAME, '--child-token-file', str(seat['handoff']),
                '--embed-task', 'fixture task', str(seat['work'])]
        result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        for key, content in before.items(): self.assertEqual(seat[key].read_bytes(), content)
        self.assertNotIn('new-session', (self.base / 'tmux-verbs').read_text() if (self.base / 'tmux-verbs').exists() else '')

    def test_normalized_name_lock_excludes_other_process(self):
        runtime = self.base / 'runtime'
        seat = Seat(runtime, 'Fixture-Seat')
        with seat.locked():
            child = subprocess.Popen([sys.executable, str(ROOT / 'hooks/seat_lifecycle.py'), 'lock-exec',
                                      '--runtime', str(runtime), '--name', 'FixtureSeat', '--',
                                      sys.executable, '-c', 'print("acquired", flush=True)'],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                     env={k:v for k,v in os.environ.items() if not k.startswith('AGENTSTACK_')})
            import select
            self.assertEqual(select.select([child.stdout], [], [], 0.2)[0], [])
        out, err = child.communicate(timeout=10)
        self.assertEqual(child.returncode, 0, err)
        self.assertEqual(out.strip(), 'acquired')

    def test_missing_or_stale_journal_preserves_everything(self):
        seat = self.arrange(True)
        self.cleanup(dict(seat['env'], AGENT_NAME=fixtures.NAME,
                          AGENTSTACK_LIFECYCLE_NAME=fixtures.NAME,
                          AGENTSTACK_LAUNCH_JOURNAL=str(self.base / 'absent')))
        self.fixture.assert_existing(seat)




def test_preregister_wrappers_do_not_seed_canonical_identity(tmp_path):
    for provider in ('codex', 'claude'):
        home = tmp_path / provider
        stack = home / '.agentstack'
        (stack / 'bin').mkdir(parents=True)
        (stack / 'hooks').mkdir()
        task = home / 'task.md'; task.write_text('fixture work')
        helper = stack / 'bin/agentstack-preregister-child'
        fixtures.executable(helper, '''#!/usr/bin/env python3
import os, pathlib, sys
args = sys.argv[1:]
path = pathlib.Path(args[args.index('--token-file-out') + 1])
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.write(fd, b'fixture-only-token'); os.close(fd)
print('FreshCurie')
''')
        fixtures.executable(stack / 'hooks/spawn_child.sh', '''#!/usr/bin/env python3
import os, pathlib, stat, sys
args = sys.argv[1:]
assert not (pathlib.Path.home()/'.agentstack/runtime/agent_token_FreshCurie').exists()
path = pathlib.Path(args[args.index('--child-token-file') + 1])
assert path.read_text() == 'fixture-only-token'
assert stat.S_IMODE(path.stat().st_mode) == 0o600
print('verified fixture handoff')
''')
        env = {k:v for k,v in os.environ.items() if k in ('PATH', 'LANG')}
        env.update(HOME=str(home), TMPDIR=str(home), AGENTSTACK_PROJECT_KEY='/fixture/project')
        result = subprocess.run(['/bin/bash', str(ROOT / f'bin/agentstack-spawn-{provider}'),
                                 'gpt-5.5' if provider == 'codex' else 'fable', str(task), str(home)],
                                env=env, capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert 'verified fixture handoff' in result.stdout


def _dashboard_fixture(monkeypatch, tmp_path, launch):
    import dashboard.server as server
    runtime = tmp_path / 'runtime'; runtime.mkdir()
    (runtime / 'agent_token_Parent').write_text('fixture parent token')
    monkeypatch.setattr(server, 'RUNTIME_DIR', str(runtime))
    monkeypatch.setattr(server, 'HERE', str(tmp_path))
    monkeypatch.setattr(server, 'SPAWN_SCRIPT', str(fixtures.SPAWN))
    monkeypatch.setattr(server, '_project_key', lambda: '/fixture/project')
    monkeypatch.setattr(server, '_spawn_name_status', lambda _: 'available')
    monkeypatch.setattr(server, '_mcp_call', lambda method, args, **kwargs: {'ok':True, 'data':
        {'name':'FreshCurie','registration_token':'fixture child token'} if method == 'register_agent' else {}})
    monkeypatch.setattr(server, '_record_name_substitution', lambda *args: None)
    class Process:
        def wait(self, timeout): return 17
    def popen(args, **kwargs):
        launch(runtime, args, kwargs['env'])
        return Process()
    monkeypatch.setattr(server.subprocess, 'Popen', popen)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return type('Result', (), {'returncode': 0})()
    monkeypatch.setattr(server.subprocess, 'run', run)
    result = server.do_spawn({'parent':'Parent', 'name':'Fresh-Curie', 'task':'fixture work',
                              'dir': str(tmp_path), 'provider':'codex', 'model':'gpt-5.6-sol'})
    assert not result['ok']
    assert 'exited with status 17' in result['error'], result
    return runtime, calls


def test_dashboard_failure_preserves_unowned_canonical_and_replaced_handoff(monkeypatch, tmp_path):
    handoffs = []
    def launch(runtime, args, env):
        token = runtime / 'agent_token_FreshCurie'
        token.write_text('other fixture owner')
        handoff = Path(args[args.index('--child-token-file') + 1])
        handoff.rename(handoff.with_suffix('.owned-old'))
        handoff.write_text('replacement fixture handoff')
        handoffs.append(handoff)
    runtime, calls = _dashboard_fixture(monkeypatch, tmp_path, launch)
    assert (runtime / 'agent_token_FreshCurie').read_text() == 'other fixture owner'
    assert handoffs[0].read_text() == 'replacement fixture handoff'
    assert not any('kill-session' in call for call in calls)


def test_dashboard_failure_cleans_only_matching_launch_generation(monkeypatch, tmp_path):
    def launch(runtime, args, env):
        seat = Seat(runtime, 'FreshCurie')
        with seat.locked():
            with __import__('unittest').mock.patch.dict(os.environ, {'AGENTSTACK_LAUNCH_ATTEMPT_ID':env['AGENTSTACK_LAUNCH_ATTEMPT_ID']}):
                journal = seat.begin('/fixture/project', runtime / 'managed_agents.txt')
            paths = seat.paths(); paths['state'].parent.mkdir(exist_ok=True)
            for key in ('token','state'): paths[key].write_text('owned fixture identity')
            paths['state'].write_text(json.dumps({'agent_name':'FreshCurie','project_key':'/fixture/project'}))
            auth = [[str(paths[key]), paths[key].stat().st_dev, paths[key].stat().st_ino] for key in ('token','state')]
            seat.update(journal['journal'], auth={'owned':auth,'observed':auth}, session_started=True)
    runtime, calls = _dashboard_fixture(monkeypatch, tmp_path, launch)
    assert any('kill-session' in call for call in calls)
    assert not (runtime / 'agent_token_FreshCurie').exists()


def test_dashboard_delayed_failure_preserves_same_inode_successor(monkeypatch, tmp_path):
    def launch(runtime, args, env):
        seat = Seat(runtime, 'FreshCurie')
        with seat.locked():
            with __import__('unittest').mock.patch.dict(os.environ, {'AGENTSTACK_LAUNCH_ATTEMPT_ID':env['AGENTSTACK_LAUNCH_ATTEMPT_ID']}):
                journal = seat.begin('/fixture/project', runtime / 'managed_agents.txt')
            paths = seat.paths(); paths['state'].parent.mkdir(exist_ok=True)
            for key in ('token','state'): paths[key].write_text('successor fixture identity')
            paths['state'].write_text(json.dumps({'agent_name':'FreshCurie','project_key':'/fixture/project'}))
            auth = [[str(paths[key]), paths[key].stat().st_dev, paths[key].stat().st_ino] for key in ('token','state')]
            seat.update(journal['journal'], auth={'owned':auth,'observed':auth}, session_started=True)
            # Same auth inodes adopted by the next launch, with a new lease.
            seat.invalidate()
            with __import__('unittest').mock.patch.dict(os.environ, {'AGENTSTACK_LAUNCH_ATTEMPT_ID':'different-successor-attempt'}):
                successor = seat.begin('/fixture/project', runtime / 'managed_agents.txt')
            seat.update(successor['journal'], auth={'observed':auth}, session_started=True)
            assert seat.validate(successor['journal']) is not None
    runtime, calls = _dashboard_fixture(monkeypatch, tmp_path, launch)
    assert (runtime / 'agent_token_FreshCurie').read_text() == 'successor fixture identity'
    assert not any('kill-session' in call for call in calls)


def test_direct_entry_shares_ownership_and_child_environment():
    for provider in ('codex', 'claude'):
        fixture = LifecycleTests(); fixture.setUp()
        seat = fixture.arrange()
        methods = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                method = request['params']['name']; methods.append(method)
                payload = {'name': fixtures.NAME, 'registration_token': fixtures.TOKEN} if method == 'register_agent' else {}
                response = {'jsonrpc':'2.0', 'id':1, 'result': {'structuredContent': payload, 'content':[{'type':'text','text':json.dumps(payload)}]}}
                self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(response).encode())
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            env = dict(seat['env'], AGENTSTACK_MCP_URL=f'http://127.0.0.1:{server.server_port}/mcp',
                       AGENTSTACK_DIRECT_CANDIDATE='Restart-Fixture')
            args = ['/bin/bash', str(fixtures.SPAWN), '--unsafe-no-resources', '--model',
                    'gpt-5.5' if provider == 'codex' else 'fable']
            if provider == 'codex': args.append('--codex')
            args += ['fixture direct work', str(seat['work'])]
            result = subprocess.run(args, env=env, cwd=seat['work'], capture_output=True, text=True, timeout=25)
            assert result.returncode == 0, result.stderr
            assert methods.count('register_agent') == 1
            child_env = json.loads((fixture.base / 'tmux-verbs.env').read_text())
            assert child_env['AGENTSTACK_RESERVED_IDENTITY'] == '1'
            assert child_env['AGENT_NAME'] == fixtures.NAME
            journal = json.loads(Path(child_env['AGENTSTACK_LAUNCH_JOURNAL']).read_text())
            assert journal['preserve'] is False
            assert seat['token'].read_text() == fixtures.TOKEN
            fixture.cleanup(child_env)
            assert not seat['token'].exists()
        finally:
            server.shutdown(); server.server_close(); thread.join(); fixture.doCleanups()


def test_direct_cross_project_local_collision_prevents_registration():
    fixture = LifecycleTests(); fixture.setUp()
    seat = fixture.arrange(True)
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(request['params']['name'])
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"result":{}}')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        env = dict(seat['env'], PROJECT_KEY='/another/project', AGENTSTACK_DIRECT_CANDIDATE='Restart-Fixture',
                   AGENTSTACK_MCP_URL=f'http://127.0.0.1:{server.server_port}/mcp')
        result = subprocess.run(['/bin/bash', str(fixtures.SPAWN), '--codex', '--model', 'gpt-5.5',
                                 '--unsafe-no-resources', 'fixture work', str(seat['work'])],
                                env=env, capture_output=True, text=True, timeout=15)
        assert result.returncode != 0
        assert 'register_agent' not in requests
        fixture.fixture.assert_existing(seat)
    finally:
        server.shutdown(); server.server_close(); thread.join(); fixture.doCleanups()


def _writer_failure_python(fixture, kind):
    """Inject after creator intent; ordinary interpreter calls stay intact."""
    real_python = sys.executable
    wrapper = fixture.base / 'bin/python3'
    auth_patch = '''import os
_original_link = os.link
def _link(source, destination, *args, **kwargs):
    if str(destination).endswith("RestartFixture.json"):
        raise PermissionError("fixture state publication failure")
    return _original_link(source, destination, *args, **kwargs)
os.link = _link
'''
    mcp_patch = '''import json
_original_dump = json.dump
def _dump(value, stream, *args, **kwargs):
    if isinstance(value, dict) and "mcpServers" in value:
        raise PermissionError("fixture config payload write failure")
    return _original_dump(value, stream, *args, **kwargs)
json.dump = _dump
'''
    code = f'''#!{real_python}
import os, sys
args = sys.argv[1:]
if args and args[0] == '-' and len(args) > 1:
    source = sys.stdin.read()
    if {kind!r} == 'auth' and args[1] == 'RestartFixture':
        source = {auth_patch!r} + source
    elif {kind!r} == 'mcp' and args[1].endswith('.mcp.json'):
        source = {mcp_patch!r} + source
    os.execv({real_python!r}, ['python3', '-c', source, *args[1:]])
os.execv({real_python!r}, ['python3', *args])
'''
    fixtures.executable(wrapper, code)


def test_partial_auth_writer_failure_rolls_back_only_its_published_inode():
    fixture = LifecycleTests(); fixture.setUp()
    try:
        seat = fixture.arrange()
        _writer_failure_python(fixture, 'auth')
        fixture.launch(seat, expect=1)
        assert not seat['token'].exists()
        assert not seat['state'].exists()
        assert seat['handoff'].read_text() == fixtures.TOKEN
        assert seat['managed'].read_text() == 'OtherSeat\n'
    finally: fixture.doCleanups()


def test_partial_mcp_writer_failure_still_records_owned_config():
    fixture = LifecycleTests(); fixture.setUp()
    try:
        seat = fixture.arrange()
        _writer_failure_python(fixture, 'mcp')
        child_env = fixture.launch(seat, provider='claude')
        assert seat['config'].exists()
        journal = json.loads(Path(child_env['AGENTSTACK_LAUNCH_JOURNAL']).read_text())
        assert any(entry[0] == str(seat['config']) for entry in journal['artifacts']['owned'])
        fixture.cleanup(child_env)
        assert not seat['config'].exists()
        assert not seat['token'].exists()
    finally: fixture.doCleanups()


def test_restart_waits_for_name_lock_before_kill_and_invalidates_old_generation():
    fixture = LifecycleTests(); fixture.setUp()
    try:
        seat = fixture.arrange(True)
        lifecycle = Seat(seat['token'].parent, fixtures.NAME)
        task = fixture.base / 'restart-task.md'; task.write_text('fixture restart work')
        hooks = fixture.base / 'restart-hooks'; hooks.mkdir()
        (hooks / 'seat_lifecycle.py').write_text((ROOT / 'hooks/seat_lifecycle.py').read_text())
        fixtures.executable(hooks / 'spawn_child.sh', '''#!/bin/bash
python3 "$AGENTSTACK_HOOKS_DIR/seat_lifecycle.py" held --runtime "$AGENTSTACK_RUNTIME_DIR" --name RestartFixture || exit 8
printf 'locked fixture launch\\n'
''')
        with lifecycle.locked():
            old = lifecycle.begin('/fixture/project', seat['managed'])
            env = dict(seat['env'], AGENTSTACK_HOOKS_DIR=str(hooks))
            child = subprocess.Popen(['/bin/bash', str(ROOT / 'bin/agentstack-restart-seat'),
                                      fixtures.NAME, str(task), 'gpt-5.5', 'medium', '/'],
                                     env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            import select
            assert select.select([child.stdout], [], [], 0.2)[0] == []
            assert not (fixture.base / 'tmux-verbs').exists()
        out, err = child.communicate(timeout=15)
        assert child.returncode == 0, err
        assert 'locked fixture launch' in out
        assert not lifecycle.current(old)
        assert (fixture.base / 'tmux-verbs').read_text().splitlines().count('kill-session') == 1
        fixture.fixture.assert_existing(seat)
    finally: fixture.doCleanups()


def test_handoff_cannot_consume_another_seats_canonical_credential():
    for kind in ('token', 'state'):
        fixture = LifecycleTests(); fixture.setUp()
        try:
            seat = fixture.arrange()
            runtime = seat['token'].parent
            protected = (runtime / 'agent_token_AnotherFixtureSeat' if kind == 'token'
                         else runtime / 'child-agents/AnotherFixtureSeat.json')
            protected.write_text('synthetic protected credential'); protected.chmod(0o600)
            before = protected.read_bytes()
            seat['handoff'] = protected
            fixture.launch(seat, expect=1)
            assert protected.read_bytes() == before
            assert not seat['token'].exists()
            assert not seat['state'].exists()
        finally: fixture.doCleanups()


def test_explicit_preservation_veto_keeps_a_fresh_owned_launch():
    fixture = LifecycleTests(); fixture.setUp()
    try:
        seat = fixture.arrange()
        child_env = fixture.launch(seat)
        fixture.cleanup(dict(child_env, AGENTSTACK_PRESERVE_SEAT_IDENTITY='1'))
        assert seat['token'].read_text() == fixtures.TOKEN
        fixture.cleanup(dict(child_env, AGENTSTACK_PRESERVE_SEAT_IDENTITY='0'))
        assert not seat['token'].exists()
    finally: fixture.doCleanups()


def test_state_project_is_checked_without_an_explicit_handoff():
    for token_present in (False, True):
        fixture = LifecycleTests(); fixture.setUp()
        try:
            seat = fixture.arrange(True)
            if not token_present:
                seat['token'].unlink()
                seat['state'].chmod(0o600)
            before = seat['state'].read_bytes()
            env = dict(seat['env'], PROJECT_KEY='/another/project')
            completed = subprocess.run(
                ['/bin/bash', str(fixtures.SPAWN), '--codex', '--model', 'gpt-5.5',
                 '--pre-registered', fixtures.NAME, '--embed-task', 'fixture project boundary', str(seat['work'])],
                env=env, capture_output=True, text=True, timeout=20)
            assert completed.returncode != 0
            assert seat['state'].read_bytes() == before
            assert seat['token'].exists() is token_present
        finally: fixture.doCleanups()


def test_top_level_managed_writer_obeys_the_shared_list_lock(tmp_path):
    import fcntl
    import select
    managed = tmp_path / "managed.txt"
    managed.write_text("OtherSeat" + chr(10))
    lock = os.open(str(managed) + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    child = None
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        script = """
source "$1"
echo ready
ags_record_managed_agent "$2" AddedSeat
echo added
"""
        child = subprocess.Popen(["/bin/bash", "-c", script, "fixture",
                                  str(ROOT / "bin/lib/agentstack-register.sh"), str(managed)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert select.select([child.stdout], [], [], 5)[0]
        assert os.read(child.stdout.fileno(), 64) == b"ready" + bytes([10])
        assert select.select([child.stdout], [], [], 0.2)[0] == []
    finally:
        os.close(lock)
        if sys.exc_info()[0] is not None and child is not None:
            child.terminate()
            child.communicate(timeout=5)
    out, err = child.communicate(timeout=10)
    assert child.returncode == 0, err
    assert out.strip() == b"added"
    assert managed.read_text().splitlines() == ["OtherSeat", "AddedSeat"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))

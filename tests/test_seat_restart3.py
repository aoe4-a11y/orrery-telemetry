"""Review counterexamples. Synthetic identities, private homes and fake CLIs only."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest
from unittest.mock import patch

import test_restart_identity as fixtures
import test_seat_lifecycle as lifecycle
from test_seat_lifecycle import FAKE_TMUX, Seat, ROOT


class Restart3Tests(unittest.TestCase):
    def setUp(self):
        self.lane = lifecycle.LifecycleTests()
        self.lane.setUp()
        self.addCleanup(self.lane.doCleanups)

    def test_background_terminal_does_not_inherit_seat_lock(self):
        base = self.lane.base
        source = fixtures.SPAWN.read_text()
        start = source.index('\nopen_child_terminal() {')
        end = source.index('\n}\n', start) + 3
        opener = source[start:end]
        marker, release = base/'opener.json', base/'opener.release'
        stub = base/'opener.py'
        stub.write_text(textwrap.dedent('''\
            import json, os, pathlib, sys, time
            try: os.fstat(9); inherited = True
            except OSError: inherited = False
            authority = [key for key in ('AGENTSTACK_LAUNCH_JOURNAL', 'AGENTSTACK_LIFECYCLE_NAME', 'AGENTSTACK_DIRECT_CANDIDATE', 'AGENTSTACK_LIFECYCLE_HOOKS_DIR', 'AGENTSTACK_PRESERVE_SEAT_IDENTITY') if key in os.environ]
            pathlib.Path(sys.argv[1]).write_text(json.dumps({'fd9': inherited, 'env': os.environ.get('AGENTSTACK_SEAT_LOCK_FD'), 'authority': authority}))
            for _ in range(500):
                if pathlib.Path(sys.argv[2]).exists(): break
                time.sleep(.02)
        '''))
        script = base/'open.sh'
        script.write_text(opener + '\n_open_child_terminal() { python3 "$FIXTURE_OPENER" "$FIXTURE_MARKER" "$FIXTURE_RELEASE"; }\nopen_child_terminal FixtureSeat\n')
        seat = Seat(base/'runtime', 'FixtureSeat')
        env = dict(self.lane.fixture.fixture_env, FIXTURE_OPENER=str(stub), FIXTURE_MARKER=str(marker), FIXTURE_RELEASE=str(release)) if hasattr(self.lane.fixture, 'fixture_env') else dict(os.environ, FIXTURE_OPENER=str(stub), FIXTURE_MARKER=str(marker), FIXTURE_RELEASE=str(release))
        env.update(AGENTSTACK_LAUNCH_JOURNAL='fixture', AGENTSTACK_LIFECYCLE_NAME='FixtureSeat', AGENTSTACK_DIRECT_CANDIDATE='FixtureSeat', AGENTSTACK_LIFECYCLE_HOOKS_DIR='fixture-release', AGENTSTACK_PRESERVE_SEAT_IDENTITY='1')
        # The fixture's parent HOME is already isolated by setUp.
        subprocess.run([sys.executable, str(ROOT/'hooks/seat_lifecycle.py'), 'lock-exec', '--runtime', str(seat.root), '--name', seat.name, '--', '/bin/bash', str(script)], env=env, check=True, timeout=10)
        import time
        try:
            for _ in range(200):
                if marker.exists(): break
                time.sleep(.01)
            self.assertTrue(marker.exists(), 'opener must actually run')
            fd = os.open(seat.lock_path, os.O_RDWR)
            try:
                try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); available = True
                except BlockingIOError: available = False
            finally: os.close(fd)
            self.assertTrue(available, 'background opener retains the seat lock')
            self.assertEqual(json.loads(marker.read_text()), {'fd9': False, 'env': None, 'authority': []})
        finally: release.touch()

    def test_arbitrary_private_text_is_not_consumable_handoff(self):
        seat = self.lane.arrange()
        foreign = self.lane.base/'unrelated-private-key'
        foreign.write_text(fixtures.TOKEN)
        foreign.chmod(0o600)
        seat['handoff'] = foreign
        args = ['/bin/bash', str(fixtures.SPAWN), '--codex', '--model', 'gpt-5.5', '--pre-registered', fixtures.NAME, '--child-token-file', str(foreign), '--embed-task', 'fixture task', str(seat['work'])]
        result = subprocess.run(args, env=seat['env'], capture_output=True, text=True, timeout=25)
        self.assertTrue(foreign.exists(), 'unrelated private text was unlinked')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(seat['token'].exists())

    def test_unknown_child_home_record_survives_automatic_cleanup(self):
        seat = self.lane.arrange()
        child = self.lane.launch(seat)
        record = seat['home']/'mail-receipts'/'other-principal.json'
        record.parent.mkdir()
        record.write_text('{"permanent":true}\n')
        self.lane.cleanup(child)
        self.assertTrue(record.exists(), 'unknown record inside owned home was deleted')
        self.assertEqual(record.read_text(), '{"permanent":true}\n')

    def test_tmux_client_environment_has_no_lifecycle_authority(self):
        for provider in ('codex','claude'):
            with self.subTest(provider=provider):
                lane = lifecycle.LifecycleTests(); lane.setUp()
                try:
                    seat = lane.arrange()
                    fake = FAKE_TMUX.replace("if verb == 'new-session':", "if verb == 'new-session':\n    base.with_suffix('.client-env').write_text(json.dumps(dict(os.environ)))")
                    fixtures.executable(lane.base/'bin/tmux', fake)
                    child = lane.launch(seat, provider, extra_env={'AGENTSTACK_FUTURE_SECRET':'secret-canary','UNKNOWN_SECRET':'secret-canary','AGENTSTACK_MATERIALS_APPENDED':'1','AGENTSTACK_LAUNCH_ATTEMPT_ID':'fixture-attempt','AGENTSTACK_LIFECYCLE_HOOKS_DIR':str(ROOT/'hooks'),'AGENTSTACK_PRESERVE_SEAT_IDENTITY':'1'})
                    client = json.loads((lane.base/'tmux-verbs.client-env').read_text())
                    for key in client:
                        self.assertFalse(key.startswith(('AGENTSTACK_','CHILD_')), key)
                    for key in ('PROJECT_KEY','PARENT_AGENT','UNKNOWN_SECRET'): self.assertNotIn(key,client)
                    self.assertIn('AGENTSTACK_LAUNCH_JOURNAL',child)
                    self.assertEqual(child['AGENTSTACK_LIFECYCLE_NAME'],fixtures.NAME)
                    self.assertEqual(child['AGENTSTACK_LIFECYCLE_HOOKS_DIR'],str(ROOT/'hooks'))
                    self.assertEqual(child['AGENTSTACK_PRESERVE_SEAT_IDENTITY'],'0')
                finally: lane.doCleanups()

    def test_per_entry_check_protects_replacement_after_initial_validation(self):
        seat = self.lane.arrange()
        child = self.lane.launch(seat)
        owner = Seat(seat['token'].parent, fixtures.NAME)
        with owner.locked():
            value = owner.validate(child['AGENTSTACK_LAUNCH_JOURNAL'])
            self.assertIsNotNone(value)
            value['auth']['owned'].sort(key=lambda entry: entry[0] != str(seat['token']))
            seat['token'].rename(seat['token'].with_suffix('.old'))
            seat['token'].write_text('replacement after last validation')
            # Isolate the per-entry guard from the earlier validate() gate.
            with patch.object(owner, 'validate', return_value=value):
                self.assertFalse(owner.delete(value['journal']))
            self.assertEqual(seat['token'].read_text(), 'replacement after last validation')
            self.assertTrue(seat['state'].exists())

    def test_cleanup_rechecks_after_second_http_call(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        seat = self.lane.arrange()
        child = self.lane.launch(seat)
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append(request['params']['name'])
                if len(calls) == 2:
                    seat['token'].rename(seat['token'].with_suffix('.old'))
                    seat['token'].write_text('replacement during retire')
                self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            child['AGENTSTACK_MCP_URL'] = f'http://127.0.0.1:{server.server_port}/mcp'
            self.lane.cleanup(child)
        finally:
            server.shutdown(); server.server_close(); thread.join()
        self.assertEqual(calls, ['release_file_reservations', 'retire_agent'])
        self.assertEqual(seat['token'].read_text(), 'replacement during retire')
        self.assertTrue(seat['state'].exists())

    def test_valid_automatic_journal_rejects_replaced_artifact_inodes(self):
        for provider, key in [('codex', 'home'), ('claude', 'config')]:
            with self.subTest(provider=provider):
                lane = lifecycle.LifecycleTests(); lane.setUp()
                try:
                    seat = lane.arrange(); child = lane.launch(seat, provider)
                    owner = Seat(seat['token'].parent, fixtures.NAME)
                    self.assertIsNotNone(owner.validate(child['AGENTSTACK_LAUNCH_JOURNAL'], automatic=True))
                    target = seat[key]; target.rename(target.with_name(target.name + '.old'))
                    if key == 'home':
                        target.mkdir(); (target/'foreign-record.json').write_text('permanent')
                    else: target.write_text('foreign config')
                    lane.cleanup(child)
                    self.assertTrue(seat['token'].exists())
                    self.assertEqual((target/'foreign-record.json').read_text() if key == 'home' else target.read_text(), 'permanent' if key == 'home' else 'foreign config')
                finally: lane.doCleanups()

    def test_registered_handoff_cannot_be_consumed_by_another_seat(self):
        from seat_lifecycle import bind_handoff
        seat = self.lane.arrange()
        other = seat['handoff'].with_name('OtherSeat.' + __import__('uuid').uuid4().hex + '.token')
        other.write_text(fixtures.TOKEN); other.chmod(0o600)
        bind_handoff(seat['token'].parent, other, 'OtherSeat', '/fixture/project')
        seat['handoff'] = other
        self.lane.launch(seat, expect=1)
        self.assertEqual(other.read_text(), fixtures.TOKEN)
        self.assertFalse(seat['token'].exists())

    def test_authenticated_restart_refreshes_generated_config_and_keeps_old_bytes(self):
        for provider in ('codex', 'claude'):
            with self.subTest(provider=provider):
                lane = lifecycle.LifecycleTests(); lane.setUp()
                try:
                    seat = lane.arrange(); old_env = lane.launch(seat, provider)
                    target = seat['home']/'config.toml' if provider == 'codex' else seat['config']
                    before = target.read_bytes()
                    token = seat['token'].read_bytes(); state = seat['state'].read_bytes()
                    if provider == 'codex':
                        Path(seat['env']['CODEX_HOME'], 'config.toml').write_text('model = "refreshed-fixture-model"\n')
                        unknown = seat['home']/'foreign-receipt.json'; unknown.write_text('keep')
                    owner = Seat(seat['token'].parent, fixtures.NAME)
                    with owner.locked(): owner.invalidate()
                    seat['handoff'] = seat['token']
                    lane.launch(seat, provider, extra_env={'AGENTSTACK_REFRESH_CHILD_CONFIG':'1', 'AGENTSTACK_MCP_URL':'http://127.0.0.1:19999/mcp'})
                    self.assertNotEqual(target.read_bytes(), before)
                    self.assertEqual(seat['token'].read_bytes(), token)
                    self.assertEqual(seat['state'].read_bytes(), state)
                    backups = list((seat['token'].parent/'seat-launches/config-backups').iterdir())
                    self.assertTrue(any(p.read_bytes() == before for p in backups))
                    if provider == 'codex': self.assertEqual(unknown.read_text(), 'keep')
                finally: lane.doCleanups()

    def test_env_writer_preserves_live_only_nonsecret_settings(self):
        seat = self.lane.arrange()
        envfile = self.lane.base/'env.sh'
        expected = {'AGENTSTACK_CODEX_SANDBOX':'danger-full-access', 'EXAMFORGE_HEAVY_SLOTS':'2', 'EXAMFORGE_MIN_FREE_MB':'8000'}
        envfile.write_text(''.join(f'export {key}={value}\n' for key, value in expected.items()))
        source = (ROOT/'scripts/install.sh').read_text()
        function = source[source.index('\nwrite_env_file() {'):source.index('\nstop_new_agent_mail() {')]
        result = subprocess.run(['/bin/bash', '-c', function+'\nplan() { :; }\nwrite_env_file\n'], env=dict(seat['env'], ENV_FILE=str(envfile), DRY_RUN='false', PYTHON_BIN=sys.executable), capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        import shlex
        parsed = dict(shlex.split(line[7:])[0].split('=',1) for line in envfile.read_text().splitlines() if line.startswith('export '))
        self.assertEqual({k:parsed[k] for k in expected}, expected)

    def test_failed_authentication_does_not_steal_active_lease(self):
        seat = self.lane.arrange()
        self.lane.launch(seat)
        owner = Seat(seat['token'].parent, fixtures.NAME)
        before = owner.lease_path.read_bytes()
        foreign = self.lane.base/'wrong-handoff'; foreign.write_text('unrelated private text'); foreign.chmod(0o600)
        seat['handoff'] = foreign
        self.lane.launch(seat, expect=1)
        self.assertEqual(owner.lease_path.read_bytes(), before)

    def test_direct_failure_after_adoption_releases_reservations_and_retires(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        seat = self.lane.arrange()
        calls = []
        rejected = []
        from schema_mail_fake import validate_call, tool_schemas
        tool_schemas()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                method = request['params']['name']; calls.append(method)
                try:
                    validate_call(method, request['params']['arguments'])
                except Exception as exc:
                    rejected.append(str(exc))
                    body = {'result':{'isError':True,'content':[{'type':'text','text':str(exc)}]}}
                    self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(body).encode()); return
                data = {'name':fixtures.NAME,'registration_token':fixtures.TOKEN} if method == 'register_agent' else {}
                body = {'result':{'structuredContent':data,'content':[{'type':'text','text':json.dumps(data)}]}}
                self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(body).encode())
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        task = self.lane.base/'task.md'; task.write_text('---\nfixture front matter\n---\nfixture work')
        try:
            env = dict(seat['env'], AGENTSTACK_MCP_URL=f'http://127.0.0.1:{server.server_port}/mcp', AGENTSTACK_DIRECT_CANDIDATE='Restart-Fixture', FIXTURE_EARLY_FAILURE='1')
            fixtures.freeze_tmux_fixture(env)
            args = ['/bin/bash', str(fixtures.SPAWN), '--codex', '--model', 'gpt-5.5', '--resources', 'fixture.txt', '--task-file', str(task), str(seat['work'])]
            result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=25)
            self.assertEqual(rejected, [], 'real tools/list contract rejected launcher arguments')
            self.assertEqual(result.returncode, 17, result.stderr)
            self.assertIn('file_reservation_paths', calls)
            self.assertEqual(calls[-2:], ['release_file_reservations', 'retire_agent'])
            self.assertFalse(seat['token'].exists())
            child = json.loads((self.lane.base/'tmux-verbs.env').read_text())
            self.assertEqual(child['CHILD_RESOURCES'], 'fixture.txt')
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_private_real_tmux_server_does_not_capture_launch_authority(self):
        import shlex
        import shutil
        import tempfile
        real_tmux = shutil.which('tmux')
        if not real_tmux: self.skipTest('tmux unavailable')
        source = fixtures.SPAWN.read_text()
        lines = [line for line in source.splitlines() if 'tmux new-session' in line and 'TMUX_CLIENT_ENV' in line]
        self.assertEqual(len(lines), 2, 'both providers must use the allowlist')
        start = source.index('    TMUX_CLIENT_ENV=(env -i)')
        end = source.index('    done', start) + len('    done')
        allowlist = source[start:end]
        for provider, line in zip(('codex','claude'), lines):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory(prefix='orrery-r4-socket-', dir='/tmp') as socket_dir:
                self.assertIn('9>&-', line, 'tmux server must not retain the name lock')
                socket = str(Path(socket_dir)/'server.sock')
                base = [real_tmux, '-S', socket]
                keys = ['AGENTSTACK_HOOKS_DIR','AGENTSTACK_HOME','AGENTSTACK_PROJECT_KEY','PROJECT_KEY','AGENTSTACK_FUTURE_SECRET', 'UNKNOWN_FUTURE_SECRET','AGENTSTACK_LIFECYCLE_HOOKS_DIR','AGENTSTACK_PRESERVE_SEAT_IDENTITY','AGENTSTACK_SEAT_LOCK_FD','AGENTSTACK_DIRECT_CANDIDATE','AGENTSTACK_LIFECYCLE_NAME','AGENTSTACK_LAUNCH_JOURNAL','AGENTSTACK_LAUNCH_ATTEMPT_ID','AGENTSTACK_MATERIALS_APPENDED']
                environment = dict(os.environ, **dict.fromkeys(keys, 'fixture-canary'))
                command = line.strip().split('tmux new-session')[0] + 'tmux -S "$1" new-session 9>&- -d -s FixtureOnly -e AGENTSTACK_LAUNCH_JOURNAL=child-fixture-journal -e AGENTSTACK_LIFECYCLE_HOOKS_DIR=child-selected-release "/bin/sleep 15"'
                try:
                    result = subprocess.run(['/bin/bash','-c',allowlist+'\n'+command,'fixture',socket], env=environment, capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    global_env = subprocess.check_output([*base, 'show-environment', '-g'], env=environment, text=True)
                    for key in keys: self.assertNotIn(key+'=', global_env)
                    child_env = subprocess.check_output([*base, 'show-environment', '-t', 'FixtureOnly'], env=environment, text=True)
                    self.assertIn('AGENTSTACK_LAUNCH_JOURNAL=child-fixture-journal', child_env)
                    self.assertIn('AGENTSTACK_LIFECYCLE_HOOKS_DIR=child-selected-release', child_env)
                    subprocess.run([*base,'new-session','-d','-s','Unrelated','/bin/sleep 15'],env=environment,check=True,timeout=10)
                    later = subprocess.check_output([*base,'show-environment','-t','Unrelated'],env=environment,text=True)
                    for key in keys: self.assertNotIn(key+'=',later)
                finally:
                    subprocess.run([*base, 'kill-server'], env=environment, capture_output=True, timeout=10)

    def test_collection_isolation_precedes_dashboard_import_and_blocks_keychain(self):
        seat = self.lane.arrange()
        code = '''import importlib.util, os, pathlib, subprocess, sys
root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('fixture_collection', root/'conftest.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
from dashboard import server
home = pathlib.Path.home()
assert str(server.RUNTIME_DIR).startswith(str(home))
assert str(server.HOOKS_DIR).startswith(str(home))
assert os.environ['TMUX_TMPDIR'].startswith('/tmp/orrery-test-tmux-')
assert os.environ['AGENTSTACK_MAIL_HTTP_BEARER_MODE'] == 'disabled'
assert subprocess.run(['security'], capture_output=True).returncode == 77
module.pytest_unconfigure(None)
'''
        result = subprocess.run([sys.executable, '-c', code, str(ROOT)], env=seat['env'], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_registration_writer_uses_a_new_inode_only_for_a_rotated_token(self):
        seat = self.lane.arrange(True)
        original = seat['token'].stat().st_ino
        script = '. "$1"; ags_store_registration_token "$2" "$3"'
        args = ['/bin/bash', '-c', script, 'fixture', str(ROOT/'bin/lib/agentstack-register.sh'), fixtures.NAME, 'rotated-fixture-token']
        first = subprocess.run(args, env=seat['env'], capture_output=True, text=True, timeout=10)
        self.assertEqual(first.returncode, 0, first.stderr)
        rotated = seat['token'].stat().st_ino
        self.assertNotEqual(original, rotated, 'in-place token rotation bypasses inode ownership')
        second = subprocess.run(args, env=seat['env'], capture_output=True, text=True, timeout=10)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(seat['token'].stat().st_ino, rotated)


def test_dashboard_reused_attempt_cannot_kill_started_same_inode_successor(monkeypatch, tmp_path):
    from unittest.mock import patch
    def launch(runtime, args, env):
        seat = Seat(runtime, 'FreshCurie')
        with seat.locked(), patch.dict(os.environ, {'AGENTSTACK_LAUNCH_ATTEMPT_ID': env['AGENTSTACK_LAUNCH_ATTEMPT_ID']}):
            first = seat.begin('/fixture/project', runtime/'managed_agents.txt')
            paths = seat.paths(); paths['state'].parent.mkdir(exist_ok=True)
            for key in ('token', 'state'): paths[key].write_text('same inode successor identity')
            paths['state'].write_text(json.dumps({'agent_name':'FreshCurie','project_key':'/fixture/project'}))
            auth = [[str(paths[k]), paths[k].stat().st_dev, paths[k].stat().st_ino] for k in ('token', 'state')]
            seat.update(first['journal'], auth={'owned': auth, 'observed': auth}, session_started=True)
            seat.invalidate()
            second = seat.begin('/fixture/project', runtime/'managed_agents.txt')
            seat.update(second['journal'], auth={'observed': auth}, session_started=True)
            assert seat.validate(second['journal']) is not None
    runtime, calls = lifecycle._dashboard_fixture(monkeypatch, tmp_path, launch)
    assert (runtime/'agent_token_FreshCurie').read_text() == 'same inode successor identity'
    assert not any('kill-session' in call for call in calls)


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-q']))

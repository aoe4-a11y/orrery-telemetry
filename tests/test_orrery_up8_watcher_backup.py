"""Synthetic watcher state backup; no live Mail or tmux interaction."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('up8_mail_cycle', ROOT / 'scripts/pre-install-mail-cycle.py')
cycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cycle)
restore_spec = importlib.util.spec_from_file_location('up8_restore', ROOT / 'scripts/post-install-restore.py')
restore = importlib.util.module_from_spec(restore_spec)
restore_spec.loader.exec_module(restore)


def test_watcher_capture_is_between_mail_stop_and_restart(tmp_path):
    home = tmp_path / 'home'
    runtime = home / '.agentstack/runtime'
    snapshot = home / '.agentstack/backups/orrery-up-6-fixture'
    database = home / '.agentstack/mail/storage.sqlite3'
    for path in (runtime / 'mail-watcher.lock', runtime / 'notify-locks', snapshot, database.parent):
        path.mkdir(parents=True, exist_ok=True)
    snapshot.chmod(0o700)
    database.write_bytes(b'fixture database')
    (home / '.agentstack/install-state.json').write_text(json.dumps({'env': {
        'AGENTSTACK_MAIL_DB': str(database), 'AGENTSTACK_MAIL_HOME': str(database.parent)}}))
    contents = {'notify-state.json': b'before', 'notify-state.json.lock': b'lock',
                'mail-watcher.lock/heartbeat': b'heartbeat', 'mail-watcher.lock/watcher.pid': b'123',
                'notify-locks/fixture.lock': b'lease'}
    for rel, data in contents.items():
        (runtime / rel).write_bytes(data)
    actions = []

    class Controller:
        def run(self, action):
            actions.append(action)
            if action == 'stop':
                (runtime / 'notify-state.json').write_bytes(b'stopped')
            elif action == 'start':
                (runtime / 'notify-state.json').write_bytes(b'restarted')

    def capture(selected_home, selected_snapshot, selected_database):
        assert actions == ['status', 'stop']
        return {'watcher_manifest_sha256': cycle.mail_backup.capture_watcher(selected_home, selected_snapshot)}

    result = cycle.cycle(home, snapshot, Controller(), capture=capture)
    assert actions == ['status', 'stop', 'start', 'status']
    manifest = snapshot / 'watcher-state/manifest.json'
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == result['watcher_manifest_sha256']
    contents['notify-state.json'] = b'stopped'
    for rel, data in contents.items():
        assert (snapshot / 'watcher-state/files/.agentstack/runtime' / rel).read_bytes() == data
    assert (runtime / 'notify-state.json').read_bytes() == b'restarted'
    result = restore.restore(home, snapshot / 'watcher-state', result['watcher_manifest_sha256'])
    assert result['restored_files'] == 5
    assert (runtime / 'notify-state.json').read_bytes() == b'stopped'
    assert (snapshot / 'watcher-state/post-install-current/.agentstack/runtime/notify-state.json').read_bytes() == b'restarted'


def test_watcher_change_aborts_capture_and_restarts_mail(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    runtime = home / '.agentstack/runtime'
    snapshot = home / '.agentstack/backups/orrery-up-6-fixture'
    database = home / '.agentstack/mail/storage.sqlite3'
    for path in (runtime, snapshot, database.parent):
        path.mkdir(parents=True, exist_ok=True)
    database.write_bytes(b'fixture')
    (home / '.agentstack/install-state.json').write_text(json.dumps({'env': {
        'AGENTSTACK_MAIL_DB': str(database), 'AGENTSTACK_MAIL_HOME': str(database.parent)}}))
    state = runtime / 'notify-state.json'
    state.write_bytes(b'before')
    original = cycle.mail_backup.snapshot_tool.clone

    def changed(source, destination):
        original(source, destination)
        if source == state:
            state.write_bytes(b'changed')

    monkeypatch.setattr(cycle.mail_backup.snapshot_tool, 'clone', changed)
    actions = []

    class Controller:
        def run(self, action):
            actions.append(action)

    def capture(selected_home, selected_snapshot, selected_database):
        cycle.mail_backup.capture_watcher(selected_home, selected_snapshot)

    with pytest.raises(ValueError, match='changed'):
        cycle.cycle(home, snapshot, Controller(), capture=capture)
    assert actions == ['status', 'stop', 'start', 'status']
    assert not (snapshot / 'watcher-state/manifest.json').exists()
    assert json.loads((snapshot / 'mail-cycle-failed.json').read_text())['previous_mail_restored'] is True


def test_new_watcher_path_refuses_restore_before_changes(tmp_path):
    home = tmp_path / 'home'
    runtime = home / '.agentstack/runtime'
    snapshot = home / '.agentstack/backups/orrery-up-6-fixture'
    runtime.mkdir(parents=True)
    snapshot.mkdir(parents=True, mode=0o700)
    (runtime / 'notify-state.json').write_bytes(b'old state')
    sha = cycle.mail_backup.capture_watcher(home, snapshot)
    (runtime / 'notify-state.json').write_bytes(b'current state')
    (runtime / 'notify-state.json.lock').write_bytes(b'new lock')
    with pytest.raises(ValueError, match='previously absent watcher path'):
        restore.restore(home, snapshot / 'watcher-state', sha)
    assert (runtime / 'notify-state.json').read_bytes() == b'current state'
    assert (runtime / 'notify-state.json.lock').read_bytes() == b'new lock'
    assert not (snapshot / 'watcher-state/post-install-current').exists()


def test_corrupt_watcher_clone_refuses_restore_before_changes(tmp_path):
    home = tmp_path / 'home'
    runtime = home / '.agentstack/runtime'
    snapshot = home / '.agentstack/backups/orrery-up-6-fixture'
    runtime.mkdir(parents=True)
    snapshot.mkdir(parents=True, mode=0o700)
    state = runtime / 'notify-state.json'
    state.write_bytes(b'old state')
    sha = cycle.mail_backup.capture_watcher(home, snapshot)
    state.write_bytes(b'current state')
    (snapshot / 'watcher-state/files/.agentstack/runtime/notify-state.json').write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='integrity'):
        restore.restore(home, snapshot / 'watcher-state', sha)
    assert state.read_bytes() == b'current state'
    assert not (snapshot / 'watcher-state/post-install-current').exists()

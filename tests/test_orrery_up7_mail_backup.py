"""Only synthetic DB files and an owned writer process are used."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / file)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
backup_tool = load('up7_backup', 'pre-install-mail-backup.py')
restore_tool = load('up7_restore', 'restore-mail-database.py')
cycle_tool = load('up7_cycle', 'pre-install-mail-cycle.py')

class MailBundleTest(unittest.TestCase):
    def test_invalid_mail_manifest_fails_before_current_db_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            home=Path(temporary)/'home'; db=home/'.agentstack/mail/storage.sqlite3'; db.parent.mkdir(parents=True)
            db.write_bytes(b'current'); snapshot=home/'.agentstack/backups/orrery-up-6-invalid'; snapshot.mkdir(parents=True,mode=0o700)
            manifest=snapshot/'manifest.json'; manifest.write_text('[]\n'); manifest.chmod(0o600)
            bundle=snapshot/'mail-database';bundle.mkdir(mode=0o700); bad=bundle/'manifest.json';bad.write_text('[1]\n');bad.chmod(0o600)
            sha=lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
            with self.assertRaises(ValueError): restore_tool.restore_bundle(home,snapshot,sha(manifest),db,sha(bad))
            self.assertEqual(db.read_bytes(),b'current')

    def test_listener_failure_after_restart_refuses_handoff(self):
        with tempfile.TemporaryDirectory() as temporary:
            home=Path(temporary)/'home'; stack=home/'.agentstack'; db=stack/'mail/storage.sqlite3'
            db.parent.mkdir(parents=True); db.write_bytes(b'synthetic')
            (stack/'install-state.json').write_text(json.dumps({'env': {'AGENTSTACK_MAIL_DB':str(db),
                'AGENTSTACK_MAIL_STATE_ROOT':str(db.parent)}}))
            snapshot=stack/'backups/orrery-up-6-no-listener'; snapshot.mkdir(parents=True,mode=0o700)
            trace=[]
            class FakeController:
                def run(self,action):
                    trace.append(action)
                    if action=='status' and trace.count('status')==2: raise ValueError('listener absent')
            with self.assertRaises(ValueError):
                cycle_tool.cycle(home,snapshot,FakeController(),capture=lambda *args: {'mail_manifest_sha256':'a'*64})
            self.assertEqual(trace,['status','stop','start','status'])
            self.assertFalse(json.loads((snapshot/'mail-cycle-failed.json').read_text())['previous_mail_restored'])

    def test_installer_switch_elapsed_is_recorded(self):
        with tempfile.TemporaryDirectory() as temporary:
            timing=Path(temporary)/'timing'; timing.write_text(''); timing.chmod(0o600)
            source=(ROOT/'scripts/install.sh').read_text()
            start=source.index('mail_update_elapsed() {'); end=source.index('\n}',start)+2
            script=source[start:end]+'\nmail_update_elapsed 0\n'
            result=subprocess.run(['/bin/bash','-c',script],env={'PATH':'/usr/bin:/bin',
                'PYTHON_BIN':sys.executable,'AGENTSTACK_OWNER_SWITCH_TIMING_FILE':str(timing)},
                text=True,capture_output=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertRegex(result.stdout.strip(),r'^\d+\.\d$')
            self.assertEqual(timing.read_text().strip(),result.stdout.strip())

    def test_absent_sidecars_stay_absent_after_restore(self):
        with tempfile.TemporaryDirectory() as temporary:
            home=Path(temporary)/'home'; db=home/'.agentstack/mail/storage.sqlite3'; db.parent.mkdir(parents=True)
            db.write_bytes(b'original'); snapshot=home/'.agentstack/backups/orrery-up-6-absent'
            snapshot.mkdir(parents=True, mode=0o700)
            manifest=snapshot/'manifest.json'; manifest.write_text('[]\n'); manifest.chmod(0o600)
            sha=hashlib.sha256(manifest.read_bytes()).hexdigest()
            result=backup_tool.capture(home,snapshot,db)
            wal=Path(str(db)+'-wal'); shm=Path(str(db)+'-shm')
            db.write_bytes(b'new'); wal.write_bytes(b'new-wal'); shm.write_bytes(b'new-shm')
            restore_tool.restore_bundle(home,snapshot,sha,db,result['mail_manifest_sha256'])
            self.assertEqual(db.read_bytes(),b'original')
            self.assertFalse(wal.exists()); self.assertFalse(shm.exists())
            self.assertEqual((snapshot/'post-install-db-bundle/wal').read_bytes(),b'new-wal')
            self.assertEqual((snapshot/'post-install-db-bundle/shm').read_bytes(),b'new-shm')

    def test_clone_drift_never_finalizes_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            home=Path(temporary)/'home'; db=home/'.agentstack/mail/storage.sqlite3'; db.parent.mkdir(parents=True)
            db.write_bytes(b'synthetic'); snapshot=home/'.agentstack/backups/orrery-up-6-drift'
            snapshot.mkdir(parents=True, mode=0o700)
            def changed(source, target):
                target.write_bytes(source.read_bytes()); source.write_bytes(b'changed')
            with mock.patch.object(backup_tool, 'idle'), mock.patch.object(backup_tool.snapshot_tool, 'clone', side_effect=changed):
                with self.assertRaises(ValueError): backup_tool.capture(home, snapshot, db)
            self.assertFalse((snapshot/'mail-database/manifest.json').exists())

    def test_old_token_named_backup_excluded_but_installed_hook_included(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary); hooks = home/'.agentstack/hooks'; hooks.mkdir(parents=True)
            (hooks/'spawn_child.sh.bak-20260925-update-token').write_bytes(b'synthetic')
            (hooks/'llm_secret_reader.py').write_bytes(b'synthetic')
            names = backup_tool.snapshot_tool.collect(home, ['.agentstack/hooks'])
            self.assertNotIn('.agentstack/hooks/spawn_child.sh.bak-20260925-update-token', names)
            self.assertIn('.agentstack/hooks/llm_secret_reader.py', names)

    def test_capture_failure_restarts_old_service_and_refuses_handoff(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)/'home'; stack = home/'.agentstack'; db = stack/'mail/storage.sqlite3'
            db.parent.mkdir(parents=True); db.write_bytes(b'synthetic')
            (stack/'install-state.json').write_text(json.dumps({'env': {'AGENTSTACK_MAIL_DB': str(db),
                'AGENTSTACK_MAIL_STATE_ROOT': str(db.parent)}}))
            snapshot = stack/'backups/orrery-up-6-failure'; snapshot.mkdir(parents=True, mode=0o700)
            trace = []
            class FakeController:
                def run(self, action): trace.append(action)
            def busy(*args): trace.append('capture'); raise ValueError('synthetic busy')
            with self.assertRaises(ValueError):
                cycle_tool.cycle(home, snapshot, FakeController(), capture=busy)
            self.assertEqual(trace, ['status', 'stop', 'capture', 'start', 'status'])
            self.assertTrue(json.loads((snapshot/'mail-cycle-failed.json').read_text())['previous_mail_restored'])

    def test_fake_controller_stops_clones_restarts_and_gates_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / 'home'; stack = home / '.agentstack'
            db = stack / 'mail/storage.sqlite3'; db.parent.mkdir(parents=True)
            db.write_bytes(b'synthetic db'); Path(str(db)+'-wal').write_bytes(b'wal'); Path(str(db)+'-shm').write_bytes(b'shm')
            (stack/'install-state.json').write_text(json.dumps({'env': {'AGENTSTACK_MAIL_DB': str(db),
                'AGENTSTACK_MAIL_STATE_ROOT': str(db.parent)}}))
            snapshot = stack/'backups/orrery-up-6-cycle'; snapshot.mkdir(parents=True, mode=0o700)
            trace = []
            class FakeController:
                def __init__(self): self.process = None; self.start()
                def start(self):
                    self.process = subprocess.Popen([sys.executable, '-c',
                        'import sys,time; f=open(sys.argv[1],"rb"); print("ready",flush=True); time.sleep(120)', str(db)],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    assert self.process.stdout.readline().strip() == 'ready'
                def run(self, action):
                    trace.append(action)
                    if action == 'stop':
                        self.process.terminate(); self.process.wait(timeout=10)
                        self.process.stdout.close(); self.process.stderr.close(); self.process = None
                    elif action == 'start': self.start()
                    elif action == 'status':
                        if self.process is None or self.process.poll() is not None: raise ValueError('listener absent')
            controller = FakeController()
            def capture(home, snapshot, database):
                trace.append('capture')
                return backup_tool.capture(home, snapshot, database)
            try:
                result = cycle_tool.cycle(home, snapshot, controller, capture=capture)
                self.assertGreaterEqual(result['preinstall_outage_seconds'], 0)
                trace.append('update')  # The entry hands off only after the cycle returns.
                self.assertEqual(trace, ['status', 'stop', 'capture', 'start', 'status', 'update'])
            finally:
                if controller.process is not None:
                    controller.process.terminate(); controller.process.wait(timeout=10)
                    controller.process.stdout.close(); controller.process.stderr.close()

    def test_owned_writer_blocks_then_three_components_clone_and_restore(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / 'home'; stack = home / '.agentstack'
            db = stack / 'mail/storage.sqlite3'; db.parent.mkdir(parents=True)
            with sqlite3.connect(db) as connection:
                connection.execute('CREATE TABLE messages(id INTEGER PRIMARY KEY)')
                connection.execute('INSERT INTO messages DEFAULT VALUES')
            connection.close()
            paths = [db, Path(str(db) + '-wal'), Path(str(db) + '-shm')]
            paths[1].write_bytes(b'synthetic wal'); paths[2].write_bytes(b'synthetic shm')
            expected = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
            snapshot = stack / 'backups/orrery-up-6-fixture'; snapshot.mkdir(parents=True, mode=0o700)
            manifest = snapshot / 'manifest.json'; manifest.write_text('[]\n'); manifest.chmod(0o600)
            manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
            writer = subprocess.Popen([sys.executable, '-c',
                'import sys,time; handles=[open(x,"rb") for x in sys.argv[1:]]; print("ready",flush=True); time.sleep(120)',
                *map(str, paths)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(writer.stdout.readline().strip(), 'ready')
                with self.assertRaises(ValueError): backup_tool.capture(home, snapshot, db)
                self.assertFalse((snapshot/'mail-database').exists())
            finally:
                writer.terminate(); writer.wait(timeout=10)
                writer.stdout.close(); writer.stderr.close()
            result = backup_tool.capture(home, snapshot, db)
            self.assertEqual(result['components_present'], 3)
            rows = json.loads((snapshot/'mail-database/manifest.json').read_text())['components']
            self.assertEqual([row['sha256'] for row in rows], expected)
            for index, path in enumerate(paths): path.write_bytes(('changed'+str(index)).encode())
            restored = restore_tool.restore_bundle(home, snapshot, manifest_sha, db, result['mail_manifest_sha256'])
            self.assertEqual(restored['restored_components'], 3)
            self.assertEqual([hashlib.sha256(path.read_bytes()).hexdigest() for path in paths], expected)
            self.assertTrue((snapshot/'post-install-db-bundle/manifest.json').is_file())

if __name__ == '__main__': unittest.main()

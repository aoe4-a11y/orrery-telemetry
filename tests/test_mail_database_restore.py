"""Exercise optional database rollback using only synthetic SQLite files."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'scripts/restore-mail-database.py'


def make_db(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    try:
        db.execute('CREATE TABLE sample (value TEXT)')
        db.execute('INSERT INTO sample VALUES (?)', (value,))
        db.commit()
    finally:
        db.close()


@pytest.fixture
def scenario(tmp_path):
    home = tmp_path / 'home'
    snapshot = home / '.agentstack/backups/orrery-up-6-fixture'
    snapshot.mkdir(parents=True, mode=0o700)
    snapshot.chmod(0o700)
    manifest = snapshot / 'manifest.json'
    manifest.write_text('[]')
    sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    database = home / '.agentstack/mail/storage.sqlite3'
    backup = home / '.agentstack/mail-service/backups/storage-old.sqlite3'
    make_db(database, 'new fixture')
    make_db(backup, 'old fixture')
    return home, snapshot, sha, database, backup


def call(s):
    home, snapshot, sha, database, backup = s
    return subprocess.run([sys.executable, str(TOOL), '--home', str(home), '--snapshot', str(snapshot),
                           '--manifest-sha256', sha, '--database', str(database), '--backup', str(backup)],
                          capture_output=True, text=True, timeout=30)


def test_restore_clones_current_and_recovers_selected_backup(scenario):
    home, snapshot, sha, database, backup = scenario
    current_hash = hashlib.sha256(database.read_bytes()).hexdigest()
    old_bytes = backup.read_bytes()
    result = call(scenario)
    assert result.returncode == 0
    assert database.read_bytes() == old_bytes
    assert backup.read_bytes() == old_bytes
    saved = snapshot / 'post-install-db/db'
    assert hashlib.sha256(saved.read_bytes()).hexdigest() == current_hash
    with sqlite3.connect(saved) as db:
        assert db.execute('SELECT value FROM sample').fetchone() == ('new fixture',)
    rows = json.loads((snapshot / 'post-install-db/manifest.json').read_text())
    assert rows and all(set(row) == {'path', 'sha256', 'bytes'} for row in rows)


def test_open_database_refuses_before_creating_safety_copy(scenario):
    home, snapshot, sha, database, backup = scenario
    connection = sqlite3.connect(database)
    try:
        result = call(scenario)
        assert result.returncode != 0
        assert not (snapshot / 'post-install-db').exists()
    finally:
        connection.close()


def test_wrong_snapshot_manifest_hash_refuses_before_changes(scenario):
    home, snapshot, sha, database, backup = scenario
    before = database.read_bytes()
    result = call((home, snapshot, '0' * 64, database, backup))
    assert result.returncode != 0
    assert database.read_bytes() == before
    assert not (snapshot / 'post-install-db').exists()


def test_backup_with_sidecar_refuses_before_changes(scenario):
    home, snapshot, sha, database, backup = scenario
    before = database.read_bytes()
    Path(str(backup) + '-wal').write_bytes(b'synthetic sidecar')
    result = call(scenario)
    assert result.returncode != 0
    assert database.read_bytes() == before
    assert not (snapshot / 'post-install-db').exists()


def test_restore_saves_current_sidecars_before_removing_them(scenario):
    home, snapshot, sha, database, backup = scenario
    wal = Path(str(database) + '-wal');shm = Path(str(database) + '-shm')
    wal.write_bytes(b'synthetic wal bytes');shm.write_bytes(b'synthetic shared bytes')
    result = call(scenario)
    assert result.returncode == 0
    assert not wal.exists() and not shm.exists()
    safety = snapshot / 'post-install-db'
    assert (safety / 'db-wal').read_bytes() == b'synthetic wal bytes'
    assert (safety / 'db-shm').read_bytes() == b'synthetic shared bytes'
    assert len(json.loads((safety / 'manifest.json').read_text())) == 3

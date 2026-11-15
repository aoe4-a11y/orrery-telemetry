"""The installer must not overwrite or prune existing Mail backups."""
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_installer_backup_preserves_existing_files_and_refuses_collision(tmp_path):
    script = (Path(__file__).resolve().parents[1] / 'scripts/install.sh').read_text()
    helper = script.split('mail_update_helper() {\n  "$PYTHON_BIN" - "$@" <<\'PY\'\n', 1)[1].split('\nPY\n}', 1)[0]
    frozen = "import time; time.strftime = lambda *args: '20000101T000000Z'\n" + helper
    source = tmp_path / 'source.sqlite3'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE sample (value TEXT)')
        db.execute('INSERT INTO sample VALUES (?)', ('fixture',))
    backups = tmp_path / 'backups'
    backups.mkdir()
    previous = []
    for number in range(4):
        path = backups / f'storage-1999010{number + 1}T000000Z-before-old.sqlite3'
        data = f'existing fixture {number}'.encode()
        path.write_bytes(data)
        previous.append((path, data))
    command = [sys.executable, '-c', frozen, 'backup', str(source), str(backups), 'candidate']
    first = subprocess.run(command, capture_output=True, text=True)
    assert first.returncode == 0
    target = backups / 'storage-20000101T000000Z-before-candidate.sqlite3'
    with sqlite3.connect(target) as db:
        assert db.execute('SELECT value FROM sample').fetchone() == ('fixture',)
    saved = target.read_bytes()
    assert target.stat().st_mode & 0o777 == 0o600
    assert all(path.read_bytes() == data for path, data in previous)
    second = subprocess.run(command, capture_output=True, text=True)
    assert second.returncode != 0
    assert target.read_bytes() == saved
    assert all(path.read_bytes() == data for path, data in previous)

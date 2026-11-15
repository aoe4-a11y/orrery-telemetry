#!/usr/bin/env python3
"""Optionally restore a Mail DB after saving current bytes on the same volume.

The owner must stop Mail and other DB writers before invoking this command.
No data or absolute user paths are printed.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
import uuid

spec = importlib.util.spec_from_file_location('snapshot_tool', Path(__file__).with_name('pre-install-snapshot.py'))
snapshot_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot_tool)


def idle(paths: list[Path]) -> None:
    for path in paths:
        if not path.exists() and not path.is_symlink():
            continue
        result = subprocess.run(['/usr/sbin/lsof', '-n', '-P', '-Fpn', str(path)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        if result.returncode not in (0, 1) or result.stdout or result.stderr:
            raise ValueError('database file is in use or cannot be checked')


def quick_check(path: Path) -> None:
    connection = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)
    try:
        if connection.execute('PRAGMA quick_check').fetchone() != ('ok',):
            raise ValueError('database integrity check failed')
    finally:
        connection.close()


def restore(home: Path, snapshot: Path, manifest_sha: str, database: Path, backup: Path) -> dict:
    for path in (snapshot, database, backup):
        rel = snapshot_tool.relative(home, path)
        snapshot_tool.assert_safe_parents(home, rel)
    if snapshot.parent != home / '.agentstack/backups' or not snapshot.name.startswith('orrery-up-6-'):
        raise ValueError('snapshot is outside the approved backup directory')
    if snapshot.is_symlink() or not snapshot.is_dir() or snapshot.stat().st_uid != os.getuid() or snapshot.stat().st_mode & 0o077:
        raise ValueError('snapshot is unavailable or not private')
    if backup.parent != home / '.agentstack/mail-service/backups' or database == backup:
        raise ValueError('backup must be an existing Mail backup')
    manifest = snapshot / 'manifest.json'
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError('snapshot manifest unavailable')
    raw = manifest.read_bytes()
    if not re.fullmatch(r'[0-9a-f]{64}', manifest_sha) or hashlib.sha256(raw).hexdigest() != manifest_sha:
        raise ValueError('snapshot manifest digest differs')
    for path in (database, backup):
        if path.is_symlink() or not path.is_file() or path.lstat().st_nlink != 1:
            raise ValueError('database and backup must be regular single-link files')
        if path.lstat().st_dev != snapshot.stat().st_dev:
            raise ValueError('database and backup must be on the snapshot volume')
    if not Path('/usr/sbin/lsof').is_file():
        raise ValueError('process-use check is unavailable')
    sidecars = [Path(str(database) + '-wal'), Path(str(database) + '-shm')]
    backup_sidecars = [Path(str(backup) + '-wal'), Path(str(backup) + '-shm')]
    if any(path.exists() or path.is_symlink() for path in backup_sidecars):
        raise ValueError('selected backup is not a standalone database')
    paths = [database, *sidecars]
    for path in sidecars:
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.lstat().st_nlink != 1)):
            raise ValueError('database sidecar is not a regular single-link file')
    idle([*paths, backup])
    quick_check(backup)
    before_backup = snapshot_tool.digest(backup)
    safety = snapshot / 'post-install-db'
    if safety.exists() or safety.is_symlink():
        raise ValueError('database safety copy already exists')
    safety.mkdir(mode=0o700)
    rows = []
    prior = {}
    for index, path in enumerate(paths):
        if not path.exists():
            prior[str(path)] = None
            continue
        before = snapshot_tool.digest(path)
        saved = safety / ('db' if index == 0 else 'db-wal' if index == 1 else 'db-shm')
        snapshot_tool.clone(path, saved)
        if snapshot_tool.digest(saved) != before or snapshot_tool.digest(path) != before:
            raise ValueError('database safety copy failed verification')
        prior[str(path)] = before
        rows.append({'path': snapshot_tool.relative(home, path), 'sha256': before[0], 'bytes': before[1]})
    safety_manifest = safety / 'manifest.json'
    fd = os.open(safety_manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(rows, f, ensure_ascii=True, separators=(',', ':'));f.write('\n')
    safety_sha = snapshot_tool.digest(safety_manifest)[0]
    temporary = database.with_name('.orrery-db-restore-' + uuid.uuid4().hex)
    snapshot_tool.clone(backup, temporary)
    if snapshot_tool.digest(temporary) != before_backup or snapshot_tool.digest(backup) != before_backup:
        raise ValueError('Mail backup copy failed verification')
    quick_check(temporary)
    idle([*paths, backup])
    for path in paths:
        observed = snapshot_tool.digest(path) if path.exists() or path.is_symlink() else None
        if observed != prior[str(path)]:
            raise ValueError('database changed during safety copy')
    for path in sidecars:
        if path.exists():
            path.unlink()
    os.replace(temporary, database)
    if snapshot_tool.digest(database) != before_backup:
        raise ValueError('restored database digest differs')
    quick_check(database)
    return {'current_db_files_preserved': len(rows), 'safety_manifest_sha256': safety_sha,
            'restored_backup_sha256': before_backup[0]}


def main() -> int:
    ap = argparse.ArgumentParser()
    for name in ('home', 'snapshot', 'database', 'backup'):
        ap.add_argument('--' + name, type=Path, required=True)
    ap.add_argument('--manifest-sha256', required=True)
    args = ap.parse_args();os.umask(0o077)
    try:
        if not all(p.is_absolute() for p in (args.home, args.snapshot, args.database, args.backup)):
            raise ValueError('absolute paths required')
        print(json.dumps(restore(args.home, args.snapshot, args.manifest_sha256, args.database, args.backup)))
        return 0
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, subprocess.TimeoutExpired):
        print('database restore refused or failed; retain all safety copies', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

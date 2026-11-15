#!/usr/bin/env python3
"""Clone an idle Mail DB and its sidecars; the caller must first stop Mail."""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

spec = importlib.util.spec_from_file_location('snapshot_tool', Path(__file__).with_name('pre-install-snapshot.py'))
snapshot_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot_tool)


def database_path(home: Path) -> Path:
    state = json.loads((home / '.agentstack/install-state.json').read_text())
    settings = state.get('env', {})
    value = settings.get('AGENTSTACK_MAIL_DB')
    if not isinstance(value, str) or not value:
        raise ValueError('installed database path unavailable')
    database = Path(value)
    if not database.is_absolute():
        raise ValueError('database path must be absolute')
    recorded_root = settings.get('AGENTSTACK_MAIL_STATE_ROOT') or settings.get('AGENTSTACK_MAIL_HOME')
    if not isinstance(recorded_root, str) or Path(recorded_root) != database.parent:
        raise ValueError('installed database and state root disagree')
    for variable, expected in (('AGENTSTACK_MAIL_DB', database), ('AGENTSTACK_MAIL_STATE_ROOT', database.parent)):
        if os.environ.get(variable) and Path(os.environ[variable]) != expected:
            raise ValueError('explicit database setting differs from installed state')
    snapshot_tool.assert_safe_parents(home, snapshot_tool.relative(home, database))
    return database


def idle(paths: list[Path]) -> None:
    for path in paths:
        if not path.exists() and not path.is_symlink():
            continue
        result = subprocess.run(['/usr/sbin/lsof', '-n', '-P', '-Fpn', str(path)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        if result.returncode not in (0, 1) or result.stdout or result.stderr:
            raise ValueError('database component is in use or cannot be checked')


def components(database: Path) -> list[Path]:
    return [database, Path(str(database) + '-wal'), Path(str(database) + '-shm')]


def capture_watcher(home: Path, snapshot: Path) -> str:
    """Capture a stable synthetic or stopped-Mail-time view, without signals."""
    roots = ['.agentstack/runtime/notify-state.json',
             '.agentstack/runtime/notify-state.json.lock',
             '.agentstack/runtime/notify-locks', '.agentstack/runtime/mail-watcher.lock']
    paths = snapshot_tool.collect(home, roots)
    target = snapshot / 'watcher-state'
    target.mkdir(mode=0o700)
    rows = []
    for rel in paths:
        if re.search(r'token|credential|secret|password', rel, re.I):
            raise ValueError('watcher path requires separate review')
        source, saved = home / rel, target / 'files' / rel
        try:
            st = source.lstat()
        except FileNotFoundError:
            rows.append({'path': rel, 'sha256': None, 'bytes': 0}); continue
        if stat.S_ISDIR(st.st_mode):
            saved.mkdir(parents=True, exist_ok=True, mode=0o700)
            rows.append({'path': rel, 'sha256': None, 'bytes': 0}); continue
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_dev != snapshot.stat().st_dev:
            raise ValueError('watcher state is not a same-volume regular file')
        digest = snapshot_tool.digest(source)
        snapshot_tool.clone(source, saved)
        if snapshot_tool.digest(saved) != digest or snapshot_tool.digest(source) != digest:
            raise ValueError('watcher state changed during clone')
        rows.append({'path': rel, 'sha256': digest[0], 'bytes': digest[1]})
    if snapshot_tool.collect(home, roots) != paths:
        raise ValueError('watcher state paths changed during clone')
    for row in rows:
        source = home / row['path']
        saved = target / 'files' / row['path']
        if row['sha256'] is not None:
            if snapshot_tool.digest(source) != (row['sha256'], row['bytes']):
                raise ValueError('watcher state changed during verification')
        elif saved.is_dir():
            if source.is_symlink() or not source.is_dir(): raise ValueError('watcher directory changed')
        elif source.exists() or source.is_symlink():
            raise ValueError('watcher state appeared during verification')
    manifest = target / 'manifest.json'
    fd = os.open(manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(rows, f, ensure_ascii=True, separators=(',', ':')); f.write('\n')
        f.flush(); os.fsync(f.fileno())
    return snapshot_tool.digest(manifest)[0]


def capture(home: Path, snapshot: Path, database: Path) -> dict:
    if snapshot.parent != home / '.agentstack/backups' or not snapshot.name.startswith('orrery-up-6-'):
        raise ValueError('snapshot outside approved backup directory')
    snapshot_tool.assert_safe_parents(home, snapshot_tool.relative(home, snapshot))
    snapshot_tool.assert_safe_parents(home, snapshot_tool.relative(home, database))
    if snapshot.is_symlink() or not snapshot.is_dir() or snapshot.stat().st_uid != os.getuid() or snapshot.stat().st_mode & 0o077:
        raise ValueError('snapshot unavailable or not private')
    paths = components(database)
    if database.is_symlink() or not database.is_file():
        raise ValueError('database unavailable')
    for path in paths:
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_nlink != 1)):
            raise ValueError('database component is not a regular single-link file')
        if path.exists() and path.stat().st_dev != snapshot.stat().st_dev:
            raise ValueError('database component is on another volume')
    idle(paths)
    estimate = sum(path.stat().st_size for path in paths if path.exists())
    if shutil.disk_usage(snapshot).free <= estimate:
        raise ValueError('insufficient free space for Mail backup')
    target = snapshot / 'mail-database'; target.mkdir(mode=0o700)
    rows = []
    for label, path in zip(('db', 'wal', 'shm'), paths):
        if not path.exists():
            if path.is_symlink(): raise ValueError('component changed to symlink')
            rows.append({'kind': label, 'present': False})
            continue
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_dev != snapshot.stat().st_dev:
            raise ValueError('database component changed')
        before = snapshot_tool.digest(path)
        dest = target / label
        snapshot_tool.clone(path, dest)
        if snapshot_tool.digest(dest) != before or snapshot_tool.digest(path) != before:
            raise ValueError('database clone did not verify')
        rows.append({'kind': label, 'present': True, 'sha256': before[0], 'bytes': before[1]})
    idle(paths)
    for row, path in zip(rows, paths):
        if path.is_symlink() or path.exists() != row['present']:
            raise ValueError('database components changed during backup')
        if row['present'] and snapshot_tool.digest(path) != (row['sha256'], row['bytes']):
            raise ValueError('database changed during backup')
    manifest = {'version': 2, 'database_relative': snapshot_tool.relative(home, database), 'components': rows}
    manifest_path = target / 'manifest.json'
    fd = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(manifest, f, ensure_ascii=True, sort_keys=True, separators=(',', ':')); f.write('\n')
        f.flush(); os.fsync(f.fileno())
    watcher_sha = capture_watcher(home, snapshot)
    return {'mail_manifest_sha256': snapshot_tool.digest(manifest_path)[0],
            'watcher_manifest_sha256': watcher_sha,
            'components_present': sum(row['present'] for row in rows)}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    args = parser.parse_args(); os.umask(0o077)
    try:
        if not args.home.is_absolute() or not args.snapshot.is_absolute(): raise ValueError('absolute paths required')
        print(json.dumps(capture(args.home, args.snapshot, database_path(args.home))))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        print('pre-install Mail clone failed; installer must not run', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

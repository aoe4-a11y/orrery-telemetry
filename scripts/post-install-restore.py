#!/usr/bin/env python3
"""Restore a verified pre-install snapshot without discarding current bytes."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid

spec = importlib.util.spec_from_file_location('snapshot_tool', Path(__file__).with_name('pre-install-snapshot.py'))
snapshot_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot_tool)


def restore(home: Path, snapshot: Path, manifest_sha256: str) -> dict:
    snapshot_tool.relative(home, snapshot)
    snapshot_tool.assert_safe_parents(home, snapshot_tool.relative(home, snapshot))
    if snapshot.parent != home / '.agentstack/backups' or not snapshot.name.startswith('orrery-up-6-'):
        raise ValueError('snapshot is outside the approved backup directory')
    if snapshot.is_symlink() or not snapshot.is_dir():
        raise ValueError('snapshot is unavailable')
    metadata = snapshot.stat()
    if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise ValueError('snapshot is not private')
    manifest = snapshot / 'manifest.json'
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError('snapshot manifest is unavailable')
    manifest_bytes = manifest.read_bytes()
    if not re.fullmatch(r'[0-9a-f]{64}', manifest_sha256) or hashlib.sha256(manifest_bytes).hexdigest() != manifest_sha256:
        raise ValueError('manifest digest does not match')
    rows = json.loads(manifest_bytes)
    if not isinstance(rows, list):
        raise ValueError('invalid manifest')
    seen = set()
    files = snapshot / 'files'
    if files.is_symlink() or not files.is_dir():
        raise ValueError('snapshot files are unavailable')
    # Verify the complete source set before changing any destination.
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'path', 'sha256', 'bytes'}:
            raise ValueError('invalid manifest row')
        rel, sha, size = row['path'], row['sha256'], row['bytes']
        if not isinstance(rel, str) or rel in seen or type(size) is not int or size < 0:
            raise ValueError('invalid manifest values')
        seen.add(rel)
        snapshot_tool.assert_safe_parents(home, rel)
        snapshot_tool.assert_safe_parents(files, rel)
        source = files / rel
        target = home / rel
        if sha is None:
            if size != 0 or (source.exists() and not source.is_dir()) or source.is_symlink():
                raise ValueError('invalid directory or absent entry')
            if source.is_dir() and (target.is_symlink() or (target.exists() and not target.is_dir())):
                raise ValueError('directory destination is incompatible')
        else:
            if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha):
                raise ValueError('invalid digest')
            if snapshot_tool.digest(source) != (sha, size):
                raise ValueError('snapshot integrity failed')
            if target.exists() and target.is_dir() and not target.is_symlink():
                raise ValueError('file destination is a directory')
    after = snapshot / 'post-install-current'
    if after.exists() or after.is_symlink():
        raise ValueError('post-install copy already exists')
    after.mkdir(mode=0o700)
    # Copy and verify every current file before replacing any of them.
    current = 0
    post_rows = []
    current_before = {}
    for row in rows:
        if row['sha256'] is None:
            continue
        rel = row['path']; target = home / rel
        if not target.exists() and not target.is_symlink():
            current_before[rel] = None
            continue
        mode = target.lstat().st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
            raise ValueError('current destination is not a file')
        before = snapshot_tool.digest(target)
        saved = after / rel
        snapshot_tool.clone(target, saved)
        if snapshot_tool.digest(saved) != before or snapshot_tool.digest(target) != before:
            raise ValueError('current file copy failed verification')
        post_rows.append({'path': rel, 'sha256': before[0], 'bytes': before[1]})
        current_before[rel] = before
        current += 1
    post_manifest = after / 'manifest.json'
    fd = os.open(post_manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(post_rows, f, ensure_ascii=True, separators=(',', ':'))
        f.write('\n')
    post_manifest_sha = snapshot_tool.digest(post_manifest)[0]
    restored = 0
    for row in rows:
        rel = row['path']; source = files / rel; target = home / rel
        if row['sha256'] is None:
            if source.is_dir() and not source.is_symlink():
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
            continue
        snapshot_tool.assert_safe_parents(home, rel)
        present = target.exists() or target.is_symlink()
        observed = snapshot_tool.digest(target) if present else None
        if observed != current_before[rel]:
            raise ValueError('current file changed during restore')
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = target.with_name('.orrery-restore-' + uuid.uuid4().hex)
        if temporary.exists() or temporary.is_symlink():
            raise ValueError('restore temporary path already exists')
        snapshot_tool.clone(source, temporary)
        expected = (row['sha256'], row['bytes'])
        if snapshot_tool.digest(temporary) != expected:
            raise ValueError('restore copy failed verification')
        os.replace(temporary, target)
        if snapshot_tool.digest(target) != expected:
            raise ValueError('restored file failed verification')
        restored += 1
    # Paths absent before the upgrade are deliberately left intact.
    return {'restored_files': restored, 'preserved_post_install_files': current,
            'post_install_manifest_sha256': post_manifest_sha,
            'originally_absent_paths': sum(row['sha256'] is None and not (files / row['path']).exists() for row in rows)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--home', type=Path, required=True)
    ap.add_argument('--snapshot', type=Path, required=True)
    ap.add_argument('--manifest-sha256', required=True)
    args = ap.parse_args()
    os.umask(0o077)
    try:
        if not args.home.is_absolute() or not args.snapshot.is_absolute():
            raise ValueError('absolute paths required')
        print(json.dumps(restore(args.home, args.snapshot, args.manifest_sha256)))
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        print('restore failed; preserve the snapshot and inspect before retrying', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

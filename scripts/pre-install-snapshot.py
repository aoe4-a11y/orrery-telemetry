#!/usr/bin/env python3
"""Clone and verify the files an ORRERY fleet install may replace.

The manifest contains relative paths, SHA-256 digests and byte counts only.
No file contents or absolute user paths are printed. Run on the installer's
volume; missing paths are recorded, not fabricated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
RELEASE = 'releases/seat-lifecycle/ee5880e3e23606e0f3252cbeed211868102f4595'
FORBIDDEN_DIRS = {'.git', 'node_modules', '.venv', 'build'}


def relative(home: Path, value: str | Path) -> str:
    path = Path(value)
    if not path.is_absolute():
        path = home / path
    try:
        part = path.relative_to(home)
    except ValueError:
        raise ValueError('a planned path is outside the selected home') from None
    if not part.parts or any(p in ('', '.', '..') for p in part.parts):
        raise ValueError('invalid planned path')
    return part.as_posix()


def assert_safe_parents(home: Path, rel: str) -> None:
    parts = PurePosixPath(rel).parts
    if not parts or rel.startswith('/') or any(p in ('', '.', '..') for p in parts):
        raise ValueError('invalid relative path')
    current = home
    for part in parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError('planned path traverses a symlink')


def plan(home: Path, project: Path, candidate: str, worktree: Path) -> list[str]:
    if not re.fullmatch(r'[0-9a-f]{40,64}', candidate):
        raise ValueError('candidate must be a full hexadecimal commit ID')
    if home.is_symlink() or not home.is_dir():
        raise ValueError('selected home must be an existing real directory')
    relative(home, project)
    if not worktree.is_absolute():
        raise ValueError('absolute installer worktree required')
    for key, expected in (('AGENTSTACK_HOME', home / '.agentstack'),
                          ('CODEX_HOME', home / '.codex'),
                          ('CLAUDE_CONFIG_DIR', home / '.claude')):
        value = os.environ.get(key)
        if value and Path(value) != expected:
            raise ValueError('non-default configuration root requires a separate reviewed plan')
    paths = {
        '.agentstack/VERSION', '.agentstack/env.sh', '.agentstack/install-state.json',
        '.agentstack/fleet-install.json', '.agentstack/bin', '.agentstack/hooks',
        '.agentstack/dashboard', '.agentstack/skills', '.agentstack/codex',
        '.agentstack/claude', '.agentstack/config', '.agentstack/templates',
        '.agentstack/scripts', '.agentstack/connections', '.agentstack/profiles',
        '.agentstack/parked-launchd',
        '.agentstack/integrations/codex_app/plugin', '.agentstack/integrations/codex_app/src',
        '.agentstack/integrations/codex_app/schemas', f'.agentstack/{RELEASE}',
        '.agentstack/mail-service/renders', '.agentstack/mail-service/runtime',
        f'.agentstack/mail-service/candidates/{candidate}',
        'AGENTS.md', 'CLAUDE.md', '.claude/settings.json', '.claude.json',
        '.claude/CLAUDE.md', '.codex/AGENTS.md',
        relative(home, project / 'AGENTS.md'), relative(home, project / 'CLAUDE.md'),
    }
    # Managed instruction migration inspects the installer cwd and its ancestors.
    for folder in (worktree, *worktree.parents):
        target = folder / 'CLAUDE.md'
        if target.is_relative_to(home):
            paths.add(relative(home, target))
        elif target.exists() or target.is_symlink():
            raise ValueError('an instruction source is outside the snapshot volume')
    # Include new destination names as well as files already on disk.
    def source_destinations(source: Path, dest: str) -> None:
        if not source.is_dir():
            return
        for folder, dirs, filenames in os.walk(source, followlinks=False):
            dirs[:] = [d for d in dirs if d not in FORBIDDEN_DIRS and d not in ('__pycache__', '.pytest_cache')]
            base = Path(folder)
            for filename in filenames:
                if filename.endswith(('.pyc', '.pyo')):
                    continue
                paths.add((PurePosixPath(dest) / (base / filename).relative_to(source).as_posix()).as_posix())
    for section in ('bin', 'hooks', 'dashboard', 'skills', 'codex', 'claude', 'templates'):
        source_destinations(ROOT / section, '.agentstack/' + section)
    source_destinations(ROOT / 'scripts/lib', '.agentstack/bin/lib')
    for section in ('plugin', 'src', 'schemas'):
        source_destinations(ROOT / 'integrations/codex_app' / section, '.agentstack/integrations/codex_app/' + section)
    source_destinations(ROOT / 'fleet' / RELEASE, '.agentstack/' + RELEASE)
    paths.update(('.agentstack/hooks/spawn_child.upstream.sh', '.agentstack/hooks/cleanup-child-agent.upstream.sh',
                  '.agentstack/bin/agentstack-preregister-child.upstream'))
    installer = (ROOT / 'scripts/install.sh').read_text()
    for variable, target in (('BIN_DIR', 'bin'), ('HOOKS_DIR', 'hooks'),
                             ('DASHBOARD_DIR', 'dashboard'), ('SKILLS_DIR', 'skills'),
                             ('RUNTIME_DIR', 'runtime')):
        pattern = r'\$' + variable + r'/([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)'
        for suffix in re.findall(pattern, installer):
            paths.add('.agentstack/' + target + '/' + suffix)
    for key in ('AGENTSTACK_CLAUDE_SETTINGS', 'AGENTSTACK_CLAUDE_JSON'):
        if os.environ.get(key):
            if not Path(os.environ[key]).is_absolute():
                raise ValueError('configured target must be absolute')
            paths.add(relative(home, os.environ[key]))
    explicit_mail_root = os.environ.get('AGENTSTACK_MAIL_SERVICE_ROOT')
    if explicit_mail_root and relative(home, explicit_mail_root) != '.agentstack/mail-service':
        raise ValueError('non-default mail service root requires a separate reviewed plan')
    for name in ('annotations.json', 'claude-mcp-merge-result.json', 'dashboard-service.json',
                 'dashboard.legacy.log', 'dashboard.log', 'dashboard.pid', 'mail-watcher.log',
                 'managed_agents.txt', 'settings-installed-entries.json', 'settings-merge-result.json'):
        paths.add('.agentstack/runtime/' + name)
    for legacy in (home / '.agentstack/runtime').glob('dashboard.legacy.*'):
        paths.add(relative(home, legacy))
    addons = json.loads((ROOT / 'fleet/addon-paths.json').read_text())
    for name in addons:
        if name.startswith('fleet/runtime/'):
            paths.add('.agentstack/' + name.removeprefix('fleet/'))
    for skill in (ROOT / 'skills').glob('*/SKILL.md'):
        paths.add('.claude/skills/' + skill.parent.name)
        paths.add('.codex/skills/' + skill.parent.name)
    state_path = home / '.agentstack/install-state.json'
    if not state_path.is_file() or state_path.is_symlink():
        raise ValueError('existing install-state is missing or not a regular file')
    state = json.loads(state_path.read_text())
    if not isinstance(state.get('owned_files', []), list) or not isinstance(state.get('services', []), list):
        raise ValueError('existing install-state has an unexpected shape')
    for name in state.get('owned_files', []):
        if not isinstance(name, str) or not Path(name).is_absolute():
            raise ValueError('invalid owned file entry')
        paths.add(relative(home, name))
    for provider, target in (('codex', home / '.codex/AGENTS.md'),
                             ('claude', home / '.claude/CLAUDE.md')):
        digest_name = hashlib.sha256(os.fsencode(str(target))).hexdigest()
        paths.add('.agentstack/backups/instruction-migration/' + provider + '/' + digest_name)
    receipts = state.get('instruction_receipts', [])
    if not isinstance(receipts, list):
        raise ValueError('invalid instruction receipts')
    receipt_root = home / '.agentstack/backups/instruction-migration'
    for raw in receipts:
        if not isinstance(raw, str):
            raise ValueError('invalid instruction receipt path')
        receipt = Path(raw)
        if not receipt.is_relative_to(receipt_root) or receipt.name != 'receipt.json':
            raise ValueError('instruction receipt is outside the expected directory')
        assert_safe_parents(home, relative(home, receipt))
        paths.add(relative(home, receipt.parent))
        if receipt.is_symlink() or not receipt.is_file():
            raise ValueError('instruction receipt is unavailable')
        doc = json.loads(receipt.read_text())
        instruction_plan = doc.get('plan', {})
        target = instruction_plan.get('target', {})
        sources = instruction_plan.get('sources', [])
        if not isinstance(target, dict) or not isinstance(sources, list):
            raise ValueError('invalid instruction receipt plan')
        for entry in [target, *sources]:
            if not isinstance(entry, dict):
                raise ValueError('invalid instruction receipt entry')
            for field in ('requested_path', 'resolved_path'):
                value = entry.get(field)
                if value:
                    if not isinstance(value, str):
                        raise ValueError('invalid instruction target')
                    paths.add(relative(home, value))
    for service in state.get('services', []):
        if not isinstance(service, dict):
            raise ValueError('invalid service entry')
        for key in ('path', 'pidfile'):
            value = service.get(key)
            if isinstance(value, str) and value:
                if not Path(value).is_absolute():
                    raise ValueError('service path must be absolute')
                paths.add(relative(home, value))
    env = state.get('env', {})
    if not isinstance(env, dict):
        raise ValueError('invalid recorded environment')
    old_project = env.get('AGENTSTACK_PROJECT_KEY')
    if old_project:
        if not isinstance(old_project, str) or not Path(old_project).is_absolute():
            raise ValueError('invalid recorded project')
        paths.add(relative(home, Path(old_project) / 'CLAUDE.md'))
    for key in ('AGENTSTACK_RUNTIME_DIR', 'AGENTSTACK_MAIL_DIR', 'AGENTSTACK_CLAUDE_JSON', 'AGENTSTACK_SKILLS_DIR'):
        value = env.get(key)
        if value and not isinstance(value, str):
            raise ValueError('invalid recorded path')
        # Non-default runtime/install roots require their own explicit inventory.
        if key in ('AGENTSTACK_RUNTIME_DIR', 'AGENTSTACK_MAIL_DIR', 'AGENTSTACK_SKILLS_DIR') and value:
            expected = { 'AGENTSTACK_RUNTIME_DIR': '.agentstack/runtime',
                         'AGENTSTACK_MAIL_DIR': '.agentstack/mail-service',
                         'AGENTSTACK_SKILLS_DIR': '.agentstack/skills' }[key]
            if relative(home, value) != expected:
                raise ValueError('non-default installed path requires a separate reviewed plan')
        if key == 'AGENTSTACK_CLAUDE_JSON' and value:
            paths.add(relative(home, value))
    prefix = env.get('AGENTSTACK_LABEL_PREFIX')
    if not isinstance(prefix, str) or not re.fullmatch(r'[A-Za-z0-9._-]+', prefix):
        raise ValueError('service label prefix unavailable in install-state')
    prefixes = {prefix}
    explicit_prefix = os.environ.get('AGENTSTACK_LABEL_PREFIX')
    if explicit_prefix:
        if not re.fullmatch(r'[A-Za-z0-9._-]+', explicit_prefix):
            raise ValueError('invalid explicit service label prefix')
        prefixes.add(explicit_prefix)
    for selected_prefix in prefixes:
        for suffix in ('agentdashboard', 'mail', 'mail-watcher'):
            label = selected_prefix + '.' + suffix
            paths.add('Library/LaunchAgents/' + label + '.plist')
            paths.add('.config/systemd/user/' + label + '.service')
            paths.add('.config/systemd/user/' + label + '.timer')
    for path in paths:
        assert_safe_parents(home, path)
    return sorted(paths)


def collect(home: Path, roots: list[str]) -> list[str]:
    result: set[str] = set()
    def visit(rel: str) -> None:
        assert_safe_parents(home, rel)
        if rel in result:
            return
        result.add(rel)
        path = home / rel
        try:
            st = path.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISDIR(st.st_mode):
            if path.name in FORBIDDEN_DIRS:
                raise ValueError('planned tree contains an excluded dependency directory')
            for child in sorted(path.iterdir(), key=lambda p: p.name):
                visit(relative(home, child))
        elif stat.S_ISLNK(st.st_mode):
            allowed = (rel.startswith('.agentstack/' + RELEASE + '/') or
                       rel.startswith('.claude/skills/') or rel.startswith('.codex/skills/'))
            if not allowed:
                raise ValueError('planned writable path is a symlink and requires review')
        elif not stat.S_ISREG(st.st_mode):
            raise ValueError('planned tree contains an unsupported file type')
    for root in roots:
        visit(root)
    return sorted(result)


def digest(path: Path) -> tuple[str, int]:
    st = path.lstat()
    h = hashlib.sha256()
    if stat.S_ISLNK(st.st_mode):
        data = os.fsencode(os.readlink(path)); h.update(data); return h.hexdigest(), len(data)
    if not stat.S_ISREG(st.st_mode):
        raise ValueError('cannot hash a non-file')
    size = 0
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as f:
        opened = os.fstat(f.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (st.st_dev, st.st_ino):
            raise ValueError('file changed during verification')
        while data := f.read(1024 * 1024):
            size += len(data); h.update(data)
    return h.hexdigest(), size


def clone(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if source.is_symlink():
        destination.symlink_to(os.readlink(source))
    else:
        result = subprocess.run(['/bin/cp', '-c', '-p', '-P', str(source), str(destination)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode:
            raise ValueError('APFS clone failed')


def snapshot(home: Path, project: Path, candidate: str, worktree: Path, destination: Path) -> dict:
    roots = plan(home, project, candidate, worktree)
    paths = collect(home, roots)
    rel_destination = relative(home, destination)
    assert_safe_parents(home, rel_destination)
    if destination.parent != home / '.agentstack/backups' or not destination.name.startswith('orrery-up-6-'):
        raise ValueError('snapshot must use the approved backup directory')
    if any(destination.is_relative_to(home / root) for root in roots):
        raise ValueError('snapshot destination overlaps a planned source')
    if destination.exists() or destination.is_symlink():
        raise ValueError('snapshot destination already exists')
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise ValueError('snapshot parent is unavailable or a symlink')
    if home.stat().st_dev != destination.parent.stat().st_dev:
        raise ValueError('snapshot destination is not on the same volume')
    destination.mkdir(mode=0o700)
    files = destination / 'files'; files.mkdir(mode=0o700)
    rows = []
    for rel in paths:
        source = home / rel
        target = files / rel
        try:
            mode = source.lstat().st_mode
        except FileNotFoundError:
            rows.append({'path': rel, 'sha256': None, 'bytes': 0})
            continue
        if source.lstat().st_dev != destination.parent.stat().st_dev:
            raise ValueError('planned source crosses a volume boundary')
        if stat.S_ISDIR(mode):
            target.mkdir(parents=True, exist_ok=True, mode=0o700)
            rows.append({'path': rel, 'sha256': None, 'bytes': 0})
            continue
        before = digest(source)
        clone(source, target)
        if digest(target) != before or digest(source) != before:
            raise ValueError('snapshot verification failed')
        rows.append({'path': rel, 'sha256': before[0], 'bytes': before[1]})
    if collect(home, roots) != paths:
        raise ValueError('planned path set changed during snapshot')
    for row in rows:
        source = home / row['path']
        saved = files / row['path']
        if row['sha256'] is not None:
            expected = (row['sha256'], row['bytes'])
            if digest(source) != expected or digest(saved) != expected:
                raise ValueError('snapshot changed before final verification')
        elif saved.is_dir():
            if source.is_symlink() or not source.is_dir():
                raise ValueError('planned directory changed')
        elif source.exists() or source.is_symlink():
            raise ValueError('an absent path appeared during snapshot')
    manifest = destination / 'manifest.json'
    fd = os.open(manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(rows, f, ensure_ascii=True, separators=(',', ':'))
        f.write('\n')
    return {'paths': len(rows), 'files': sum(r['sha256'] is not None for r in rows),
            'bytes': sum(r['bytes'] for r in rows), 'manifest_sha256': digest(manifest)[0]}


def verify_snapshot(home: Path, project: Path, candidate: str, worktree: Path, destination: Path, expected_sha: str) -> None:
    rel_destination = relative(home, destination)
    assert_safe_parents(home, rel_destination)
    if destination.parent != home / '.agentstack/backups' or not destination.name.startswith('orrery-up-6-'):
        raise ValueError('snapshot is outside the approved backup directory')
    manifest = destination / 'manifest.json'
    if destination.is_symlink() or not destination.is_dir() or manifest.is_symlink() or not manifest.is_file():
        raise ValueError('snapshot manifest unavailable')
    metadata = destination.stat()
    if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise ValueError('snapshot is not private')
    raw = manifest.read_bytes()
    if not re.fullmatch(r'[0-9a-f]{64}', expected_sha) or hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError('snapshot manifest digest differs')
    rows = json.loads(raw)
    if not isinstance(rows, list) or any(not isinstance(r, dict) or set(r) != {'path', 'sha256', 'bytes'} for r in rows):
        raise ValueError('invalid snapshot manifest')
    roots = plan(home, project, candidate, worktree)
    paths = collect(home, roots)
    if [r['path'] for r in rows] != paths:
        raise ValueError('planned paths changed after snapshot')
    files = destination / 'files'
    if files.is_symlink() or not files.is_dir():
        raise ValueError('snapshot files unavailable')
    for row in rows:
        rel = row['path']
        assert_safe_parents(home, rel)
        assert_safe_parents(files, rel)
        source = home / rel
        saved = files / rel
        sha, size = row['sha256'], row['bytes']
        if sha is not None:
            if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha) or type(size) is not int or size < 0:
                raise ValueError('invalid snapshot file entry')
            if digest(source) != (sha, size) or digest(saved) != (sha, size):
                raise ValueError('snapshot no longer matches current source')
        elif size != 0:
            raise ValueError('invalid directory or absent entry')
        elif saved.is_dir() and not saved.is_symlink():
            if source.is_symlink() or not source.is_dir():
                raise ValueError('planned directory changed')
        elif source.exists() or source.is_symlink() or saved.exists() or saved.is_symlink():
            raise ValueError('an absent path appeared after snapshot')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--home', type=Path, required=True)
    ap.add_argument('--project', type=Path, required=True)
    ap.add_argument('--candidate', required=True)
    ap.add_argument('--worktree', type=Path, required=True)
    ap.add_argument('--destination', type=Path)
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--plan-output', type=Path)
    ap.add_argument('--verify-manifest-sha')
    args = ap.parse_args()
    os.umask(0o077)
    try:
        if not args.home.is_absolute() or not args.project.is_absolute():
            raise ValueError('absolute home and project required')
        if args.verify_manifest_sha:
            if args.destination is None or not args.destination.is_absolute() or args.plan:
                raise ValueError('absolute snapshot destination required for verification')
            verify_snapshot(args.home, args.project, args.candidate, args.worktree, args.destination, args.verify_manifest_sha)
            print(json.dumps({'snapshot_verified': True}))
        elif args.plan:
            roots = plan(args.home, args.project, args.candidate, args.worktree)
            paths = collect(args.home, roots)
            if args.plan_output:
                if not args.plan_output.is_absolute():
                    raise ValueError('absolute plan output required')
                rel_output = relative(args.home, args.plan_output)
                assert_safe_parents(args.home, rel_output)
                fd = os.open(args.plan_output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w') as f:
                    json.dump([{'path': p, 'sha256': None, 'bytes': 0} for p in paths], f)
                    f.write('\n')
            print(json.dumps({'planned_roots': len(roots), 'planned_paths': len(paths)}))
        else:
            if args.destination is None or not args.destination.is_absolute():
                raise ValueError('absolute snapshot destination required')
            print(json.dumps(snapshot(args.home, args.project, args.candidate, args.worktree, args.destination)))
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        print('snapshot failed; installer must not run', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

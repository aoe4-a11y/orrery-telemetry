#!/usr/bin/env python3
"""Fail closed before the installer can retire its legacy tmux watcher."""
import os
from pathlib import Path
import shlex
import subprocess
import sys


def watcher_pid_is_safe(pid: int, home: Path) -> bool:
    # Read only the exact pane process, never the process list or a shell pane.
    proc = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'uid=', '-o', 'command='],
                          capture_output=True, text=True)
    if proc.returncode or not proc.stdout.strip():
        return False
    try:
        uid, command = proc.stdout.strip().split(None, 1)
        args = shlex.split(command)
    except ValueError:
        return False
    expected = str(home / '.agentstack/hooks/watch_agent_mail_signals.sh')
    if uid != str(os.getuid()) or not (args == [expected] or
            (len(args) == 2 and args[0] in ('bash', '/bin/bash', 'sh', '/bin/sh') and args[1] == expected)):
        return False
    # Unknown descendants may be other work. Defer instead of killing them.
    children = subprocess.run(['/usr/bin/pgrep', '-P', str(pid)], capture_output=True, text=True)
    return children.returncode == 1 and not children.stdout.strip()


def guard(home: Path, lock: Path = Path('/tmp/orrery-mail-watcher.lock')) -> None:
    if os.environ.get('AGENTSTACK_MAIL_WATCHER_SESSION', 'mail-watcher') != 'mail-watcher':
        raise ValueError('non-default watcher session')
    if os.environ.get('AGENTSTACK_TEST_LEGACY_MAIL_WATCHER_LOCK_DIR'):
        raise ValueError('legacy lock override')
    # It is outside the snapshot. Preserve even a plausibly stale lock.
    if lock.exists() or lock.is_symlink():
        raise ValueError('legacy watcher lock requires separate review')
    sessions = subprocess.run(['tmux', 'list-sessions', '-F', '#{session_name}'], capture_output=True, text=True)
    if sessions.returncode:
        raise ValueError('cannot verify tmux sessions')
    if 'mail-watcher' not in sessions.stdout.splitlines():
        return
    panes = subprocess.run(['tmux', 'list-panes', '-s', '-t', '=mail-watcher', '-F', '#{pane_pid}'],
                           capture_output=True, text=True)
    ids = panes.stdout.splitlines()
    if panes.returncode or not ids or any(not s.isascii() or not s.isdigit() or int(s) <= 1 for s in ids):
        raise ValueError('cannot verify watcher panes')
    if not all(watcher_pid_is_safe(int(pid), home) for pid in ids):
        raise ValueError('watcher session contains an unverified process')


if __name__ == '__main__':
    try:
        guard(Path.home())
    except (OSError, ValueError):
        print('watcher safety guard failed; installer must not run', file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
"""Owner-only stop, idle clone, restart, health gate; never prints private paths."""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

spec = importlib.util.spec_from_file_location('mail_backup', Path(__file__).with_name('pre-install-mail-backup.py'))
mail_backup = importlib.util.module_from_spec(spec); spec.loader.exec_module(mail_backup)


class Controller:
    def __init__(self, home: Path, worktree: Path):
        state = json.loads((home / '.agentstack/install-state.json').read_text())
        settings, mail = state.get('env', {}), state.get('agent_mail', {})
        if mail.get('provider') != 'agentstack' or mail.get('deployment_identified') is not True:
            raise ValueError('installed Mail deployment is not identified')
        database = mail_backup.database_path(home)
        root, service_env = settings.get('AGENTSTACK_MAIL_DIR'), mail.get('service_env')
        url = settings.get('AGENTSTACK_MCP_URL')
        if not all(isinstance(x, str) and x for x in (root, service_env, url)):
            raise ValueError('installed Mail controller settings unavailable')
        root, service_env = Path(root), Path(service_env)
        if not root.is_absolute() or not service_env.is_absolute() or not service_env.is_relative_to(root / 'renders'):
            raise ValueError('installed Mail render is not in the managed root')
        for path in (root, service_env):
            mail_backup.snapshot_tool.assert_safe_parents(home, mail_backup.snapshot_tool.relative(home, path))
        if service_env.is_symlink() or not service_env.is_file():
            raise ValueError('installed Mail render unavailable')
        runner = service_env.parent / 'run-agentstack-mail.sh'
        if runner.is_symlink() or not runner.is_file():
            raise ValueError('installed Mail runner unavailable')
        controller = worktree / 'bin/agentstack-mailctl'
        if not controller.is_file(): raise ValueError('candidate Mail controller unavailable')
        runtime = root / 'runtime'
        for name, expected in (('AGENTSTACK_MAIL_RUNTIME_DIR', runtime), ('AGENTSTACK_MAIL_PIDFILE', runtime/'agentstack-mail.pid'),
                               ('AGENTSTACK_MAIL_LOG', runtime/'agentstack-mail.log'),
                               ('AGENTSTACK_MAIL_STOPPED_MARKER', runtime/'agentstack-mail.stopped'),
                               ('AGENTSTACK_MAIL_CONTROL_LOCK', runtime/'agentstack-mailctl.lock')):
            if os.environ.get(name) and Path(os.environ[name]) != expected:
                raise ValueError('explicit Mail controller location differs')
        for name, expected in (('AGENTSTACK_MAIL_DIR', str(root)), ('AGENTSTACK_MCP_URL', url),
                               ('AGENTSTACK_MAIL_LAUNCHD_LABEL', settings.get('AGENTSTACK_MAIL_LAUNCHD_LABEL') or '')):
            if os.environ.get(name) and os.environ[name] != expected:
                raise ValueError('explicit Mail controller setting differs')
        if os.environ.get('AGENTSTACK_MAILCTL_SWEEP') not in (None, '', '0'):
            raise ValueError('Mail controller is in autostart sweep mode')
        if any(os.environ.get(name) for name in ('AGENTSTACK_MAIL_SERVICE_ENV', 'AGENTSTACK_MAIL_SERVICE_VENV',
                                                  'AGENTSTACK_MAIL_PACKAGE_SOURCE', 'AGENTSTACK_MAIL_CANDIDATE_ID')):
            raise ValueError('explicit candidate override requires a reviewed plan')
        self.command = ['/bin/bash', str(controller)]
        self.env = os.environ.copy()
        self.env.update(AGENTSTACK_MAILCTL_SKIP_ENV='1', AGENTSTACK_HOME=str(home),
            AGENTSTACK_MAIL_DIR=str(root), AGENTSTACK_MAIL_ENV=str(service_env),
            AGENTSTACK_MAIL_RUNNER=str(runner), AGENTSTACK_MAIL_PIDFILE=str(runtime/'agentstack-mail.pid'),
            AGENTSTACK_MAIL_LOG=str(runtime/'agentstack-mail.log'), AGENTSTACK_MAIL_DB=str(database),
            AGENTSTACK_MCP_URL=url, AGENTSTACK_MAIL_LAUNCHD_LABEL=settings.get('AGENTSTACK_MAIL_LAUNCHD_LABEL') or '')

    def run(self, action: str) -> None:
        result = subprocess.run([*self.command, action], env=self.env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=240)
        if result.returncode:
            raise ValueError('Mail controller refused ' + action)


def cycle(home: Path, snapshot: Path, controller, capture=mail_backup.capture, clock=time.monotonic) -> dict:
    database = mail_backup.database_path(home)
    controller.run('status')  # Must own a healthy listener before stopping it.
    began = clock()
    def record_failure(restored):
        report = {'previous_mail_restored': restored, 'elapsed_to_recovery_check_seconds': round(clock() - began, 3)}
        path = snapshot / 'mail-cycle-failed.json'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f: json.dump(report, f); f.write('\n')
    try:
        controller.run('stop')
        result = capture(home, snapshot, database)
    except BaseException:
        # Even a failed stop can have partially stopped Mail; use the same controller.
        restored = False
        try:
            controller.run('start')
            controller.run('status')
            restored = True
        finally:
            record_failure(restored)
        raise
    try:
        controller.run('start')
        controller.run('status')  # Controller checks listener and health/DB identity.
    except BaseException:
        record_failure(False)
        raise
    result['preinstall_outage_seconds'] = round(clock() - began, 3)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    for name in ('home', 'snapshot', 'worktree'): parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(); os.umask(0o077)
    try:
        if not all(path.is_absolute() for path in (args.home, args.snapshot, args.worktree)):
            raise ValueError('absolute paths required')
        print(json.dumps(cycle(args.home, args.snapshot, Controller(args.home, args.worktree))))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        print('Mail pre-install stop/clone/restart gate failed; installer must not run', file=sys.stderr)
        return 1

if __name__ == '__main__': raise SystemExit(main())

"""Watcher guard with a fake tmux and synthetic pane process responses."""
import importlib.util
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('watcher_guard', ROOT / 'scripts/pre-install-watcher-guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


@pytest.mark.parametrize('case,accepted', [('absent', True), ('watcher', True), ('seat', False)])
def test_fake_tmux_never_signals_panes(tmp_path, monkeypatch, case, accepted):
    home = tmp_path / 'home'
    home.mkdir()
    binary = tmp_path / 'tmux'
    binary.write_text('''#!/bin/sh
case "$1" in
  list-sessions) [ "$CASE" = absent ] || printf 'mail-watcher\\n';;
  list-panes) printf '45678\\n';;
  *) exit 42;;
esac
''')
    binary.chmod(0o755)
    monkeypatch.setenv('PATH', str(tmp_path))
    monkeypatch.setenv('CASE', case)
    monkeypatch.delenv('AGENTSTACK_MAIL_WATCHER_SESSION', raising=False)
    monkeypatch.delenv('AGENTSTACK_TEST_LEGACY_MAIL_WATCHER_LOCK_DIR', raising=False)
    real_run = subprocess.run
    def run(argv, **kwargs):
        if argv[0] == '/bin/ps':
            command = '/bin/bash ' + str(home / '.agentstack/hooks/watch_agent_mail_signals.sh')
            if case == 'seat': command = '/bin/zsh'
            return subprocess.CompletedProcess(argv, 0, f'{os.getuid()} {command}\n', '')
        if argv[0] == '/usr/bin/pgrep':
            return subprocess.CompletedProcess(argv, 1, '', '')
        return real_run(argv, **kwargs)
    monkeypatch.setattr(guard.subprocess, 'run', run)
    if accepted:
        guard.guard(home, tmp_path / 'absent-lock')
    else:
        with pytest.raises(ValueError): guard.guard(home, tmp_path / 'absent-lock')


def test_override_and_unreviewed_lock_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENTSTACK_MAIL_WATCHER_SESSION', 'other-seat')
    with pytest.raises(ValueError): guard.guard(tmp_path, tmp_path / 'lock')
    monkeypatch.delenv('AGENTSTACK_MAIL_WATCHER_SESSION')
    monkeypatch.delenv('AGENTSTACK_TEST_LEGACY_MAIL_WATCHER_LOCK_DIR', raising=False)
    (tmp_path / 'lock').mkdir()
    with pytest.raises(ValueError): guard.guard(tmp_path, tmp_path / 'lock')


def test_unknown_watcher_child_is_not_safe(tmp_path, monkeypatch):
    watcher = str(tmp_path / '.agentstack/hooks/watch_agent_mail_signals.sh')
    def run(argv, **kwargs):
        if argv[0] == '/bin/ps':
            return subprocess.CompletedProcess(argv, 0, f'{os.getuid()} /bin/bash {watcher}\n', '')
        return subprocess.CompletedProcess(argv, 0, '12345\n', '')
    monkeypatch.setattr(guard.subprocess, 'run', run)
    assert not guard.watcher_pid_is_safe(45678, tmp_path)

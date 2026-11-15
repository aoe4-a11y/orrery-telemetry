"""Fleet closed-seat signals must survive until the same seat returns."""
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'hooks/watch_agent_mail_signals.sh').read_text()


def function(name):
    match = re.search(rf'^{name}\(\) \{{\n.*?^\}}\n', SOURCE, re.M | re.S)
    assert match
    return match.group()


def run_workers(tmp_path, commands):
    sessions = tmp_path / 'sessions'; sessions.write_text('')
    trace = tmp_path / 'trace'; state = tmp_path / 'state.json'
    shell = 'set -euo pipefail\n' + function('state_should_attempt') + function('state_mark_result') + function('deliver_worker') + '''
STATE_DIR="$ROOT"; STATE_FILE="$ROOT/state.json"; RETRY_COOLDOWN=0
PERSISTENT_DELIVER="$ROOT/missing"; HEADLESS_REPLY_TIMEOUT=1; TMUX_TIMEOUT=1
run_to() {
  shift
  case "$2" in
    show-environment) return 1;;
    list-sessions) cat "$ROOT/sessions";;
    capture-pane) printf 'Claude ready\\n';;
    *) return 1;;
  esac
}
release_delivery_lease() { :; }
inject_notification() { printf 'delivered\\n' >> "$ROOT/trace"; }
log() { :; }
''' + commands
    result = subprocess.run(['/bin/bash', '-c', shell], env={'ROOT': str(tmp_path),
        'HOME': str(tmp_path), 'PATH': '/usr/bin:/bin:/usr/sbin:/sbin'},
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    return state, trace


def test_closed_seat_dirty_bit_survives_and_notifies_after_restart(tmp_path):
    signal = tmp_path / 'fixture.signal'; signal.write_text('synthetic')
    state, trace = run_workers(tmp_path, '''
deliver_worker "$ROOT/fixture.signal" FixtureSeat 77 Sender Subject normal 0 '' 0 '' ''
test -f "$ROOT/fixture.signal"
state_should_attempt FixtureSeat 77
printf 'FixtureSeat\\n' > "$ROOT/sessions"
deliver_worker "$ROOT/fixture.signal" FixtureSeat 77 Sender Subject normal 0 '' 0 '' ''
''')
    assert signal.exists()  # server-owned legacy dirty bit
    assert trace.read_text() == 'delivered\n'
    assert json.loads(state.read_text())['FixtureSeat:77']['last_result'] == 'success'


def test_only_old_per_message_signal_is_removed_for_absent_seat(tmp_path):
    old = tmp_path / 'old' / '1.signal'; old.parent.mkdir(); old.write_text('fixture')
    fresh = tmp_path / 'fresh' / '2.signal'; fresh.parent.mkdir(); fresh.write_text('fixture')
    past = time.time() - 49 * 3600; os.utime(old, (past, past))
    run_workers(tmp_path, '''
deliver_worker "$ROOT/old/1.signal" FixtureSeat 1 Sender Subject normal 1 '' 0 '' ''
deliver_worker "$ROOT/fresh/2.signal" FixtureSeat 2 Sender Subject normal 1 '' 0 '' ''
''')
    assert not old.exists()
    assert fresh.exists()


def test_absent_state_is_not_terminal_and_remains_retryable(tmp_path):
    state = tmp_path / 'state.json'
    state.write_text(json.dumps({'FixtureSeat:3': {'terminal': True}}))
    shell = 'set -euo pipefail\n' + function('state_should_attempt') + function('state_mark_result') + '''
STATE_FILE="$ROOT/state.json"; RETRY_COOLDOWN=0
state_mark_result FixtureSeat 3 session_not_found watcher
state_should_attempt FixtureSeat 3
'''
    result = subprocess.run(['/bin/bash', '-c', shell], env={'ROOT': str(tmp_path),
        'PATH': '/usr/bin:/bin:/usr/sbin:/sbin'}, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert 'terminal' not in json.loads(state.read_text())['FixtureSeat:3']

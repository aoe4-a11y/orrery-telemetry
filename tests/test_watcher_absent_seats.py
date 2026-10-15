"""Exercise real watcher functions against private signals and a fake tmux."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "hooks/watch_agent_mail_signals.sh").read_text()
HELPERS = (SOURCE[SOURCE.index("importance_rank()"):SOURCE.index("trap cleanup EXIT")]
           + SOURCE[SOURCE.index("agent_is_head()"):SOURCE.index("if command -v fswatch")])


def _signal(root, agent="Worker", message=21, *, legacy=False):
    p = root / "signals" / "agents" / (f"{agent}.signal" if legacy else f"{agent}/{message}.signal")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"message": {"id": message, "from": "Sender",
                                        "subject": "fixture", "importance": "normal"}}))
    os.utime(p, (time.time() - 172800,) * 2)
    return p


def _run(root, body, *, names=("Worker",), mode="ok", actual_timeout=False):
    root.mkdir(exist_ok=True)
    (root / "names.json").write_text(json.dumps(names))
    (root / "mode").write_text(mode)
    fake = root / "tmux"
    fake.write_text('''#!/usr/bin/env python3
import json,os,pathlib,sys,time
r=pathlib.Path(os.environ['FIXTURE_ROOT']);args=sys.argv[1:]
with (r/'calls.jsonl').open('a') as f:f.write(json.dumps(args)+'\\n')
names=json.loads((r/'names.json').read_text());mode=(r/'mode').read_text()
if args[0]=='list-sessions':
 if mode=='timeout':time.sleep(2)
 if mode=='error':sys.exit(1)
 print('\\n'.join(names));sys.exit(0)
target=args[args.index('-t')+1]
assert target.startswith('='), target
if args[0]=='has-session':sys.exit(0 if target[1:] in names and mode!='vanished' else 1)
if args[0]=='capture-pane':print('› Ask Codex to do anything');sys.exit(0)
raise AssertionError('unexpected real terminal operation')
''')
    fake.chmod(0o755)
    (root / "runtime/leases").mkdir(parents=True, exist_ok=True)
    header = f'''set -euo pipefail
STATE_DIR={shlex.quote(str(root / 'runtime'))}
STATE_FILE="$STATE_DIR/state.json"
LEASE_DIR="$STATE_DIR/leases"
SIGNALS_DIR={shlex.quote(str(root / 'signals'))}
RETRY_COOLDOWN=30
LEASE_TTL=120
TMUX_TIMEOUT=0.15
MAX_WORKERS=12
NOTIFY_MIN_IMPORTANCE=low
SESSION_NAMES=""
SESSION_TOPOLOGY=unknown
SESSION_CHECK_EPOCH=0
SCANNING_SIGNALS=0
AVAILABILITY_AGENTS=()
AVAILABILITY_STATES=()
write_heartbeat() {{ :; }}
'''
    override = "" if actual_timeout else 'run_to() { shift; "$@"; }\n'
    script = root / "run.sh"
    script.write_text(header + HELPERS + override + '''
write_heartbeat() { :; }
inject_notification() { printf '%s:%s\\n' "$2" "$3" >> "$FIXTURE_ROOT/delivered"; return "${INJECT_RESULT:-0}"; }
''' + body + "\nwait\n")
    env = {"PATH": str(root) + os.pathsep + os.environ["PATH"],
           "HOME": str(root / "home"), "CODEX_HOME": str(root / "home/.codex"),
           "FIXTURE_ROOT": str(root), "AGENTSTACK_RUNTIME_DIR": str(root / "runtime")}
    p = subprocess.run(["/bin/bash", str(script)], env=env, text=True,
                       capture_output=True, timeout=15)
    assert p.returncode == 0, p.stdout + p.stderr
    calls = [json.loads(s) for s in (root / "calls.jsonl").read_text().splitlines()]
    return p, calls


def test_absent_seat_is_deferred_once_per_transition_without_consuming_signals(tmp_path):
    files = [_signal(tmp_path, message=i) for i in (21, 22)]
    before = [p.read_bytes() for p in files]
    p, calls = _run(tmp_path, "process_existing_signals\nprocess_existing_signals", names=())
    assert p.stdout.count("Worker absent") == 1 and "Signal:" not in p.stdout
    assert [f.read_bytes() for f in files] == before
    assert not (tmp_path / "runtime/notify-state.json").exists()
    assert not (tmp_path / "delivered").exists()
    assert [c[0] for c in calls] == ["list-sessions", "list-sessions"]


def test_session_prefix_is_not_an_exact_recipient(tmp_path):
    signal = _signal(tmp_path)
    p, calls = _run(tmp_path, "process_existing_signals", names=("WorkerExtra",))
    assert "Worker absent" in p.stdout and "Signal:" not in p.stdout
    assert signal.exists() and not any(c[0] == "has-session" for c in calls)


@pytest.mark.parametrize("mode", ["error", "timeout"])
def test_topology_failure_is_unknown_and_bounded(tmp_path, mode):
    signal = _signal(tmp_path)
    start = time.monotonic()
    p, _ = _run(tmp_path, "process_existing_signals", mode=mode, actual_timeout=True)
    assert time.monotonic() - start < 4
    assert "Worker unknown" in p.stdout and "Worker absent" not in p.stdout
    assert signal.exists() and "Signal:" not in p.stdout


def test_returning_seat_retries_pending_immediately_and_success_stays_terminal(tmp_path):
    signal = _signal(tmp_path, legacy=True)
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime/notify-state.json").write_text(json.dumps({"Worker:21": {
        "last_result": "session_not_found", "last_attempt_epoch": int(time.time())}}))
    p, calls = _run(tmp_path, '''process_existing_signals
printf '["Worker"]' > "$FIXTURE_ROOT/names.json"
process_existing_signals
wait
process_existing_signals''', names=())
    assert "Worker absent" in p.stdout and "Worker present" in p.stdout
    assert (tmp_path / "delivered").read_text().count("Worker:") == 1
    state = json.loads((tmp_path / "runtime/notify-state.json").read_text())
    assert state["Worker:21"]["last_result"] == "success" and signal.exists()
    assert all(c[c.index("-t") + 1] == "=Worker" for c in calls if "-t" in c)


def test_seat_disappearing_after_snapshot_keeps_old_per_message_signal(tmp_path):
    signal = _signal(tmp_path)
    p, _ = _run(tmp_path, "process_existing_signals", mode="vanished")
    assert signal.exists() and not (tmp_path / "delivered").exists()
    state = json.loads((tmp_path / "runtime/notify-state.json").read_text())
    assert state["Worker:21"]["last_result"] == "session_not_found"


@pytest.mark.parametrize("result", ["success", "pane_busy", "capture_timeout", "submit_pending"])
def test_presence_does_not_override_success_or_other_failure_cooldown(tmp_path, result):
    _signal(tmp_path, legacy=True)
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime/notify-state.json").write_text(json.dumps({"Worker:21": {
        "last_result": result, "last_attempt_epoch": int(time.time())}}))
    p, _ = _run(tmp_path, "process_existing_signals")
    assert "Signal:" not in p.stdout and not (tmp_path / "delivered").exists()


def test_head_special_path_is_not_subject_to_worker_absence_gate(tmp_path):
    _signal(tmp_path, agent="ProudTuring", legacy=True)
    p, calls = _run(tmp_path, "process_existing_signals", names=())
    state = json.loads((tmp_path / "runtime/notify-state.json").read_text())
    assert state["ProudTuring:21"]["last_result"] == "head_no_pane"
    assert "ProudTuring absent" not in p.stdout
    assert not any(c[0] in ("has-session", "capture-pane") for c in calls)

"""Execute watcher submission helpers with isolated terminal state and lost CR."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'hooks/watch_agent_mail_signals.sh').read_text()
HELPERS = SOURCE[SOURCE.index('notification_is_in_input()'):SOURCE.index('# deliver_worker: 1 signal')]
MARKER = 'mail notification: message_id=20597;'
PROMPT = 'AgentStack ' + MARKER + ' fixture'


def test_composer_detection_ignores_history_and_accepted_queue(tmp_path):
    script = tmp_path / 'detect.sh'
    script.write_text(HELPERS + '\nnotification_is_in_input "$1"\n')
    cases = [
        ('› ' + PROMPT + '\nfooter\n', 0),
        ('› ' + PROMPT + '\nWorked for 1s\n› Ask Codex to do anything\n', 1),
        ('• Messages to be submitted after next tool call\n  ↳ ' + PROMPT + '\n› Ask Codex to do anything\n', 1),
        ('› unrelated draft\nfooter\n', 1),
    ]
    for screen, expected in cases:
        run = subprocess.run(['/bin/bash', str(script), MARKER], input=screen, text=True, capture_output=True)
        assert run.returncode == expected, (screen, run.stderr)


def _run(tmp_path, mode):
    fake = tmp_path / 'tmux'
    fake.write_text('''#!/usr/bin/env python3
import json,os,pathlib,sys
root=pathlib.Path(os.environ['FIXTURE_ROOT']);state=root/'state.json';log=root/'calls.jsonl'
args=sys.argv[1:];s=json.loads(state.read_text()) if state.exists() else {'draft':'','accepted':0}
with log.open('a') as h:h.write(json.dumps(args)+'\\n')
if args[0]=='capture-pane':print('› '+(s['draft'] or 'Ask Codex to do anything')+'\\nfooter')
elif args[0]=='send-keys':
 if '-l' in args:s['draft']=args[-1]
 elif args[-1]=='Enter' and os.environ['FIXTURE_MODE']!='persistent':s['accepted']+=1;s['draft']=''
 # C-m deliberately reports success while retaining the draft.
state.write_text(json.dumps(s))
''')
    fake.chmod(0o755)
    script = tmp_path / 'run.sh'
    script.write_text('set -euo pipefail\nTMUX_TIMEOUT=2\n' + HELPERS + '''
run_to() { shift; "$@"; }
acquire_delivery_lease() { mkdir "$FIXTURE_ROOT/lease" 2>/dev/null; }
release_delivery_lease() { rmdir "${FIXTURE_ROOT:?}/lease"; }
inject_result=0
inject_notification fixture SandyLangmuir "$1" "$2" || inject_result=$?
printf '%s\\n' "$inject_result"
''')
    env = {**os.environ, 'FIXTURE_ROOT': str(tmp_path), 'FIXTURE_MODE': mode,
           'PATH': str(tmp_path) + os.pathsep + os.environ['PATH']}
    result = subprocess.run(['/bin/bash', str(script), MARKER, PROMPT], env=env, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    return int(result.stdout.strip()), json.loads((tmp_path / 'state.json').read_text()), [json.loads(s) for s in (tmp_path / 'calls.jsonl').read_text().splitlines()]


def test_visible_retained_draft_gets_one_confirmed_enter_retry(tmp_path):
    code, state, calls = _run(tmp_path, 'recover')
    assert code == 0 and state['accepted'] == 1 and state['draft'] == ''
    assert sum('-l' in c for c in calls) == 1
    assert sum(c[-1] == 'Enter' for c in calls) == 1
    assert not (tmp_path / 'lease').exists()


def test_persistent_draft_is_not_success_and_next_scan_does_not_append(tmp_path):
    code, state, calls = _run(tmp_path, 'persistent')
    assert code == 3 and state['accepted'] == 0
    code, state, calls = _run(tmp_path, 'persistent')
    assert code == 3 and state['accepted'] == 0
    assert sum('-l' in c for c in calls) == 1  # exact retained draft reused
    assert not (tmp_path / 'lease').exists()


def test_other_notification_in_composer_is_deferred(tmp_path):
    (tmp_path / 'state.json').write_text(json.dumps({'draft': 'AgentStack mail notification: message_id=21016; other', 'accepted': 0}))
    code, state, calls = _run(tmp_path, 'recover')
    assert code == 4 and state['accepted'] == 0
    assert all(c[0] != 'send-keys' for c in calls)

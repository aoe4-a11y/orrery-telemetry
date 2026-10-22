"""OPS-JOBEND-1: notify the owning seat when an observed heavy job disappears.

No pane input, process signals, mailbox reads, or SQLite access. The existing
five-minute seat watcher calls this census independently of its stall alerts.
"""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time

HOME = Path.home() / '.agentstack'
STATE = HOME / 'runtime/seat-jobend-state.json'
TMUX = '/opt/homebrew/bin/tmux'
PROJECT = '/Users/huyuhutaru/tools/examforge'
SHELLS = {'sh', 'bash', 'zsh', 'dash', 'ksh'}


def execute(argv, timeout=15):
    result = subprocess.run(argv, capture_output=True, text=True,
                            env=dict(os.environ, LC_ALL='C'), timeout=timeout)
    if result.returncode:
        raise RuntimeError('process census failed: ' + Path(argv[0]).name)
    return result.stdout


def parse_processes(output):
    rows = {}
    for line in output.splitlines():
        fields = line.strip().split(None, 8)
        if len(fields) != 9 or not fields[0].isdigit() or not fields[1].isdigit():
            raise ValueError('malformed process census')
        pid, parent = int(fields[0]), int(fields[1])
        started = ' '.join(fields[3:8])
        rows[pid] = dict(pid=pid, ppid=parent, tty=fields[2], started=started,
                         key=str(pid) + ':' + started, args=fields[8])
    if not rows:
        raise ValueError('empty process census')
    return rows


def process_snapshot():
    return parse_processes(execute(['ps', '-ww', '-axo', 'pid=,ppid=,tty=,lstart=,command=']))


def pane_snapshot():
    output = execute([TMUX, 'list-panes', '-a', '-F',
                      '#{session_name}|#{pane_pid}|#{pane_tty}'])
    panes = []
    for line in output.splitlines():
        seat, pid, tty = line.split('|')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', seat) or not pid.isdigit():
            continue
        panes.append(dict(seat=seat, pid=int(pid), tty=tty.removeprefix('/dev/')))
    return panes


def command_kind(args):
    # Read only the executable/script prefix, never a Codex/Claude prompt or
    # a shell -c body. A word in a prompt is not an executing heavy job.
    prefix = args.split(None, 1)[0] if args.strip() else ''
    first = Path(prefix).name
    if first not in SHELLS | {'xcodebuild', 'xcrun', 'heavy_job_lock.sh'}:
        return None
    try:
        lexer = shlex.shlex(args[:8192], posix=True)
        lexer.whitespace_split = True
        tokens = []
        for _ in range(16):
            token = lexer.get_token()
            if token is None:
                break
            tokens.append(token)
    except ValueError:
        return None
    if not tokens:
        return None
    index = 0
    if first in SHELLS:
        index = 1
        while index < len(tokens) and tokens[index].startswith('-'):
            option = tokens[index]
            if option != '--' and 'c' in option.lstrip('-'):
                return None
            index += 1
            if option == '--':
                break
        if index >= len(tokens) or Path(tokens[index]).name != 'heavy_job_lock.sh':
            return None
        first = 'heavy_job_lock.sh'
    elif first == 'xcrun':
        if len(tokens) < 2 or tokens[1] != 'xcodebuild':
            return None
        first, index = 'xcodebuild', 1
    if first == 'heavy_job_lock.sh':
        name = tokens[index + 1] if len(tokens) > index + 1 else 'unknown'
        # Labels, not raw command strings or arguments that could carry keys.
        label = re.sub(r'[^A-Za-z0-9_.:/+-]', '_', name)[:100]
        return dict(kind='heavy_job_lock', label=label,
                    excerpt='heavy_job_lock.sh ' + label)
    operation = next((t for t in tokens if t in
                      {'build', 'test', 'build-for-testing', 'test-without-building', 'archive'}), '')
    return dict(kind='xcodebuild', label='xcodebuild',
                excerpt=('xcodebuild ' + operation).strip())


def ancestor_seat(row, processes, panes):
    owners = {pane['pid']: pane['seat'] for pane in panes}
    pid, seen = row['pid'], set()
    while pid in processes and pid not in seen:
        if pid in owners:
            return owners[pid]
        seen.add(pid)
        pid = processes[pid]['ppid']
    # nohup children may retain the pane's terminal after reparenting.
    if row['tty'] not in {'??', '?', '-'}:
        matches = {p['seat'] for p in panes if p['tty'] == row['tty']}
        if len(matches) == 1:
            return matches.pop()
    return None


def discover_logs(pid):
    try:
        output = execute(['/usr/sbin/lsof', '-w', '-a', '-p', str(pid), '-d', '1,2', '-Fn'], 5)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return []
    found = []
    for line in output.splitlines():
        if line.startswith('n/'):
            p = Path(line[1:])
            if p.suffix.lower() in {'.log', '.txt', '.out'} and p.is_file():
                found.append(dict(path=str(p), offset=p.stat().st_size))
    return list({r['path']: r for r in found}.values())


def finished_exit(job):
    if job['kind'] != 'heavy_job_lock':
        return None
    pattern = re.compile(r'^traffic: \[' + re.escape(job['label']) +
                         r'\] done \(exit (-?\d+)\)\s*$')
    for item in job.get('logs', []):
        try:
            with open(item['path'], 'rb') as stream:
                size = os.fstat(stream.fileno()).st_size
                if size < item['offset']:
                    continue
                stream.seek(max(item['offset'], size - 16384))
                lines = stream.read(16384).decode('utf-8', errors='replace').splitlines()
            for line in reversed(lines):
                match = pattern.fullmatch(line)
                if match:
                    return int(match[1])
        except OSError:
            continue
    return None


def advance(state, processes, panes, now=None, log_finder=discover_logs):
    """Pure state transition except bounded FD metadata lookup for new jobs."""
    now = time.time() if now is None else now
    active = state.setdefault('active', {})
    events = state.setdefault('events', {})
    live = {row['key']: row for row in processes.values()}
    heavy = {row['pid']: (row, kind) for row in processes.values()
             if (kind := command_kind(row['args']))}
    claimed = set()
    # Keep the original owner/group even if a tracked job is reparented/setsid.
    for job in active.values():
        alive_members = {key for key in job['members'] if key in live}
        member_pids = {live[key]['pid'] for key in alive_members}
        for row, _ in heavy.values():
            parent, seen = row['ppid'], set()
            while parent in processes and parent not in seen:
                if parent in member_pids:
                    alive_members.add(row['key'])
                    break
                seen.add(parent)
                parent = processes[parent]['ppid']
        job['members'] = sorted(alive_members)
        claimed.update(alive_members)
    for row, kind in heavy.values():
        if row['key'] in claimed:
            continue
        # The outermost heavy wrapper represents one job, including xcodebuild.
        parent, seen, nested = row['ppid'], set(), False
        while parent in processes and parent not in seen:
            if parent in heavy:
                nested = True
                break
            seen.add(parent)
            parent = processes[parent]['ppid']
        if nested:
            continue
        seat = ancestor_seat(row, processes, panes)
        if not seat:
            continue
        ident = hashlib.sha256((seat + ':' + row['key']).encode()).hexdigest()[:24]
        if ident in events:
            continue
        members = {row['key']}
        for child, _ in heavy.values():
            parent, seen = child['ppid'], set()
            while parent in processes and parent not in seen:
                if parent == row['pid']:
                    members.add(child['key'])
                    break
                seen.add(parent)
                parent = processes[parent]['ppid']
        active[ident] = dict(id=ident, seat=seat, pid=row['pid'], started=row['started'],
                             first_seen=now, members=sorted(members),
                             logs=log_finder(row['pid']), **kind)
        claimed.update(members)
    ended = []
    for ident, job in list(active.items()):
        if job['members']:
            continue
        job.update(ended_observed=now, exit_code=finished_exit(job), status='pending')
        events[ident] = job
        del active[ident]
        ended.append(job)
    return ended


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        json.dump(state, stream, ensure_ascii=False, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
        temporary = stream.name
    os.replace(temporary, path)


def send_server(job):
    # launchd is outside the session-bound Codex proxy. The existing stack
    # helper retrieves the operations identity credential inside this process;
    # it is never printed, persisted in state, or included in exceptions.
    # launchd still invokes the legacy watcher with Apple's Python 3.9; the
    # installed canonical mail client requires Python >=3.10 (dataclass slots).
    if sys.version_info < (3, 10):
        result = subprocess.run(['/opt/homebrew/bin/python3', __file__, '--send-job'],
                                input=json.dumps(job), capture_output=True,
                                text=True, timeout=40)
        if result.returncode:
            raise RuntimeError('canonical mail client failed')
        return json.loads(result.stdout)
    sys.path.insert(0, str(HOME / 'integrations/codex_app/src'))
    from agentstack_codex_app.agent_mail_client import AgentMailClient, HttpJsonRpcTransport
    helper = HOME / 'bin/lib/agentstack-register.sh'
    result = subprocess.run(['/bin/bash', '-c', 'source "$1"; ags_load_registration_token "$2"',
                             'jobend', str(helper), 'KindPasteur'],
                            capture_output=True, text=True, timeout=10)
    if result.returncode or not result.stdout.strip():
        raise RuntimeError('operations identity credential unavailable')
    client = AgentMailClient(HttpJsonRpcTransport(
        os.environ.get('AGENTSTACK_MCP_URL', 'http://127.0.0.1:18765/mcp'),
        bearer_token=os.environ.get('MCP_AGENT_MAIL_TOKEN'), timeout=20))
    logs = '\n'.join('log: ' + item['path'] for item in job['logs']) or 'log: 未特定'
    exit_text = str(job['exit_code']) if job['exit_code'] is not None else '未測定'
    body = (f"OPS-JOBEND-1。席 {job['seat']} で観測した重い job の process が終了しました。\n"
            f"command 抜粋: `{job['excerpt']}`\nPID: {job['pid']} / job_id: {job['id']}\n"
            f"{logs}\nexit code: {exit_text}\n"
            "成否・試験件数は元log/結果を確認してください。自動採用は行いません。")
    response = client.send_message(project_key=PROJECT, agent_name='KindPasteur',
        registration_token=result.stdout.strip(), to=[job['seat']],
        subject=f"[station] job終了: {job['excerpt']} ({job['id']})", body_md=body)
    return response


def notify_pending(state, path, sender=send_server):
    for job in state.get('events', {}).values():
        if job['status'] != 'pending':
            continue
        # The server has no idempotency-key API. Persist the delivery attempt
        # BEFORE sending: a restart/lost response must never send a second mail.
        job['status'] = 'sending'
        save_state(path, state)
        try:
            response = sender(job)
            job['status'] = 'sent'
            job['delivery'] = response
        except Exception as error:
            job['status'] = 'delivery_uncertain'
            job['error_type'] = type(error).__name__
        save_state(path, state)


def sweep(state_path=STATE, dry_run=False, only_seat=None):
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(state_path) + '.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return []
        state = json.loads(state_path.read_text()) if state_path.exists() else dict(version=1)
        panes = pane_snapshot()
        if only_seat:
            panes = [p for p in panes if p['seat'] == only_seat]
        ended = advance(state, process_snapshot(), panes)
        if dry_run:
            for job in ended:
                print(json.dumps(dict(dry_run=True, seat=job['seat'], id=job['id'],
                                      command=job['excerpt']), ensure_ascii=False))
        else:
            save_state(state_path, state)
            notify_pending(state, state_path)
        return ended


if __name__ == '__main__':
    if sys.argv[1:] == ['--send-job']:
        try:
            print(json.dumps(send_server(json.load(sys.stdin))))
        except Exception as error:
            print(type(error).__name__, file=sys.stderr)
            sys.exit(1)
    else:
        sweep(dry_run=os.environ.get('SEAT_STALL_DRYRUN') == '1')

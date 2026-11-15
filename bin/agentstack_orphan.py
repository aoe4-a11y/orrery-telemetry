"""OPS-ORPHAN-1: advisory orphan CPU alerts, called by the existing 5min watcher.

No process signals, pane control, mailbox reads, or automatic cleanup. State
contains only PID/start/CPU, a redacted <=200 character command and matched path.
"""
import copy
import ctypes
import datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess
import time
from agentstack_jobend import save_state
from agentstack_stallself import send_server, sent_id

STATE = Path.home() / '.agentstack/runtime/seat-orphan-cpu-state.json'
HEAD = 'ProudTuring'
DURATION = 30 * 60
MAX_SAMPLE_GAP = 450  # A missed 5min cycle breaks continuity.


def cpu_seconds(value):
    days = 0
    if '-' in value:
        day, value = value.split('-', 1)
        days = int(day)
    parts = [float(x) for x in value.split(':')]
    if len(parts) not in (2, 3) or any(not math.isfinite(x) or x < 0 for x in parts):
        raise ValueError('invalid cumulative CPU time')
    # Explicit formats: Darwin MM:SS.xx; also HH:MM:SS and D-HH:MM:SS.
    return days * 86400 + sum(x * 60 ** i for i, x in enumerate(reversed(parts)))


def parse_processes(output):
    rows = {}
    for line in output.splitlines():
        parts = line.strip().split(None, 9)
        if len(parts) != 10:
            raise ValueError('malformed orphan process census')
        pid, parent = int(parts[0]), int(parts[1])
        cpu = float(parts[2])
        if pid <= 0 or parent < 0 or not math.isfinite(cpu) or cpu < 0:
            raise ValueError('invalid orphan process census')
        started = ' '.join(parts[3:8])
        rows[pid] = dict(pid=pid, ppid=parent, cpu_percent=cpu, started=started,
                         cpu_time=parts[8], cpu_seconds=cpu_seconds(parts[8]),
                         args=parts[9], key=str(pid) + ':' + started)
    if not rows:
        raise ValueError('empty orphan process census')
    return rows


def process_snapshot():
    result = subprocess.run(['ps', '-ww', '-axo', 'pid=,ppid=,pcpu=,lstart=,time=,args='],
                            capture_output=True, text=True, timeout=15,
                            env=dict(os.environ, LC_ALL='C'))
    if result.returncode:
        raise RuntimeError('orphan process census failed')
    return parse_processes(result.stdout)


def managed_path(value, directory=False):
    if not value or not os.path.isabs(value):
        return False
    parts = Path(os.path.normpath(value)).parts
    # Exact directory names or canonical timestamp-kind-id governor roots;
    # an arbitrary argument/string containing "scratch" is not a path match.
    for index, part in enumerate(parts if directory else parts[:-1]):
        if part in {'artifacts', 'evidence', 'source-worktree', 'scratch'}:
            return True
        if re.fullmatch(r'\d{8}T\d{6}Z-(?:evidence|source-worktree)(?:-[0-9a-f]+)?', part):
            return True
    return False


def codex_home_from_procargs(raw):
    """Read only the real NUL-delimited environment, ignoring argv lookalikes."""
    try:
        argc = struct.unpack_from('i', raw)[0]
        if not 0 <= argc <= 100000:
            return None
        offset = raw.index(b'\0', 4) + 1  # executable path
        while offset < len(raw) and raw[offset] == 0:
            offset += 1
        for _ in range(argc):
            offset = raw.index(b'\0', offset) + 1
        for field in raw[offset:].split(b'\0'):
            if field.startswith(b'CODEX_HOME='):
                return os.fsdecode(field[len(b'CODEX_HOME='):])
    except (ValueError, struct.error):
        return None
    return None


def executable_path(pid):
    try:
        lib = ctypes.CDLL('/usr/lib/libproc.dylib')
        call = lib.proc_pidpath
        call.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        call.restype = ctypes.c_int
        buffer = ctypes.create_string_buffer(4096)
        if call(pid, buffer, len(buffer)) > 0:
            return os.fsdecode(buffer.value)
    except (OSError, AttributeError):
        pass
    return None


def codex_home(pid):
    # Local SDK sys/sysctl.h: CTL_KERN=1, KERN_PROCARGS2=49.
    try:
        lib = ctypes.CDLL(None)
        call = lib.sysctl
        call.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_uint,
                         ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
                         ctypes.c_void_p, ctypes.c_size_t]
        call.restype = ctypes.c_int
        mib = (ctypes.c_int * 3)(1, 49, pid)
        size = ctypes.c_size_t()
        if call(mib, 3, None, ctypes.byref(size), None, 0) or not 0 < size.value <= 8 * 1024 * 1024:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if call(mib, 3, buffer, ctypes.byref(size), None, 0):
            return None
        return codex_home_from_procargs(buffer.raw[:size.value])
    except (OSError, AttributeError):
        return None


def matched_path(pid):
    exe = executable_path(pid)
    if managed_path(exe):
        return dict(kind='executable', path=exe)
    try:
        result = subprocess.run(['/usr/sbin/lsof', '-w', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'],
                                capture_output=True, text=True, timeout=3)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith('n') and managed_path(line[1:], directory=True):
                    return dict(kind='cwd', path=line[1:])
    except (OSError, subprocess.TimeoutExpired):
        pass
    home = codex_home(pid)
    if managed_path(home, directory=True):
        return dict(kind='CODEX_HOME', path=home)
    return None


def command_excerpt(args):
    # Preserve only safe pieces of the first200 characters. Prompt/shell bodies,
    # credentials and other positional content are never written to state/mail.
    raw = args[:200].replace('`', "'")
    try:
        tokens = shlex.split(raw)
    except ValueError:
        return (raw.split(None, 1)[0] + ' [arguments redacted]')[:200]
    if not tokens:
        return ''
    if Path(tokens[0]).name in {'sh', 'bash', 'zsh', 'dash', 'ksh'} and any(
            t.startswith('-') and 'c' in t.lstrip('-') for t in tokens[1:3]):
        return (tokens[0] + ' [shell body redacted]')[:200]
    out, redact_next = [tokens[0]], False
    for token in tokens[1:]:
        if redact_next:
            out.append('[redacted]');redact_next = False;continue
        if re.search(r'(?:token|password|secret|api.?key|prompt|input|message)', token, re.I) and token.startswith('-'):
            out.append(token.split('=', 1)[0] + ('=[redacted]' if '=' in token else ''))
            redact_next = '=' not in token
        elif token.startswith('-'):
            out.append(token.split('=', 1)[0] + ('=[redacted]' if '=' in token else ''))
        elif os.path.isabs(token) and not any(x in token for x in ['\n','\r',';','|','$','`']):
            out.append(token)
        elif token in {'app-server', 'daemon', 'server', 'run', 'exec'} or re.fullmatch(r'\d+(?:\.\d+)?', token):
            out.append(token)
        else:
            out.append('[redacted]')
    return ' '.join(out)[:200]


def advance(state, processes, now=None, path_finder=matched_path):
    now = time.time() if now is None else now
    previous = state.setdefault('candidates', {})
    events = state.setdefault('events', {})
    current, added = {}, []
    for row in processes.values():
        if row['ppid'] != 1 or row['cpu_percent'] <= 100 or row['key'] in events:
            continue
        path = path_finder(row['pid'])
        if not path:
            continue
        old = previous.get(row['key'])
        delta = now - old['last_seen'] if old else 0
        rate = 100 * (row['cpu_seconds'] - old['cpu_seconds']) / delta if old and delta > 0 else 0
        uninterrupted = (old and 0 < delta <= MAX_SAMPLE_GAP and rate > 100
                         and old['matched_path'] == path)
        since = old['since'] if uninterrupted else now
        sample = dict(pid=row['pid'], started=row['started'], ppid=1,
                      since=since, last_seen=now, cpu_seconds=row['cpu_seconds'],
                      cpu_time=row['cpu_time'], cpu_percent=row['cpu_percent'],
                      interval_cpu_percent=rate if uninterrupted else None,
                      observations=old['observations'] + 1 if uninterrupted else 1,
                      command=command_excerpt(row['args']), matched_path=path)
        if now - since >= DURATION:
            event = dict(sample, status='pending', detected_at=now,
                         observed_seconds=now-since,
                         id=hashlib.sha256(row['key'].encode()).hexdigest()[:24])
            events[row['key']] = event
            added.append(event)
        else:
            current[row['key']] = sample
    state.update(version=1, candidates=current, last_sweep=now)
    return added


def notice(event):
    return dict(seat=HEAD, subject='[station] orphan CPU検出: PID ' + str(event['pid']),
                body_md=("OPS-ORPHAN-1・M-022。親PID1・CPU100%超を5分周期で30分以上連続観測しました。停止の判断はheadです。\n"
                         f"PID: {event['pid']} / 開始時刻: {event['started']}\n"
                         f"累計CPU時間: {event['cpu_time']} / 現CPU: {event['cpu_percent']}%\n"
                         f"連続観測: {int(event['observed_seconds'])}秒 / {event['observations']}標本\n"
                         f"command先頭200字（内容/鍵はredact）: `{event['command']}`\n"
                         f"該当path ({event['matched_path']['kind']}): {event['matched_path']['path']}\n"
                         "検出は使用席の不存在を断定しません。PIDと開始時刻を再照合してから判断してください。"))


def notify_pending(state, state_path, sender=send_server):
    for event in state.get('events', {}).values():
        if event['status'] != 'pending':
            continue
        event['status'] = 'sending'
        save_state(state_path, state)  # durable at-most-once claim before transport
        try:
            ident = sent_id(sender(notice(event)))
            if ident is None:
                raise ValueError('canonical transport returned no message ID')
            event.update(status='sent', sent_message_id=ident)
        except Exception as error:
            event.update(status='delivery_uncertain', error_type=type(error).__name__)
        save_state(state_path, state)


def sweep(state_path=STATE, dry_run=False, snapshot=process_snapshot,
          path_finder=matched_path, now=None, sender=send_server):
    state_path = Path(state_path)
    if dry_run:
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        result = advance(copy.deepcopy(state), snapshot(), now, path_finder)
        return result  # no writes, lock creation, mail, or consuming a real claim
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(state_path) + '.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return []
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        result = advance(state, snapshot(), now, path_finder)
        save_state(state_path, state)
        notify_pending(state, state_path, sender)
        return result


if __name__ == '__main__':
    for event in sweep(dry_run=os.environ.get('SEAT_STALL_DRYRUN') == '1'):
        print(json.dumps(dict(pid=event['pid'], id=event['id'], status=event['status'])))

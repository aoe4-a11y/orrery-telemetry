#!/usr/bin/python3
"""Fleet-only, fail-closed seat watchdog. No mail transport and no restart operations."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

TMUX = '/opt/homebrew/bin/tmux'
PS = '/bin/ps'
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
SGR = re.compile(r'\x1b\[([0-9;]*)m')
MODAL = re.compile(r"can.t be shown|Trusted Access|Learn more|help\.openai\.com|Hooks need review|\[y/n\]|\(y/N\)|\bAllow\b|\bapprove\b|Do you want|[❯›]\s*\d+\.|esc to (?:cancel|go back)|enter to confirm|Would you like to|Yes, proceed", re.I)
FOOTER = re.compile(r'^\s*(?:GPT-|gpt-|⚠ \d+ warnings?\b)')
BAR = re.compile(r'^\s*[─━\-]{3,}\s*$')
QUEUE = '• Messages to be submitted after next tool call'
MIN_STABLE = 80
HUMAN_IDLE = 180
DRY_LIMIT = 65536
CLOCK_SOURCE = 'uptime-raw-v1'
CRITICAL_EVENTS = {'sent', 'send-failed', 'changed-before-send', 'error'}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def plain(value):
    return ANSI.sub('', value)


def dim_in_region(ansi, first, last):
    dim = False
    for i, line in enumerate(ansi.splitlines()):
        pos = 0
        for m in SGR.finditer(line):
            if first <= i < last and dim and line[pos:m.start()].strip():
                return True
            codes = (m.group(1) or '0').split(';')
            j = 0
            while j < len(codes):
                code = codes[j]
                if code in ('38','48','58') and j + 1 < len(codes):
                    if codes[j + 1] == '5': j += 3; continue
                    if codes[j + 1] == '2': j += 5; continue
                if code in ('', '0', '22'): dim = False
                elif code == '2': dim = True
                j += 1
            pos = m.end()
        if first <= i < last and dim and line[pos:].strip(): return True
    return False


def candidate(kind, pane, ansi):
    lines = pane.splitlines()
    if plain(ansi).splitlines() != lines: return None, 'capture-changed'
    if MODAL.search('\n'.join(lines[-16:])): return None, 'modal'
    for line in lines:
        if line.startswith(QUEUE): continue
        if re.search(r'Working \(|esc to interrupt', line): return None, 'working'
    marker = r'^›[ \u00a0]' if kind == 'codex' else r'^❯[ \u00a0]'
    prompts = [i for i, line in enumerate(lines) if re.match(marker, line)]
    if not prompts: return None, 'no-composer'
    start = prompts[-1]
    if kind == 'claude':
        ends = [i for i in range(start + 1, len(lines)) if BAR.fullmatch(lines[i])]
        if not ends or start == 0 or not BAR.fullmatch(lines[start - 1]):
            return None, 'no-claude-frame'
        end = ends[0]
        if not re.search(r'bypass permissions|auto mode on|accept edits', '\n'.join(lines[end + 1:])):
            return None, 'no-claude-footer'
        if any(line.strip() and not line.startswith((' ', '\t')) for line in lines[start + 1:end]):
            return None, 'unknown-continuation'
    else:
        ends = [i for i in range(start + 1, len(lines)) if FOOTER.match(lines[i])]
        if not ends: return None, 'no-codex-footer'
        end = ends[0]
    composer = '\n'.join([lines[start][2:]] + lines[start + 1:end])
    # 27144: only the exact Codex placeholder is an empty composer. Any
    # continuation text or changed character keeps the dim guard in force.
    placeholder = kind == 'codex' and composer.strip() == 'Ask Codex to do anything'
    if dim_in_region(ansi, start, end) and not placeholder: return None, 'dim-composer'
    if composer.strip() and not placeholder:
        if kind == 'codex' and composer.lstrip().startswith(('Ask Codex to do anything', 'Press up to edit queued messages', 'Try "')):
            return None, 'unknown-placeholder'
        return {'branch':kind + '-composer', 'composer':composer, 'payload':composer}, None
    if kind == 'claude': return None, 'empty-composer'
    # Only the anchored Codex UI block immediately above its latest composer.
    # A quoted phrase in transcript text, or any Claude phrase, cannot enter this path.
    headers = [i for i in range(max(0, start - 16), start) if lines[i].startswith(QUEUE)]
    if not headers: return None, 'empty-composer'
    q = headers[-1]
    block = lines[q:start]
    if not any(re.match(r'^\s+↳ ', line) for line in block[1:]): return None, 'no-queued-ui'
    if any(line.strip() and not line.startswith((' ', '\t')) for line in block[1:]):
        return None, 'no-queued-ui'
    return {'branch':'codex-queued', 'composer':composer, 'payload':'\n'.join(block)}, None


def process_kind(root, rows):
    if root not in rows: return None, [], 'process-unreadable'
    children = {}
    for pid, row in rows.items(): children.setdefault(row['ppid'], []).append(pid)
    todo = list(children.get(root, [])); seen = {root}; found = set(); evidence = []
    while todo:
        pid = todo.pop()
        if pid in seen: return None, evidence, 'process-unreadable'
        seen.add(pid)
        row = rows[pid]
        names = {os.path.basename(row['comm']), os.path.basename(row.get('argv0', ''))}
        kinds = {name.removesuffix('.exe') for name in names} & {'codex', 'claude'}
        found.update(kinds)
        if kinds: evidence.append({'pid':pid, 'kind':sorted(kinds)})
        todo.extend(children.get(pid, []))
    if not found: return None, evidence, 'process-none'
    if len(found) != 1: return None, evidence, 'process-ambiguous'
    return next(iter(found)), evidence, None


class Watchdog:
    def __init__(self):
        self.test = os.environ.get('UNSTICK_TEST_MODE') == '1'
        self.tmux = TMUX
        self.ps = PS
        if self.test:
            override = os.environ.get('TMUX_BIN', '')
            if not override or Path(override).resolve() == Path(TMUX).resolve():
                raise ValueError('test mode requires a fake TMUX_BIN')
            self.tmux = override
            self.ps = os.environ.get('UNSTICK_TEST_PS_BIN', PS)
        self.now = float(os.environ['UNSTICK_TEST_NOW']) if self.test and 'UNSTICK_TEST_NOW' in os.environ else time.time()
        self.live = os.environ.get('UNSTICK_LIVE') == '1' and not os.environ.get('UNSTICK_DRY_RUN')
        self.runtime = Path.home() / '.agentstack/runtime'
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.state = Path(os.environ.get('UNSTICK_STATE_DIR', str(self.runtime / 'unstick-state-v2'))) / ('live' if self.live else 'dry')
        self.state.mkdir(parents=True, exist_ok=True)
        self.log = Path(os.environ.get('UNSTICK_LOG_PATH', str(self.runtime / ('unstick-seats.log' if self.live else 'unstick-seats.dry-run.log'))))
        self.diagnostics = self.runtime / 'unstick-seats.live-diagnostics.log'
        self.err = Path(os.environ.get('UNSTICK_ERR_PATH', str(self.runtime / 'unstick-seats.err')))
        self.roster = Path(os.environ.get('UNSTICK_ROSTER_PATH', str(self.runtime / 'unstick-roster.json')))
        self.run_id = str(os.getpid()) + '-' + str(time.time_ns())

    def clock(self):
        return self.now if self.test else time.time()

    def monotonic(self):
        if self.test and 'UNSTICK_TEST_MONO' in os.environ: return float(os.environ['UNSTICK_TEST_MONO'])
        if self.test and 'UNSTICK_TEST_NOW' in os.environ: return self.now
        # macOS Python 3.9 monotonic() has a process-local origin.
        return time.clock_gettime(time.CLOCK_UPTIME_RAW)

    def record(self, event, **fields):
        data = {'time':self.now, 'run_id':self.run_id, 'mode':'live' if self.live else 'dry-run', 'event':event, **fields}
        line = json.dumps(data, ensure_ascii=False, sort_keys=True) + '\n'
        permanent = self.live and event in CRITICAL_EVENTS
        target = self.log if permanent or not self.live else self.diagnostics
        target.parent.mkdir(parents=True, exist_ok=True)
        if not permanent and target.exists() and target.stat().st_size + len(line.encode()) > DRY_LIMIT:
            os.replace(target, target.with_name(target.name + '.previous'))
        with target.open('a') as f: f.write(line)

    def error(self, message):
        self.err.parent.mkdir(parents=True, exist_ok=True)
        with self.err.open('a') as f: f.write(json.dumps({'time':self.now,'run_id':self.run_id,'level':'ERROR','message':message}) + '\n')
        self.record('error', message=message)

    def command(self, args):
        return subprocess.run(args, capture_output=True, text=True, timeout=15)

    def roster_names(self):
        data = json.loads(self.roster.read_text())
        if data.get('project_id') != 1 or data.get('project_key') != '/Users/huyuhutaru/tools/examforge':
            raise ValueError('roster project mismatch')
        names = data['agents']
        if not isinstance(names, list) or not names: raise ValueError('roster is empty')
        if any(not isinstance(x, str) or not x or any(c in x for c in '\n\r\x00:/') for x in names):
            raise ValueError('invalid roster name')
        return set(names)

    def processes(self):
        result = self.command([self.ps, '-axo', 'pid=,ppid=,comm='])
        if result.returncode: raise ValueError('cannot read process tree')
        rows = {}
        for line in result.stdout.splitlines():
            items = line.strip().split(None, 2)
            if len(items) != 3: raise ValueError('unparseable process row')
            rows[int(items[0])] = {'ppid':int(items[1]), 'comm':items[2]}
        # comm is an actual executable name/path; argv[0] is an independent fallback.
        args = self.command([self.ps, '-axo', 'pid=,args='])
        if args.returncode: raise ValueError('cannot read process argv[0]')
        for line in args.stdout.splitlines():
            items = line.strip().split(None, 1)
            if not items: continue
            pid = int(items[0])
            if pid not in rows or len(items) != 2: continue
            try: rows[pid]['argv0'] = shlex.split(items[1])[0]
            except (ValueError, IndexError): pass
        return rows

    def meta(self, name):
        target = '=' + name + ':'
        result = self.command([self.tmux,'display-message','-p','-t',target,'#{session_name}|#{pane_id}|#{pane_pid}|#{session_attached}'])
        if result.returncode: raise ValueError('cannot read pane metadata')
        actual, pane_id, pid, attached = result.stdout.strip().split('|')
        if actual != name or not re.fullmatch(r'%\d+', pane_id): raise ValueError('pane target mismatch')
        return {'session':name,'target':target,'pane_id':pane_id,'pane_pid':int(pid),'attached':int(attached)}

    def human_active(self, meta):
        result = self.command([self.tmux,'list-clients','-t',meta['target'],'-F','#{session_name}|#{client_activity}'])
        if result.returncode: return True
        clients = []
        for line in result.stdout.splitlines():
            parts = line.split('|')
            if len(parts) != 2 or parts[0] != meta['session']: return True
            try: clients.append(float(parts[1]))
            except ValueError: return True
        if meta['attached'] and not clients: return True
        return any(self.now - value <= HUMAN_IDLE for value in clients)

    def capture(self, target):
        normal = self.command([self.tmux,'capture-pane','-p','-t',target])
        colored = self.command([self.tmux,'capture-pane','-p','-e','-t',target])
        if normal.returncode or colored.returncode: raise ValueError('capture failed')
        return normal.stdout, colored.stdout

    def inspect(self, name, processes):
        self.now = self.clock()
        meta = self.meta(name)
        kind, evidence, failure = process_kind(meta['pane_pid'], processes)
        detail = {'kind':kind,'descendants':evidence,'pane_id':meta['pane_id']}
        if failure: return None, failure, detail
        if self.human_active(meta): return None, 'human-active', detail
        pane, ansi = self.capture(meta['target'])
        item, failure = candidate(kind, pane, ansi)
        if failure: return None, failure, detail
        item.update(meta)
        item['kind'] = kind
        item['composer_sha256'] = digest(item.pop('composer'))
        item['pane_tail_sha256'] = digest('\n'.join(pane.splitlines()[-12:]))
        item['payload_sha256'] = digest(item.pop('payload'))
        item['fingerprint'] = digest(json.dumps(item, sort_keys=True))
        return item, None, detail

    def run_locked(self):
        names = self.roster_names()
        sessions = self.command([self.tmux,'list-sessions','-F','#{session_name}'])
        flag = self.runtime / 'unstick-no-server.state'
        if sessions.returncode:
            for name in names:
                stale = self.state / (digest(name) + '.json')
                if stale.exists(): stale.unlink()
            if re.search(r'no server running|[Nn]o such file or directory|[Cc]onnection refused', sessions.stderr):
                if not flag.exists():
                    self.record('info', reason='no-tmux-server')
                    flag.write_text('no server\n')
                return 0
            self.error('tmux list-sessions failed: ' + sessions.stderr.strip());return 1
        if flag.exists(): flag.unlink()
        try: processes = self.processes()
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            counts = {}
            for name in sessions.stdout.splitlines():
                branch = 'process-unreadable' if name in names else 'not-rostered'
                if name in names:
                    stale = self.state / (digest(name) + '.json')
                    if stale.exists(): stale.unlink()
                self.record('session',session=name,branch=branch)
                counts[branch] = counts.get(branch,0) + 1
            self.record('scan',branches=counts);return 0
        totals = {}
        for name in sessions.stdout.splitlines():
            if name not in names:
                self.record('session',session=name,branch='not-rostered');totals['not-rostered']=totals.get('not-rostered',0)+1;continue
            file = self.state / (digest(name) + '.json')
            try:
                item, failure, details = self.inspect(name, processes)
                if failure:
                    if file.exists(): file.unlink()
                    self.record('session',session=name,branch=failure,**details)
                    totals[failure]=totals.get(failure,0)+1;continue
                self.now = self.clock()
                previous = json.loads(file.read_text()) if file.exists() else {}
                first = previous.get('first_seen')
                first_mono = previous.get('first_seen_mono')
                tick = self.monotonic()
                if previous.get('clock_source') != CLOCK_SOURCE or previous.get('fingerprint') != item['fingerprint'] or not isinstance(first,(int,float)) or not isinstance(first_mono,(int,float)) or first > self.now or first_mono > tick:
                    file.write_text(json.dumps({'clock_source':CLOCK_SOURCE,'fingerprint':item['fingerprint'],'first_seen':self.now,'first_seen_mono':tick})+'\n')
                    decision='first-seen'
                elif self.now - first < MIN_STABLE or tick - first_mono < MIN_STABLE:
                    decision='too-soon'
                else:
                    fresh, reason, _ = self.inspect(name, self.processes())
                    if reason or fresh['fingerprint'] != item['fingerprint']:
                        if file.exists(): file.unlink()
                        decision='changed-before-send'
                        self.record('changed-before-send', session=name, branch=item['branch'], reason=reason or 'fingerprint-changed', composer_sha256=item['composer_sha256'], pane_tail_sha256=item['pane_tail_sha256'])
                    else:
                        audit={k:item[k] for k in ['branch','kind','target','pane_id','composer_sha256','pane_tail_sha256','fingerprint']}
                        if self.live:
                            pressed=self.command([self.tmux,'send-keys','-t',item['target'],'C-m' if item['kind']=='codex' else 'Enter'])
                            if pressed.returncode:
                                self.record('send-failed',session=name,**audit)
                                self.error('send-keys failed for '+name);decision='send-failed'
                            else:
                                self.record('sent',session=name,**audit);decision='sent'
                        else:
                            self.record('would-send-keys',session=name,**audit);decision='would-send-keys'
                        if file.exists(): file.unlink()
                self.record('session',session=name,branch=decision,candidate_branch=item['branch'],**details)
                totals[decision]=totals.get(decision,0)+1
            except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
                if file.exists(): file.unlink()
                self.record('session',session=name,branch='unreadable',detail=type(exc).__name__)
                totals['unreadable']=totals.get('unreadable',0)+1
        self.record('scan',branches=totals)
        return 0

    def run(self):
        lock_path = self.runtime / 'unstick-seats.lock'
        with lock_path.open('a') as lock:
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print(json.dumps({'event':'lock-busy','mode':'live' if self.live else 'dry-run'}));return 0
            try: return self.run_locked()
            except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
                # A failed roster/global read breaks the observation sequence too.
                # Only this watchdog's hash-named stability entries are removed.
                for stale in self.state.iterdir():
                    if re.fullmatch(r'[0-9a-f]{64}\.json', stale.name): stale.unlink()
                self.error(type(exc).__name__ + ': ' + str(exc));return 1
            finally: fcntl.flock(lock, fcntl.LOCK_UN)


def main():
    try: return Watchdog().run()
    except (ValueError,OSError) as exc:
        print('unstick configuration error: '+str(exc),file=sys.stderr);return 1

if __name__ == '__main__':
    raise SystemExit(main())

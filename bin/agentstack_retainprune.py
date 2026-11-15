"""M-071 / OPS-RETAIN-PRUNE-1: existing watcher, missing entries only.

The governor remains authoritative. No file contents/root cleanup or daemon.
Final file SHA is in an external audit because embedding it is self-referential.
"""
import copy
import ctypes
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from agentstack_jobend import save_state
from agentstack_stallself import send_server, sent_id

RELEASE = Path.home() / '.local/lib/dev-storage-governor/releases/3035a06f5e57b5bf33bf166bebb4f5a146a3f224/src'
POLICY = Path.home() / 'Library/Application Support/DevStorageGovernor/policy.json'
MANIFEST = Path.home() / '.dev-storage-governor/examforge/20261019T144903Z-records-299842f7/current-retention.json'
STATE = Path.home() / '.agentstack/runtime/retain-prune-state.json'
FIELDS = ('protected_paths', 'current_builds', 'current_inputs', 'distributed_archives')
MEMORY_LIMIT = 512 * 1024**2
REFERENCE_LIMIT = 64 * 1024**2
PREFIX_LIMIT = 100000


class SweepBudgetExceeded(ValueError):
    def __init__(self, resource, observed, limit):
        self.resource, self.observed, self.limit = resource, observed, limit
        super().__init__('%s budget exceeded: %s > %s' % (resource, observed, limit))


def physical_footprint(pid):
    # Darwin rusage_info_v2: uuid[16], then seven uint64 fields before footprint.
    # Fail closed on a failed sample; RSS misses compressed physical memory.
    lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    buf = ctypes.create_string_buffer(1024)
    if lib.proc_pid_rusage(pid, 2, ctypes.byref(buf)):
        raise OSError(ctypes.get_errno(), 'retain-prune footprint unavailable')
    return ctypes.c_uint64.from_buffer(buf, 72).value


def guarded_run(args, timeout=600):
    """Bound the worker, including imports/parsers/fixture checks, on every Python.

    Only this Popen child's PID receives signals. Files are anonymous scratch;
    no live policy/manifest/state is touched by the monitor.
    """
    started = time.monotonic()
    peak = 0
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        child = subprocess.Popen(args, stdout=out, stderr=err)
        try:
            while child.poll() is None:
                try:
                    used = physical_footprint(child.pid)
                except OSError:
                    if child.poll() is None:
                        raise
                    break
                peak = max(peak, used)
                if used > MEMORY_LIMIT:
                    child.send_signal(signal.SIGUSR1)  # faulthandler, no locals/content
                    time.sleep(.05)
                    raise SweepBudgetExceeded('physical_footprint_bytes', used, MEMORY_LIMIT)
                if os.fstat(out.fileno()).st_size + os.fstat(err.fileno()).st_size > 1024**2:
                    raise SweepBudgetExceeded('worker_output_bytes',
                        os.fstat(out.fileno()).st_size + os.fstat(err.fileno()).st_size, 1024**2)
                if time.monotonic() - started > timeout:
                    raise subprocess.TimeoutExpired(args, timeout)
                time.sleep(.02)
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()
            if sys.exc_info()[0] is not None:
                # launchd's existing stderr log retains the bounded stack, with
                # no argv, input values or frame locals. No new logging daemon.
                err.seek(0)
                diagnostic = err.read(65536).decode('utf-8', errors='replace')
                if diagnostic:
                    print(diagnostic, file=sys.stderr, flush=True)
        out.seek(0)
        result = SimpleNamespace(returncode=child.returncode,
                                 stdout=out.read(1024**2).decode('utf-8'),
                                 peak_footprint_bytes=peak)
        return result


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_regular(path):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW), 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('reference must be a regular file')
        if info.st_size > REFERENCE_LIMIT:
            raise SweepBudgetExceeded('reference_bytes', info.st_size, REFERENCE_LIMIT)
        # read(limit) preallocates limit bytes even for tiny regular files.
        # Size + 1 detects growth without reserving the entire budget each time.
        data = stream.read(info.st_size + 1)
        after = os.fstat(stream.fileno())
        if len(data) != info.st_size or (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('reference changed during read')
        return data


def validator(policy):
    if str(RELEASE) not in sys.path:
        sys.path.insert(0, str(RELEASE))
    from dev_storage_governor import storage_v6 as v6

    class StreamingProcessPaths(set):
        """Keep actual targets/argv, never the quadratic set of failed prefixes.

        A prefix at or beyond PATH_MAX cannot be used by stat on this filesystem.
        Longer prefixes from that same start are equally impossible: stop there,
        retaining the full argv for the governor's conservative overlap matching.
        No directory is entered and no file contents are read by this census.
        """
        def __init__(self, arguments):
            import re
            self.arguments = tuple(v6.permission_filtered_argv(arg) for arg in arguments)
            argv_bytes = sum(len(os.fsencode(arg)) for arg in self.arguments)
            if argv_bytes > 2 * 1024**2:
                raise SweepBudgetExceeded('process_argv_bytes', argv_bytes, 2 * 1024**2)
            super().__init__(p for arg in self.arguments for p in v6.absolute_paths(arg))
            path_max = os.pathconf('/', 'PC_PATH_MAX')
            if path_max <= 0:
                raise ValueError('filesystem path limit unavailable')
            checked = 0
            for arg in self.arguments:
                for start in re.finditer(r'(?:^|(?<=[\s=]))/', arg):
                    tail = arg[start.start():]
                    for end in re.finditer(r'''$|[\s'";|&()]''', tail):
                        # Character bound first, then filesystem byte bound.
                        if end.start() >= path_max:
                            break
                        raw = tail[:end.start()]
                        if len(os.fsencode(raw)) >= path_max:
                            break
                        checked += 1
                        if checked > PREFIX_LIMIT:
                            raise SweepBudgetExceeded('process_prefixes', checked, PREFIX_LIMIT)
                        candidate = Path(raw)
                        if candidate.is_file() or candidate.is_dir():
                            self.add(candidate)

    original_paths, original_read = v6.ProcessPaths, v6.r.record_bytes
    consumed = 0
    def bounded_read(path):
        nonlocal consumed
        data = read_regular(path)
        consumed += len(data)
        if consumed > 256 * 1024**2:
            raise SweepBudgetExceeded('validation_reference_bytes', consumed, 256 * 1024**2)
        return data
    # This is an adapter in the sweep only; the immutable governor release stays
    # byte-identical. Restore globals even when validation fails.
    try:
        v6.ProcessPaths, v6.r.record_bytes = StreamingProcessPaths, bounded_read
        return v6.CurrentProtection(policy)
    finally:
        v6.ProcessPaths, v6.r.record_bytes = original_paths, original_read


def budget_event(error, before):
    return dict(kind='unknown', scope='sweep_budget', before_sha256='sweep-budget:' + before,
                manifest_sha256=before, error_type=type(error).__name__, error=str(error),
                resource=error.resource, observed=error.observed, limit=error.limit,
                retry='next_cycle')


def validate_shape(value):
    if not isinstance(value, dict) or value.get('version') != 1 or value.get('complete') is not True:
        raise ValueError('incomplete current manifest')
    for field in FIELDS:
        rows = value.get(field)
        if not isinstance(rows, list) or any(not isinstance(p, str) or not Path(p).is_absolute() for p in rows):
            raise ValueError('invalid current manifest field: ' + field)
    scope = value.get('scope', {})
    if not isinstance(scope, dict) or not isinstance(scope.get('pruned_missing', []), list):
        raise ValueError('invalid scope.pruned_missing')


def missing_entries(value, mounted=os.path.ismount):
    missing = []
    for field in FIELDS:
        for raw in value[field]:
            path = Path(raw)
            # An unavailable volume is never evidence that its contents ended.
            for location in (path, path.resolve()):
                if len(location.parts) > 2 and location.parts[1] == 'Volumes':
                    if not mounted(Path('/Volumes') / location.parts[2]):
                        raise OSError(errno.ENODEV, 'volume unavailable', str(location))
            try:
                path.lstat()
            except FileNotFoundError:
                # resolve catches inaccessible/symlink-loop components; only ENOENT
                # qualifies. An existing dangling symlink is deliberately retained.
                try:
                    path.resolve(strict=True)
                except FileNotFoundError:
                    missing.append((field, raw))
                else:
                    raise ValueError('path appeared during missing check')
            else:
                path.resolve(strict=True)
    return missing


def notice(event):
    if event.get('scope') == 'sweep_budget':
        subject = '[blocked] RETAIN-SWEEP-MEM-1 sweep budget exceeded'
        body = ('R-183/P1/P30。sweepを止め、結果はunknownです。\n'
                'resource: ' + event['resource'] + '\nobserved: ' + str(event['observed']) +
                '\nlimit: ' + str(event['limit']) + '\nmanifest SHA256: ' + event['manifest_sha256'])
    elif event.get('scope') == 'handoff_timeout':
        subject = '[blocked] M-071 retention確認が同じSHAで3周期時間切れ'
        body = ('M-071/35206。確認結果はunknownで、次の周期に再試行します。\n'
                'manifest読取不能とは判定していません。置換していません。\n'
                'manifest SHA256: ' + str(event['manifest_sha256']) +
                '\nconsecutive timeouts: ' + str(event['consecutive_timeouts']) +
                '\nhandoff timeout seconds: 600')
    elif event['kind'] == 'fixture_held':
        subject = '[blocked] M-071 fixture-roles に held・自動復元なし'
        body = ('M-071/35054。fixture-rolesのheldを検出しました。復元/変更はしていません。\n'
                'held records: ' + str(event['count']) + '\nindex: ' + event['index'] +
                '\nindex SHA256: ' + event['index_sha256'] + '\ncomponents（最大10件）:\n' +
                '\n'.join(row['path'] + ' expected_sha256=' + str(row['expected_sha256'])
                          for row in event['components']))
    elif event['kind'] == 'pruned':
        subject = '[station] M-071 current-retention の欠落pathを除外'
        body = ('M-071/R-095。無いpathだけを除外しCurrentProtectionで再検証しました。\n'
                'count: ' + str(event['count']) + '\nbefore SHA256: ' + event['before_sha256'] +
                '\nafter SHA256: ' + event['after_sha256'] + '\naudit: ' + event['audit'])
    elif event.get('scope') == 'fixture_roles':
        subject = '[blocked] M-071 fixture-roles 読取不可・変更なし'
        body = ('M-071/35054。index/fixtureを変更していません。\nexception: ' +
                event['error_type'] + '\n' + event['error'][:300])
    else:
        subject = '[blocked] M-071 current-retention 読取不可・置換なし'
        body = ('M-071/M-022。manifestを置換していません。\nSHA256: ' + event['before_sha256'] +
                '\nexception: ' + event['error_type'] + '\n' + event['error'][:300])
    return dict(seat='ProudTuring', subject=subject, body_md=body)


def emit(state, state_path, event, sender):
    key = event['before_sha256']
    if key in state.get('events', {}):
        return
    event['status'] = 'sending'
    state.setdefault('events', {})[key] = event
    save_state(state_path, state)  # at most once, including uncertain transport
    try:
        ident = sent_id(sender(notice(event)))
        if ident is None:
            raise ValueError('canonical transport returned no message ID')
        event.update(status='sent', message_id=ident)
    except Exception as error:
        event.update(status='delivery_uncertain', delivery_error=type(error).__name__)
    save_state(state_path, state)


def check_once(policy_path, manifest_path, state_path, dry_run=False,
               validate=validator, sender=send_server, mounted=os.path.ismount):
    manifest_path, state_path, policy_path = map(Path, (manifest_path, state_path, policy_path))
    state = json.loads(read_regular(state_path)) if state_path.exists() else {}
    raw, before = None, 'unreadable'
    temp_path = None
    try:
        raw = read_regular(manifest_path)
        before = sha(raw)
        policy_raw = read_regular(policy_path)
        policy = json.loads(policy_raw)
        if policy.get('retention_current_manifest') != str(manifest_path):
            raise ValueError('policy points at a different manifest; no implicit authority')
        try:
            validate(policy)
        except FileNotFoundError as initial:
            value = json.loads(raw)
            validate_shape(value)
            missing = missing_entries(value, mounted)
            # Must be an actual missing explicit entry, not an unrelated scanner
            # or recursively referenced config failure.
            if not missing or not initial.filename or not any(
                    Path(p).is_relative_to(Path(initial.filename)) for _, p in missing):
                raise
        else:
            return dict(kind='healthy', before_sha256=before)
        if dry_run:
            return dict(kind='would_validate_prune', before_sha256=before, count=len(missing))
        updated = copy.deepcopy(value)
        for field, path in missing:
            updated[field] = [p for p in updated[field] if p != path]
        audit_path = manifest_path.with_name(manifest_path.name + '.prune-' + before + '.json')
        updated.setdefault('scope', {}).setdefault('pruned_missing', []).append(dict(
            before_sha256=before, reason='explicit path absent (ENOENT)',
            paths=[dict(field=f, path=p) for f, p in missing],
            after_sha256_record=str(audit_path)))
        new_raw = (json.dumps(updated, ensure_ascii=False, indent=2) + '\n').encode()
        with tempfile.NamedTemporaryFile(dir=manifest_path.parent, prefix='.retain-prune-', delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(new_raw)
            os.fchmod(stream.fileno(), stat.S_IMODE(manifest_path.stat().st_mode))
            stream.flush()
            os.fsync(stream.fileno())
        checked_policy = dict(policy, retention_current_manifest=str(temp_path))
        protection = validate(checked_policy)
        if missing_entries(value, mounted) != missing:
            raise ValueError('path existence changed; retry on next cycle')
        # Config identity and policy/manifest byte checks reject observed writer
        # drift. An uncooperative writer in the final check/rename interval is
        # outside flock semantics; all cooperating sweeps share the sibling lock.
        for path, digest in protection.sources.items():
            if sha(read_regular(Path(path))) != digest:
                raise ValueError('current input changed during validation')
        if read_regular(policy_path) != policy_raw or read_regular(manifest_path) != raw:
            raise ValueError('policy/manifest changed during validation')
        backup = manifest_path.with_name(manifest_path.name + '.bak-' + before[:8])
        if backup.exists():
            if read_regular(backup) != raw:
                raise ValueError('backup collision')
        else:
            with backup.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        event = dict(kind='pruned', count=len(missing), before_sha256=before,
                     after_sha256=sha(new_raw), audit=str(audit_path), backup=str(backup),
                     removed=[dict(field=f, path=p) for f, p in missing], created_at=time.time())
        # Persist prepared proof first. Crash recovery can inspect actual hashes.
        save_state(audit_path, dict(event, phase='prepared'))
        if read_regular(manifest_path) != raw or read_regular(policy_path) != policy_raw:
            raise ValueError('manifest/policy changed before replace')
        if missing_entries(value, mounted) != missing:
            raise ValueError('missing path appeared before replace')
        os.replace(temp_path, manifest_path)
        temp_path = None
        save_state(audit_path, dict(event, phase='applied'))
        emit(state, state_path, event, sender)
        return event
    except Exception as error:
        # Unreadable fingerprints include stat/error only; never credentials.
        if raw is None:
            before = 'unreadable-' + sha((str(manifest_path) + type(error).__name__ + str(error)).encode())
        event = (budget_event(error, before) if isinstance(error, SweepBudgetExceeded) else
                 dict(kind='error', before_sha256=before, error_type=type(error).__name__, error=str(error)[:300]))
        if not dry_run:
            emit(state, state_path, event, sender)
        return event
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)



def fixture_roles(index):
    if str(RELEASE) not in sys.path:
        sys.path.insert(0, str(RELEASE))
    from dev_storage_governor.fixture_roles import FixtureRoles
    return FixtureRoles.from_index(index)


def check_fixtures(policy_path, state_path, dry_run=False, sender=send_server,
                   load_roles=fixture_roles):
    """Advisory only. Never prune an index or restore any component."""
    state_path = Path(str(state_path) + '.fixture-roles.json')
    state = json.loads(read_regular(state_path)) if state_path.exists() else {}
    fingerprint = 'fixture-unreadable'
    try:
        policy = json.loads(read_regular(Path(policy_path)))
        index_path = policy.get('retention_evidence_index')
        if index_path is None:
            return dict(kind='not_configured')
        if not isinstance(index_path, str) or not Path(index_path).is_absolute():
            raise ValueError('absolute retention_evidence_index required')
        raw = read_regular(Path(index_path))
        index_sha = sha(raw)
        fingerprint = 'fixture-index-' + index_sha
        index = json.loads(raw)
        if (not isinstance(index, dict) or index.get('version') != 1
                or index.get('complete') is not True or not isinstance(index.get('sources'), list)):
            raise ValueError('incomplete deletion evidence index')
        roles = load_roles(index)
        if not roles.holds:
            return dict(kind='healthy', count=0, records=len(roles.records), index_sha256=index_sha)
        components = set()
        for row in roles.holds.values():
            for component in row['components']:
                components.add((component['path'], component['expected_sha256']))
        components = [dict(path=path, expected_sha256=expected) for path, expected in sorted(components)]
        # Index bytes alone do not change when a producer disappears. Include
        # the actual held set so this new failure is observable under that index.
        fingerprint = 'fixture-held-' + sha(json.dumps(dict(index_sha256=index_sha,
            holds=roles.holds), sort_keys=True, ensure_ascii=False).encode())
        event = dict(kind='fixture_held', before_sha256=fingerprint, index=index_path,
                     index_sha256=index_sha, count=len(roles.holds),
                     components=components[:10], total_components=len(components))
        if not dry_run:
            emit(state, state_path, event, sender)
        return event
    except Exception as error:
        event = dict(kind='error', scope='fixture_roles', before_sha256=fingerprint,
                     error_type=type(error).__name__, error=str(error)[:300])
        if not dry_run:
            emit(state, state_path, event, sender)
        return event


def combined_check(policy_path, manifest_path, state_path, dry_run=False, **kwargs):
    result = check_once(policy_path, manifest_path, state_path, dry_run, **kwargs)
    result['fixture_roles'] = check_fixtures(policy_path, state_path, dry_run,
                                           sender=kwargs.get('sender', send_server))
    return result



def manifest_sha(path):
    try:
        return sha(read_regular(Path(path)))
    except (OSError, ValueError):
        return None


def clear_timeout_streak(state_path):
    """Any completed/non-timeout handoff breaks the consecutive sequence."""
    path = Path(state_path)
    if not path.exists():
        return
    with open(str(path) + '.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        state = json.loads(read_regular(path))
        prior = state.get('handoff_timeout', {})
        if prior.get('consecutive', 0):
            prior['consecutive'] = 0
            state['handoff_timeout'] = prior
            save_state(path, state)


def timeout_unknown(manifest_path, state_path, started_sha, dry_run=False,
                    sender=send_server):
    path = Path(state_path)
    def record():
        state = json.loads(read_regular(path)) if path.exists() else {}
        current = manifest_sha(manifest_path)
        prior = state.get('handoff_timeout', {})
        # A changing/unreadable identity cannot prove 3 same-SHA timeouts.
        if current is None or current != started_sha:
            count = 0
        else:
            count = (prior.get('consecutive', 0) if prior.get('sha256') == current else 0) + 1
        event = dict(kind='unknown', scope='handoff_timeout', reason='TimeoutExpired',
                     retry='next_cycle', manifest_sha256=current,
                     consecutive_timeouts=count,
                     before_sha256='handoff-timeout:' + str(current))
        if not dry_run:
            state['handoff_timeout'] = dict(sha256=current, consecutive=count)
            save_state(path, state)
            if count >= 3:
                emit(state, path, event, sender)
        return event
    if dry_run:
        return record()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + '.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return dict(kind='unknown', scope='handoff_timeout', reason='state_lock_busy', retry='next_cycle')
        return record()


def sweep(policy_path=POLICY, manifest_path=MANIFEST, state_path=STATE, dry_run=False,
          _memory_worker=False, **kwargs):
    # launchd's Apple Python3.9 cannot import the governor. Preserve its existing
    # interpreter and run only this independent sweep with the installed Python.
    # The operational route ALWAYS uses a monitored worker, even on modern
    # Python. Injected validators/senders remain in-process for isolated tests.
    if sys.version_info < (3, 10) or (not _memory_worker and not kwargs):
        args = ['/opt/homebrew/bin/python3', __file__, '--sweep',
                '--memory-worker', '--policy', str(policy_path), '--manifest', str(manifest_path), '--state', str(state_path)]
        if dry_run:
            args.append('--dry-run')
        started_sha = manifest_sha(manifest_path)
        try:
            result = guarded_run(args, timeout=600)
            if result.returncode:
                raise RuntimeError('retain-prune interpreter handoff failed')
            outcome = json.loads(result.stdout)
            outcome['worker_peak_footprint_bytes'] = getattr(result, 'peak_footprint_bytes', None)
            if not dry_run:
                clear_timeout_streak(state_path)
            return outcome
        except SweepBudgetExceeded as error:
            event = budget_event(error, started_sha or 'unreadable')
            if not dry_run:
                path = Path(state_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(str(path) + '.lock', 'a') as lock:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        return dict(event, notification='state_lock_busy')
                    state = json.loads(read_regular(path)) if path.exists() else {}
                    emit(state, path, event, kwargs.get('sender', send_server))
            return event
        except subprocess.TimeoutExpired:
            return timeout_unknown(manifest_path, state_path, started_sha, dry_run,
                                   sender=kwargs.get('sender', send_server))
        except Exception as error:
            if not dry_run:
                clear_timeout_streak(state_path)
            # Keep notification semantics even if validation's interpreter dies.
            def failed_validation(_):
                raise RuntimeError('retain-prune handoff: ' + type(error).__name__)
            state_file = Path(state_path)
            if dry_run:
                return check_once(policy_path, manifest_path, state_path, True,
                                  validate=failed_validation)
            state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(str(state_file) + '.lock', 'a') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return dict(kind='lock_busy')
                return check_once(policy_path, manifest_path, state_path,
                                  validate=failed_validation,
                                  sender=kwargs.get('sender', send_server))
    if dry_run:
        return combined_check(policy_path, manifest_path, state_path, True, **kwargs)
    state_path, manifest_path = Path(state_path), Path(manifest_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    # Separate lock does not interfere with governor or running heavy jobs.
    with open(str(state_path) + '.lock', 'a') as lock, open(str(manifest_path) + '.prune.lock', 'a') as manifest_lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(manifest_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return dict(kind='lock_busy')
        return combined_check(policy_path, manifest_path, state_path, **kwargs)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--sweep', action='store_true')
    parser.add_argument('--memory-worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--policy', default=str(POLICY))
    parser.add_argument('--manifest', default=str(MANIFEST))
    parser.add_argument('--state', default=str(STATE))
    options = parser.parse_args()
    if options.memory_worker:
        import faulthandler
        faulthandler.register(signal.SIGUSR1, all_threads=True)
    print(json.dumps(sweep(options.policy, options.manifest, options.state,
                           dry_run=options.dry_run, _memory_worker=options.memory_worker), ensure_ascii=False))

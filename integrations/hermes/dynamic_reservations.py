"""Trusted reservation management through the existing plugin MCP connection."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import threading
import uuid

from mail_lifecycle import read, save
from mail_probe import granted_receipts, normalize_reservations
from reservation_guard import create_guard, _matches


def result_value(value):
    if not isinstance(value, dict) or value.get('ok') is False or value.get('error'):
        raise ValueError('Product reservation call failed')
    value = value.get('structuredContent', value.get('result', value))
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict) or value.get('error'):
        raise ValueError('Product reservation receipt missing')
    return value


class Reservations:
    def __init__(self, state, call):
        self.state, self.call = Path(state), call
        self.attempt, self.task = read(self.state / 'attempt.json'), read(self.state / 'task.json')
        self.root = Path(self.task['worktree']).resolve(strict=True)
        self.lock = threading.RLock()
        self.pending = {}

    @contextmanager
    def ledger(self):
        with self.lock, (self.state / 'reservation-ledger.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.state / 'reservation-ledger.json'
            row = read(path) if path.exists() else {'attempt_id': self.attempt['attempt_id'],
                'agent_name': self.attempt['agent_name'], 'source': 'product-bound-proxy',
                'receipts': [], 'released_ids': [], 'pending_calls': []}
            if (row.get('attempt_id') != self.attempt['attempt_id'] or row.get('agent_name') != self.attempt['agent_name']
                    or row.get('source') != 'product-bound-proxy'):
                raise ValueError('Reservation ledger binding mismatch')
            try:
                yield row
            finally:
                pending = path.with_suffix('.pending')
                save(pending, row)
                os.replace(pending, path)

    def target(self, args, *, write=True):
        supplied = args.get('path')
        if not isinstance(supplied, str) or not Path(supplied).is_absolute():
            raise ValueError('outside-worktree')
        target = Path(supplied).resolve()
        if not target.is_relative_to(self.root) or '.git' in target.relative_to(self.root).parts:
            raise ValueError('outside-worktree')
        relative = target.relative_to(self.root).as_posix()
        if write and self.task.get('scope_mode') == 'files' and not any(_matches(relative, p) for p in self.task['allowed_paths']):
            raise ValueError('outside-assignment-scope')
        return relative

    def acquire(self, args, call_id):
        relative = self.target(args)
        request_id = uuid.uuid4().hex
        with self.ledger() as row:
            row.setdefault('pending_calls', []).append(request_id)
        value = result_value(self.call('reserve_files', {'paths': [relative], 'exclusive': True,
            'ttl_seconds': 1800, 'reason': 'Managed Hermes file write'}))
        # Preserve every actual grant even if validation/conflict fails afterwards.
        granted = granted_receipts(value, [relative], self.attempt['agent_name'])
        with self.ledger() as row:
            by_id = {receipt['id']: receipt for receipt in row['receipts']}
            by_id.update({receipt['id']: receipt for receipt in granted})
            row['receipts'] = list(by_id.values())
            row['released_ids'] = [n for n in row['released_ids'] if n not in {r['id'] for r in granted}]
            row['pending_calls'].remove(request_id)
        receipts = normalize_reservations(value, [relative], self.attempt['agent_name'])
        scoped = {**self.task, 'allowed_paths': [relative], 'reservation_receipts': receipts,
                  'reservation_source': 'product-bound-proxy'}
        decision = create_guard(self.attempt, scoped, lambda _: None)('write_file', args)
        if decision:
            raise ValueError(decision['message'])
        with self.lock:
            self.pending[call_id] = [r['id'] for r in receipts]

    def release(self, call_id):
        with self.lock:
            ids = self.pending.pop(call_id, [])
        if not ids:
            return
        value = result_value(self.call('release_reservations', {'file_reservation_ids': ids}))
        if type(value.get('released')) is not int or value['released'] != len(ids):
            raise ValueError('Product release not confirmed')
        with self.ledger() as row:
            row['released_ids'] = sorted(set(row['released_ids']) | set(ids))


def inventory(state):
    """All known real grants, including partial boot grants and dynamic writes."""
    state = Path(state)
    attempt = read(state / 'attempt.json')
    task = read(state / 'task.json')
    if task.get('attempt_id') != attempt['attempt_id']:
        raise ValueError('Task reservation binding mismatch')
    rows = list(task.get('reservation_receipts', []))
    released = set()
    for name in ('reservations.json', 'reservation-ledger.json'):
        path = state / name
        if not path.exists():
            continue
        value = read(path)
        if (value.get('attempt_id') != attempt['attempt_id'] or value.get('agent_name') != attempt['agent_name']
                or value.get('source') != 'product-bound-proxy' or value.get('pending_calls')):
            raise ValueError('Unresolved reservation inventory')
        rows.extend(value.get('receipts', []))
        released.update(value.get('released_ids', []))
    for row in rows:
        if type(row.get('id')) is not int or row['id'] <= 0 or row.get('owner') != attempt['agent_name']:
            raise ValueError('Unbound reservation inventory')
    ids = {row['id'] for row in rows}
    if not released <= ids:
        raise ValueError('Release ledger has unknown IDs')
    return ids, released

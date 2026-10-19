"""Synchronous reservation gate with private profile memory and skills preserved."""
import hashlib
import os
from pathlib import Path

from mail_lifecycle import read, save, stamp
from mail_probe import mail_receipt
from reservation_guard import create_guard, require_guard
from task_evidence import append, event

MAIL_TOOL = 'mcp__orrery_mail__send_message'
PRIVATE_TOOLS = {'memory', 'skills_list', 'skill_view', 'skill_manage', 'session_search'}


def install(ctx, state):
    state = Path(state)
    config, attempt, task = [read(state / name) for name in ('run-config.json', 'attempt.json', 'task.json')]
    if task.get('interactive') is True:
        return install_interactive(ctx, state, config, attempt, task)
    profile = Path(config['profile_home']).resolve()
    if Path(os.environ.get('HERMES_HOME', '')).resolve() != profile or config['purpose'] != 'file-task':
        raise ValueError('Managed task profile mismatch')
    if task.get('reservation_source') != 'product-bound-proxy' or not task.get('reservation_receipts'):
        raise ValueError('Real reservation receipts required')
    expected_mail = read(state / 'message.json')
    seen_read = set()
    scope = lambda row: append(state, 'events.jsonl', row)
    file_guard = create_guard(attempt, task, scope)

    def deny(tool, reason):
        event(state, 'tool-denied', tool=tool, reason=reason)
        return {'action': 'block', 'message': reason}

    def before(tool_name, args, **_):
        try:
            if args.get('profile') not in (None, '', config['profile_name']):
                return deny(tool_name, 'outside-current-profile')
            if tool_name in ('read_file', 'write_file'):
                target = Path(args.get('path', '')).resolve()
                if Path(args.get('path', '')).is_absolute() and any(
                        target.is_relative_to(profile / name) for name in ('skills', 'memories')):
                    event(state, 'tool-allowed', tool=tool_name, private_profile=True)
                    return None
                return file_guard(tool_name, args)
            if tool_name in PRIVATE_TOOLS:
                if tool_name == 'session_search':
                    locator = args.get('session_id')
                    if (isinstance(locator, str) and '/' in locator
                            and locator.partition('/')[0] not in ('', config['profile_name'])):
                        return deny(tool_name, 'outside-current-profile')
                if tool_name in ('skill_view', 'skill_manage'):
                    for key in ('name', 'path', 'category'):
                        value = args.get(key)
                        if isinstance(value, str) and (Path(value).is_absolute() or '..' in Path(value).parts):
                            return deny(tool_name, 'outside-current-profile')
                return None
            if tool_name != MAIL_TOOL:
                return deny(tool_name, 'not-in-wire-tools')
            if args != expected_mail:
                return deny(tool_name, 'unexpected-mail-arguments')
            for spec in task['expected']:
                requested = Path(task['worktree']) / spec['path']
                target = requested.resolve()
                if (requested.is_symlink() or not target.is_relative_to(Path(task['worktree']).resolve()) or not target.is_file()
                        or (task.get('require_read_before_report', True) and str(target) not in seen_read)
                        or target.stat().st_mtime_ns < attempt['started_at_ns']):
                    return deny(tool_name, 'artifact-not-ready')
                data = target.read_bytes()
                valid = (hashlib.sha256(data).hexdigest() == spec['sha256'] if 'sha256' in spec
                         else isinstance(spec.get('contains'), str) and spec['contains'].encode() in data)
                if not valid:
                    return deny(tool_name, 'artifact-not-ready')
            save(state / 'report-intent.json', {'attempt_id': attempt['attempt_id'],
                 'agent_name': attempt['agent_name'], 'at': stamp()}, exclusive=True)
            event(state, 'tool-allowed', tool=tool_name)
            return None
        except Exception:
            return deny(tool_name, 'managed-guard-error')

    before.orrery_guard_attempt = attempt['attempt_id']
    before.orrery_guard_task = task['task_id']

    def after(tool_name, result, args=None, status=None, **_):
        args = args or {}
        if tool_name == 'read_file' and status == 'ok':
            seen_read.add(str(Path(args['path']).resolve()))
        if tool_name == 'write_file' and status == 'ok':
            target = Path(args['path']).resolve()
            if target.is_file() and target.is_relative_to(Path(task['worktree']).resolve()):
                event(state, 'artifact-written', path=target.relative_to(Path(task['worktree']).resolve()).as_posix(),
                      sha256=hashlib.sha256(target.read_bytes()).hexdigest())
        if tool_name == MAIL_TOOL:
            receipt = mail_receipt(result)
            if receipt:
                valid = (receipt['ok'] and receipt['from'] == attempt['agent_name']
                         and receipt['to'] in (task['report_to'], [task['report_to']]))
                save(state / 'mail-send-receipt.json', {**receipt, 'ok': bool(valid),
                     'attempt_id': attempt['attempt_id'], 'agent_name': attempt['agent_name'],
                     'source': 'product-bound-proxy', 'checked_at': stamp()}, exclusive=True)
                event(state, 'mail-sent', **{**receipt, 'ok': bool(valid)})

    ctx.register_hook('pre_tool_call', before)
    ctx.register_hook('post_tool_call', after)
    event(state, 'plugin-ready', tools=['read_file', 'write_file', MAIL_TOOL], runtime_phase=attempt['phase'], process_id=os.getpid())
    event(state, 'task-start')


def install_interactive(ctx, state, config, attempt, task):
    from dynamic_reservations import Reservations, result_value
    from mail_probe import granted_receipts
    from task_evidence import audit
    profile = Path(config['profile_home']).resolve()
    if Path(os.environ.get('HERMES_HOME', '')).resolve() != profile:
        raise ValueError('Managed current profile required')
    probe = read(state / 'mail-probe.json')
    names = probe.get('tools', [])
    if not names or not all(isinstance(name, str) and name.isidentifier() for name in names):
        raise ValueError('Authenticated product schema roster required')
    wire = {'mcp__orrery_mail__' + name for name in names}
    reservations = Reservations(state, lambda tool, args: ctx.call_mcp('orrery_mail', tool, args, timeout=20))

    def deny(tool, reason):
        event(state, 'tool-denied', tool=tool, reason=reason)
        return {'action': 'block', 'message': reason}

    def before(tool_name, args, tool_call_id=None, **_):
        try:
            if args.get('profile') not in (None, '', config['profile_name']):
                return deny(tool_name, 'outside-current-profile')
            if tool_name in ('read_file', 'write_file'):
                raw = args.get('path', '')
                target = Path(raw).resolve()
                if Path(raw).is_absolute() and any(target.is_relative_to(profile / name) for name in ('skills', 'memories')):
                    return None
                reservations.target(args, write=tool_name == 'write_file')
                if tool_name == 'write_file':
                    reservations.acquire(args, tool_call_id or str(target))
                return None
            if tool_name in PRIVATE_TOOLS:
                if tool_name == 'session_search':
                    locator = args.get('session_id')
                    if (isinstance(locator, str) and '/' in locator
                            and locator.partition('/')[0] not in ('', config['profile_name'])):
                        return deny(tool_name, 'outside-current-profile')
                for key in ('name', 'path', 'category'):
                    value = args.get(key)
                    if isinstance(value, str) and (Path(value).is_absolute() or '..' in Path(value).parts):
                        return deny(tool_name, 'outside-current-profile')
                return None
            if tool_name not in wire:
                return deny(tool_name, 'unsupported-managed-tool')
            if tool_name in ('mcp__orrery_mail__reserve_files', 'mcp__orrery_mail__renew_reservations'):
                if not tool_call_id:
                    return deny(tool_name, 'missing-native-call-id')
                with reservations.ledger() as ledger:
                    ledger.setdefault('pending_calls', []).append('model-' + tool_call_id)
            # Communication permission is the product proxy's policy. Formal
            # report_to is checked only by the task evaluator, not here.
            return None
        except ValueError as error:
            reason = str(error) if str(error) in ('outside-worktree', 'outside-assignment-scope') else 'reservation-unavailable'
            return deny(tool_name, reason)
        except Exception:
            return deny(tool_name, 'managed-guard-error')

    before.orrery_guard_attempt = attempt['attempt_id']
    before.orrery_guard_task = task['task_id']

    def after(tool_name, result, args=None, status=None, tool_call_id=None, **_):
        args = args or {}
        try:
            active = read(state / 'activity.json') if (state / 'activity.json').exists() else {}
            binding = {'task_id': active.get('task_id'), 'turn_id': active.get('turn_id')}
            if tool_name == 'write_file':
                target = Path(args.get('path', '')).resolve()
                reservations.release(tool_call_id or str(target))
                if status == 'ok' and target.is_file() and target.is_relative_to(reservations.root):
                    event(state, 'artifact-written', **binding,
                          path=target.relative_to(reservations.root).as_posix(), sha256=hashlib.sha256(target.read_bytes()).hexdigest())
            if tool_name == MAIL_TOOL:
                receipt = mail_receipt(result)
                if receipt:
                    event(state, 'mail-sent', **binding, **receipt)
            if tool_name == 'mcp__orrery_mail__reserve_files':
                value = result_value(result)
                grants = granted_receipts(value, args.get('paths', []), attempt['agent_name'])
                with reservations.ledger() as ledger:
                    rows = {r['id']: r for r in ledger['receipts']}
                    rows.update({r['id']: r for r in grants})
                    ledger['receipts'] = list(rows.values())
                    ledger['released_ids'] = [n for n in ledger['released_ids'] if n not in {r['id'] for r in grants}]
                    ledger['pending_calls'].remove('model-' + tool_call_id)
            if tool_name == 'mcp__orrery_mail__renew_reservations':
                value = result_value(result)
                with reservations.ledger() as ledger:
                    paths = [row['path_pattern'] for row in ledger['receipts']]
                    updated = [{**row, 'expires_ts': row.get('new_expires_ts')} for row in value.get('file_reservations', [])]
                    grants = granted_receipts({'granted': updated}, paths, attempt['agent_name'])
                    if type(value.get('renewed')) is not int or value['renewed'] != len(grants):
                        raise ValueError('Renewal not confirmed')
                    rows = {r['id']: r for r in ledger['receipts']}
                    if any(r['id'] not in rows for r in grants):
                        raise ValueError('Renewal includes unknown grant')
                    rows.update({r['id']: r for r in grants})
                    ledger['receipts'] = list(rows.values())
                    ledger['pending_calls'].remove('model-' + tool_call_id)
            if tool_name == 'mcp__orrery_mail__release_reservations':
                value = result_value(result)
                with reservations.ledger() as ledger:
                    ids = args.get('file_reservation_ids')
                    if ids is None:
                        ids = [r['id'] for r in ledger['receipts'] if r['id'] not in ledger['released_ids']]
                    if type(value.get('released')) is not int or value['released'] != len(ids):
                        raise ValueError('Product release not confirmed')
                    ledger['released_ids'] = sorted(set(ledger['released_ids']) | set(ids))
        except Exception:
            audit(state, 'blocked-reservation-evidence', reason='trusted-reservation-receipt-unavailable')
            raise RuntimeError('Managed reservation evidence unavailable') from None

    ctx.register_hook('pre_tool_call', before)
    ctx.register_hook('post_tool_call', after)
    event(state, 'plugin-ready', tools=sorted({'read_file', 'write_file'} | wire),
          runtime_phase=attempt['phase'], process_id=os.getpid())


def assert_registered(manager, state):
    state = Path(state)
    attempt, task = read(state / 'attempt.json'), read(state / 'task.json')
    callbacks = list(manager.iter_hook_callbacks('pre_tool_call'))
    required = [cb for cb in callbacks if getattr(cb, 'orrery_guard_attempt', None) == attempt['attempt_id']
                and getattr(cb, 'orrery_guard_task', None) == task['task_id']]
    if len(required) != 1 or len(callbacks) != 1:
        raise RuntimeError('Exactly the required managed reservation callback must be loaded')
    require_guard(manager, required[0])
    return required[0]


def register(ctx):
    state = os.environ.get('ORRERY_HERMES_STATE_ROOT')
    if not state or not Path(state).is_absolute():
        raise ValueError('Explicit managed state required')
    install(ctx, state)

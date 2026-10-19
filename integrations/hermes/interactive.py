"""Observe native CLI turns without taking ownership of its input loop."""
import functools
from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path
import uuid

from mail_lifecycle import read, save, stamp
from task_evidence import append


@contextmanager
def report_boundary(state):
    with (Path(state) / 'task-reports.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def freeze_report(state, *, locked=False):
    if not locked:
        with report_boundary(state):
            return freeze_report(state, locked=True)
    from completion import evaluate_task
    state = Path(state)
    outcome = evaluate_task(state)
    task = read(state / 'task.json')
    live = read(state / 'activity.json') if (state / 'activity.json').exists() else {}
    report = state / 'task-reports' / (task['task_id'] + '.json')
    if (task.get('task_mode', 'assignment') != 'assignment' or outcome['success'] is not True
            or report.exists() or live.get('activity') != 'idle'
            or live.get('task_id') != task['task_id'] or live.get('latest_turn', {}).get('completed') is not True):
        return outcome
    artifacts = [{'path': spec['path'], 'sha256': hashlib.sha256((Path(task['worktree']) / spec['path']).read_bytes()).hexdigest()}
                 for spec in task['expected']]
    audit = [json.loads(line) for line in (state / 'audit.jsonl').read_text().splitlines() if line.strip()]
    events = [json.loads(line) for line in (state / 'events.jsonl').read_text().splitlines() if line.strip()]
    outcome.update(evaluation='reported', turn_id=live['turn_id'], artifacts=artifacts, reported_at=stamp(),
        provider_sequences=[row['seq'] for row in audit if row.get('task_id') == task['task_id'] and row.get('phase') == 'provider-usage'
                            and row.get('confirmed') is True and row.get('terminal') is True],
        mail_message_ids=[row['message_id'] for row in events if row.get('task_id') == task['task_id']
                          and row.get('phase') == 'mail-sent' and row.get('ok') is True])
    report.parent.mkdir(mode=0o700, exist_ok=True)
    save(report, outcome, exclusive=True)
    return outcome


def activity(state, value, **fields):
    attempt = read(Path(state) / 'attempt.json')
    row = {'attempt_id': attempt['attempt_id'], 'activity': value, 'at': stamp(), **fields}
    save(Path(state) / 'activity.json', row)
    return row


def observe_chat(cls, state):
    """Use the native result, never rendered text or a successful CLI exit.

    Hermes sets _last_turn_result in _chat_settle_turn. Clear it before every
    call: an early credential failure must not inherit a previous success.
    No user message, generated response or error text is persisted here.
    """
    state = Path(state)
    original = cls.chat

    @functools.wraps(original)
    def chat(self, *args, **kwargs):
        attempt, task = read(state / 'attempt.json'), read(state / 'task.json')
        report = state / 'task-reports' / (task['task_id'] + '.json')
        turn_id = uuid.uuid4().hex
        self._last_turn_result = None
        with report_boundary(state):
            freeze_report(state, locked=True)
            tid = task['task_id'] if task.get('task_mode', 'assignment') == 'assignment' and not report.exists() else None
            binding = {'task_id': tid, 'turn_id': turn_id}
            activity(state, 'thinking', **binding)
        completed = False
        try:
            return original(self, *args, **kwargs)
        finally:
            result = getattr(self, '_last_turn_result', None)
            completed = bool(isinstance(result, dict) and result.get('completed') is True
                             and not any(result.get(key) for key in ('failed', 'partial', 'interrupted')))
            row = {'attempt_id': attempt['attempt_id'], **binding, 'phase': 'turn-end',
                   'reason_kind': 'completed' if completed else 'failed', 'at': stamp(),
                   'source': 'hermes-native-chat-result'}
            with report_boundary(state):
                append(state, 'events.jsonl', row)
                latest = {'id': turn_id, 'completed': completed, 'at': row['at']}
                activity(state, 'idle', **binding, latest_turn=latest)
                if tid:
                    save(state / 'task-completion.json', freeze_report(state, locked=True))

    cls.chat = chat
    build = getattr(cls, '_tui_build_application', None)
    if build is not None:
        @functools.wraps(build)
        def application(self, *args, **kwargs):
            app = build(self, *args, **kwargs)
            seen = False
            def rendered(_app):
                nonlocal seen
                if seen:
                    return
                seen = True
                import os
                from task_evidence import event
                event(state, 'native-ready', process_id=os.getpid())
                live = read(state / 'activity.json')
                if live.get('activity') == 'starting':
                    activity(state, 'idle', task_id=None, turn_id=None)
            app.after_render += rendered
            return app
        cls._tui_build_application = application
    return original


def cli_arguments(config, state):
    """-q seeds a real TTY; omitting it opens an idle native conversation."""
    from runner import pilot_toolsets, profile_config_path
    profile = read(profile_config_path(config))
    args = [config['hermes_executable'], '-p', config['profile_name'],
            '--provider', config['provider'], '-m', config['model'],
            '-t', ','.join(pilot_toolsets(profile, file_task=True))]
    prompt = (Path(state) / 'task.md').read_text()
    if prompt.strip():
        args += ['-q', prompt]
    return args


def constrain_native_surface(cls, state):
    """First-segment unsupported native shortcuts cannot bypass tool/root guards.

    This is a temporary capability boundary, not the long-term command set.
    Memory/skills/curator remain enabled through their profile-scoped tools.
    """
    command = cls.process_command
    allowed = {'help', 'exit', 'quit', 'status', 'profile'}

    @functools.wraps(command)
    def process(self, text, **kwargs):
        name = text.strip().split(maxsplit=1)[0].lstrip('/').lower() if text.strip() else ''
        if name not in allowed:
            print('This native shortcut is not supported in this managed segment; use the conversation tools.')
            return True
        return command(self, text, **kwargs)

    cls.process_command = process
    def bang(self, text):
        if text.lstrip().startswith('!'):
            print('Direct shell shortcuts are not supported in this managed segment.')
            return True
        return False
    cls.handle_bang_shell = bang
    route_images = cls._chat_route_images
    def images(self, message, paths):
        if paths:
            raise ValueError('Native image attachments are not supported in this managed segment')
        return route_images(self, message, paths)
    cls._chat_route_images = images
    # Hermes's @file expansion reads paths outside the tool dispatch boundary.
    # Leave references literal until that surface receives the same root policy.
    cls._chat_expand_context_references = lambda self, message: (message, None)
    cls._expand_paste_references = lambda self, message: message or ''

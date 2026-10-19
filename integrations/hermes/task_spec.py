"""Conversation inputs and optional formal assignments for managed Hermes."""
from pathlib import Path, PurePosixPath
import re
import uuid
import json

from reservation_guard import _matches


def validate(value):
    if not isinstance(value, dict) or set(value) - {'prompt', 'allowed_paths', 'expected', 'task_mode', 'report_policy'}:
        raise ValueError('Unknown task fields')
    mode = value.get('task_mode', 'assignment' if value.get('expected') else 'conversation')
    if mode not in ('assignment', 'conversation') or value.get('report_policy', 'pane') not in ('pane', 'mail'):
        raise ValueError('Unknown task mode or report policy')
    prompt, paths, expected = value.get('prompt', ''), value.get('allowed_paths', []), value.get('expected', [])
    if not isinstance(prompt, str) or (mode == 'assignment' and not prompt.strip()):
        raise ValueError('Task prompt required')
    if not isinstance(paths, list) or not isinstance(expected, list):
        raise ValueError('Task paths and checks must be lists')
    if mode == 'conversation' and expected:
        raise ValueError('Expected artifacts require assignment mode')
    for pattern in paths:
        if not isinstance(pattern, str) or not pattern:
            raise ValueError('Relative reservation path required')
        literal = pattern
        rel = PurePosixPath(literal)
        if rel.is_absolute() or '..' in rel.parts or '.git' in rel.parts or not rel.parts or any(c in literal for c in '*?['):
            raise ValueError('Only relative literal file paths supported in this stage')
    if len(set(paths)) != len(paths):
        raise ValueError('Duplicate reservation paths')
    seen = set()
    for spec in expected:
        if not isinstance(spec, dict) or set(spec) - {'path', 'contains', 'sha256'}:
            raise ValueError('Expected file check malformed')
        if ('contains' in spec) == ('sha256' in spec):
            raise ValueError('Expected file requires exactly one contains or sha256 check')
        name = spec.get('path')
        if (not isinstance(name, str) or not name or PurePosixPath(name).is_absolute()
                or any(part in ('..', '.git') for part in PurePosixPath(name).parts)
                or (paths and not any(_matches(name, pattern) for pattern in paths)) or name in seen):
            raise ValueError('Expected file must be inside reserved paths')
        if 'sha256' in spec:
            if not isinstance(spec['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', spec['sha256']):
                raise ValueError('Expected sha256 must be a lowercase digest')
        elif not isinstance(spec.get('contains'), str):
            raise ValueError('Expected contains or sha256 check required')
        seen.add(name)
    return value


def normalize(value, parent=None):
    value = validate(value)
    mode = value.get('task_mode', 'assignment' if value.get('expected') else 'conversation')
    policy = value.get('report_policy', 'mail' if mode == 'assignment' and parent else 'pane')
    if policy == 'mail' and not parent:
        raise ValueError('Mail report policy requires an actual parent')
    return {'prompt': value.get('prompt', ''), 'allowed_paths': value.get('allowed_paths', []),
            'expected': value.get('expected', []), 'task_mode': mode, 'report_policy': policy}


def materialize(state, value, config, attempt, save):
    """Do not seed or alter requested artifacts before the child runs."""
    value = normalize(value, config.get('parent'))
    state = Path(state)
    task = {'attempt_id': attempt['attempt_id'], 'task_id': uuid.uuid4().hex,
            'worktree': config['worktree'], 'report_to': config['parent'],
            'allowed_paths': value['allowed_paths'], 'expected': value['expected'],
            'task_mode': value['task_mode'], 'report_policy': value['report_policy'],
            'scope_mode': 'files' if value['task_mode'] == 'assignment' and value['allowed_paths'] else 'worktree',
            'interactive': config.get('runtime_mode') == 'interactive',
            'reservation_source': 'product-bound-proxy', 'reservation_receipts': [],
            'require_read_before_report': False}
    save(state / 'task.json', task)
    save(state / 'requested-task.json', value, exclusive=True)
    instructions = ('Registration is complete. Use the provided product Mail tools; do not inspect credentials '
        'or use another Mail transport. Use absolute file paths under ' + config['worktree'] + '. '
        'Writes acquire actual product reservations. Private memory and skills remain available. '
        'A completed turn or task report keeps this conversation open for the next input.')
    if value['task_mode'] == 'assignment':
        instructions += '\nRequested file checks: ' + json.dumps(value['expected'])
        if value['report_policy'] == 'mail':
            instructions += '\nAfter completing the checks, report the result by Mail to ' + config['parent'] + '.'
    # Empty initial text must open an idle native pane; system policy lives in
    # the managed entry, not in a fabricated user task.
    save(state / 'runtime-instructions.json', {'text': instructions}, exclusive=True)
    if config.get('runtime_mode') == 'batch' and value['report_policy'] == 'mail':
        save(state / 'message.json', {'to': [config['parent']], 'subject': 'Hermes managed task result',
            'body_md': 'path: ' + ', '.join(str(Path(config['worktree']) / row['path']) for row in value['expected'])
                       + ' — completed the requested file checks.'})
    (state / 'task.md').write_text(value['prompt'])
    return task

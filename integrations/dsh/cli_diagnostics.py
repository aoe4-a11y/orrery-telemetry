"""Fixed-vocabulary diagnostics: never serialize exception text or subprocess output."""
import errno
import json
import subprocess

PREFIX = 'ORRERY_DSH_CLI_ERROR '
STEPS = frozenset(('init', 'bind', 'assemble', 'start', 'run', 'release', 'stop', 'attach', 'state', 'clean', 'abandon'))
SUMMARIES = {
    'validation_failed': 'Invalid run configuration or state',
    'filesystem_failed': 'Filesystem operation failed',
    'process_failed': 'Subprocess failed',
}
VALIDATION_SUMMARIES = frozenset((
    'Explicit non-secret run configuration and original HOME required',
    'Absolute configured paths required',
    'Use a dedicated worktree outside the live project',
    'One explicit task with expected artifacts required',
    'Narrow file scope and expected artifact required',
    'First run accepts literal relative file paths only',
    'Expected artifact must be in the reserved scope',
    'Registered identity does not match the run configuration',
    'Real reservation binding missing',
    'Credential adapter is not implemented for this OS',
    'Explicit credential reference required',
    'Credential lookup failed; do not retry automatically',
    'Do not inherit a model key into the launcher/tmux',
    "Credential lookup requires this attempt's owned pane",
    'Mail probe did not authenticate before credential lookup',
    'Owned runtime disappearance not confirmed',
    'Owned group absence must be confirmed',
    'State already exists; preserve prior attempt',
))
TYPES = frozenset(('ValueError', 'KeyError', 'TypeError', 'JSONDecodeError', 'OSError', 'FileNotFoundError',
                   'PermissionError', 'FileExistsError', 'NotADirectoryError', 'IsADirectoryError',
                   'CalledProcessError', 'TimeoutExpired', 'SubprocessError', 'SystemExit'))


def diagnostic(step, exc):
    reason = ('process_failed' if isinstance(exc, subprocess.SubprocessError) else
              'filesystem_failed' if isinstance(exc, OSError) else 'validation_failed')
    row = {'step': step if step in STEPS else 'unknown', 'type': type(exc).__name__ if type(exc).__name__ in TYPES else 'ValueError',
           'reason': reason, 'summary': SUMMARIES[reason]}
    if isinstance(exc, (ValueError, SystemExit)) and str(exc) in VALIDATION_SUMMARIES:
        row['summary'] = str(exc)
    elif isinstance(exc, OSError) and exc.errno in errno.errorcode:
        row['summary'] += ' (' + errno.errorcode[exc.errno] + ')'
    elif isinstance(exc, subprocess.TimeoutExpired):
        row['summary'] += ' (timeout)'
    elif isinstance(exc, subprocess.CalledProcessError):
        row['summary'] += ' (nonzero exit)'
    return row


def encode(step, exc):
    return PREFIX + json.dumps(diagnostic(step, exc), separators=(',', ':'))


def parse(text, step):
    """Accept only our fixed vocabulary, even when unrelated stderr is present."""
    if not isinstance(text, str):
        return None
    for line in reversed(text.splitlines()):
        if not line.startswith(PREFIX):
            continue
        try:
            row = json.loads(line[len(PREFIX):])
            reason = row['reason']
            summaries = {SUMMARIES[reason], SUMMARIES[reason] + ' (timeout)', SUMMARIES[reason] + ' (nonzero exit)'}
            summaries.update(VALIDATION_SUMMARIES if reason == 'validation_failed' else ())
            summaries.update(SUMMARIES[reason] + ' (' + name + ')' for name in errno.errorcode.values())
            if (set(row) == {'step', 'type', 'reason', 'summary'} and row['step'] == step and step in STEPS
                    and row['type'] in TYPES and row['summary'] in summaries):
                return row
        except (ValueError, TypeError, KeyError):
            pass
    return None

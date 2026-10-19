"""Native Hermes pre-tool adapter; decisions stay in the common product hooks.

This is the same mistake guard as the other clients, not a shell sandbox.
Loading this plugin is Hermes's responsibility; no separate launch preflight.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess
import sys


def payloads(tool_name, args, *, cwd, session_id=''):
    """Map native file edits, including both endpoints of a V4A move."""
    base = {'cwd': cwd, 'session_id': session_id}
    name = {'terminal': 'Bash', 'write_file': 'Write', 'patch': 'Edit',
            'read_file': 'Read'}.get(tool_name, tool_name)
    inputs = [dict(args)]
    if tool_name == 'patch' and args.get('mode') == 'patch':
        text = args.get('patch') or ''
        paths = re.findall(r'^\*\*\*\s*(?:Update|Add|Delete)\s+File:\s*(.+)$', text, re.M)
        for source, target in re.findall(r'^\*\*\*\s*Move\s+File:\s*(.+?)\s*->\s*(.+)$', text, re.M):
            paths.extend((source, target))
        if args.get('path'):
            paths.append(args['path'])
        inputs = [{'path': path.strip()} for path in dict.fromkeys(paths)]
    for item in inputs:
        # Resolve like Hermes's host file tools, without changing their arguments.
        if isinstance(item.get('path'), str):
            target = Path(item['path']).expanduser()
            item['file_path'] = str((Path(cwd) / target).resolve())
        yield {**base, 'tool_name': name, 'tool_input': item}


def _cwd(tool_name, args, task_id):
    # File tools follow Hermes's per-task terminal cwd, not necessarily os.getcwd.
    from tools.file_tools_paths import _resolve_base_dir
    cwd = str(_resolve_base_dir(task_id or 'default'))
    if tool_name == 'terminal' and args.get('workdir'):
        cwd = str((Path(cwd) / Path(args['workdir']).expanduser()).resolve())
    return cwd


def before(tool_name, args, session_id='', task_id='', **_):
    root = Path(os.environ['AGENTSTACK_HOME'])
    cwd = _cwd(tool_name, args, task_id)
    for payload in payloads(tool_name, args, cwd=cwd, session_id=session_id):
        checks = []
        if payload['tool_name'] in ('Bash', 'Write', 'Edit'):
            checks.append(['/bin/bash', str(root / 'hooks/check-agent-registered.sh')])
        checks.append([sys.executable, str(root / 'hooks/deny-llm-key-read.py')])
        if payload['tool_name'] in ('Write', 'Edit'):
            checks.append(['/bin/bash', str(root / 'hooks/check-file-reservation.sh')])
        for argv in checks:
            result = subprocess.run(argv, input=json.dumps(payload), text=True,
                                    capture_output=True, cwd=cwd, timeout=60)
            if result.returncode == 2:
                return {'action': 'block', 'message': result.stderr.strip() or 'ORRERY tool guard denied this call'}
            if result.returncode:
                # Match the normal hook contract: only exit 2 is a veto.
                print('ORRERY hook returned a non-veto error', file=sys.stderr)
    return None


def session_started(session_id, **_):
    """Save only this CLI's event, never a delegated child or a shared MRU."""
    try:
        from agent.delegation_context import is_delegated_child_context
        if is_delegated_child_context() or not session_id:
            return
        path = Path(os.environ['AGENTSTACK_NATIVE_SESSION_FILE'])
        value = {'harness': 'hermes', 'native_session_id': session_id,
                 'created_at': datetime.now(timezone.utc).isoformat()}
        temporary = path.with_name(path.name + '.' + str(os.getpid()) + '.tmp')
        try:
            with temporary.open('w', encoding='utf-8') as handle:
                os.chmod(temporary, 0o600)
                json.dump(value, handle)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    except Exception:
        # Resume metadata is optional; failure must not prevent native startup.
        print('ORRERY could not save the native session reference', file=sys.stderr)


def register(ctx):
    ctx.register_hook('pre_tool_call', before)
    ctx.register_hook('on_session_start', session_started)

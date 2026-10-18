"""Local private tools are outside the installer's payload ownership.

Only names and synthetic sentinels live in this repository; private tool bodies
must never be committed. Each real lifecycle entrypoint runs in an isolated home.
"""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

import test_runtime_defaults as installer
import test_restart_identity as identity
import test_seat_lifecycle as lifecycle


LOCAL_TOOLS = '''agentstack-check-seats agentstack-memory-guard
agentstack-owner-checkin.py agentstack-reap-idle-seats agentstack-rule-mirror-check
agentstack-seat-cost.py agentstack-seat-stall-watch.py agentstack-station-materials
agentstack-supervisor.py agentstack-tmux-server-migrate agentstack-unstick-seats.sh
codex-session-restore codex-stats codex-usage head-accept head-send
orrery-audit-evidence orrery-audit-login orrery-audit-run orrery-ci
orrery-head-tripwire owner-quote-index owner-sheet-health owner-sheet-server.py
simulator-window-guard test_agentstack_unstick_seats.py'''.split()


def fixture_payloads():
    return {name: f'private fixture tool: {name}\n'.encode() for name in LOCAL_TOOLS}


def test_installer_restart_and_cleanup_preserve_local_tools(tmp_path, monkeypatch, record_property):
    payloads = fixture_payloads()
    assert len(payloads) == 26
    home = tmp_path / 'home'
    stack = home / '.agentstack'
    tool_dir = stack / 'bin'
    tool_dir.mkdir(parents=True)
    for name, data in payloads.items():
        path = tool_dir / name
        path.write_bytes(data)
        path.chmod(0o700)
    expected = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
    stages = []

    def check(stage):
        measured = {name: hashlib.sha256((tool_dir / name).read_bytes()).hexdigest() for name in payloads}
        assert measured == expected, stage
        stages.append({'stage': stage, 'sha256': measured})

    # Reuse the production installer fixture, including its actual three
    # installer invocations. Only service/OS commands are fake. An explicit
    # uninstall is outside this install/restart/exit-cleanup contract.
    original_run = subprocess.run
    def observe_run(command, *args, **kwargs):
        result = original_run(command, *args, **kwargs)
        if any(str(value).endswith(('/scripts/install.sh', '/bin/agentstack-uninstall')) for value in command):
            check('installer' if str(command[1]).endswith('install.sh') else 'uninstall')
        return result
    with monkeypatch.context() as context:
        context.setattr(subprocess, 'run', observe_run)
        installer._exercise_noninteractive_installer(tmp_path, uninstall=False)
    assert len(stages) == 3

    lane = lifecycle.LifecycleTests(); lane.setUp()
    try:
        seat = lane.arrange()
        seat['env'].update(HOME=str(home), AGENTSTACK_HOME=str(stack))
        # Point only the isolated restart env at the synthetic identity.
        # Never change a live home or service configuration.
        (stack / 'env.sh').write_text(''.join(
            f'export {key}={shlex.quote(value)}\n' for key, value in seat['env'].items()
            if key.startswith('AGENTSTACK_') or key in ('PATH', 'PROJECT_KEY', 'PARENT_AGENT')))
        child = lane.launch(seat)
        check('launch')
        task = lane.base / 'restart-task.md'; task.write_text('synthetic preservation fixture')
        result = original_run(['/bin/bash', str(lifecycle.ROOT / 'bin/agentstack-restart-seat'),
                               identity.NAME, str(task), 'gpt-5.5', 'medium', '/'],
                              env=seat['env'], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        check('restart')
        # A delayed old callback and the current callback both preserve tools.
        lane.cleanup(child)
        check('delayed-cleanup')
        current = json.loads((lane.base / 'tmux-verbs.env').read_text())
        lane.cleanup(current)
        check('current-cleanup')
    finally:
        lane.doCleanups()
    record_property('local_tool_preservation', json.dumps(stages, sort_keys=True))

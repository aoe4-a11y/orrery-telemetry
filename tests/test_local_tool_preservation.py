"""Local private tools are outside the installer's payload ownership.

Only names and synthetic sentinels live in this repository; private tool bodies
must never be committed. Each real lifecycle entrypoint runs in an isolated home.
"""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import pytest
from lifecycle_overlay import stage, wrapper

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


@pytest.mark.parametrize("platform", ["Linux", "Darwin"])
def test_installer_restart_and_cleanup_preserve_local_tools(tmp_path, monkeypatch, record_property, platform):
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
        installer._exercise_noninteractive_installer(tmp_path, uninstall=False, platform=platform)
    assert len(stages) == 3

    lane = lifecycle.LifecycleTests(); lane.setUp()
    try:
        seat = lane.arrange()
        seat['env']['HOME']=str(home)
        layout=stage(lane,seat)
        child=wrapper(lane,seat,layout,'codex')
        check('overlay-launch')
        owner=lifecycle.Seat(layout['runtime'],identity.NAME)
        assert owner.validate(child['AGENTSTACK_LAUNCH_JOURNAL'],automatic=True) is not None
        assert child['AGENTSTACK_PRESERVE_SEAT_IDENTITY']=='0'
        # Exercise actual deletion, rather than only the preserve veto. This
        # catches a Seat.delete mutant touching runtime/../bin.
        result=original_run(['/bin/bash',str(layout['hooks']/'cleanup-child-agent.sh')],env=child,capture_output=True,text=True,timeout=15)
        assert result.returncode==0,result.stderr
        for key in ('token','state','home'): assert not seat[key].exists(),key
        check('current-cleanup-owned-delete')
        child=wrapper(lane,seat,layout,'codex')
        task=lane.base/'restart-task.md';task.write_text('synthetic preservation fixture')
        result=original_run(['/bin/bash',str(layout['stack']/'bin/agentstack-restart-seat'),identity.NAME,str(task),'gpt-5.5','medium','/'],env=seat['env'],capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stderr
        check('restart')
        result=original_run(['/bin/bash',str(layout['hooks']/'cleanup-child-agent.sh')],env=child,capture_output=True,text=True,timeout=15)
        assert result.returncode==0,result.stderr
        assert seat['token'].exists()
        check('delayed-cleanup')
        current=json.loads((lane.base/'tmux-verbs.env').read_text())
        assert current['AGENTSTACK_PRESERVE_SEAT_IDENTITY']=='1'
        result=original_run(['/bin/bash',str(layout['hooks']/'cleanup-child-agent.sh')],env=current,capture_output=True,text=True,timeout=15)
        assert result.returncode==0,result.stderr
        check('restarted-identity-preservation')
        # env-less administrative name also chooses the guarded route.
        result=original_run(['/bin/bash',str(layout['hooks']/'cleanup-child-agent.sh'),identity.NAME],env=seat['env'],capture_output=True,text=True,timeout=15)
        assert result.returncode==0,result.stderr
        assert seat['token'].exists()
        assert not (stack/'legacy.called').exists()
        check('explicit-cleanup')
    finally:
        lane.doCleanups()
    record_property('local_tool_preservation', json.dumps(stages, sort_keys=True))

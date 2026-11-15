"""Preserve the previous restart cwd without copying its value to source."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fleet_payload_restart', ROOT / 'scripts/install-fleet-payload.py')
payload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(payload)


@pytest.mark.parametrize('explicit', [False, True])
def test_rendered_restart_uses_previous_or_explicit_cwd(tmp_path, monkeypatch, explicit):
    home = tmp_path / 'home'; home.mkdir()
    stack = home / '.agentstack'; (stack / 'bin').mkdir(parents=True)
    runtime = stack / 'runtime'; (runtime / 'child-agents').mkdir(parents=True)
    default = home / 'default-work'; default.mkdir()
    selected = home / 'explicit-work'; selected.mkdir()
    task = home / 'task'; task.write_text('fixture')
    (runtime / 'agent_token_Fixture').write_text('fixture')
    (runtime / 'child-agents/Fixture.json').write_text(json.dumps({'project_key': str(home)}))
    old = stack / 'bin/agentstack-restart-seat'
    old.write_text('WORKDIR="${5:-$HOME/default-work}"\n')
    monkeypatch.setenv('HOME', str(home))
    _, rendered = payload.prepared_restart(stack)
    old.write_text(rendered)
    assert payload.prepared_restart(stack)[1] == rendered
    fake = home / 'fake'; fake.mkdir()
    hooks = home / 'hooks'; hooks.mkdir()
    trace = home / 'trace'
    for path, text in {
        stack / 'bin/agentstack-memory-budget': '#!/bin/sh\nexit 0\n',
        fake / 'tmux': '#!/bin/sh\n[ "$1" != has-session ]\n',
        fake / 'sleep': '#!/bin/sh\nexit 0\n',
        fake / 'python3': '#!/bin/sh\ncase "$1" in -c) exec /usr/bin/python3 "$@";; *) exit 0;; esac\n',
        hooks / 'spawn_child.sh': '#!/bin/sh\npwd > "$TRACE"\n',
    }.items():
        path.write_text(text); path.chmod(0o755)
    env = {'HOME': str(home), 'PATH': str(fake) + ':/usr/bin:/bin', 'TRACE': str(trace),
           'AGENTSTACK_HOME': str(stack), 'AGENTSTACK_RUNTIME_DIR': str(runtime),
           'AGENTSTACK_LIFECYCLE_HOOKS_DIR': str(hooks), 'AGENTSTACK_HOOKS_DIR': str(hooks),
           'AGENTSTACK_PROJECT_KEY': str(home)}
    args = ['/bin/bash', str(old), 'Fixture', str(task), 'model', 'medium']
    if explicit: args.append(str(selected))
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert Path(trace.read_text().strip()) == (selected if explicit else default)


@pytest.mark.parametrize('source', ['# missing\n',
    'WORKDIR="${5:-$HOME/one}"\nWORKDIR="${5:-$HOME/two}"\n',
    'WORKDIR="${5:-$HOME/does-not-exist}"\n',
    'WORKDIR="${5:-$(touch /fixture/unsafe)}"\n'])
def test_invalid_old_default_stops_before_render(tmp_path, monkeypatch, source):
    home = tmp_path / 'home'; home.mkdir()
    stack = home / '.agentstack'; (stack / 'bin').mkdir(parents=True)
    old = stack / 'bin/agentstack-restart-seat'; old.write_text(source)
    monkeypatch.setenv('HOME', str(home))
    with pytest.raises(ValueError): payload.prepared_restart(stack)
    assert old.read_text() == source

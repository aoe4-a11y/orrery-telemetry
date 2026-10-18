"""Materialize the documented partial release inside one synthetic home."""
import json
import os
from pathlib import Path
import shlex
import subprocess

import test_restart_identity as identity
from test_seat_lifecycle import ROOT


def stage(lane, seat):
    home = Path(seat['env']['HOME'])
    stack = home/'.agentstack'
    stack.mkdir(exist_ok=True)
    runtime = stack/'runtime'
    old_runtime = seat['token'].parent
    if not runtime.exists():
        old_runtime.rename(runtime)
    else:
        # Existing installer runtime is synthetic. Merge only this fixture's
        # exact files, refusing nonempty collisions.
        for path in old_runtime.iterdir():
            dest=runtime/path.name
            if path.is_dir() and dest.is_dir():
                assert not list(dest.iterdir()), str(dest)
                dest.rmdir()
            elif dest.exists():
                assert dest.is_file() and dest.stat().st_size==0, str(dest)
                dest.unlink()
            path.rename(dest)
        old_runtime.rmdir()
    for key in ('token','state','config','home','managed','handoff'):
        seat[key] = runtime/seat[key].relative_to(old_runtime)
    for key,value in list(seat['env'].items()):
        seat['env'][key] = value.replace(str(old_runtime),str(runtime))
    release = stack/'releases/seat-lifecycle/fixture-commit/hooks'
    release.mkdir(parents=True)
    global_hooks = stack/'hooks'; global_hooks.mkdir(exist_ok=True)
    # Exact file set, deliberately no integrations/ or bin/ in the release.
    for name in ('spawn_child.sh','cleanup-child-agent.sh','seat_lifecycle.py','set-ghostty-title.sh'):
        (release/name).write_bytes((ROOT/'hooks'/name).read_bytes())
        (release/name).chmod(0o700)
    for name in ('project-context.sh','resolve-agent-name.sh','session-identity-policy.sh',
                 'reservation-common.sh','release-file-reservation-worker.py','record-session-index.py'):
        source = ROOT/'hooks'/name
        if source.exists() and not (global_hooks/name).exists(): (global_hooks/name).symlink_to(source)
    for name in ('project-context.sh','resolve-agent-name.sh'):
        (release/name).symlink_to(global_hooks/name)
    bin_dir = stack/'bin'; (bin_dir/'lib').mkdir(parents=True,exist_ok=True)
    for name in ('agentstack-spawn-codex','agentstack-spawn-claude','agentstack-restart-seat'):
        (bin_dir/name).write_bytes((ROOT/'bin'/name).read_bytes()); (bin_dir/name).chmod(0o700)
    for name in ('agentstack-register.sh','agentstack-scientists.sh'):
        if not (bin_dir/'lib'/name).exists(): (bin_dir/'lib'/name).symlink_to(ROOT/'bin/lib'/name)
    proxy = stack/'integrations/codex_app/plugin/scripts/run-mcp.sh'
    proxy.parent.mkdir(parents=True,exist_ok=True); identity.executable(proxy,'#!/bin/sh\nexit 0\n')
    helper = '''#!/usr/bin/env python3
import pathlib, sys
args=sys.argv[1:]
p=pathlib.Path(args[args.index('--token-file-out')+1])
p.write_text('fixture-only-token'); p.chmod(0o600)
sys.path.insert(0, RELEASE)
from seat_lifecycle import bind_handoff
bind_handoff(p.parent.parent,p,'RestartFixture',args[args.index('--project-key')+1])
print('RestartFixture')
'''.replace('RELEASE',repr(str(release)))
    identity.executable(bin_dir/'agentstack-preregister-child',helper)
    legacy = release.parent/'legacy/cleanup-child-agent.sh'
    legacy.parent.mkdir()
    identity.executable(legacy, '#!/bin/bash\nprintf legacy > "'+str(stack/'legacy.called')+'"\n')
    dispatcher=(ROOT/'hooks/cleanup-child-agent-dispatch.sh').read_text().replace('__RELEASE_HOOKS__',str(release)).replace('__LEGACY_CLEANUP__',str(legacy))
    identity.executable(global_hooks/'cleanup-child-agent.sh',dispatcher)
    identity.executable(global_hooks/'spawn_child.sh', '#!/bin/bash\nexport AGENTSTACK_HOME='+shlex.quote(str(stack))+'\nexport AGENTSTACK_LIFECYCLE_HOOKS_DIR='+shlex.quote(str(release))+'\nexec /bin/bash "$AGENTSTACK_LIFECYCLE_HOOKS_DIR/spawn_child.sh" "$@"\n')
    seat['env'].update(AGENTSTACK_HOOKS_DIR=str(global_hooks),AGENTSTACK_LIFECYCLE_HOOKS_DIR=str(release))
    for key in ('AGENTSTACK_HOME','AGENTSTACK_MCP_PROXY','AGENTSTACK_REGISTER_LIB'):
        seat['env'].pop(key,None)
    # Deployment adds the lifecycle selector to an existing env.sh which does
    # not define AGENTSTACK_HOME/MCP_PROXY. Do not mask their absence.
    (stack/'env.sh').write_text(''.join('export '+k+'='+shlex.quote(v)+'\n' for k,v in seat['env'].items() if k.startswith('AGENTSTACK_')))
    identity.freeze_tmux_fixture(seat['env'])
    return dict(stack=stack,runtime=runtime,release=release,hooks=global_hooks,legacy=legacy)


def wrapper(lane, seat, layout, provider):
    task=lane.base/'overlay-task.md'; task.write_text('fixture work')
    result=subprocess.run(['/bin/bash',str(layout['stack']/f'bin/agentstack-spawn-{provider}'),
                           'gpt-5.5' if provider=='codex' else 'fable',str(task),str(seat['work'])],
                          env=seat['env'],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,(result.returncode,result.stdout,result.stderr)
    return json.loads((lane.base/'tmux-verbs.env').read_text())

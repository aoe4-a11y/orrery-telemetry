"""Real standard launcher, synthetic preregistration/pane; no provider or Mail."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_spawn_child_embed_task import _fake_launch_env, _codex_handoff, _executable, SPAWN, ROOT


def fixture(tmp_path, *, gone=False):
    env,work=_fake_launch_env(tmp_path,codex=False)
    token=_codex_handoff(tmp_path,'HarnessChild')
    binding=Path(str(token)+'.binding.json')
    data=json.loads(binding.read_text());data['program']='dsh';binding.write_text(json.dumps(data));binding.chmod(0o600)
    proxy=tmp_path/'product-proxy.sh';_executable(proxy,'#!/bin/sh\nexit 0\n')
    env['AGENTSTACK_MCP_PROXY']=str(proxy)
    fake=tmp_path/'harness-fixture.py'
    generator=tmp_path/'generator.py'
    generator.write_text("import argparse,json,os\np=argparse.ArgumentParser();p.add_argument('--input');p.add_argument('--out');a=p.parse_args();v=json.load(open(a.input));json.dump({'argv':['/usr/bin/true'],'env':{},'cwd':v['cwd']},open(a.out,'w'));os.chmod(a.out,0o600)\n")
    fake.write_text('import sys,runpy\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1]);script=Path(sys.argv.pop(1))/"harness_child.py"\nif sys.argv[1]=="validate":raise SystemExit(0) # Synthetic static admission only.\nm=runpy.run_path(str(script));g=m["prepare"].__globals__;g["selection"]=lambda *a:{"python":sys.executable};g["config_generator"]=lambda *a:Path('+repr(str(generator))+')\nraise SystemExit(m["main"]())\n')
    wrapper=tmp_path/'helper-wrapper.py'
    wrapper.write_text('import os,sys\nos.execv(sys.executable,[sys.executable,'+repr(str(fake))+','+repr(str(ROOT/'hooks'))+',*sys.argv[1:]])\n')
    env['AGENTSTACK_HARNESS_CHILD_HELPER']=str(wrapper)
    env['AGENTSTACK_PYTHON']=sys.executable
    manifest=tmp_path/'manifest.json';manifest.write_text('{}')
    env['AGENTSTACK_MANAGED_SPAWN_CONFIG']=str(manifest)
    tmux=tmp_path/'bin/tmux';text=tmux.read_text()
    if gone:
        text=text.replace('has-session) [[ -f "$FAKE_TMUX_ALIVE" ]]', 'has-session) exit 1')
    tmux.write_text(text)
    for program in ('claude','codex'):
        _executable(tmp_path/'bin'/program,'#!/bin/sh\nprintf called > '+str(tmp_path/'forbidden-native-probe')+'\nexit 91\n')
    return env,work,token


@pytest.mark.parametrize('standalone',[False,True])
def test_standard_preregistered_harness_reuses_binding_proxy_and_real_workdir(tmp_path,standalone):
    env,work,token=fixture(tmp_path)
    args=['/bin/bash',str(SPAWN),'--pre-registered','HarnessChild','--child-token-file',str(token),
          '--harness','dsh','--backend','strata','--model','formal-model']
    if standalone:args+=['--standalone','',str(work)]
    else:args+=['--embed-task','Literal $(must-not-run) `task`',str(work)]
    result=subprocess.run(args,env=env,cwd=ROOT,text=True,capture_output=True,timeout=25)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='HarnessChild'
    state=json.loads((Path(env['AGENTSTACK_RUNTIME_DIR'])/'child-agents/HarnessChild.json').read_text())
    assert state['program']=='dsh' and state['provider']=='dsh'
    h=json.loads((Path(state['harness_state_dir'])/'input.json').read_text())
    assert h['cwd']==str(work.resolve())
    assert h['parent_agent']==(None if standalone else 'ParentAgent')
    prompt=Path(h['prompt_file']).read_text()
    assert (prompt=='' if standalone else 'Literal $(must-not-run) `task`' in prompt)
    assert Path(h['instructions_file']).is_file()
    proxy_config=json.loads(Path(h['mcp_config']).read_text())
    assert {row['env']['AGENTSTACK_PROXY_PROGRAM'] for row in proxy_config['mcpServers'].values()}=={'dsh'}
    assert not (tmp_path/'forbidden-native-probe').exists()
    assert not token.exists() and not Path(str(token)+'.binding.json').exists()
    assert not (Path(env['AGENTSTACK_RUNTIME_DIR'])/'child-agents/.HarnessChild.registration-pending.json').exists()
    assert '/usr/bin/true' in Path(env['FAKE_TMUX_LOG']).read_text()


def test_failed_harness_start_keeps_identity_and_handoff_when_cleanup_unconfirmed(tmp_path):
    env,work,token=fixture(tmp_path,gone=True)
    result=subprocess.run(['/bin/bash',str(SPAWN),'--pre-registered','HarnessChild','--child-token-file',str(token),
        '--harness','dsh','--backend','strata','--model','formal-model','--standalone','',str(work)],
        env=env,cwd=ROOT,text=True,capture_output=True,timeout=25)
    assert result.returncode!=0
    assert token.exists() and Path(str(token)+'.binding.json').exists()
    state=Path(env['AGENTSTACK_RUNTIME_DIR'])/'child-agents/HarnessChild.json'
    assert state.exists() and json.loads(state.read_text())['harness_state_dir']
    assert 'cleanup unconfirmed' in result.stderr
    assert 'kill-session' not in Path(env['FAKE_TMUX_LOG']).read_text()


@pytest.mark.parametrize('flags',[
 ['--harness','dsh'], ['--backend','strata'], ['--harness','unknown','--backend','strata'],
 ['--harness','dsh','--backend','strata','--codex'],
 ['--harness','dsh','--backend','strata','--tools','browser'],
])
def test_bad_harness_flags_stop_before_any_registration_or_tmux(tmp_path,flags):
    env,work=_fake_launch_env(tmp_path,codex=False)
    result=subprocess.run(['/bin/bash',str(SPAWN),*flags,'--model','formal-model','--unsafe-no-resources','task',str(work)],
        env=env,cwd=ROOT,text=True,capture_output=True,timeout=10)
    assert result.returncode!=0
    assert not Path(env['FAKE_TMUX_LOG']).exists()


def test_harness_does_not_silently_drop_installed_default_tools(tmp_path):
    env,work,token=fixture(tmp_path)
    env['AGENTSTACK_CHILD_DEFAULT_TOOLS']='browser'
    result=subprocess.run(['/bin/bash',str(SPAWN),'--pre-registered','HarnessChild',
        '--child-token-file',str(token),'--harness','dsh','--backend','strata',
        '--model','formal-model','--standalone','',str(work)],env=env,cwd=ROOT,
        text=True,capture_output=True,timeout=10)
    assert result.returncode!=0 and 'native_default_tools_unsupported' in result.stderr
    assert token.exists() and not Path(env['FAKE_TMUX_LOG']).exists()

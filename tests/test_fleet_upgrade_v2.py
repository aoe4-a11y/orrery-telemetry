"""Fleet compatibility: real isolated tmux, synthetic CLI/Mail, exact file identities."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import uuid

import pytest

ROOT=Path(__file__).resolve().parents[1]
RELEASE='releases/seat-lifecycle/ee5880e3e23606e0f3252cbeed211868102f4595'
NAME='SunnyCurie'

def executable(path,text):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text);path.chmod(0o755)

def payload_module():
    spec=importlib.util.spec_from_file_location('fleet_payload',ROOT/'scripts/install-fleet-payload.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

def stage(home,new):
    stack=home/'.agentstack';stack.mkdir(parents=True)
    for tree in ('hooks','bin'):
        shutil.copytree(ROOT/tree,stack/tree,ignore=shutil.ignore_patterns('__pycache__','.pytest_cache'))
    if new:
        payload_module().install(stack)
    else:
        shutil.copytree(ROOT/'fleet'/RELEASE,stack/RELEASE,symlinks=True)
        for link in (stack/RELEASE).rglob('*'):
            if link.is_symlink():
                target=os.readlink(link).replace('/Users/huyuhutaru/.agentstack',str(stack));link.unlink();link.symlink_to(target)
        for rel in ('bin/agentstack-preregister-child','bin/agentstack-spawn-codex','bin/agentstack-restart-seat'):
            shutil.copy2(ROOT/'fleet'/rel,stack/rel)
        # The pre-upgrade shim, only its absolute install prefix is relocated.
        for rel in ('hooks/spawn_child.sh','hooks/cleanup-child-agent.sh'):
            text=(ROOT/'docs/orrery-up-2/live-code'/rel).read_text().replace('/Users/huyuhutaru/.agentstack',str(stack))
            executable(stack/rel,text)
    return stack

REGISTER='''ags_mail_load_token() { :; }
ags_pick_available_agent_name() { printf SunnyCurie; }
ags_has_scientist_suffix() { return 0; }
ags_generate_registration_token() { printf isolated-test-owner; }
ags_mcp_call() { printf '{}'; }
ags_mcp_has_error() { return 1; }
ags_extract_agent_name() { printf SunnyCurie; }
ags_extract_registration_token() { printf isolated-test-owner; }
ags_apply_contact_policy() { :; }
'''

def run_arm(root,entry,new):
    home=root/'home';stack=stage(home,new);runtime=stack/'runtime';runtime.mkdir(exist_ok=True)
    project=home/'project';project.mkdir();task=home/'task.md';task.write_text('# Fixture task\nORRERY-UP-2 identity fixture')
    fake=home/'.local/bin';fake.mkdir(parents=True)
    tmux=shutil.which('tmux');assert tmux
    socket='orrery-up2-'+uuid.uuid4().hex
    executable(fake/'tmux','#!/bin/bash\nexec '+tmux+' -L '+socket+' -f /dev/null "$@"\n')
    executable(fake/'codex','''#!/bin/bash
case "${1:-}" in
 --version) echo 'codex-cli 0.159.3'; exit 0 ;;
 --help) echo ' --ask-for-approval <POLICY>'; exit 0 ;;
esac
python3 -c 'import json,os; from pathlib import Path; (Path.home()/"tls-process-env.json").write_text(json.dumps({"ssl_cert_file_present":"SSL_CERT_FILE" in os.environ,"codex_ca_certificate_present":"CODEX_CA_CERTIFICATE" in os.environ}))'
printf 'gpt-6.1-sol medium fixture\n? for shortcuts\n› '
while IFS= read -r line; do printf '\n%s\n› ' "$line"; done
''')
    native=(ROOT/'fleet/external/codex-native-tls').read_text().replace('/Users/huyuhutaru/.local/bin/codex',str(fake/'codex'))
    executable(fake/'codex-native-tls',native)
    executable(fake/'child-shell','#!/bin/bash\n[[ "${1:-}" != -lc ]] || shift\nexec /bin/bash --noprofile --norc -c "$1"\n')
    lib=home/'register.sh';lib.write_text(REGISTER)
    env={k:v for k,v in os.environ.items() if not k.startswith(('AGENTSTACK_','CHILD_','PARENT_','AGS_')) and k not in ('HOME','CODEX_HOME','AGENT_NAME','PROJECT_KEY','TMUX','TMUX_PANE','OPENAI_API_KEY','MCP_AGENT_MAIL_TOKEN')}
    env.update(HOME=str(home),PATH=str(fake)+':'+env['PATH'],PARENT_AGENT='ParentAgent',
       AGENTSTACK_HOME=str(stack),AGENTSTACK_HOOKS_DIR=str(stack/'hooks'),
       AGENTSTACK_RUNTIME_DIR=str(runtime),AGENTSTACK_PROJECT_KEY=str(project),PROJECT_KEY=str(project),
       AGENTSTACK_REGISTER_LIB=str(lib),AGENTSTACK_CODEX_BIN=str(fake/'codex-native-tls'),
       SSL_CERT_FILE='/fixture/certificate.pem',CODEX_CA_CERTIFICATE='/fixture/certificate.pem',TLS_ENV_PROOF=str(home/'tls-process-env.json'),
       AGENTSTACK_CHILD_SHELL=str(fake/'child-shell'),AGENTSTACK_MCP_URL='http://127.0.0.1:9/mcp',
       AGENTSTACK_MCP_PROXY=str(home/'missing-proxy'),AGENTSTACK_TERMINAL='none',AGENTSTACK_AUTO_OPEN_CHILD='0')
    (stack/'env.sh').write_text('export AGENTSTACK_HOME='+str(stack)+'\n')
    token=runtime/('agent_token_'+NAME);state=runtime/'child-agents'/f'{NAME}.json'
    if entry=='restart-seat':
        token.write_text('isolated-test-owner');token.chmod(0o600);state.parent.mkdir()
        state.write_text(json.dumps({'agent_name':NAME,'project_key':str(project),'registration_token':'isolated-test-owner'}));state.chmod(0o600)
        command=[str(stack/'bin/agentstack-restart-seat'),NAME,str(task),'gpt-6.1-sol','medium',str(project)]
    elif entry=='spawn-codex':
        command=[str(stack/'bin/agentstack-spawn-codex'),'gpt-6.1-sol',str(task),str(project),'Fixture task','medium']
    else:
        sys.path.insert(0,str(stack/RELEASE/'hooks'))
        spec=importlib.util.spec_from_file_location('fixture_lifecycle_'+uuid.uuid4().hex,stack/RELEASE/'hooks/seat_lifecycle.py')
        lifecycle=importlib.util.module_from_spec(spec);spec.loader.exec_module(lifecycle)
        handoff=runtime/('spawn-tokens/'+uuid.uuid4().hex+'.token');handoff.parent.mkdir();handoff.write_text('isolated-test-owner');handoff.chmod(0o600)
        lifecycle.bind_handoff(runtime,handoff,NAME,str(project))
        command=[str(stack/'hooks/spawn_child.sh'),'--codex','--model','gpt-6.1-sol','--effort','medium','--pre-registered',NAME,'--child-token-file',str(handoff),'--embed-task','--task-file',str(task),str(project)]
    result=None
    try:
        subprocess.run([str(fake/'tmux'),'new-session','-d','-s','FixtureEnvSeed','/bin/cat'],env=env,check=True)
        positive=subprocess.check_output([str(fake/'tmux'),'show-environment','-g','SSL_CERT_FILE'],env=env,text=True)
        assert positive.startswith('SSL_CERT_FILE=')
        result=subprocess.run(command,cwd=project,env=env,capture_output=True,text=True,timeout=60)
        assert result.returncode==0,(entry,new,result.stdout,result.stderr)
        pane=subprocess.run([str(fake/'tmux'),'list-panes','-t','='+NAME,'-F','#{session_name}|#{pane_current_command}|#{pane_dead}'],env=env,capture_output=True,text=True,check=True).stdout.strip()
        assert pane.startswith(NAME+'|') and pane.endswith('|0'),pane
        data=json.loads(state.read_text())
        assert data['agent_name']==NAME and data['project_key']==str(project)
        assert token.read_text()=='isolated-test-owner'
        return {'token_name':token.name,'token_mode':stat.S_IMODE(token.stat().st_mode),'state_name':state.name,
                'state_mode':stat.S_IMODE(state.stat().st_mode),'state_keys':sorted(data),'state_identity':data['agent_name'],
                'server_certificate_variable_positive_control':positive.startswith('SSL_CERT_FILE='),
                'child_process_environment':json.loads((home/'tls-process-env.json').read_text()),
                'pane_session':pane.split('|')[0],'pane_alive':pane.endswith('|0'),'launcher_exit':result.returncode}
    finally:
        subprocess.run([str(fake/'tmux'),'kill-session','-t','='+NAME],env=env,capture_output=True)
        subprocess.run([str(fake/'tmux'),'kill-session','-t','=FixtureEnvSeed'],env=env,capture_output=True)

@pytest.mark.parametrize('entry',['restart-seat','spawn-codex','spawn_child'])
def test_three_entrances_preserve_current_generation_identity(tmp_path,entry):
    old=run_arm(tmp_path/'old',entry,False);new=run_arm(tmp_path/'new',entry,True)
    assert old==new
    assert new['token_mode']==new['state_mode']==0o600
    assert new['child_process_environment']=={'ssl_cert_file_present':False,'codex_ca_certificate_present':False}
    out=ROOT/'docs/orrery-up-2';out.mkdir(exist_ok=True)
    (out/('parity-'+entry+'.json')).write_text(json.dumps({'transport':'real isolated tmux; synthetic provider/Mail; no paid API','old':old,'new':new,'equal':old==new},indent=2)+'\n')

def test_all_release_file_bytes_and_symlink_targets_are_preserved():
    inv=json.loads((ROOT/'docs/orrery-up-2/inventory.json').read_text())
    rows=[r for r in inv['rows'] if r['installed'].startswith(RELEASE+'/') and r.get('kind')=='file']
    assert len(rows)==5
    links=[r for r in inv['rows'] if r['installed'].startswith(RELEASE+'/') and r.get('kind')=='symlink']
    assert len(links)==3
    for row in links:
        assert hashlib.sha256(os.readlink(ROOT/'fleet'/row['installed']).encode()).hexdigest()==row['sha256']
    for row in rows:
        assert hashlib.sha256((ROOT/'fleet'/row['installed']).read_bytes()).hexdigest()==row['sha256']

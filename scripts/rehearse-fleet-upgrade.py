#!/usr/bin/env python3
"""Real installer rehearsal in one governor cache root; no production settings.

Use the repository's documented test service-manager stubs and teardown helpers.
It provisions a real isolated Mail database and dashboard, then stops both.
"""
from __future__ import annotations
import argparse,hashlib,json,os,pathlib,re,shutil,socket,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_install_agentstack_mail import _free_port,_stop_mail,_wait_health
from service_teardown import stop_dashboard


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=pathlib.Path,required=True);a=ap.parse_args()
    home=a.root/'rehearsal-home';home.mkdir(parents=True,exist_ok=True)
    stack=home/'.agentstack';stack.mkdir(exist_ok=True)
    inventory=json.loads((ROOT/'docs/orrery-up-1/inventory.json').read_text())
    seeded=[]
    for row in inventory['rows']:
        rel=row['installed']; archive=row.get('archive');src=row.get('source')
        if archive:raw=(ROOT/archive).read_bytes()
        elif row['disposition']=='upstream-source-no-local-delta':
            source=src or rel
            q=subprocess.run(['git','show','e5039ff:'+source],cwd=ROOT,capture_output=True)
            if q.returncode:continue
            raw=q.stdout
        else:continue
        dst=stack/rel;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(raw)
        live=pathlib.Path('/Users/huyuhutaru/.agentstack')/rel
        if live.is_file():shutil.copymode(live,dst)
        seeded.append(rel)
    project=home/'project';project.mkdir(exist_ok=True)
    # Only token-free install exports; never open runtime credential paths.
    for rel in ['env.sh','integrations/codex_app/env.sh']:
        src=pathlib.Path('/Users/huyuhutaru/.agentstack')/rel
        text=src.read_text()
        for line in text.splitlines():
            if re.match(r'export [A-Z_]*(TOKEN|SECRET|PASSWORD)[A-Z_]*=',line):
                raise ValueError('unexpected secret export; refusing to clone env')
        text=text.replace('/Users/huyuhutaru',str(home)).replace(str(home)+'/tools/examforge',str(project))
        dst=stack/rel;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_text(text);dst.chmod(0o600)
    (stack/'install-state.json').write_text(json.dumps({'install_dir':str(stack),'owned_files':[str(stack/p) for p in seeded],'schema_version':1}))
    fake=a.root/'rehearsal-fake-bin';fake.mkdir(exist_ok=True)
    for name,body in {'uname':'#!/bin/sh\necho Linux\n','systemctl':'#!/bin/sh\nexit 1\n','tmux':'#!/bin/sh\nexit 1\n'}.items():
        p=fake/name;p.write_text(body);p.chmod(0o755)
    mail_port=_free_port();dashboard_port=_free_port();mail_url=f'http://127.0.0.1:{mail_port}/mcp'
    env={k:v for k,v in os.environ.items() if not k.startswith(('AGENTSTACK_','AGS_','CHILD_','PARENT_')) and k not in ('AGENT_NAME','CODEX_HOME','PROJECT_KEY','MCP_AGENT_MAIL_TOKEN')}
    env.update(HOME=str(home),CODEX_HOME=str(home/'.codex'),PATH=str(fake)+':'+os.environ['PATH'],
        AGENTSTACK_HOME=str(stack),AGENTSTACK_PROJECT_KEY=str(project),
        AGENTSTACK_PORT=str(dashboard_port),AGENTSTACK_MCP_URL=mail_url,
        AGENTSTACK_MAIL_STATE_ROOT=str(stack/'mail'),AGENTSTACK_MAIL_SERVICE_ROOT=str(stack/'mail-service'),
        AGENTSTACK_MAIL_WATCHER_SESSION='orrery-up-1-test-unused',
        AGENTSTACK_LABEL_PREFIX='org.agentstack.test.orrery-up-1',AGENTSTACK_TERMINAL='none',
        AGENTSTACK_AUTO_OPEN_CHILD='0',AGENTSTACK_PYTHON=sys.executable,
        AGENTSTACK_CODEX_BIN=shutil.which('codex') or '',
        AGENTSTACK_SPAWN_DIRS=str(project),AGENTSTACK_SPAWN_ROOTS=str(home),
        AGENTSTACK_PROTECTED_ROOTS=str(project),AGENTSTACK_CODEX_ADD_DIRS='',
        AGENTSTACK_CODEX_MODELS='gpt-6.1-sol,gpt-6-astra,gpt-5.6-sol,gpt-5.6-terra,gpt-5.6-luna')
    result={'home':str(home),'mail_port':mail_port,'dashboard_port':dashboard_port,'seeded':len(seeded),'mode':'real isolated native Mail and dashboard; fake no-service Linux manager; scoped approvals skipped'}
    try:
        install=subprocess.run(['/bin/bash',str(ROOT/'scripts/install.sh'),'--install-dir',str(stack),'--project-key',str(project),'--scoped'],cwd=ROOT,env=env)
        result['installer_exit']=install.returncode
        if install.returncode:raise RuntimeError('isolated installer failed')
        health=_wait_health(mail_url);result['mail_health']='ready';result['mail_database_matches']=health.get('database_url','').endswith(str(stack/'mail/storage.sqlite3'))
        comparisons=[]
        for row in inventory['rows']:
            rel=row['installed'];installed=stack/rel;archive=row.get('archive');src=row.get('source')
            if row['disposition']=='historical-generation-preserved':expected=ROOT/archive
            elif row['disposition']=='local-addition-installed':expected=ROOT/src
            elif row['disposition'] in ('local-delta-merged','local-delta-manually-ported') and src and (installed.exists()):
                expected=ROOT/src
                # Optional marketplace is retained by the core installer; its
                # old bytes stay available, while core src/plugin gets new bytes.
                if '/marketplace/' in rel:expected=ROOT/archive
            else:continue
            if not installed.is_file():
                comparisons.append({'path':rel,'match':False,'reason':'missing'});continue
            left=expected.read_bytes();right=installed.read_bytes()
            if rel=='hooks/settings.template.json':
                left=left.replace(b'__AGENTSTACK_HOOKS_DIR__',str(stack/'hooks').encode())
            comparisons.append({'path':rel,'expected_sha256':hashlib.sha256(left).hexdigest(),'installed_sha256':sha(installed),'match':left==right})
        result['comparisons']=comparisons;result['comparison_failed']=sum(not x['match'] for x in comparisons)
        generated=(stack/'env.sh').read_text()
        result['custom_exports_retained']=all('export '+k+'=' in generated for k in ['AGENTSTACK_CODEX_SANDBOX','EXAMFORGE_MIN_FREE_MB','EXAMFORGE_HEAVY_SLOTS'])
        result['optional_env_preserved']=(stack/'integrations/codex_app/env.sh').read_text().endswith('export AGENTSTACK_CODEX_APP_WAKE_POLL_SECONDS=2\n')
        result['version']=(stack/'VERSION').read_text().strip()
        if result['comparison_failed'] or not result['custom_exports_retained']:raise RuntimeError('customization comparison failed')
    finally:
        stop_dashboard(home)
        _stop_mail(home,stack/'mail',mail_port)
        result['helper_processes_stopped']=True
        (ROOT/'docs/orrery-up-1/rehearsal.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({k:v for k,v in result.items() if k!='comparisons'},indent=2))
if __name__=='__main__':main()

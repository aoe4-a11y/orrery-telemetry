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
    inventory=json.loads((ROOT/'docs/orrery-up-2/inventory.json').read_text())
    seeded=[]
    for row in inventory['rows']:
        rel=row['installed'];archive=row.get('archive')
        if rel.startswith(('@home/','runtime/','mail-service/','env.sh')) or row.get('disposition') in ('untouched-generated','owner-setting-retained-hash-only','literal-values-and-codex-comments-preserved','env-history-retained-hash-only'):
            continue
        original=pathlib.Path('/Users/huyuhutaru/.agentstack')/rel
        if original.is_symlink():
            target=stack/rel;target.parent.mkdir(parents=True,exist_ok=True)
            link=os.readlink(original).replace('/Users/huyuhutaru/.agentstack',str(stack))
            target.symlink_to(link);seeded.append(rel);continue
        if not original.is_file():continue
        raw=original.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row['sha256']:
            raise ValueError('live code drift before rehearsal: '+rel)
        dst=stack/rel;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(raw)
        shutil.copymode(original,dst);seeded.append(rel)
    for row in inventory['rows']:
        rel=row['installed']
        if rel.startswith('env.sh.bak'):
            original=pathlib.Path('/Users/huyuhutaru/.agentstack')/rel
            text=original.read_text()
            if any(re.match(r'export [A-Z_]*(TOKEN|SECRET|PASSWORD)[A-Z_]*=',line) for line in text.splitlines()):
                raise ValueError('credential export in env history; refusing copy')
            shutil.copy2(original,stack/rel);seeded.append(rel)
    # Runtime scripts are explicit code inputs, never a recursive runtime copy.
    for row in inventory['rows']:
        rel=row['installed']
        if rel.startswith('runtime/') and row.get('archive'):
            dst=stack/rel;dst.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/row['archive'],dst);seeded.append(rel)
    project=home/'project';project.mkdir(exist_ok=True)
    native_tls=home/'.local/bin/codex-native-tls';native_tls.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'fleet/external/codex-native-tls',native_tls)
    # Only token-free install exports; never open runtime credential paths.
    for rel in ['env.sh','integrations/codex_app/env.sh']:
        src=pathlib.Path('/Users/huyuhutaru/.agentstack')/rel
        text=src.read_text()
        for line in text.splitlines():
            if re.match(r'export [A-Z_]*(TOKEN|SECRET|PASSWORD)[A-Z_]*=',line):
                raise ValueError('unexpected secret export; refusing to clone env')
        # Generated Mail deployment paths require their own isolated candidate,
        # not a transplanted production service.env/DB. Preserve all custom
        # operational exports, but let the documented installer provision these.
        if rel == 'env.sh':
            generated_mail_keys = {'AGENTSTACK_MAIL_ENV', 'AGENTSTACK_MAIL_DB',
                'AGENTSTACK_MAIL_HOME', 'AGENTSTACK_MAIL_DIR', 'AGENTSTACK_MAIL_STATE_ROOT',
                'AGENTSTACK_MAIL_LAUNCHD_LABEL', 'AGENTSTACK_SIGNALS_DIR'}
            text = '\n'.join(line for line in text.splitlines()
                if not any(line.startswith('export '+key+'=') for key in generated_mail_keys))+'\n'
        text=text.replace('/Users/huyuhutaru',str(home)).replace(str(home)+'/tools/examforge',str(project)).replace('/Volumes/',str(home)+'/Volumes/')
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
        AGENTSTACK_MAIL_WATCHER_SESSION='orrery-up-2-test-unused',
        AGENTSTACK_LABEL_PREFIX='org.agentstack.test.orrery-up-2',AGENTSTACK_TERMINAL='none',
        AGENTSTACK_AUTO_OPEN_CHILD='0',AGENTSTACK_PYTHON=sys.executable,
        AGENTSTACK_CODEX_BIN=str(native_tls),
        AGENTSTACK_SPAWN_DIRS=str(project),AGENTSTACK_SPAWN_ROOTS=str(home),
        AGENTSTACK_PROTECTED_ROOTS=str(project),AGENTSTACK_CODEX_ADD_DIRS='',
        AGENTSTACK_CODEX_MODELS='gpt-6.1-sol,gpt-6-astra,gpt-5.6-sol,gpt-5.6-terra,gpt-5.6-luna')
    result={'home':str(home),'mail_port':mail_port,'dashboard_port':dashboard_port,'seeded':len(seeded),'mode':'real isolated native Mail and dashboard; fake no-service Linux manager; scoped approvals skipped'}
    try:
        install=subprocess.run(['/bin/bash',str(ROOT/'scripts/install-fleet-upgrade.sh'),'--rehearsal-root',str(a.root)],cwd=ROOT,env=env)
        result['wrapper_exit']=install.returncode
        wrapper_result=a.root/'wrapper-result.json'
        if wrapper_result.is_file():result.update(json.loads(wrapper_result.read_text()))
        else:result['installer_exit']=install.returncode
        if install.returncode:raise RuntimeError('isolated installer failed')
        health=_wait_health(mail_url);result['mail_health']='ready';result['mail_database_matches']=health.get('database_url','').endswith(str(stack/'mail/storage.sqlite3'))
        comparisons=[]
        for row in inventory['rows']:
            if row['installed'].startswith('env.sh.bak'):
                comparisons.append({'path':row['installed'],'match':sha(stack/row['installed'])==row['sha256'],'kind':'env-history-exact'})
        import difflib
        differences=[]
        for row in inventory['rows']:
            rel=row['installed'];installed=stack/rel
            if rel.startswith(('@home/','env.sh')) or row.get('disposition') in ('untouched-generated','owner-setting-retained-hash-only','literal-values-and-codex-comments-preserved','env-history-retained-hash-only'):
                continue
            if not installed.exists() and not installed.is_symlink():
                comparisons.append({'path':rel,'match':False,'reason':'missing'});continue
            if rel.startswith('integrations/codex_app/') and not rel.startswith(('integrations/codex_app/src/','integrations/codex_app/plugin/')):
                comparisons.append({'path':rel,'match':sha(installed)==row['sha256'],'kind':'existing-optional-install-retained','expected_sha256':row['sha256'],'installed_sha256':sha(installed)})
                continue
            expected=ROOT/row['source'] if row.get('source') else None
            if row.get('disposition')=='versioned-compatibility-default':
                expected=None # dispatcher checked against explicit identity below
            if row.get('archive') and ('.bak' in pathlib.Path(rel).name or rel.startswith('launchd/')):
                expected=ROOT/row['archive']
            if row.get('kind')=='symlink':
                comparisons.append({'path':rel,'match':installed.is_symlink(),'kind':'symlink'});continue
            if expected is None or not expected.is_file():
                if row.get('state')=='unchanged':
                    # Latest upstream is expected for unmodified core files.
                    continue
                expected=ROOT/row['archive'] if row.get('archive') else None
            if rel in ('hooks/spawn_child.sh','hooks/cleanup-child-agent.sh','bin/agentstack-preregister-child'):
                comparisons.append({'path':rel,'match':'.upstream' in installed.read_text(),'kind':'dispatcher'})
                continue
            if expected is not None and expected.is_file():
                left=expected.read_bytes();right=installed.read_bytes()
                if rel=='hooks/settings.template.json':left=left.replace(b'__AGENTSTACK_HOOKS_DIR__',str(stack/'hooks').encode())
                if rel.startswith('integrations/codex_app/marketplace/') and row.get('archive'):left=(ROOT/row['archive']).read_bytes()
                comparisons.append({'path':rel,'expected_sha256':hashlib.sha256(left).hexdigest(),'installed_sha256':sha(installed),'match':left==right})
                live=pathlib.Path('/Users/huyuhutaru/.agentstack')/rel
                if live.is_file() and not live.is_symlink() and live.read_bytes()!=right:
                    differences.extend(difflib.unified_diff(live.read_text().splitlines(True),installed.read_text().splitlines(True),fromfile='live/'+rel,tofile='installed/'+rel))
        (ROOT/'docs/orrery-up-2/live-to-install.diff').write_text(''.join(differences))
        result['comparisons']=comparisons;result['comparison_failed']=sum(not x['match'] for x in comparisons)
        generated=(stack/'env.sh').read_text()
        old_env=pathlib.Path('/Users/huyuhutaru/.agentstack/env.sh').read_text().replace('/Users/huyuhutaru',str(home)).replace(str(home)+'/tools/examforge',str(project)).replace('/Volumes/',str(home)+'/Volumes/')
        (ROOT/'docs/orrery-up-2/env-preservation.diff').write_text(''.join(difflib.unified_diff(old_env.splitlines(True),generated.splitlines(True),fromfile='before/env.sh',tofile='after/env.sh')))
        result['native_tls_bin_retained']=('export AGENTSTACK_CODEX_BIN='+str(native_tls)) in generated
        result['native_tls_comments_retained']=all(line in generated for line in pathlib.Path('/Users/huyuhutaru/.agentstack/env.sh').read_text().splitlines() if line.startswith('# 2026-10-22 head:') or line.startswith('# 席の Codex'))
        manifest=json.loads((stack/'install-state.json').read_text())
        result['native_tls_manifest_retained']=manifest['env']['AGENTSTACK_CODEX_BIN']==str(native_tls)
        result['custom_exports_retained']=all('export '+k+'=' in generated for k in ['AGENTSTACK_CODEX_SANDBOX','EXAMFORGE_MIN_FREE_MB','EXAMFORGE_HEAVY_SLOTS'])
        result['optional_env_preserved']=(stack/'integrations/codex_app/env.sh').read_text().endswith('export AGENTSTACK_CODEX_APP_WAKE_POLL_SECONDS=2\n')
        result['version']=(stack/'VERSION').read_text().strip()
        import urllib.request
        with urllib.request.urlopen(f'http://127.0.0.1:{dashboard_port}/api/version',timeout=5) as response:
            result['dashboard_version']=json.load(response)
        result['rollback_snapshot']=str(a.root/'rollback/payload-before-upgrade')
        if result['comparison_failed'] or not result['custom_exports_retained'] or not all(result[k] for k in ('native_tls_bin_retained','native_tls_comments_retained','native_tls_manifest_retained')):raise RuntimeError('customization comparison failed')
    finally:
        stop_dashboard(home, label_prefix='org.agentstack.test.orrery-up-2')
        _stop_mail(home,stack/'mail',mail_port)
        import time
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            with socket.socket() as probe:
                if probe.connect_ex(('127.0.0.1',dashboard_port))!=0:break
            time.sleep(.1)
        result['helper_processes_stopped']=True
        for label,port in [('mail',mail_port),('dashboard',dashboard_port)]:
            with socket.socket() as probe:
                stopped=probe.connect_ex(('127.0.0.1',port))!=0
            result[label+'_port_closed']=stopped
            if not stopped:raise RuntimeError(label+' process still listening')
        (ROOT/'docs/orrery-up-2/rehearsal.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({k:v for k,v in result.items() if k!='comparisons'},indent=2))
if __name__=='__main__':main()

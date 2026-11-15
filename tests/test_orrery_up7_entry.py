"""Exercise the owner entry with synthetic tools and a pseudo-terminal."""
import json
import os
from pathlib import Path
import pty
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class EntryTest(unittest.TestCase):
    def run_entry(self, fail_cycle, fail_final=False):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary); home=base/'home'; backup=home/'.agentstack/backups'; backup.mkdir(parents=True)
            project=home/'project'; project.mkdir(); repo=home/'repo'; repo.mkdir(); bindir=base/'bin'; bindir.mkdir()
            owner=base/'owner'; owner.mkdir(); trace=base/'trace'; installer=base/'installer'
            def script(name, text):
                p=bindir/name; p.write_text(text); p.chmod(0o755)
            script('git', '#!/bin/sh\ncase "$*" in *rev-parse*) echo 0123456789012345678901234567890123456789;; esac\n')
            script('dev-storage-governor', '#!/bin/sh\nprintf "%s\\n" "$TEST_OWNER_ROOT"\n')
            script('agentstack-station-materials', '''#!/bin/bash
while (($#)); do if [[ "$1" == --destination ]]; then dest="$2"; shift 2; else shift; fi; done
mkdir -p "$dest/scripts"
cp "$TEST_INSTALL_STUB" "$dest/scripts/install.sh"
''')
            installer.write_text('''#!/bin/bash
printf 'update\\n' >> "$TEST_TRACE"
printf '{"agent_mail":{"update":{"result":"switched","outage_seconds":"1.0"}}}\\n' > "$HOME/.agentstack/install-state.json"
''')
            script('python3', '''#!/usr/bin/python3
import hashlib,json,os,pathlib,sys
args=sys.argv[1:]
if not args or args[0]=='-': os.execv('/usr/bin/python3',['/usr/bin/python3',*args])
name=pathlib.Path(args[0]).name
def arg(name): return pathlib.Path(args[args.index(name)+1])
def trace(event):
    with open(os.environ['TEST_TRACE'],'a') as f:f.write(event+'\\n')
if name=='pre-install-snapshot.py':
    if '--plan-output' in args:
        plan=arg('--plan-output');trace('final-plan' if '-final-plan-' in plan.name else 'pre-plan');plan.write_text('[]\\n')
    elif '--verify-manifest-sha' in args:
        trace('final-verify' if '-final-' in arg('--destination').name else 'pre-verify')
    elif '--verify-manifest-sha' not in args:
        dest=arg('--destination');is_final='-final-' in dest.name;trace('final-snapshot' if is_final else 'pre-snapshot')
        if is_final and os.environ.get('TEST_FAIL_FINAL')=='1':sys.exit(1)
        dest.mkdir(mode=0o700);raw=b'[]\\n';(dest/'manifest.json').write_bytes(raw)
        print(json.dumps({'manifest_sha256':hashlib.sha256(raw).hexdigest()}))
    sys.exit(0)
if name=='pre-install-mail-cycle.py':
    with open(os.environ['TEST_TRACE'],'a') as f:f.write('cycle\\n')
    if os.environ.get('TEST_FAIL_CYCLE')=='1':sys.exit(1)
    dest=arg('--snapshot')/'mail-database';dest.mkdir();raw=b'{}\\n';(dest/'manifest.json').write_bytes(raw)
    print(json.dumps({'mail_manifest_sha256':hashlib.sha256(raw).hexdigest(),'preinstall_outage_seconds':1.2}));sys.exit(0)
os.execv('/usr/bin/python3',['/usr/bin/python3',*args])
''')
            env={'HOME':str(home),'PATH':str(bindir)+':/usr/bin:/bin:/usr/sbin:/sbin',
                 'AGENTSTACK_UPGRADE_REPO':str(repo),'AGENTSTACK_UPGRADE_REF':'fixture',
                 'AGENTSTACK_PROJECT_KEY':str(project),'TEST_OWNER_ROOT':str(owner),
                 'TEST_INSTALL_STUB':str(installer),'TEST_TRACE':str(trace),
                 'TEST_FAIL_CYCLE':'1' if fail_cycle else '0','TEST_FAIL_FINAL':'1' if fail_final else '0'}
            master,slave=pty.openpty()
            try:
                result=subprocess.run(['/bin/bash',str(ROOT/'scripts/run-mail-fetch-upgrade-from-ref.sh')],
                                      stdin=slave,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                      text=True,env=env,timeout=45)
            finally: os.close(slave);os.close(master)
            actions=trace.read_text().splitlines() if trace.exists() else []
            return result.returncode,actions,result.stderr
    def test_cycle_success_hands_off_to_update(self):
        code,actions,err=self.run_entry(False)
        self.assertEqual(code,0,err);self.assertEqual(actions,['pre-plan','pre-snapshot','pre-verify','cycle',
            'final-plan','final-snapshot','final-verify','update'])
    def test_cycle_failure_never_starts_installer(self):
        code,actions,_=self.run_entry(True)
        self.assertNotEqual(code,0);self.assertEqual(actions,['pre-plan','pre-snapshot','pre-verify','cycle'])
    def test_final_snapshot_failure_never_starts_installer(self):
        code,actions,_=self.run_entry(False,True)
        self.assertNotEqual(code,0);self.assertEqual(actions,['pre-plan','pre-snapshot','pre-verify','cycle',
            'final-plan','final-snapshot'])

if __name__=='__main__':unittest.main()

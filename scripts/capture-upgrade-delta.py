#!/usr/bin/env python3
"""Extend ORRERY-UP-1's inventory, excluding credential and generated state.

Code is archived before three-way merges; conflicts are never installed.
"""
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LIVE = Path('/Users/huyuhutaru/.agentstack')
OUT = ROOT/'docs/orrery-up-2'
OLD = ROOT/'docs/orrery-up-1/inventory.json'
LIB = runpy.run_path(str(ROOT/'scripts/capture-local-upgrade.py'))
RELEASE = 'releases/seat-lifecycle/ee5880e3e23606e0f3252cbeed211868102f4595'

def sha(raw): return hashlib.sha256(raw).hexdigest()
def raw(path):
    return os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
def blob(ref, rel):
    p = subprocess.run(['git','show',ref+':'+rel],cwd=ROOT,capture_output=True)
    return p.stdout if p.returncode == 0 else None
def write(rel, data, mode=0o644):
    p=ROOT/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);p.chmod(mode)
def excluded(rel):
    return (any(x in Path(rel).parts for x in ('__pycache__','.pytest_cache','.git','.venv','node_modules'))
        or rel.endswith(('.pyc','.pyo','.sqlite3','.db')))

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    old=json.loads(OLD.read_text()); before={r['installed']:r for r in old['rows']}
    rows=[]; additions=[]; conflicts=[]
    candidates=set(before)
    for name in ('bin','hooks','config','skills','dashboard','integrations','claude','codex','launchd',RELEASE):
        for base, dirs, files in os.walk(LIVE/name,followlinks=False):
            dirs[:]=[d for d in dirs if not excluded(d)]
            for f in files:
                rel=str((Path(base)/f).relative_to(LIVE))
                if not excluded(rel) and not any(x in f.lower() for x in ('agent_token_','auth.json','credential','secret')):
                    candidates.add(rel)
    # Runtime contents are not traversed: only explicitly identified shell/Python code.
    for p in (LIVE/'runtime').iterdir():
        if p.suffix in ('.sh','.py') and p.is_file() and not any(x in p.name.lower() for x in ('token','credential','secret')):
            candidates.add(str(p.relative_to(LIVE)))
    # Historical code files after the previous capture, not mail/DB/log backups.
    for p in (LIVE/'backups').iterdir():
        if p.is_file() and p.suffix in ('.py','.sh') and p.stat().st_mtime >= 1759276800+365*86400:
            candidates.add(str(p.relative_to(LIVE)))
    for rel in sorted(candidates):
        prior=before.get(rel,{});p=Path('/Users/huyuhutaru')/rel[6:] if rel.startswith('@home/') else LIVE/rel
        row={'installed':rel,'old_sha256':prior.get('live_sha256'),'old_disposition':prior.get('disposition')}
        rows.append(row)
        if rel.startswith(('mail-service/','runtime/')) and not (rel.startswith('runtime/') and p.suffix in ('.sh','.py')) or excluded(rel):
            row.update(state='generated-excluded',disposition='untouched-generated');continue
        if not p.exists() and not p.is_symlink():row.update(state='deleted',disposition='not-reintroduced');continue
        data=raw(p);row.update(sha256=sha(data),bytes=len(data),kind='symlink' if p.is_symlink() else 'file')
        row['state']='new' if rel not in before else 'unchanged' if row['sha256']==prior.get('live_sha256') else 'changed'
        source=prior.get('source') or LIB['source_for'](rel,ROOT)
        row['source']=source
        if row['state']=='unchanged':row['disposition']='retained-by-up1-merge';continue
        if rel.startswith('@home/') or rel.startswith('env.sh') or rel.endswith('env.sh') or rel.endswith('.plist') or p.is_symlink():
            row['disposition']='owner-setting-retained-hash-only';continue
        data=LIB['safe_code'](p)
        archive='docs/orrery-up-2/live-code/'+rel;write(archive,data,p.stat().st_mode&0o777);row['archive']=archive
        if '.bak' in p.name or rel.startswith(('backups/','launchd/',RELEASE+'/legacy/')):
            row['disposition']='historical-code-preserved';continue
        if rel.startswith(RELEASE+'/hooks/'):
            # Preserve the release in full; integrate effective hooks below.
            row['disposition']='release-code-preserved';continue
        if rel in ('hooks/spawn_child.sh','hooks/cleanup-child-agent.sh'):
            data=LIB['safe_code'](LIVE/RELEASE/'hooks'/p.name)
            row['effective_live']=RELEASE+'/hooks/'+p.name
        if rel.startswith('runtime/'):
            source='fleet/'+rel;write(source,data,p.stat().st_mode&0o777);row.update(source=source,disposition='local-addition-installed');additions.append(source);continue
        if source is None and rel.startswith(('bin/','hooks/','config/')):source=rel
        if source is None:
            row['disposition']='retained-outside-core-installer';continue
        row['source']=source
        ancestor=None
        if prior.get('archive'):
            q=ROOT/prior['archive']
            if q.is_file() and sha(q.read_bytes())==prior.get('live_sha256'):ancestor=q.read_bytes()
        if ancestor is None:
            test=blob('e5039ff',source)
            if test is not None and sha(test)==prior.get('live_sha256'):ancestor=test
        current=ROOT/source
        if not current.is_file():
            write(source,data,p.stat().st_mode&0o777);row['disposition']='local-addition-installed';additions.append(source)
        elif ancestor is not None:
            base=OUT/'merge-inputs'/rel;base.parent.mkdir(parents=True,exist_ok=True);base.write_bytes(ancestor)
            local=base.with_name(base.name+'.local');local.write_bytes(data)
            merged=subprocess.run(['git','merge-file','-p',str(current),str(base),str(local)],capture_output=True)
            if merged.returncode==0:current.write_bytes(merged.stdout);row['disposition']='delta-merged'
            else:
                review='docs/orrery-up-2/merge-review/'+rel;write(review,merged.stdout)
                row.update(disposition='pending-conflict',review=review);conflicts.append(rel)
        elif current.read_bytes()==data:row['disposition']='already-equivalent'
        elif rel not in before:
            row['disposition']='pending-new-path-collision';conflicts.append(rel)
        else:
            row['disposition']='pending-unknown-baseline';conflicts.append(rel)
    result={'source_root':str(LIVE),'old_inventory_sha256':sha(OLD.read_bytes()),'counts':dict(collections.Counter(r['state'] for r in rows)), 'rows':rows}
    (OUT/'inventory.json').write_text(json.dumps(result,indent=2)+'\n')
    (OUT/'addon-paths.json').write_text(json.dumps(additions,indent=2)+'\n')
    print(json.dumps({'counts':result['counts'],'conflicts':conflicts,'addons':len(additions)},indent=2))

if __name__=='__main__':main()

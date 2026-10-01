#!/usr/bin/env python3
"""Copy/restore upgrade-owned payloads; never traverse Mail or runtime state."""
from __future__ import annotations
import argparse,hashlib,json,os,pathlib,shutil,sys

PAYLOAD=('bin','hooks','skills','dashboard','codex','claude','integrations/codex_app','VERSION','env.sh','install-state.json')
EXTERNAL=('.claude/settings.json','.claude.json','.claude/CLAUDE.md','.codex/AGENTS.md')

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def snapshot(home, dest, project_key=None, codex_home=None):
    if dest.exists():raise ValueError('snapshot destination already exists')
    live=home/'.agentstack'
    if not live.is_dir():raise ValueError('existing install not found')
    dest.mkdir(parents=True,mode=0o700);os.chmod(dest,0o700)
    records=[]
    def copy(path, rel):
        if path.is_symlink():
            records.append({'path':str(rel),'kind':'symlink','target':os.readlink(path)})
            return
        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.name in ('__pycache__','.venv','runtime','mail','proxy-runtime'):continue
                copy(child,rel/child.name)
        elif path.is_file():
            dst=dest/'files'/rel;dst.parent.mkdir(parents=True,exist_ok=True,mode=0o700);shutil.copy2(path,dst)
            records.append({'path':str(rel),'kind':'file','sha256':digest(dst),'mode':path.stat().st_mode&0o777})
    for name in PAYLOAD:
        p=live/name
        if p.exists() or p.is_symlink():copy(p,pathlib.Path('.agentstack')/name)
    for name in EXTERNAL:
        p=home/name
        if p.is_file():copy(p,pathlib.Path(name))
    for extra in [project_key/'CLAUDE.md' if project_key else None,
                  codex_home/'AGENTS.md' if codex_home else None]:
        if extra is not None and extra.is_file():
            if not extra.is_relative_to(home):raise ValueError('managed document is outside the recorded home')
            rel=extra.relative_to(home)
            if not any(row['path']==str(rel) for row in records):copy(extra,rel)
    # Save this installation's service definitions; exclude every other owner's label.
    for p in (home/'Library/LaunchAgents').glob('org.agentstack*.plist'):
        if p.is_file():copy(p,p.relative_to(home))
    manifest={'home':str(home),'records':records,'excluded':['.agentstack/mail','.agentstack/runtime','.agentstack/mail-service']}
    (dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');os.chmod(dest/'manifest.json',0o600)
    return len(records)

def restore(home,dest):
    manifest=json.loads((dest/'manifest.json').read_text())
    if manifest['home']!=str(home):raise ValueError('snapshot home does not match destination')
    for row in manifest['records']:
        rel=pathlib.Path(row['path'])
        if rel.is_absolute() or '..' in rel.parts:raise ValueError('invalid snapshot path')
        if row['kind']=='file' and digest(dest/'files'/rel)!=row['sha256']:raise ValueError('snapshot integrity check failed')
    for row in manifest['records']:
        target=home/row['path'];target.parent.mkdir(parents=True,exist_ok=True)
        if row['kind']=='file':
            if target.is_symlink():target.unlink()
            shutil.copy2(dest/'files'/row['path'],target)
        elif row['kind']=='symlink':
            if target.is_symlink():target.unlink()
            elif target.exists():raise ValueError('symlink restore would replace an unexpected real path')
            target.symlink_to(row['target'])
    return len(manifest['records'])

def main():
    ap=argparse.ArgumentParser();ap.add_argument('operation',choices=['snapshot','restore']);ap.add_argument('--home',type=pathlib.Path,required=True);ap.add_argument('--directory',type=pathlib.Path,required=True);ap.add_argument('--project-key',type=pathlib.Path);ap.add_argument('--codex-home',type=pathlib.Path);a=ap.parse_args()
    if not a.home.is_absolute() or not a.directory.is_absolute():ap.error('absolute paths required')
    n=snapshot(a.home,a.directory,a.project_key,a.codex_home) if a.operation=='snapshot' else restore(a.home,a.directory)
    print(json.dumps({'operation':a.operation,'records':n,'manifest':str(a.directory/'manifest.json'),'manifest_sha256':digest(a.directory/'manifest.json'),'mail_and_runtime':'untouched'}))
if __name__=='__main__':main()

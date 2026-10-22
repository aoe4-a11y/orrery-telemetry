#!/usr/bin/env python3
"""Inventory a live install without ever opening runtime credentials or databases.

Capture code-only deltas and backup generations; generated state is hash-only.
Run once in an isolated upgrade worktree. Never writes to the live source.
"""
import argparse, hashlib, json, pathlib, re, shutil, subprocess

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def blob(ref, path):
    p=subprocess.run(['git','show',f'{ref}:{path}'],capture_output=True)
    return p.stdout if p.returncode==0 else None

def source_for(rel, repo):
    aliases={'bin/agentstack-doctor':'scripts/doctor.sh','bin/agentstack-selftest':'scripts/selftest.py','bin/agentstack-uninstall':'scripts/uninstall.sh','bin/agentstack-merge-settings':'scripts/lib/merge_settings.py','bin/agentstack-merge-claude-mcp':'scripts/lib/merge_claude_mcp.py','bin/lib/mcp_endpoint.py':'scripts/lib/mcp_endpoint.py', 'integrations/codex_app/bin/doctor-codex-app-integration':'scripts/doctor-codex-app-integration.sh','integrations/codex_app/bin/run-bridge':'scripts/run-codex-app-bridge.sh','integrations/codex_app/bin/uninstall-codex-app-integration':'scripts/uninstall-codex-app-integration.sh'}
    if rel in aliases:return aliases[rel]
    prefix='integrations/codex_app/marketplace/plugins/agentstack-codex-app/'
    if rel.startswith(prefix):
        suffix=rel[len(prefix):]
        return 'integrations/codex_app/'+suffix if suffix.startswith(('src/','schemas/')) else 'integrations/codex_app/plugin/'+suffix
    if (repo/rel).is_file():return rel
    return None

def safe_code(p):
    raw=p.read_bytes()
    if b'\x00' in raw:raise ValueError('non-text code: '+str(p))
    if re.search(rb'(?:sk-(?:proj-)?[A-Za-z0-9_-]{24,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})',raw):
        raise ValueError('credential-shaped literal: '+str(p))
    return raw

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=pathlib.Path,required=True);ap.add_argument('--base',default='e5039ff');args=ap.parse_args()
    repo=pathlib.Path.cwd();h=args.source;out=repo/'docs/orrery-up-1';out.mkdir(parents=True,exist_ok=True)
    state=json.loads((h/'install-state.json').read_text());owned={str(pathlib.Path(x).relative_to(h)) for x in state['owned_files'] if pathlib.Path(x).is_relative_to(h)}
    rows=[];addons=[];conflicts=[]
    candidates=set(owned)
    for root in ['bin','hooks','config']:
        candidates.update(str(p.relative_to(h)) for p in (h/root).rglob('*') if p.is_file() and '__pycache__' not in str(p))
    candidates.update(str(p.relative_to(h)) for p in (h/'integrations/codex_app').rglob('*') if p.is_file() and '.bak' in p.name)
    for rel in sorted(candidates):
        p=h/rel;row={'installed':rel,'owned':rel in owned}
        if not p.is_file():row['disposition']='absent';rows.append(row);continue
        row['live_sha256']=sha(p)
        generated=('__pycache__' in rel or rel.endswith('.pyc') or rel.startswith(('runtime/','mail-service/')) or rel.endswith(('env.sh','install-state.json','.plist')) or '/marketplace/.agents/' in rel)
        is_backup='.bak' in p.name
        if is_backup and p.name.startswith('env.sh'):
            row['disposition']='generated-env-history-hash-only';rows.append(row);continue
        if generated:
            row['disposition']='generated-retained-or-rerendered';rows.append(row);continue
        if is_backup:
            dest=out/'backup-generations'/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(safe_code(p));shutil.copymode(p,dest)
            row.update(disposition='historical-generation-preserved',archive=str(dest.relative_to(repo)));rows.append(row);continue
        mapped=source_for(rel,repo);row['source']=mapped
        base=blob(args.base,mapped) if mapped else None
        cur=p.read_bytes()
        if base==cur:
            row['disposition']='upstream-source-no-local-delta';rows.append(row);continue
        cur=safe_code(p)
        if mapped is None or (base is None and rel.startswith(('bin/','hooks/','config/'))):
            if not rel.startswith(('bin/','hooks/','config/')):
                row['disposition']='generated-artifact-no-source';rows.append(row);continue
            mapped=rel;row['source']=mapped;dest=repo/mapped;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(cur);shutil.copymode(p,dest);addons.append(mapped);row['disposition']='local-addition-installed'
        else:
            dest=repo/mapped
            archive=out/'live-code'/rel;archive.parent.mkdir(parents=True,exist_ok=True);archive.write_bytes(cur);shutil.copymode(p,archive);row['archive']=str(archive.relative_to(repo))
            if base is None:
                row['disposition']='source-without-old-baseline-review';conflicts.append(rel)
            else:
                local=out/'merge-inputs'/rel;local.parent.mkdir(parents=True,exist_ok=True);local.write_bytes(cur)
                ancestor=local.with_name(local.name+'.ancestor');ancestor.write_bytes(base)
                merged=subprocess.run(['git','merge-file','-p',str(dest),str(ancestor),str(local)],capture_output=True)
                if merged.returncode==0:
                    dest.write_bytes(merged.stdout);row['disposition']='local-delta-merged'
                else:
                    conflict=out/'merge-review'/rel;conflict.parent.mkdir(parents=True,exist_ok=True);conflict.write_bytes(merged.stdout);row['disposition']='local-delta-conflict-review';conflicts.append(rel)
        rows.append(row)
    (out/'inventory.json').write_text(json.dumps({'source_root':str(h),'base':args.base,'owned_count':len(state['owned_files']),'rows':rows},indent=2)+'\n')
    (out/'addon-paths.json').write_text(json.dumps(addons,indent=2)+'\n')
    print(json.dumps({'rows':len(rows),'addons':len(addons),'conflicts':conflicts},indent=2))
if __name__=='__main__':main()

#!/usr/bin/env python3
"""Read-only audit of code paths and hashes; never traverse runtime credentials."""
import hashlib,json,os,runpy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
lib=runpy.run_path(str(ROOT/'scripts/capture-upgrade-delta.py'))
LIVE=lib['LIVE']; excluded=lib['excluded']; RELEASE=lib['RELEASE']
d=json.loads((ROOT/'docs/orrery-up-2/inventory.json').read_text())
known={r['installed']:r for r in d['rows']};found=set()
scopes=('bin','hooks','config','skills','dashboard','integrations','claude','codex','launchd',RELEASE)
for scope in scopes:
 for base,dirs,files in os.walk(LIVE/scope,followlinks=False):
  dirs[:]=[x for x in dirs if not excluded(x)]
  for name in files:
   rel=str((Path(base)/name).relative_to(LIVE))
   if not excluded(rel) and not any(x in name.lower() for x in ('agent_token_','auth.json','credential','secret')):found.add(rel)
for path in (LIVE/'runtime').iterdir():
 if path.suffix in ('.sh','.py') and path.is_file() and not any(x in path.name.lower() for x in ('token','credential','secret')):found.add(str(path.relative_to(LIVE)))
for path in (LIVE/'backups').iterdir():
 if path.is_file() and path.suffix in ('.py','.sh') and path.stat().st_mtime>=1790784000:found.add(str(path.relative_to(LIVE)))
drift=[];missing=[]
for rel,row in known.items():
 if 'sha256' not in row:continue
 path=Path('/Users/huyuhutaru')/rel[6:] if rel.startswith('@home/') else LIVE/rel
 if not path.exists() and not path.is_symlink():missing.append(rel);continue
 raw=os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=row['sha256']:drift.append(rel)
result={'scopes':scopes,'scanned_code_paths':len(found),'recorded_rows':len(known),'new_unrecorded':sorted(found-known.keys()),'missing':missing,'changed_after_capture':drift,'generated_excluded':sum(r['state']=='generated-excluded' for r in known.values()),'runtime_policy':'enumerate top-level names; read only .sh/.py code, never credentials/state/DB'}
(ROOT/'docs/orrery-up-2/inventory-audit.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
raise SystemExit(bool(result['new_unrecorded'] or missing or drift))

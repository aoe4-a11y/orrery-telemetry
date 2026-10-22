#!/usr/bin/env python3
"""Install the approved versioned fleet compatibility payload, without credentials."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
RELEASE='releases/seat-lifecycle/ee5880e3e23606e0f3252cbeed211868102f4595'

def record_manifest(dest, records):
    manifest=dest/"install-state.json"
    if manifest.is_file():
        data=json.loads(manifest.read_text());data["owned_files"]=sorted(set(data.get("owned_files",[]))|{str(dest/r["path"]) for r in records}|{str(dest/"fleet-install.json")})
        manifest.write_text(json.dumps(data,indent=2)+"\n")

def install(dest):
    records=[]
    def put(source,relative):
        target=dest/relative;target.parent.mkdir(parents=True,exist_ok=True)
        if target.is_symlink():target.unlink()
        shutil.copy2(source,target)
        records.append({'path':relative,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    def script(relative,text):
        target=dest/relative;target.write_text(text);target.chmod(0o755)
        records.append({'path':relative,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    for base,dirs,files in os.walk(ROOT/'fleet'/RELEASE):
        for name in files:
            source=Path(base)/name;rel=str(source.relative_to(ROOT/'fleet'))
            if source.is_symlink():
                target=dest/rel;target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists() or target.is_symlink():target.unlink()
                target.symlink_to('../../../../hooks/'+name)
                records.append({'path':rel,'symlink':os.readlink(target)})
            else:put(source,rel)
    # Keep all upstream entry bodies at explicit alternate paths. Their helpers
    # remain adjacent in the ordinary hooks/bin tree.
    for name in ('spawn_child.sh','cleanup-child-agent.sh'):
        put(ROOT/'hooks'/name,'hooks/'+name.removesuffix('.sh')+'.upstream.sh')
    put(ROOT/'bin/agentstack-preregister-child','bin/agentstack-preregister-child.upstream')
    for name in ('spawn_child.sh','cleanup-child-agent.sh'):
        prelude='#!/bin/bash\nset -euo pipefail\nSTACK="${AGENTSTACK_HOME:-$HOME/.agentstack}"\n'
        prelude+='if [[ "${AGENTSTACK_FLEET_SPAWN:-legacy}" == upstream ]]; then\n'
        prelude+='    unset AGENTSTACK_LIFECYCLE_HOOKS_DIR\n    export AGENTSTACK_HOOKS_DIR="$STACK/hooks"\n'
        prelude+='    exec /bin/bash "$STACK/hooks/'+name.removesuffix('.sh')+'.upstream.sh" "$@"\nfi\n'
        if name=='spawn_child.sh':
            text=prelude+'export AGENTSTACK_HOME="$STACK"\nexport AGENTSTACK_HOOKS_DIR="$STACK/hooks"\nexport AGENTSTACK_LIFECYCLE_HOOKS_DIR="$STACK/'+RELEASE+'/hooks"\nexec /bin/bash "$AGENTSTACK_LIFECYCLE_HOOKS_DIR/spawn_child.sh" "$@"\n'
        else:
            original=(ROOT/'docs/orrery-up-2/live-code/hooks/cleanup-child-agent.sh').read_text()
            original=original.replace('#!/bin/bash\n','',1).replace('/Users/huyuhutaru/.agentstack','$STACK')
            text=prelude+original
        script('hooks/'+name,text)
    old=(ROOT/'fleet/bin/agentstack-preregister-child').read_text()
    select='if [[ "${AGENTSTACK_FLEET_SPAWN:-legacy}" == upstream ]]; then\n    exec "${AGENTSTACK_HOME:-$HOME/.agentstack}/bin/agentstack-preregister-child.upstream" "$@"\nfi\n'
    script('bin/agentstack-preregister-child',old.replace('set -euo pipefail\n','set -euo pipefail\n'+select,1))
    addons=json.loads((ROOT/'docs/orrery-up-2/addon-paths.json').read_text())
    for rel in addons:
        if rel.startswith('fleet/runtime/'):put(ROOT/rel,rel.removeprefix('fleet/'))
        elif rel.startswith(('bin/','hooks/')):put(ROOT/rel,rel)
    for rel in ('bin/agentstack-spawn-codex','bin/agentstack-restart-seat'):
        put(ROOT/'fleet'/rel,rel)
    env=dest/'env.sh'
    text=env.read_text() if env.is_file() else ''
    text='\n'.join(line for line in text.splitlines() if not line.startswith('export AGENTSTACK_FLEET_COMPAT='))+'\nexport AGENTSTACK_FLEET_COMPAT=1\n'
    env.write_text(text);env.chmod(0o600)
    report={'policy':'head mail 35265; legacy generation is default; upstream is explicit','files':records}
    (dest/'fleet-install.json').write_text(json.dumps(report,indent=2)+'\n')
    record_manifest(dest, records)
    return report

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--install-dir',type=Path,required=True);ap.add_argument('--record-only',action='store_true');a=ap.parse_args()
    if not a.install_dir.is_absolute():ap.error('absolute install-dir required')
    if a.record_only:
        result=json.loads((a.install_dir/"fleet-install.json").read_text())
        record_manifest(a.install_dir,result["files"])
    else:
        result=install(a.install_dir)
    print(json.dumps({'fleet_files':len(result['files']),'default':'legacy','upstream':'explicit opt-in'}))

#!/usr/bin/env python3
"""Install the approved versioned fleet compatibility payload, without credentials."""
import argparse
import ast
import hashlib
import json
import os
import re
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
RELEASE='releases/seat-lifecycle/ee5880e3e23606e0f3252cbeed211868102f4595'

def record_manifest(dest, records):
    manifest=dest/"install-state.json"
    if manifest.is_file():
        data=json.loads(manifest.read_text());data["owned_files"]=sorted(set(data.get("owned_files",[]))|{str(dest/r["path"]) for r in records}|{str(dest/"fleet-install.json")})
        manifest.write_text(json.dumps(data,indent=2)+"\n")

def fleet_configuration(dest):
    """Carry the installed fleet's two local paths without putting them in Git."""
    project = os.environ.get("AGENTSTACK_FLEET_MATERIALS_PROJECT", "")
    extra = os.environ.get("AGENTSTACK_FLEET_CLAUDE_ADD_DIR", "")
    if not project or not extra:
        previous = dest / RELEASE / "hooks/spawn_child.sh"
        if previous.is_symlink() or not previous.is_file():
            raise ValueError("fleet configuration unavailable; existing release source or explicit settings required")
        old = previous.read_text(encoding="utf-8")
        projects = re.findall(r'\[\[ "\$\{AGENTSTACK_MATERIALS_APPENDED:-0\}" != 1 && "\$PROJECT_KEY" == "([^"\n]+)"', old)
        extras = re.findall(r'--add-dir (/[A-Za-z0-9_./-]+)', old)
        if not project and len(projects) == 1:
            project = projects[0]
        if not extra and len(extras) == 1:
            extra = extras[0]
    if not all(re.fullmatch(r"/[A-Za-z0-9_./-]+", value) for value in (project, extra)):
        raise ValueError("fleet configuration unavailable or unsafe; fleet payload was not written")
    return project, extra


def prepared_release(dest):
    project, extra = fleet_configuration(dest)
    template = ROOT / 'fleet' / RELEASE / 'hooks/spawn_child.sh'
    text = template.read_text(encoding='utf-8')
    if text.count('__FLEET_MATERIALS_PROJECT__') != 1 or text.count('__FLEET_CLAUDE_EXTRA_DIR__') != 1:
        raise ValueError("fleet release template invalid; fleet payload was not written")
    return template, text.replace('__FLEET_MATERIALS_PROJECT__', project).replace('__FLEET_CLAUDE_EXTRA_DIR__', extra)


def prepared_station(dest):
    """Render installed station configuration while preserving it outside Git."""
    previous = dest / 'bin/agentstack-station-materials'
    if previous.is_symlink() or not previous.is_file():
        raise ValueError("installed station configuration unavailable; fleet payload was not written")
    old = previous.read_text(encoding='utf-8')
    tree = ast.parse(old)
    assignments = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ('PROJECT_ALIASES', 'PRIVATE_ROOT'):
                if name in assignments:
                    raise ValueError("ambiguous station configuration; fleet payload was not written")
                if name == 'PROJECT_ALIASES':
                    aliases = ast.literal_eval(node.value)
                    if not isinstance(aliases, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in aliases.items()):
                        raise ValueError("invalid station aliases; fleet payload was not written")
                else:
                    if not (isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == 'Path' and len(node.value.args) == 1 and not node.value.keywords):
                        raise ValueError("invalid station private root; fleet payload was not written")
                    root = ast.literal_eval(node.value.args[0])
                    if not isinstance(root, str) or not Path(root).is_absolute():
                        raise ValueError("invalid station private root; fleet payload was not written")
                assignments[name] = ast.get_source_segment(old, node)
    if set(assignments) != {'PROJECT_ALIASES', 'PRIVATE_ROOT'}:
        raise ValueError("station configuration incomplete; fleet payload was not written")
    template = ROOT / 'bin/agentstack-station-materials'
    text = template.read_text(encoding='utf-8')
    for name, value in assignments.items():
        marker = name + (' = {}' if name == 'PROJECT_ALIASES' else ' = None') + '  # __FLEET_' + name + '_ASSIGNMENT__'
        if text.count(marker) != 1:
            raise ValueError("station template invalid; fleet payload was not written")
        text = text.replace(marker, value)
    ast.parse(text)
    return template, text


def prepared_head_accept(dest):
    previous = dest / 'bin/head-accept'
    if previous.is_symlink() or not previous.is_file():
        raise ValueError("installed head-accept configuration unavailable; fleet payload was not written")
    old = previous.read_text(encoding='utf-8')
    tree = ast.parse(old)
    matches = [n for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1
               and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'BASES']
    if len(matches) != 1 or not isinstance(matches[0].value, ast.List):
        raise ValueError("invalid head-accept configuration; fleet payload was not written")
    for node in ast.walk(matches[0].value):
        if not isinstance(node, (ast.List, ast.Load, ast.Call, ast.Name, ast.Constant, ast.BinOp, ast.Div)):
            raise ValueError("unsafe head-accept configuration; fleet payload was not written")
        if isinstance(node, ast.Name) and node.id not in ('Path', 'HOME'):
            raise ValueError("unsafe head-accept configuration; fleet payload was not written")
        if isinstance(node, ast.Call) and not (isinstance(node.func, ast.Name) and node.func.id == 'Path'
                                               and len(node.args) == 1 and not node.keywords
                                               and isinstance(node.args[0], ast.Constant)
                                               and isinstance(node.args[0].value, str)):
            raise ValueError("unsafe head-accept configuration; fleet payload was not written")
    template = ROOT / 'bin/head-accept'
    text = template.read_text(encoding='utf-8')
    marker = "BASES = [HOME / '.dev-storage-governor']  # __FLEET_HEAD_BASES_ASSIGNMENT__"
    if text.count(marker) != 1:
        raise ValueError("head-accept template invalid; fleet payload was not written")
    rendered = text.replace(marker, ast.get_source_segment(old, matches[0]))
    ast.parse(rendered)
    return template, rendered


def prepared_reaper(dest):
    previous = dest / 'bin/agentstack-reap-idle-seats'
    if previous.is_symlink() or not previous.is_file():
        raise ValueError("installed reaper configuration unavailable; fleet payload was not written")
    old = previous.read_text(encoding='utf-8')
    pattern = r'^REGISTRY_GLOBS="\$\{REAP_REGISTRY_GLOBS:-[A-Za-z0-9_$/.\-:*?]+\}"$'
    matches = re.findall(pattern, old, re.M)
    if len(matches) != 1:
        raise ValueError("reaper configuration invalid; fleet payload was not written")
    template = ROOT / 'bin/agentstack-reap-idle-seats'
    text = template.read_text(encoding='utf-8')
    marker = 'REGISTRY_GLOBS="${REAP_REGISTRY_GLOBS:?registry paths must be configured}" # __FLEET_REAPER_REGISTRY_ASSIGNMENT__'
    if text.count(marker) != 1:
        raise ValueError("reaper template invalid; fleet payload was not written")
    return template, text.replace(marker, matches[0])


def prepared_mail_project(dest, name):
    if name not in ('agentstack_stallself.py', 'agentstack_jobend.py'):
        raise ValueError("unknown operations helper; fleet payload was not written")
    previous = dest / 'bin' / name
    if previous.is_symlink() or not previous.is_file():
        raise ValueError("operations project configuration unavailable; fleet payload was not written")
    old = previous.read_text(encoding='utf-8')
    assignments = [n for n in ast.parse(old).body if isinstance(n, ast.Assign) and len(n.targets) == 1
                   and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'PROJECT']
    if len(assignments) != 1:
        raise ValueError("operations project configuration invalid; fleet payload was not written")
    value = ast.literal_eval(assignments[0].value)
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError("operations project configuration invalid; fleet payload was not written")
    template = ROOT / 'bin' / name
    text = template.read_text(encoding='utf-8')
    marker = 'PROJECT = os.environ.get("AGENTSTACK_PROJECT_KEY", "")  # __FLEET_MAIL_PROJECT_ASSIGNMENT__'
    if text.count(marker) != 1:
        raise ValueError("operations helper template invalid; fleet payload was not written")
    rendered = text.replace(marker, ast.get_source_segment(old, assignments[0]))
    ast.parse(rendered)
    return template, rendered


def prepared_doctor(dest):
    previous = dest / 'bin/agentstack-doctor'
    if previous.is_symlink() or not previous.is_file():
        raise ValueError("installed doctor configuration unavailable; fleet payload was not written")
    old = previous.read_text(encoding='utf-8')
    old_values = re.findall(r"tmux run-shell 'ls (/[A-Za-z0-9_./-]+) >/dev/null", old)
    new_values = re.findall(r'^AGENTSTACK_TCC_PROBE_DIR="\$\{AGENTSTACK_TCC_PROBE_DIR:-(/[A-Za-z0-9_./-]+)\}"$', old, re.M)
    values = old_values + new_values
    if len(values) != 1:
        raise ValueError("doctor probe configuration invalid; fleet payload was not written")
    template = ROOT / 'scripts/doctor.sh'
    text = template.read_text(encoding='utf-8')
    marker = 'AGENTSTACK_TCC_PROBE_DIR="${AGENTSTACK_TCC_PROBE_DIR:-}" # __FLEET_TCC_PROBE_ASSIGNMENT__'
    if text.count(marker) != 1:
        raise ValueError("doctor template invalid; fleet payload was not written")
    assignment = 'AGENTSTACK_TCC_PROBE_DIR="${AGENTSTACK_TCC_PROBE_DIR:-' + values[0] + '}"'
    return template, text.replace(marker, assignment)


def prepared_unstick(dest):
    previous = dest / 'bin/agentstack_unstick_seats.py'
    if previous.is_symlink() or not previous.is_file():
        raise ValueError("installed unstick project unavailable; fleet payload was not written")
    old = previous.read_text(encoding='utf-8')
    values = re.findall(r"data\.get\('project_key'\) != '(/[A-Za-z0-9_./-]+)'", old)
    if len(values) != 1:
        raise ValueError("unstick project configuration invalid; fleet payload was not written")
    template = ROOT / 'bin/agentstack_unstick_seats.py'
    text = template.read_text(encoding='utf-8')
    marker = '__FLEET_UNSTICK_PROJECT__'
    if text.count(marker) != 1:
        raise ValueError("unstick template invalid; fleet payload was not written")
    rendered = text.replace(marker, values[0])
    ast.parse(rendered)
    return template, rendered


def prepared_local_paths(dest, relative, defaults):
    if relative not in ('bin/codex-session-restore', 'fleet/runtime/head-evidence-export.py'):
        raise ValueError("unknown local-path helper; fleet payload was not written")
    previous = dest / relative.removeprefix('fleet/')
    if previous.is_symlink() or not previous.is_file():
        raise ValueError("installed local-path configuration unavailable; fleet payload was not written")
    old = previous.read_text(encoding='utf-8')
    assignments = {}
    for node in ast.parse(old).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in defaults:
            name = node.targets[0].id
            if name in assignments:
                raise ValueError("ambiguous local-path configuration; fleet payload was not written")
            for value in ast.walk(node.value):
                if not isinstance(value, (ast.List, ast.Tuple, ast.Load, ast.Call, ast.Name, ast.Constant, ast.BinOp, ast.Div)):
                    raise ValueError("unsafe local-path configuration; fleet payload was not written")
                if isinstance(value, ast.Name) and value.id not in ('Path', 'HOME', 'map', 'tuple'):
                    raise ValueError("unsafe local-path configuration; fleet payload was not written")
                if isinstance(value, ast.Call) and not (isinstance(value.func, ast.Name) and value.func.id in ('Path', 'map', 'tuple') and not value.keywords):
                    raise ValueError("unsafe local-path configuration; fleet payload was not written")
            assignments[name] = ast.get_source_segment(old, node)
    if set(assignments) != set(defaults):
        raise ValueError("local-path configuration incomplete; fleet payload was not written")
    template = ROOT / relative
    text = template.read_text(encoding='utf-8')
    for name, default in defaults.items():
        marker = name + ' = ' + default + '  # __FLEET_' + name + '_ASSIGNMENT__'
        if text.count(marker) != 1:
            raise ValueError("local-path template invalid; fleet payload was not written")
        text = text.replace(marker, assignments[name])
    ast.parse(text)
    return template, text


def prepared_tmux_status(dest):
    previous = dest / 'bin/agentstack-tmux-server-migrate'
    if previous.is_symlink() or not previous.is_file():
        raise ValueError("installed tmux probe unavailable; fleet payload was not written")
    old = previous.read_text(encoding='utf-8')
    old_values = re.findall(r"tmux run-shell 'ls (/[A-Za-z0-9_./-]+) >/dev/null", old)
    new_values = re.findall(r'^AGENTSTACK_TCC_PROBE_DIR="\$\{AGENTSTACK_TCC_PROBE_DIR:-(/[A-Za-z0-9_./-]+)\}"$', old, re.M)
    values = old_values + new_values
    if len(values) != 1:
        raise ValueError("tmux probe configuration invalid; fleet payload was not written")
    template = ROOT / 'bin/agentstack-tmux-server-migrate'
    text = template.read_text(encoding='utf-8')
    marker = 'AGENTSTACK_TCC_PROBE_DIR="${AGENTSTACK_TCC_PROBE_DIR:-}" # __FLEET_TMUX_PROBE_ASSIGNMENT__'
    if text.count(marker) != 1:
        raise ValueError("tmux status template invalid; fleet payload was not written")
    assignment = 'AGENTSTACK_TCC_PROBE_DIR="${AGENTSTACK_TCC_PROBE_DIR:-' + values[0] + '}"'
    return template, text.replace(marker, assignment)


def prepared_addons():
    rows = json.loads((ROOT / 'fleet/addon-paths.json').read_text())
    if not isinstance(rows, list) or not all(isinstance(rel, str) for rel in rows) or len(rows) != len(set(rows)):
        raise ValueError("invalid fleet addon manifest; fleet payload was not written")
    for rel in rows:
        if not rel.startswith(('bin/', 'hooks/', 'fleet/runtime/')) or '..' in Path(rel).parts:
            raise ValueError("invalid fleet addon path; fleet payload was not written")
        source = ROOT / rel
        if source.is_symlink() or not source.is_file():
            raise ValueError("fleet addon missing or unsafe; fleet payload was not written")
    if 'bin/agentstack-station-materials' not in rows or 'bin/agentstack-memory-budget' not in rows:
        raise ValueError("required fleet addon missing; fleet payload was not written")
    return rows


def prepared_cleanup_dispatch():
    upstream = (ROOT / 'hooks/cleanup-child-agent.sh').read_text()
    marker = '\nset -euo pipefail\n'
    if not upstream.startswith('#!/bin/bash\n') or marker not in upstream:
        raise ValueError("cleanup dispatch source invalid; fleet payload was not written")
    return upstream[len('#!/bin/bash\n'):upstream.index(marker)]


def prepared_spawn_dispatch():
    upstream = (ROOT / 'hooks/spawn_child.sh').read_text()
    marker = '# spawn_child.sh - launch a child agent'
    if not upstream.startswith('#!/bin/bash\n') or upstream.count(marker) != 1:
        raise ValueError("spawn dispatch source invalid; fleet payload was not written")
    dispatch = upstream[len('#!/bin/bash\n'):upstream.index(marker)]
    if 'agentstack-memory-budget' not in dispatch or 'ags_client_entry spawn-child' not in dispatch:
        raise ValueError("spawn admission or global dispatch missing; fleet payload was not written")
    return dispatch


def install(dest):
    template, rendered = prepared_release(dest)
    station_template, station_rendered = prepared_station(dest)
    head_template, head_rendered = prepared_head_accept(dest)
    reaper_template, reaper_rendered = prepared_reaper(dest)
    doctor_template, doctor_rendered = prepared_doctor(dest)
    tmux_template, tmux_rendered = prepared_tmux_status(dest)
    unstick_template, unstick_rendered = prepared_unstick(dest)
    local_paths = dict((prepared_local_paths(dest, 'bin/codex-session-restore', {'CATALOG':'None', 'LIVE':'None', 'ROOTS':'()'}),
                        prepared_local_paths(dest, 'fleet/runtime/head-evidence-export.py', {'LEDGER':'None', 'ARTIFACT_BASES':'[]'})))
    mail_projects = dict(prepared_mail_project(dest, name) for name in ('agentstack_stallself.py', 'agentstack_jobend.py'))
    addons = prepared_addons()
    cleanup_dispatch = prepared_cleanup_dispatch()
    spawn_dispatch = prepared_spawn_dispatch()
    records=[]
    def put(source,relative):
        target=dest/relative;target.parent.mkdir(parents=True,exist_ok=True)
        if target.is_symlink():target.unlink()
        if source == station_template:
            target.write_text(station_rendered, encoding='utf-8');shutil.copymode(source,target)
        elif source == head_template:
            target.write_text(head_rendered, encoding='utf-8');shutil.copymode(source,target)
        elif source == reaper_template:
            target.write_text(reaper_rendered, encoding='utf-8');shutil.copymode(source,target)
        elif source in mail_projects:
            target.write_text(mail_projects[source], encoding='utf-8');shutil.copymode(source,target)
        elif source == doctor_template:
            target.write_text(doctor_rendered, encoding='utf-8');shutil.copymode(source,target)
        elif source == tmux_template:
            target.write_text(tmux_rendered, encoding='utf-8');shutil.copymode(source,target)
        elif source == unstick_template:
            target.write_text(unstick_rendered, encoding='utf-8');shutil.copymode(source,target)
        elif source in local_paths:
            target.write_text(local_paths[source], encoding='utf-8');shutil.copymode(source,target)
        else:
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
            elif source == template:
                target=dest/rel;target.parent.mkdir(parents=True,exist_ok=True)
                if target.is_symlink():target.unlink()
                target.write_text(rendered, encoding='utf-8');shutil.copymode(source,target)
                records.append({'path':rel,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
            else:put(source,rel)
    # Keep all upstream entry bodies at explicit alternate paths. Their helpers
    # remain adjacent in the ordinary hooks/bin tree.
    for name in ('spawn_child.sh','cleanup-child-agent.sh'):
        put(ROOT/'hooks'/name,'hooks/'+name.removesuffix('.sh')+'.upstream.sh')
    put(ROOT/'bin/agentstack-preregister-child','bin/agentstack-preregister-child.upstream')
    for name in ('spawn_child.sh','cleanup-child-agent.sh'):
        prelude='#!/bin/bash\nset -euo pipefail\nSTACK="${AGENTSTACK_HOME:-$HOME/.agentstack}"\n'
        if name=='cleanup-child-agent.sh':
            prelude='#!/bin/bash\n'+cleanup_dispatch+'\nset -euo pipefail\n'+'STACK="${AGENTSTACK_HOME:-$HOME/.agentstack}"\n'
        if name=='spawn_child.sh':
            prelude='#!/bin/bash\n'+spawn_dispatch+'\nset -euo pipefail\n'+'STACK="${AGENTSTACK_HOME:-$HOME/.agentstack}"\n'
        prelude+='if [[ "${AGENTSTACK_FLEET_SPAWN:-legacy}" == upstream ]]; then\n'
        prelude+='    unset AGENTSTACK_LIFECYCLE_HOOKS_DIR\n    export AGENTSTACK_HOOKS_DIR="$STACK/hooks"\n'
        prelude+='    exec /bin/bash "$STACK/hooks/'+name.removesuffix('.sh')+'.upstream.sh" "$@"\nfi\n'
        if name=='spawn_child.sh':
            text=prelude+'export AGENTSTACK_HOME="$STACK"\nexport AGENTSTACK_HOOKS_DIR="$STACK/hooks"\nexport AGENTSTACK_LIFECYCLE_HOOKS_DIR="$STACK/'+RELEASE+'/hooks"\nexec /bin/bash "$AGENTSTACK_LIFECYCLE_HOOKS_DIR/spawn_child.sh" "$@"\n'
        else:
            original=(ROOT/'fleet/hooks/cleanup-child-agent-legacy.sh').read_text()
            text=prelude+original
        script('hooks/'+name,text)
    old=(ROOT/'bin/agentstack-preregister-child').read_text()
    select='if [[ "${AGENTSTACK_FLEET_SPAWN:-legacy}" == upstream ]]; then\n    exec "${AGENTSTACK_HOME:-$HOME/.agentstack}/bin/agentstack-preregister-child.upstream" "$@"\nfi\n'
    script('bin/agentstack-preregister-child',old.replace('set -euo pipefail\n','set -euo pipefail\n'+select,1))
    for rel in addons:
        if rel.startswith('fleet/runtime/'):put(ROOT/rel,rel.removeprefix('fleet/'))
        elif rel.startswith(('bin/','hooks/')):put(ROOT/rel,rel)
    for rel in ('bin/agentstack-spawn-codex','bin/agentstack-restart-seat'):
        put(ROOT/'fleet'/rel,rel)
    put(doctor_template, 'bin/agentstack-doctor')
    env=dest/'env.sh'
    text=env.read_text() if env.is_file() else ''
    text='\n'.join(line for line in text.splitlines() if not line.startswith('export AGENTSTACK_FLEET_COMPAT='))+'\nexport AGENTSTACK_FLEET_COMPAT=1\n'
    env.write_text(text);env.chmod(0o600)
    report={'policy':'head mail 35265; legacy generation is default; upstream is explicit','files':records}
    (dest/'fleet-install.json').write_text(json.dumps(report,indent=2)+'\n')
    record_manifest(dest, records)
    return report

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--install-dir',type=Path,required=True);ap.add_argument('--record-only',action='store_true');ap.add_argument('--validate-only',action='store_true');a=ap.parse_args()
    if not a.install_dir.is_absolute():ap.error('absolute install-dir required')
    if a.validate_only:
        prepared_release(a.install_dir)
        prepared_station(a.install_dir)
        prepared_head_accept(a.install_dir)
        prepared_reaper(a.install_dir)
        prepared_doctor(a.install_dir)
        prepared_tmux_status(a.install_dir)
        prepared_unstick(a.install_dir)
        prepared_local_paths(a.install_dir, 'bin/codex-session-restore', {'CATALOG':'None', 'LIVE':'None', 'ROOTS':'()'})
        prepared_local_paths(a.install_dir, 'fleet/runtime/head-evidence-export.py', {'LEDGER':'None', 'ARTIFACT_BASES':'[]'})
        for name in ('agentstack_stallself.py', 'agentstack_jobend.py'):
            prepared_mail_project(a.install_dir, name)
        prepared_addons()
        prepared_cleanup_dispatch()
        prepared_spawn_dispatch()
        print('fleet configuration validated')
        raise SystemExit(0)
    if a.record_only:
        result=json.loads((a.install_dir/"fleet-install.json").read_text())
        record_manifest(a.install_dir,result["files"])
    else:
        result=install(a.install_dir)
    print(json.dumps({'fleet_files':len(result['files']),'default':'legacy','upstream':'explicit opt-in'}))

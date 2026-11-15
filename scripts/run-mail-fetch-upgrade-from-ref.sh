#!/bin/bash
# Owner entry: the candidate is previewed here; the interactive installer runs only on request.
set -euo pipefail
mode=install
if [[ "${1:-}" == --preview && $# == 1 ]]; then mode=preview
elif [[ $# != 0 ]]; then echo 'usage: run-mail-fetch-upgrade-from-ref.sh [--preview]' >&2; exit 2
fi
: "${AGENTSTACK_UPGRADE_REPO:?set the existing repository path}"
: "${AGENTSTACK_UPGRADE_REF:?set the reviewed fork ref}"
: "${AGENTSTACK_PROJECT_KEY:?set the existing ORRERY project key}"
[[ "$AGENTSTACK_UPGRADE_REPO" == /* && "$AGENTSTACK_PROJECT_KEY" == /* ]] || { echo 'repository and project key must be absolute' >&2; exit 2; }
revision="$(git -C "$AGENTSTACK_UPGRADE_REPO" rev-parse --verify "${AGENTSTACK_UPGRADE_REF}^{commit}")"
script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
if [[ "$mode" == preview ]]; then
  [[ "$(git -C "$script_root" rev-parse HEAD)" == "$revision" ]] || { echo 'preview source does not match the reviewed ref' >&2; exit 2; }
  [[ -z "$(git -C "$script_root" status --porcelain --untracked-files=no)" ]] || { echo 'preview source has tracked edits' >&2; exit 2; }
  python3 - "$script_root" <<'PY'
import json, pathlib, sys
root=pathlib.Path(sys.argv[1])
rows=json.loads((root/'fleet/addon-paths.json').read_text())
release=pathlib.Path('releases/seat-lifecycle/ee5880e3e23606e0f3252cbeed211868102f4595')
targets={row.removeprefix('fleet/') if row.startswith('fleet/runtime/') else row for row in rows}
for path in (root/'fleet'/release).rglob('*'):
    if path.is_file() or path.is_symlink():
        targets.add(str(path.relative_to(root/'fleet')))
targets.update(('hooks/spawn_child.sh','hooks/cleanup-child-agent.sh',
                'hooks/spawn_child.upstream.sh','hooks/cleanup-child-agent.upstream.sh',
                'bin/agentstack-preregister-child','bin/agentstack-preregister-child.upstream',
                'bin/agentstack-spawn-codex','bin/agentstack-restart-seat','bin/agentstack-doctor',
                'env.sh','fleet-install.json','install-state.json'))
print('fleet payload possible destinations:',len(targets))
for target in sorted(targets):
    print('fleet destination:',target)
print('core installer possible destinations: VERSION, dashboard/, hooks/, bin/, skills/, codex/, claude/, templates/, env.sh, install-state.json')
print('owner-approved configuration may include Claude MCP/settings and managed instruction blocks')
print('planned service actions: dashboard service start/restart; Mail autostart and watcher registration; Mail candidate verification and managed switch')
print('before install: clone and verify existing install payload into same-volume private backup; preserve all existing Mail backups')
print('before install: stop Mail, verify DB/WAL/SHM clones, then restart and check the old listener')
print('after old Mail restarts: create and verify a second payload snapshot immediately before installer')
print('DB restore priority: installer backup first; pre-install clone is the earlier anchor')
print('service labels, live-specific conditional file changes, database backup location and outage duration: not measured by this preview')
PY
  printf 'reviewed source commit: %s\n' "$revision"
  exit 0
fi
[[ -t 0 ]] || { echo 'run in the head/owner terminal for interactive approvals' >&2; exit 2; }
[[ "${AGENTSTACK_ASSUME_YES:-0}" == 0 ]] || { echo 'remove AGENTSTACK_ASSUME_YES' >&2; exit 2; }
command -v dev-storage-governor >/dev/null || { echo 'dev-storage-governor unavailable' >&2; exit 2; }
command -v agentstack-station-materials >/dev/null || { echo 'agentstack-station-materials unavailable' >&2; exit 2; }
root="$(dev-storage-governor allocate --project examforge --task ORRERY-UP-6-owner --owner owner --kind build-cache --reuse-key orrery-up-6-owner-source --storage-base internal --internal-reason source-worktree --retention-class ephemeral --retention-category scratch --content-class private-protected --budget-gib 1 --reproduction-command 'scripts/install.sh --mail update' --input-identity "$revision" --accepted-evidence scripts/install.sh)"
worktree="$root/source"
if [[ ! -d "$worktree" ]]; then
  agentstack-station-materials worktree --source "$AGENTSTACK_UPGRADE_REPO" --destination "$worktree" --branch upgrade/orrery-up-6-owner-20261115 --revision "$revision" --receipt "$root/worktree.json"
fi
[[ "$(git -C "$worktree" rev-parse HEAD)" == "$revision" && -z "$(git -C "$worktree" status --porcelain)" ]] || { echo 'owner worktree differs; preserving it and stopping' >&2; exit 1; }
printf 'reviewed source commit: %s\n' "$revision"
backup_parent="$HOME/.agentstack/backups"
[[ -d "$backup_parent" && ! -L "$backup_parent" ]] || { echo 'approved backup parent unavailable' >&2; exit 1; }
plan_file="$backup_parent/orrery-up-6-plan-$(date -u '+%Y%m%dT%H%M%SZ').json"
python3 "$worktree/scripts/pre-install-snapshot.py" --home "$HOME" \
  --project "$AGENTSTACK_PROJECT_KEY" --candidate "$revision" --worktree "$worktree" \
  --plan --plan-output "$plan_file" >/dev/null || {
  echo 'snapshot plan failed; installer was not started' >&2; exit 1;
}
printf 'private snapshot plan: ~/.agentstack/backups/%s\n' "${plan_file##*/}"
snapshot="$backup_parent/orrery-up-6-$(date -u '+%Y%m%dT%H%M%SZ')"
result_file="$root/pre-install-snapshot-$(date -u '+%Y%m%dT%H%M%SZ').json"
( set -o noclobber; umask 077; python3 "$worktree/scripts/pre-install-snapshot.py" --home "$HOME" \
    --project "$AGENTSTACK_PROJECT_KEY" --candidate "$revision" --worktree "$worktree" --destination "$snapshot" > "$result_file" ) || {
  echo 'snapshot did not verify; installer was not started' >&2; exit 1;
}
manifest_sha="$(python3 - "$result_file" "$snapshot/manifest.json" "$plan_file" <<'PYVERIFY'
import hashlib, json, pathlib, re, sys
result = json.loads(pathlib.Path(sys.argv[1]).read_text())
sha = result['manifest_sha256']
raw = pathlib.Path(sys.argv[2]).read_bytes()
if not re.fullmatch(r'[0-9a-f]{64}', sha) or hashlib.sha256(raw).hexdigest() != sha:
    raise SystemExit(1)
planned = json.loads(pathlib.Path(sys.argv[3]).read_text())
recorded = json.loads(raw)
if [row['path'] for row in planned] != [row['path'] for row in recorded]:
    raise SystemExit(1)
print(sha)
PYVERIFY
)" || { echo 'snapshot manifest verification failed; installer was not started' >&2; exit 1; }
python3 "$worktree/scripts/pre-install-snapshot.py" --home "$HOME" \
  --project "$AGENTSTACK_PROJECT_KEY" --candidate "$revision" --worktree "$worktree" --destination "$snapshot" \
  --verify-manifest-sha "$manifest_sha" >/dev/null || {
  echo 'snapshot no longer matches; installer was not started' >&2; exit 1;
}
mail_result="$root/pre-install-mail-backup-$(date -u '+%Y%m%dT%H%M%SZ').json"
( set -o noclobber; umask 077; python3 "$worktree/scripts/pre-install-mail-cycle.py" \
    --home "$HOME" --snapshot "$snapshot" --worktree "$worktree" > "$mail_result" ) || {
  echo 'pre-install Mail stop/clone/restart gate failed; installer was not started' >&2; exit 1;
}
mail_manifest_sha="$(python3 - "$mail_result" "$snapshot/mail-database/manifest.json" <<'PYMAIL'
import hashlib, json, pathlib, re, sys
result = json.loads(pathlib.Path(sys.argv[1]).read_text())
sha = result['mail_manifest_sha256']
if not re.fullmatch(r'[0-9a-f]{64}', sha) or hashlib.sha256(pathlib.Path(sys.argv[2]).read_bytes()).hexdigest() != sha:
    raise SystemExit(1)
print(sha)
PYMAIL
)" || { echo 'Mail backup manifest verification failed; installer was not started' >&2; exit 1; }
# Stopping and restarting Mail changes runtime PID/marker/log files. Keep the
# first snapshot and its DB bundle as the earlier anchor, then capture the
# payload again after the old listener is healthy and before the installer.
final_plan="$backup_parent/orrery-up-6-final-plan-$(date -u '+%Y%m%dT%H%M%SZ').json"
python3 "$worktree/scripts/pre-install-snapshot.py" --home "$HOME" \
  --project "$AGENTSTACK_PROJECT_KEY" --candidate "$revision" --worktree "$worktree" \
  --plan --plan-output "$final_plan" >/dev/null || {
  echo 'final snapshot plan failed; installer was not started' >&2; exit 1;
}
final_snapshot="$backup_parent/orrery-up-6-final-$(date -u '+%Y%m%dT%H%M%SZ')"
final_result="$root/final-pre-install-snapshot-$(date -u '+%Y%m%dT%H%M%SZ').json"
( set -o noclobber; umask 077; python3 "$worktree/scripts/pre-install-snapshot.py" --home "$HOME" \
    --project "$AGENTSTACK_PROJECT_KEY" --candidate "$revision" --worktree "$worktree" --destination "$final_snapshot" > "$final_result" ) || {
  echo 'final snapshot did not verify; installer was not started' >&2; exit 1;
}
final_manifest_sha="$(python3 - "$final_result" "$final_snapshot/manifest.json" "$final_plan" <<'PYFINAL'
import hashlib,json,pathlib,re,sys
result=json.loads(pathlib.Path(sys.argv[1]).read_text())
sha=result['manifest_sha256']; raw=pathlib.Path(sys.argv[2]).read_bytes()
if not re.fullmatch(r'[0-9a-f]{64}',sha) or hashlib.sha256(raw).hexdigest()!=sha:
    raise SystemExit(1)
if [row['path'] for row in json.loads(pathlib.Path(sys.argv[3]).read_text())] != [row['path'] for row in json.loads(raw)]:
    raise SystemExit(1)
print(sha)
PYFINAL
)" || { echo 'final snapshot manifest verification failed; installer was not started' >&2; exit 1; }
python3 "$worktree/scripts/pre-install-snapshot.py" --home "$HOME" \
  --project "$AGENTSTACK_PROJECT_KEY" --candidate "$revision" --worktree "$worktree" --destination "$final_snapshot" \
  --verify-manifest-sha "$final_manifest_sha" >/dev/null || {
  echo 'final snapshot no longer matches; installer was not started' >&2; exit 1;
}
[[ "$(git -C "$worktree" rev-parse HEAD)" == "$revision" && -z "$(git -C "$worktree" status --porcelain)" ]] || {
  echo 'owner worktree changed after snapshot; installer was not started' >&2; exit 1;
}
printf 'verified snapshot: ~/.agentstack/backups/%s; manifest SHA-256: %s\n' "${snapshot##*/}" "$manifest_sha"
printf 'verified pre-install Mail backup manifest SHA-256: %s\n' "$mail_manifest_sha"
printf 'verified final payload snapshot: ~/.agentstack/backups/%s; manifest SHA-256: %s\n' "${final_snapshot##*/}" "$final_manifest_sha"
python3 - "$mail_result" <<'PYOUTAGE'
import json,sys
result=json.load(open(sys.argv[1]))
print('pre-install Mail stop until old listener healthy, seconds:',result['preinstall_outage_seconds'])
PYOUTAGE
timing_file="$root/installer-switch-$(date -u '+%Y%m%dT%H%M%SZ').seconds"
( set -o noclobber; umask 077; : > "$timing_file" ) || { echo 'switch timing file unavailable; installer was not started' >&2; exit 1; }
install_rc=0
(
  cd "$worktree"
  AGENTSTACK_FLEET_COMPAT=1 AGENTSTACK_OWNER_SWITCH_TIMING_FILE="$timing_file" \
    /bin/bash scripts/install.sh --project-key "$AGENTSTACK_PROJECT_KEY" --mail update
) || install_rc=$?
python3 - "$timing_file" <<'PYTIMING'
import pathlib,re,sys
try:
    entries=pathlib.Path(sys.argv[1]).read_text().splitlines()
    value=entries[-1] if entries and re.fullmatch(r'[0-9]+\.[0-9]+',entries[-1]) else 'unrecorded'
except OSError:
    value='unrecorded'
print('installer Mail switch measured seconds:',value)
PYTIMING
if [[ "$install_rc" == 0 ]]; then
  python3 - "$HOME/.agentstack/install-state.json" <<'PYUPDATE'
import json,sys
try:
    update=json.load(open(sys.argv[1])).get('agent_mail',{}).get('update',{})
    print('installer Mail update result:',update.get('result','unrecorded'))
    print('installer Mail switch outage seconds:',update.get('outage_seconds','unrecorded'))
except (OSError, ValueError, AttributeError):
    print('installer Mail switch outage seconds: unrecorded')
PYUPDATE
else
  echo 'installer failed; switch outage may be unrecorded in state' >&2
fi
exit "$install_rc"

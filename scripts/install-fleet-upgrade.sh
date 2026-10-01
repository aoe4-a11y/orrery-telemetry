#!/bin/bash
# Owner runs this from their terminal. R-005: approvals remain interactive.
set -euo pipefail
UPGRADE_REPO="$(cd "$(dirname "$0")/.." && pwd)"
if [[ ! -t 0 ]]; then
    echo 'Run this in your own terminal: the installer needs interactive approvals (R-005).' >&2
    exit 2
fi
if [[ -n "${AGENTSTACK_ASSUME_YES:-}" && "${AGENTSTACK_ASSUME_YES}" != 0 ]]; then
    echo 'Remove AGENTSTACK_ASSUME_YES before this interactive fleet upgrade.' >&2
    exit 2
fi
UPGRADE_ROOT="$(dev-storage-governor allocate --project orrery-telemetry --task ORRERY-UP-1-rollback --owner owner --kind archive --reuse-key orrery-up-1-rollback --retention-class protected --storage-base devssd-private --content-class private-protected --pin --budget-gib 2 --reproduction-command 'scripts/fleet-upgrade-backup.py restore' --input-identity "$(git -C "$UPGRADE_REPO" rev-parse HEAD)" --accepted-evidence docs/orrery-up-1/receipt.md)"
UPGRADE_SNAPSHOT="$UPGRADE_ROOT/payload-before-upgrade"
python3 "$UPGRADE_REPO/scripts/fleet-upgrade-backup.py" snapshot --home "$HOME" --directory "$UPGRADE_SNAPSHOT" --project-key /Users/huyuhutaru/tools/examforge --codex-home "${CODEX_HOME:-$HOME/.codex}"
printf 'Rollback snapshot: %s\n' "$UPGRADE_SNAPSHOT"
# Preserve old explicit candidates, add the selected current default.
CURRENT_MODELS="$(python3 - "$HOME/.agentstack/env.sh" <<'PY'
import pathlib,shlex,sys
models=''
for line in pathlib.Path(sys.argv[1]).read_text().splitlines():
    if line.startswith('export AGENTSTACK_CODEX_MODELS='):
        raw=shlex.split(line.split('=',1)[1],comments=True)
        if len(raw)==1:models=raw[0]
print(','.join(dict.fromkeys(['gpt-6.1-sol']+[x.strip() for x in models.split(',') if x.strip()])))
PY
)"
cd "$UPGRADE_REPO"
AGENTSTACK_CODEX_MODELS="$CURRENT_MODELS" ./scripts/install.sh --project-key /Users/huyuhutaru/tools/examforge
"$HOME/.agentstack/bin/agentstack-doctor"

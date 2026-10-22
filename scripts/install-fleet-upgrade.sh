#!/bin/bash
# Owner runs this from their terminal. R-005: approvals remain interactive.
set -euo pipefail
UPGRADE_REPO="$(cd "$(dirname "$0")/.." && pwd)"
REHEARSAL_ROOT=""
if [[ "${1:-}" == --rehearsal-root && $# == 2 ]]; then
    REHEARSAL_ROOT="$2"
    python3 - "$HOME" "$REHEARSAL_ROOT" <<'PYGUARD'
from pathlib import Path
import os,sys,urllib.parse
home,root=(Path(p).resolve() for p in sys.argv[1:])
if home == Path("/Users/huyuhutaru") or not home.is_relative_to(root) or not root.is_absolute():
    raise SystemExit("rehearsal override requires an isolated HOME below its root")
url=urllib.parse.urlparse(os.environ.get("AGENTSTACK_MCP_URL", ""))
if url.hostname not in ("127.0.0.1","localhost") or url.port in (None,18765):
    raise SystemExit("rehearsal requires an explicit isolated loopback Mail port")
PYGUARD
elif [[ $# != 0 ]]; then
    echo "Usage: install-fleet-upgrade.sh [--rehearsal-root ISOLATED_ROOT]" >&2
    exit 2
fi
if [[ ! -t 0 && -z "$REHEARSAL_ROOT" ]]; then
    echo 'Run this in your own terminal: the installer needs interactive approvals (R-005).' >&2
    exit 2
fi
if [[ -n "${AGENTSTACK_ASSUME_YES:-}" && "${AGENTSTACK_ASSUME_YES}" != 0 ]]; then
    echo 'Remove AGENTSTACK_ASSUME_YES before this interactive fleet upgrade.' >&2
    exit 2
fi
if [[ -n "$REHEARSAL_ROOT" ]]; then
    UPGRADE_ROOT="$REHEARSAL_ROOT/rollback"
    mkdir -p "$UPGRADE_ROOT"
else
    UPGRADE_ROOT="$(dev-storage-governor allocate --project examforge --task ORRERY-UP-2-rollback --owner owner --kind archive --reuse-key orrery-up-2-rollback --retention-class protected --storage-base devssd-private --content-class private-protected --pin --budget-gib 2 --reproduction-command 'scripts/fleet-upgrade-backup.py restore' --input-identity "$(git -C "$UPGRADE_REPO" rev-parse HEAD)" --accepted-evidence docs/orrery-up-2/receipt.md)"
fi
UPGRADE_SNAPSHOT="$UPGRADE_ROOT/payload-before-upgrade"
UPGRADE_PROJECT=/Users/huyuhutaru/tools/examforge
if [[ -n "$REHEARSAL_ROOT" ]]; then UPGRADE_PROJECT="$HOME/project"; fi
python3 "$UPGRADE_REPO/scripts/fleet-upgrade-backup.py" snapshot --home "$HOME" --directory "$UPGRADE_SNAPSHOT" --project-key "$UPGRADE_PROJECT" --codex-home "${CODEX_HOME:-$HOME/.codex}"
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
INSTALL_ARGS=(--project-key /Users/huyuhutaru/tools/examforge --mail keep)
if [[ -n "$REHEARSAL_ROOT" ]]; then
    INSTALL_ARGS=(--project-key "$HOME/project" --install-dir "$HOME/.agentstack" --scoped --mail keep)
fi
AGENTSTACK_FLEET_COMPAT=1 AGENTSTACK_CODEX_MODELS="$CURRENT_MODELS" ./scripts/install.sh "${INSTALL_ARGS[@]}"
"$HOME/.agentstack/bin/agentstack-doctor"

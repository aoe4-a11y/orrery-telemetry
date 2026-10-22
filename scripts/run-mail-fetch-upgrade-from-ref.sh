#!/bin/bash
# Head/owner entry: review this script before interactive --mail update (R-102).
set -euo pipefail
[[ -t 0 ]] || { echo 'Run in the head/owner terminal for interactive approvals (R-005, R-102).' >&2; exit 2; }
[[ "${AGENTSTACK_ASSUME_YES:-0}" == 0 ]] || { echo 'Remove AGENTSTACK_ASSUME_YES.' >&2; exit 2; }
BOOTSTRAP_REPO=/Users/huyuhutaru/tools/orrery-telemetry
BOOTSTRAP_REV="$(git -C "$BOOTSTRAP_REPO" rev-parse fork/freshpauling/orrery-up-3-mail-fetch)"
BOOTSTRAP_ROOT="$(/Users/huyuhutaru/.local/bin/dev-storage-governor allocate --project examforge --task ORRERY-UP-3-owner --owner owner --kind build-cache --reuse-key orrery-up-3-owner-source --storage-base internal --internal-reason source-worktree --retention-class ephemeral --retention-category scratch --content-class private-protected --budget-gib 1 --reproduction-command 'scripts/install.sh --mail update' --input-identity "$BOOTSTRAP_REV" --accepted-evidence docs/orrery-up-3/guide.md)"
BOOTSTRAP_WORKTREE="$BOOTSTRAP_ROOT/source"
if [[ ! -d "$BOOTSTRAP_WORKTREE" ]]; then
    /Users/huyuhutaru/.local/bin/agentstack-station-materials worktree --source "$BOOTSTRAP_REPO" --destination "$BOOTSTRAP_WORKTREE" --branch upgrade/orrery-up-3-owner-20261022 --revision "$BOOTSTRAP_REV" --receipt "$BOOTSTRAP_ROOT/worktree.json"
fi
[[ "$(git -C "$BOOTSTRAP_WORKTREE" rev-parse HEAD)" == "$BOOTSTRAP_REV" && -z "$(git -C "$BOOTSTRAP_WORKTREE" status --porcelain)" ]] || { echo 'Owner worktree differs; preserving it and stopping.' >&2; exit 1; }
printf 'Reviewed source: %s\n' "$BOOTSTRAP_REV"
BOOTSTRAP_EXIT=0
(
    cd "$BOOTSTRAP_WORKTREE"
    AGENTSTACK_FLEET_COMPAT=1 /bin/bash scripts/install.sh --project-key /Users/huyuhutaru/tools/examforge --mail update
) || BOOTSTRAP_EXIT=$?
printf 'Installer exit: %s\n' "$BOOTSTRAP_EXIT"
# The active candidate is installed outside this source tree. Record cleanup
# candidates, but leave deletion to the head's permitted shell (message 35336).
python3 - "$BOOTSTRAP_WORKTREE" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1]);files=[p for p in root.rglob('*') if p.is_file() and not p.is_symlink()]
print(json.dumps({'cleanup_path':str(root),'bytes':sum(p.stat().st_size for p in files),'files':len(files),'reason':'pushed source; installed Mail candidate is separately retained'}))
PY
exit "$BOOTSTRAP_EXIT"

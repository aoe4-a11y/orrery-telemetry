#!/bin/bash
# Run from the owner's terminal via git show; no live settings change before backup.
set -euo pipefail
[[ -t 0 ]] || { echo 'Open Terminal.app and run the documented command (R-005).' >&2; exit 2; }
BOOTSTRAP_REPO=/Users/huyuhutaru/tools/orrery-telemetry
BOOTSTRAP_REV="$(git -C "$BOOTSTRAP_REPO" rev-parse fork/upgrade/orrery-up-2-20261022)"
BOOTSTRAP_ROOT="$(dev-storage-governor allocate --project examforge --task ORRERY-UP-2-owner --owner owner --kind build-cache --reuse-key orrery-up-2-owner-source --storage-base internal --internal-reason source-worktree --retention-class ephemeral --retention-category scratch --content-class private-protected --budget-gib 1 --reproduction-command 'scripts/install-fleet-upgrade.sh' --input-identity "$BOOTSTRAP_REV" --accepted-evidence docs/orrery-up-2/receipt.md)"
BOOTSTRAP_WORKTREE="$BOOTSTRAP_ROOT/source"
if [[ ! -d "$BOOTSTRAP_WORKTREE" ]]; then
    agentstack-station-materials worktree --source "$BOOTSTRAP_REPO" --destination "$BOOTSTRAP_WORKTREE" --branch upgrade/orrery-up-2-owner-20261022 --revision "$BOOTSTRAP_REV" --receipt "$BOOTSTRAP_ROOT/worktree.json"
fi
[[ "$(git -C "$BOOTSTRAP_WORKTREE" rev-parse HEAD)" == "$BOOTSTRAP_REV" && -z "$(git -C "$BOOTSTRAP_WORKTREE" status --porcelain)" ]] || { echo 'Owner worktree differs; preserving it and stopping.' >&2; exit 1; }
BOOTSTRAP_EXIT=0
/bin/bash "$BOOTSTRAP_WORKTREE/scripts/install-fleet-upgrade.sh" || BOOTSTRAP_EXIT=$?
if [[ -z "$(git -C "$BOOTSTRAP_WORKTREE" status --porcelain)" ]]; then
    python3 - "$BOOTSTRAP_WORKTREE" <<'PYCENSUS'
from pathlib import Path
import json,sys
root=Path(sys.argv[1]);files=[p for p in root.rglob('*') if p.is_file() and not p.is_symlink()]
print(json.dumps({'cleanup_path':str(root),'bytes':sum(p.stat().st_size for p in files),'files':len(files),'reason':'owner upgrade source is reproducible from pushed ref'}))
PYCENSUS
    git -C "$BOOTSTRAP_REPO" worktree remove "${BOOTSTRAP_WORKTREE:?}"
    BOOTSTRAP_RESULT=success
    [[ "$BOOTSTRAP_EXIT" == 0 ]] || BOOTSTRAP_RESULT=failure
    dev-storage-governor close --path "$BOOTSTRAP_ROOT" --state done --result "$BOOTSTRAP_RESULT" --receipt-reference docs/orrery-up-2/receipt.md --owner owner
    df -h / /Volumes/DevSSD-Private
fi
exit "$BOOTSTRAP_EXIT"

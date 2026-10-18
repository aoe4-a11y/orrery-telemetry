#!/bin/bash
# Render the two literal paths when staging. Never install this template raw.
set -euo pipefail
RELEASE_HOOKS="__RELEASE_HOOKS__"
LEGACY_CLEANUP="__LEGACY_CLEANUP__"
[[ "$RELEASE_HOOKS" != __* && "$LEGACY_CLEANUP" != __* ]] || exit 1
NAME="${1:-${AGENT_NAME:-${AGENTSTACK_LIFECYCLE_NAME:-}}}"
[[ "$NAME" =~ ^[A-Za-z0-9_.-]+$ ]] || exit 0
RUNTIME="${AGENTSTACK_RUNTIME_DIR:-${AGENTSTACK_HOME:-$HOME/.agentstack}/runtime}"
HELPER="$RELEASE_HOOKS/seat_lifecycle.py"
if ! python3 "$HELPER" held --runtime "$RUNTIME" --name "$NAME"; then
    exec python3 "$HELPER" lock-exec --runtime "$RUNTIME" --name "$NAME" -- /bin/bash "$0" "$@"
fi
# Hold the lock through the legacy callback: a successor cannot begin between
# classification and the old name-keyed cleanup.
ROUTE="$(python3 "$HELPER" cleanup-route --runtime "$RUNTIME" --name "$NAME")" || exit 0
if [[ "$ROUTE" == guarded || -n "${AGENTSTACK_LAUNCH_JOURNAL:-}" || -n "${AGENTSTACK_LIFECYCLE_NAME:-}" ]]; then
    export AGENTSTACK_LIFECYCLE_HOOKS_DIR="$RELEASE_HOOKS"
    exec /bin/bash "$RELEASE_HOOKS/cleanup-child-agent.sh" "$@"
fi
exec /bin/bash "$LEGACY_CLEANUP" "$@"

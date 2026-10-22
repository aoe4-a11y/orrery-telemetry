#!/bin/bash
set -euo pipefail
export AGENTSTACK_HOME=/Users/huyuhutaru/.agentstack
export AGENTSTACK_HOOKS_DIR=/Users/huyuhutaru/.agentstack/hooks
export AGENTSTACK_LIFECYCLE_HOOKS_DIR=/Users/huyuhutaru/.agentstack/releases/seat-lifecycle/ee5880e3e23606e0f3252cbeed211868102f4595/hooks
exec /bin/bash "$AGENTSTACK_LIFECYCLE_HOOKS_DIR/spawn_child.sh" "$@"

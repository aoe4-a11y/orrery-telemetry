#!/bin/bash
# Only UNSTICK_LIVE=1 (and no dry-run override) can enable key presses.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)" || exit 1
exec /usr/bin/python3 "$SCRIPT_DIR/agentstack_unstick_seats.py"

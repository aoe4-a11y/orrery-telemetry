#!/usr/bin/env bash
# Shared new-child name guard. Never mutate a prior seat or relax lifecycle.
# Callback sets AGS_CHILD_NAME; only a proven state identity collision retries.
ags_child_name_check() {
  python3 - "${AGENTSTACK_RUNTIME_DIR:-${AGENTSTACK_HOME:-$HOME/.agentstack}/runtime}" "$1" "$2" <<'PYNAME'
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import sys

runtime, project, name = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
    raise SystemExit("agentstack: invalid child name")
children = runtime / "child-agents"
if children.is_symlink():
    raise SystemExit("agentstack: child state directory is a symlink")
path = children / (name + ".json")
try:
    info = path.lstat()
except FileNotFoundError:
    raise SystemExit(0)
if not stat.S_ISREG(info.st_mode):
    raise SystemExit("agentstack: child state is not a regular file")
try:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd) as stream:
        if os.fstat(stream.fileno()).st_size > 1024 * 1024:
            raise ValueError("oversized state")
        state = json.load(stream)
    if not isinstance(state, dict):
        raise ValueError("invalid state")
except (OSError, ValueError):
    raise SystemExit("agentstack: cannot verify existing child state")
if state.get("project_key") == project and state.get("agent_name") == name:
    raise SystemExit(0)
# One bounded, non-secret line per rejected name; no state or response payload.
runtime.mkdir(parents=True, exist_ok=True)
fd = os.open(runtime / "spawn_incidents.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND
             | getattr(os, "O_NOFOLLOW", 0), 0o600)
with os.fdopen(fd, "a") as stream:
    info = os.fstat(stream.fileno())
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        raise SystemExit("agentstack: invalid spawn incident log")
    fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
    stream.write(name + ": 他プロジェクトの状態と重なった\n")
    stream.flush()
raise SystemExit(73)
PYNAME
}

ags_child_name_retry() {
  local project="$1" code
  shift
  # Fixed bound: an occupied namespace is not a transport/auth retry policy.
  for AGS_CHILD_NAME_ATTEMPT in 1 2 3 4 5; do
    AGS_CHILD_NAME=""
    if "$@"; then :; else code=$?; return "$code"; fi
    if ags_child_name_check "$project" "$AGS_CHILD_NAME"; then
      return 0
    else
      code=$?
    fi
    [[ "$code" == 73 ]] || return "$code"
  done
  printf '%s\n' 'agentstack: child state name collisions exhausted (5 attempts)' >&2
  return 1
}

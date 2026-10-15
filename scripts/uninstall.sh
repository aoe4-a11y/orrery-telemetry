#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${AGENTSTACK_HOME:-$HOME/.agentstack}"
MANIFEST="$INSTALL_DIR/install-state.json"
MERGE_TOOL="$INSTALL_DIR/bin/agentstack-merge-settings"
MCP_MERGE_TOOL="$INSTALL_DIR/bin/agentstack-merge-claude-mcp"
DRY_RUN=false
PURGE_DATA=false

usage() {
  cat <<'EOF'
Usage: uninstall.sh [--dry-run] [--purge-data] [--install-dir PATH]

Uninstalls only files, services, and manifest-recorded settings changes from
install-state.json. By default, ORRERY Mail state, database, and runtime logs are
retained. Use --purge-data to remove exact retained paths recorded in the
manifest.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --purge-data)
      PURGE_DATA=true
      shift
      ;;
    --install-dir)
      INSTALL_DIR="$2"
      MANIFEST="$INSTALL_DIR/install-state.json"
      MERGE_TOOL="$INSTALL_DIR/bin/agentstack-merge-settings"
      MCP_MERGE_TOOL="$INSTALL_DIR/bin/agentstack-merge-claude-mcp"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! -f "$MANIFEST" ]]; then
  echo "No manifest found: $MANIFEST" >&2
  exit 1
fi

if [[ ! -x "$MERGE_TOOL" && -f "$SCRIPT_DIR/lib/merge_settings.py" ]]; then
  MERGE_TOOL="$SCRIPT_DIR/lib/merge_settings.py"
fi
if [[ ! -x "$MCP_MERGE_TOOL" && -f "$SCRIPT_DIR/lib/merge_claude_mcp.py" ]]; then
  MCP_MERGE_TOOL="$SCRIPT_DIR/lib/merge_claude_mcp.py"
fi

python3 - "$MANIFEST" "$DRY_RUN" "$PURGE_DATA" "$MERGE_TOOL" \
  "$MCP_MERGE_TOOL" <<'PY'
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import socket
import time
from urllib.parse import urlparse

manifest_path = pathlib.Path(sys.argv[1]).expanduser()
dry_run = sys.argv[2] == "true"
purge_data = sys.argv[3] == "true"
merge_tool = pathlib.Path(sys.argv[4]).expanduser()
mcp_merge_tool = pathlib.Path(sys.argv[5]).expanduser()

data = json.loads(manifest_path.read_text(encoding="utf-8"))

def say(action, path):
    prefix = "DRY-RUN would" if dry_run else "will"
    print(f"{prefix} {action}: {path}")

def run(argv):
    if dry_run:
        print("DRY-RUN would run: " + " ".join(argv))
        return
    subprocess.run(argv, check=False)

def safe_path(path):
    p = pathlib.Path(path).expanduser()
    s = str(p)
    home = str(pathlib.Path.home())
    if s in ("", "/", home):
        raise RuntimeError(f"refusing unsafe path from manifest: {s!r}")
    return p

def settings_merge_data():
    merge = data.get("settings_merge")
    if isinstance(merge, dict):
        return merge
    install_dir = pathlib.Path(data.get("install_dir", "")).expanduser()
    fallback = install_dir / "runtime" / "settings-merge-result.json"
    if fallback.exists():
        loaded = json.loads(fallback.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            return loaded
    return None

def remove_settings_hooks():
    merge = settings_merge_data()
    if not merge or not merge.get("changed") or merge.get("operation") != "merge":
        return
    settings_path = merge.get("settings_path")
    hooks_dir = merge.get("hooks_dir")
    if not isinstance(settings_path, str) or not isinstance(hooks_dir, str):
        raise RuntimeError("manifest settings_merge is missing settings_path/hooks_dir")
    if not merge_tool.exists():
        raise RuntimeError(f"missing settings merge helper: {merge_tool}")
    install_dir = pathlib.Path(data.get("install_dir", "")).expanduser()
    backup_dir = install_dir / "backups"
    result_json = install_dir / "runtime" / "settings-remove-result.json"
    argv = [
        sys.executable,
        str(merge_tool),
        "--remove",
        "--settings",
        settings_path,
        "--hooks-dir",
        hooks_dir,
        "--backup-dir",
        str(backup_dir),
        "--manifest",
        str(manifest_path),
        "--result-json",
        str(result_json),
    ]
    if dry_run:
        argv.append("--dry-run")
    subprocess.run(argv, check=True)

def remove_claude_mcp():
    merge = data.get("claude_mcp_merge")
    if not isinstance(merge, dict) or not merge.get("changed"):
        return
    if not mcp_merge_tool.exists():
        raise RuntimeError(f"missing Claude MCP merge helper: {mcp_merge_tool}")
    install_dir = pathlib.Path(data.get("install_dir", "")).expanduser()
    config_path = merge.get("config_path")
    if not isinstance(config_path, str) or not config_path:
        raise RuntimeError("manifest claude_mcp_merge is missing config_path")
    argv = [
        sys.executable,
        str(mcp_merge_tool),
        "--remove",
        "--config",
        config_path,
        "--backup-dir",
        str(install_dir / "backups"),
        "--manifest",
        str(manifest_path),
        "--result-json",
        str(install_dir / "runtime" / "claude-mcp-remove-result.json"),
    ]
    if dry_run:
        argv.append("--dry-run")
    subprocess.run(argv, check=True)

def stop_owned_mail(svc):
    """Keep the controller/render until its bounded stop has been verified."""
    install = pathlib.Path(data["install_dir"])
    controller = install / "bin" / "agentstack-mailctl"
    config = data["env"]
    marker = pathlib.Path(svc["pidfile"])
    env_file = pathlib.Path(config["AGENTSTACK_MAIL_ENV"])
    runner = env_file.parent / "run-agentstack-mail.sh"
    if str(runner) not in data.get("owned_files", []):
        raise RuntimeError("mail runner is not owned by this manifest; controls retained")
    if not controller.is_file():
        raise RuntimeError("mail controller missing; controls and manifest retained")
    pid = None
    if marker.exists():
        lines = marker.read_text().splitlines()
        if len(lines) != 2 or not lines[0].isdigit() or lines[1] != str(runner):
            raise RuntimeError("mail identity marker mismatch; controls retained")
        pid = int(lines[0])
        if pid <= 1:
            raise RuntimeError("unsafe mail pid; controls retained")
        ps = subprocess.run(["ps", "-ww", "-o", "uid=,command=", "-p", str(pid)],
                            capture_output=True, text=True, timeout=5)
        if ps.returncode == 1 and not ps.stdout.strip() and not ps.stderr.strip():
            pass
        elif ps.returncode == 0 and not ps.stderr.strip():
            uid, command = ps.stdout.strip().split(None, 1)
            if ps.returncode or int(uid) != os.getuid() or command != f"/bin/bash {runner}":
                raise RuntimeError("live mail runner identity mismatch; controls retained")
        else:
            raise RuntimeError("cannot verify live mail runner identity; controls retained")
    argv = [str(controller), "stop"]
    if dry_run:
        print("DRY-RUN would verify stopped before removing controls: " + " ".join(argv))
        return
    child_env = {k: v for k, v in os.environ.items()
                 if not k.startswith("AGENTSTACK_MAIL_") and k != "AGENTSTACK_MCP_URL"}
    child_env.update({
        "AGENTSTACK_HOME": str(install), "AGENTSTACK_MAILCTL_SKIP_ENV": "1",
        "AGENTSTACK_MAIL_DIR": str(marker.parent.parent),
        "AGENTSTACK_MAIL_PIDFILE": str(marker),
        "AGENTSTACK_MAIL_ENV": str(env_file), "AGENTSTACK_MAIL_RUNNER": str(runner),
        "AGENTSTACK_MAIL_DB": config["AGENTSTACK_MAIL_DB"],
        "AGENTSTACK_MCP_URL": config["AGENTSTACK_MCP_URL"],
        "AGENTSTACK_MAIL_LAUNCHD_LABEL": config.get("AGENTSTACK_MAIL_LAUNCHD_LABEL", ""),
        "AGENTSTACK_PYTHON": sys.executable,
    })
    subprocess.run(argv, env=child_env, check=True, timeout=60)
    # Independently require the configured endpoint to be released before the
    # destructive file-removal phase, even if a controller reported success.
    endpoint = urlparse(config["AGENTSTACK_MCP_URL"])
    deadline = time.monotonic() + 5
    while True:
        live = False
        if pid:
            ps = subprocess.run(["ps", "-p", str(pid), "-o", "pid="],
                                capture_output=True, text=True, timeout=5)
            if ps.returncode not in (0, 1) or ps.stderr.strip():
                raise RuntimeError("cannot verify mail runner exit; controls retained")
            live = bool(ps.stdout.strip())
        with socket.socket() as probe:
            probe.settimeout(0.2)
            occupied = probe.connect_ex((endpoint.hostname, endpoint.port or (443 if endpoint.scheme == "https" else 80))) == 0
        if not live and not occupied:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("mail runner or endpoint survived stop; controls retained")
        time.sleep(0.1)

for svc in data.get("services", []):
    kind = svc.get("kind")
    if kind == "nohup" and svc.get("role") == "ORRERY Mail":
        stop_owned_mail(svc)
        continue
    if kind == "launchd":
        label = svc.get("label", "")
        run(["launchctl", "bootout", f"gui/{os.getuid()}/{label}"])
    elif kind == "systemd-user":
        unit = svc.get("unit", "")
        run(["systemctl", "--user", "disable", "--now", unit])
        run(["systemctl", "--user", "daemon-reload"])
    elif kind == "nohup":
        pidfile = svc.get("pidfile", "")
        if pidfile:
            p = pathlib.Path(pidfile).expanduser()
            if p.exists():
                # agentstack-mailctl writes TWO lines: the pid, then the runner it
                # started (bin/agentstack-mailctl write_pid). int() over the whole
                # file raises, pid falls back to 0, and the mail server keeps
                # running after an uninstall. Parse it the way the controller
                # does, and do not signal a pid that has been recycled into
                # something else.
                recorded_runner = ""
                try:
                    lines = p.read_text(encoding="utf-8").splitlines()
                    pid = int(lines[0].split()[0]) if lines and lines[0].split() else 0
                    recorded_runner = lines[1].strip() if len(lines) > 1 else ""
                except Exception:
                    pid = 0
                if pid > 1 and recorded_runner:
                    try:
                        command = subprocess.run(
                            ["ps", "-ww", "-o", "command=", "-p", str(pid)],
                            capture_output=True, text=True, timeout=10,
                        ).stdout
                    except Exception:
                        command = ""
                    if command and recorded_runner not in command:
                        print(f"skipping pid {pid}: not the recorded runner")
                        pid = 0
                if pid > 1:
                    if dry_run:
                        print(f"DRY-RUN would terminate pid from {p}: {pid}")
                    else:
                        try:
                            os.kill(pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass

remove_claude_mcp()
remove_settings_hooks()

owned_files = [safe_path(p) for p in data.get("owned_files", [])]
if manifest_path not in owned_files:
    owned_files.append(manifest_path)

skill_link_paths = set()
for record in data.get("skill_links", []):
    if not isinstance(record, dict):
        raise RuntimeError("manifest skill_links entries must be objects")
    raw_path = record.get("path")
    raw_target = record.get("target")
    if not isinstance(raw_path, str) or not isinstance(raw_target, str):
        raise RuntimeError("manifest skill_links entries require string path and target")
    path = safe_path(raw_path)
    target = pathlib.Path(raw_target).expanduser().resolve(strict=False)
    skill_link_paths.add(path)
    if not path.is_symlink():
        if path.exists():
            print(f"kept modified skill path: {path}", file=sys.stderr)
        continue
    raw_actual = pathlib.Path(os.readlink(path))
    actual = raw_actual if raw_actual.is_absolute() else path.parent / raw_actual
    if actual.resolve(strict=False) != target:
        print(f"kept retargeted skill link: {path}", file=sys.stderr)
        continue
    say("remove owned skill link", path)
    if not dry_run:
        path.unlink()

for path in owned_files:
    if path in skill_link_paths:
        continue
    say("remove file", path)
    if not dry_run:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except IsADirectoryError:
            raise RuntimeError(f"manifest owned_files entry is a directory: {path}")

if purge_data:
    for raw in data.get("purge_paths", []):
        path = safe_path(raw)
        say("purge exact path", path)
        if not dry_run:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass

for raw in sorted(data.get("owned_dirs", []), key=lambda p: len(str(p)), reverse=True):
    path = safe_path(raw)
    say("remove empty directory", path)
    if not dry_run:
        try:
            path.rmdir()
        except FileNotFoundError:
            pass
        except OSError:
            print(f"kept non-empty directory: {path}", file=sys.stderr)
PY

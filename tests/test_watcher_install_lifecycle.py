"""Installer ownership controls: no real launchctl/systemctl or mail service."""
import json
import os
from pathlib import Path
import plistlib
import shlex
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "scripts/install.sh").read_text()


def _function(name):
    start = SOURCE.index(name + "() {")
    end = SOURCE.index("} # end " + name, start) + len("} # end " + name)
    return SOURCE[start:end]


@pytest.mark.parametrize("mode", ["approved", "unapproved", "lock_mismatch", "unloaded"])
def test_existing_fleet_job_is_reused_only_with_explicit_approval_and_live_identity(tmp_path, mode):
    home = tmp_path / "home"
    hooks = home / ".agentstack/hooks"
    hooks.mkdir(parents=True)
    watcher = hooks / "watch_agent_mail_signals.sh"
    watcher.write_text("trap 'exit 0' TERM\nwhile :; do sleep 0.05; done\n")
    process = subprocess.Popen(["/bin/bash", str(watcher)], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    try:
        plist_dir = home / "Library/LaunchAgents"
        plist_dir.mkdir(parents=True)
        label = "org.agentstack.test.fleet.mail-watcher"
        generic_label = "org.agentstack.test.mail-watcher"
        (plist_dir / (label + ".plist")).write_bytes(plistlib.dumps({
            "Label": label, "ProgramArguments": ["/bin/bash", str(watcher)]}))
        generic = plist_dir / (generic_label + ".plist")
        generic.write_bytes(plistlib.dumps({"Label": generic_label, "ProgramArguments": []}))
        original = generic.read_bytes()
        marker = tmp_path / "watcher.pid"
        marker.write_text(str(process.pid if mode != "lock_mismatch" else os.getpid()))
        fake = tmp_path / "bin"
        fake.mkdir()
        launchctl = fake / "launchctl"
        launchctl.write_text('''#!/usr/bin/env python3
import json,os,sys
with open(os.environ['FIXTURE_CALLS'],'a') as f:f.write(json.dumps(sys.argv[1:])+'\\n')
assert sys.argv[1]=='print', 'unexpected service mutation'
if os.environ['FIXTURE_MODE']=='unloaded':sys.exit(113)
print('state = running\\npid = '+os.environ['FIXTURE_PID'])
''')
        launchctl.chmod(0o755)
        script = tmp_path / "test.sh"
        script.write_text(f'''set -euo pipefail
PYTHON_BIN={shlex.quote(sys.executable)}
HOOKS_DIR={shlex.quote(str(hooks))}
MAIL_WATCHER_LABEL={generic_label}
AGENT_MAIL_WATCHER_KIND=""
AGENT_MAIL_WATCHER_PATH=""
DRY_RUN=false
say() {{ printf '%s\\n' "$*"; }}
die() {{ printf '%s\\n' "$*" >&2; exit 2; }}
warn() {{ die "$@"; }}
render_mail_watcher_unit() {{ die 'unexpected render'; }}
stop_tmux_mail_watcher() {{ die 'unexpected tmux mutation'; }}
''' + _function("find_external_mail_watcher") + "\n" + _function("enable_mail_watcher") + '''
enable_mail_watcher
printf 'KIND=%s\\nPATH_OUT=%s\\n' "$AGENT_MAIL_WATCHER_KIND" "$AGENT_MAIL_WATCHER_PATH"
''')
        calls = tmp_path / "calls.jsonl"
        env = {"PATH": str(fake) + os.pathsep + os.environ["PATH"], "HOME": str(home),
               "CODEX_HOME": str(home / ".codex"), "PYTHONOPTIMIZE": "1", "FIXTURE_CALLS": str(calls),
               "FIXTURE_PID": str(process.pid), "FIXTURE_MODE": mode,
               "AGENTSTACK_MAIL_WATCHER_PIDFILE": str(marker),
               "AGENTSTACK_EXTERNAL_MAIL_WATCHER_LABEL": label if mode != "unapproved" else ""}
        p = subprocess.run(["/bin/bash", str(script)], env=env, text=True,
                           capture_output=True, timeout=15)
        if mode == "approved":
            assert p.returncode == 0 and "KIND=external-launchd" in p.stdout, p.stdout + p.stderr
            assert "PATH_OUT=\n" in p.stdout
        else:
            assert p.returncode != 0 and "refusing to register a duplicate" in p.stderr
        assert generic.read_bytes() == original
        assert process.poll() is None
        if calls.exists():
            assert all(json.loads(line)[0] == "print" for line in calls.read_text().splitlines())
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.parametrize("mode,expected", [("owned", 0), ("external", 1),
                                         ("runner_mismatch", 2), ("foreign_pid", 2)])
def test_native_reuse_requires_both_prior_ownership_and_exact_current_runner(tmp_path, mode, expected):
    install = tmp_path / ".agentstack"
    render = install / "mail-service/renders/fixture"
    render.mkdir(parents=True)
    runner = render / "run-agentstack-mail.sh"
    runner.write_text("trap 'exit 0' TERM\nwhile :; do sleep 0.05; done\n")
    env_file = render / "service.env"
    env_file.write_text("# private fixture\n")
    marker = install / "mail-service/runtime/agentstack-mail.pid"
    marker.parent.mkdir()
    process = subprocess.Popen(["/bin/bash", str(runner)])
    try:
        marker.write_text(f"{process.pid if mode != 'foreign_pid' else os.getpid()}\n{runner}\n")
        manifest = install / "install-state.json"
        manifest.write_text(json.dumps({"install_dir": str(install),
            "owned_files": [str(env_file), str(runner)] if mode != "runner_mismatch" else [],
            "services": [{"role": "ORRERY Mail", "kind": "nohup", "pidfile": str(marker)}]
                        if mode != "external" else []}))
        script = tmp_path / "owned.sh"
        values = {"PYTHON_BIN": sys.executable, "MANIFEST": str(manifest),
                  "INSTALL_DIR": str(install), "NATIVE_MAIL_PIDFILE": str(marker),
                  "NATIVE_MAIL_RUNNER": str(runner), "NATIVE_MAIL_ENV": str(env_file)}
        script.write_text("\n".join(f"{k}={shlex.quote(v)}" for k, v in values.items())
                          + "\n" + _function("previously_owned_native_mail")
                          + "\npreviously_owned_native_mail\n")
        p = subprocess.run(["/bin/bash", str(script)], env={**os.environ, "PYTHONOPTIMIZE": "1"}, text=True, capture_output=True, timeout=10)
        assert p.returncode == expected, p.stdout + p.stderr
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=5)

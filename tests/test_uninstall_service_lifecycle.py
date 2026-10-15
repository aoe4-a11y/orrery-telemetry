"""Real isolated runner/port teardown; never use an installed host service."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import threading

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from service_teardown import stop_test_mail

ROOT = Path(__file__).resolve().parents[1]


def _occupied(port):
    with socket.socket() as probe:
        probe.settimeout(0.1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


@contextmanager
def _service(tmp_path):
    home = tmp_path / "home"
    install = home / ".agentstack"
    render = install / "mail-service/renders/fixture"
    render.mkdir(parents=True)
    marker = install / "mail-service/runtime/agentstack-mail.pid"
    marker.parent.mkdir()
    controller = install / "bin/agentstack-mailctl"
    controller.parent.mkdir()
    controller.write_bytes((ROOT / "bin/agentstack-mailctl").read_bytes())
    controller.chmod(0o755)
    env_file = render / "service.env"
    env_file.write_text("# isolated test configuration\n")
    env_sh = install / "env.sh"
    env_sh.write_text("# isolated test configuration\n")
    db = install / "mail/storage.sqlite3"
    db.parent.mkdir()
    db.touch()
    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(port),
                               "--bind", "127.0.0.1"], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, cwd=home)
    runner = render / "run-agentstack-mail.sh"
    runner.write_text(f"trap 'kill -TERM {server.pid}; sleep 0.2; exit 0' TERM\n"
                      "while :; do sleep 0.05; done\n")
    process = subprocess.Popen(["/bin/bash", str(runner)], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    reapers = [threading.Thread(target=child.wait) for child in (process, server)]
    for reaper in reapers:
        reaper.start()
    try:
        marker.write_text(f"{process.pid}\n{runner}\n")
        manifest = install / "install-state.json"
        env = {"AGENTSTACK_MAIL_ENV": str(env_file), "AGENTSTACK_MAIL_DB": str(db),
               "AGENTSTACK_MCP_URL": f"http://127.0.0.1:{port}/mcp",
               "AGENTSTACK_MAIL_LAUNCHD_LABEL": "org.agentstack.test.lifecycle.mail"}
        manifest.write_text(json.dumps({"install_dir": str(install), "env": env,
            "services": [{"kind": "nohup", "pidfile": str(marker), "role": "ORRERY Mail"}],
            "owned_files": list(map(str, [controller, runner, env_file, env_sh])),
            "owned_dirs": []}))
        deadline = time.monotonic() + 5
        while not _occupied(port):
            assert server.poll() is None and time.monotonic() < deadline
            time.sleep(0.02)
        yield {"home": home, "install": install, "manifest": manifest,
               "marker": marker, "controller": controller, "runner": runner,
               "process": process, "server": server, "port": port, "db": db,
               "env_file": env_file}
    finally:
        # Live Popen handles owned by this fixture, never an arbitrary pidfile.
        for child in (process, server):
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)
        for reaper in reapers:
            reaper.join(timeout=5)
            assert not reaper.is_alive()


def _uninstall(fixture, *, path=None):
    env = {"HOME": str(fixture["home"]),
           "CODEX_HOME": str(fixture["home"] / ".codex"), "PATH": path or os.environ["PATH"]}
    return subprocess.run(["/bin/bash", str(ROOT / "scripts/uninstall.sh"),
                           "--install-dir", str(fixture["install"])],
                          env=env, text=True, capture_output=True, timeout=70)


def test_uninstall_waits_for_runner_and_port_before_removing_controls(tmp_path):
    with _service(tmp_path) as f:
        p = _uninstall(f)
        assert p.returncode == 0, p.stdout + p.stderr
        assert f["process"].poll() is not None and f["server"].poll() is not None
        assert not _occupied(f["port"]) and not f["controller"].exists()
        assert not f["manifest"].exists() and not f["marker"].exists()
        assert f["db"].exists()


def test_stop_failure_retains_controller_runner_env_and_manifest(tmp_path):
    with _service(tmp_path) as f:
        # An exit 0 alone is insufficient: this controller deliberately lies.
        f["controller"].write_text("#!/bin/sh\nexit 0\n")
        p = _uninstall(f)
        assert p.returncode != 0 and "survived stop" in p.stderr
        assert all(f[k].exists() for k in ("manifest", "controller", "runner", "env_file"))
        assert f["process"].poll() is None and f["server"].poll() is None


def test_uninstall_does_not_signal_recycled_unrelated_pid(tmp_path):
    with _service(tmp_path) as f:
        other = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
        try:
            f["marker"].write_text(f"{other.pid}\n{f['runner']}\n")
            p = _uninstall(f)
            assert p.returncode != 0 and "identity mismatch" in p.stderr
            assert other.poll() is None and f["process"].poll() is None
            assert f["controller"].exists() and f["manifest"].exists()
        finally:
            other.terminate()
            other.wait(timeout=5)


def test_missing_controller_does_not_allow_uninstall_to_remove_evidence(tmp_path):
    with _service(tmp_path) as f:
        f["controller"].unlink()
        p = _uninstall(f)
        assert p.returncode != 0 and "controller missing" in p.stderr
        assert f["manifest"].exists() and f["runner"].exists() and f["env_file"].exists()
        # The test's finally path can use the canonical source controller,
        # but only because ownership/config/live identity still agree.
        stop_test_mail(f["home"])
        assert f["process"].poll() is not None and not _occupied(f["port"])


def test_assertion_failure_still_stops_manifest_owned_test_service(tmp_path):
    with _service(tmp_path) as f:
        with pytest.raises(AssertionError, match="fixture assertion"):
            try:
                raise AssertionError("fixture assertion")
            finally:
                stop_test_mail(f["home"])
        assert f["process"].poll() is not None and f["server"].poll() is not None
        assert not _occupied(f["port"]) and f["db"].exists()


def test_unanswerable_process_query_does_not_allow_a_signal(tmp_path):
    with _service(tmp_path) as f:
        fake = tmp_path / "fake-bin"
        fake.mkdir()
        ps = fake / "ps"
        ps.write_text("#!/bin/sh\necho 'process query denied' >&2\nexit 1\n")
        ps.chmod(0o755)
        p = _uninstall(f, path=str(fake) + os.pathsep + os.environ["PATH"])
        assert p.returncode != 0 and "cannot verify live mail runner" in p.stderr
        assert f["process"].poll() is None and f["server"].poll() is None
        assert f["manifest"].exists() and f["controller"].exists()

"""Read-only stale classification must never infer absence from probe failure."""
import importlib.util
import os
from pathlib import Path
import subprocess

import pytest

SPEC = importlib.util.spec_from_file_location(
    "watcher_lock_status", Path(__file__).resolve().parents[1] / "scripts/watcher_lock_status.py")
status = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(status)


def fixture(tmp_path, monkeypatch):
    lock = tmp_path / "lock"
    lock.mkdir()
    (lock / "watcher.pid").write_text("987654\n")
    (lock / "heartbeat").write_text("")
    monkeypatch.setattr(status.os, "kill", lambda *args: (_ for _ in ()).throw(ProcessLookupError()))
    return lock


def runner(mode, lock):
    def run(args, **kwargs):
        if args[0] == "launchctl":
            if mode == "loaded":
                return subprocess.CompletedProcess(args, 0, "state = waiting", "")
            if mode == "job_denied":
                return subprocess.CompletedProcess(args, 113, "", "permission denied")
            return subprocess.CompletedProcess(args, 113, "", "Could not find service fixture")
        if mode == "ps_denied":
            raise subprocess.CalledProcessError(1, args)
        if mode == "changed":
            (lock / "heartbeat").write_text("changed")
        output = {
            "ps_empty": "", "ps_bad": "malformed", "pid_reused": "987654 501 other\n",
            "another": f"123 {os.getuid()} /bin/bash /fixture/watch.sh\n",
            "legacy": f"123 {os.getuid()} /bin/bash -lc 'exec /bin/bash /fixture/watch.sh'\n",
        }.get(mode, f"123 {os.getuid()} harmless-command\n")
        return subprocess.CompletedProcess(args, 0, output, "")
    return run


def inspect(lock, mode="clean", backend=None):
    return status.inspect_lock(lock, 987654, [987655] if backend is None else backend,
                               f"gui/{os.getuid()}/org.agentstack.test.fixture",
                               Path("/fixture/watch.sh"), run=runner(mode, lock))


def test_verified_stale_is_read_only(tmp_path, monkeypatch):
    lock = fixture(tmp_path, monkeypatch)
    before = {p.name: (p.read_bytes(), p.lstat()) for p in lock.iterdir()}
    report = inspect(lock)
    assert report["status"] == "stale", report
    assert before == {p.name: (p.read_bytes(), p.lstat()) for p in lock.iterdir()}
    assert set(report["witness"]) == {"pid", "watcher.pid", "heartbeat", "directory"}


@pytest.mark.parametrize("mode", ["loaded", "job_denied", "ps_denied", "ps_empty",
                                  "ps_bad", "pid_reused", "another", "legacy", "changed"])
def test_unverified_or_changed_state_is_not_stale(mode, tmp_path, monkeypatch):
    lock = fixture(tmp_path, monkeypatch)
    assert inspect(lock, mode)["status"] != "stale"
    assert (lock / "watcher.pid").exists() and (lock / "heartbeat").exists()


@pytest.mark.parametrize("probe", ["alive", "denied", "backend_alive"])
def test_absence_requires_esrch_for_every_recorded_process(probe, tmp_path, monkeypatch):
    lock = fixture(tmp_path, monkeypatch)
    def kill(pid, signal):
        if probe == "denied":
            raise PermissionError()
        if probe == "alive" or pid == 987655:
            return
        raise ProcessLookupError()
    monkeypatch.setattr(status.os, "kill", kill)
    assert inspect(lock)["status"] != "stale"


@pytest.mark.parametrize("damage", ["pid_mismatch", "invalid_pid", "symlink", "extra", "missing", "no_backend"])
def test_unknown_controls_are_preserved(damage, tmp_path, monkeypatch):
    lock = fixture(tmp_path, monkeypatch)
    if damage == "pid_mismatch":
        (lock / "watcher.pid").write_text("987656")
    elif damage == "invalid_pid":
        (lock / "watcher.pid").write_text("0")
    elif damage == "symlink":
        (lock / "heartbeat").unlink()
        (lock / "heartbeat").symlink_to(lock / "watcher.pid")
    elif damage == "extra":
        (lock / "unowned").write_text("keep")
    elif damage == "missing":
        (lock / "heartbeat").unlink()
    assert inspect(lock, backend=[] if damage == "no_backend" else None)["status"] != "stale"
    assert (lock / "watcher.pid").exists()

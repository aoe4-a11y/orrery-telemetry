#!/usr/bin/env python3
"""Read-only cutover gate. 'stale' is a snapshot, never permission to unlink.

After stopping the exact job, supply its recorded PID/backend PIDs. A caller
must separately authorize recovery, archive controls, and recheck witnesses
immediately before mutation. Unknown, active, or changing state is a stop.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess


def _controls(lock: Path):
    directory = lock.lstat()
    if not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.getuid():
        raise ValueError("lock type/owner")
    if {p.name for p in lock.iterdir()} != {"watcher.pid", "heartbeat"}:
        raise ValueError("unexpected control members")
    result = {}
    for name in ("watcher.pid", "heartbeat"):
        fd = os.open(lock / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > 1048576:
                raise ValueError("control type/owner/size")
            data = os.read(fd, 1048577)
            after = os.fstat(fd)
            if info != after or len(data) != info.st_size:
                raise ValueError("control changed")
            result[name] = {"device": info.st_dev, "inode": info.st_ino,
                            "mode": info.st_mode, "uid": info.st_uid,
                            "bytes": info.st_size, "mtime_ns": info.st_mtime_ns,
                            "ctime_ns": info.st_ctime_ns,
                            "sha256": hashlib.sha256(data).hexdigest()}
            if name == "watcher.pid":
                text = data.decode("ascii").strip()
                if not re.fullmatch(r"[1-9][0-9]*", text) or int(text) <= 1:
                    raise ValueError("invalid pid")
                result["pid"] = int(text)
        finally:
            os.close(fd)
    result["directory"] = (directory.st_dev, directory.st_ino, directory.st_uid,
                           directory.st_mode, directory.st_mtime_ns, directory.st_ctime_ns)
    return result


def _absent(pid):
    if pid <= 1:
        raise ValueError("unsafe pid")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    # Permission denial or any other error is unknown, not absence.
    return False


def inspect_lock(lock: Path, expected_pid: int, backend_pids: list[int],
                 target: str, script: Path, *, run=subprocess.run):
    report = {"status": "unknown", "lock": str(lock), "target": target,
              "expected_pid": expected_pid, "backend_pids": backend_pids}
    try:
        if not re.fullmatch(r"gui/" + str(os.getuid()) + r"/[A-Za-z0-9_.-]+", target):
            raise ValueError("job target must be exact current-user label")
        before = _controls(lock)
        report["witness"] = before
        if before["pid"] != expected_pid or not backend_pids:
            raise ValueError("recorded pid/backend mismatch")
        pids = [expected_pid, *backend_pids]
        if not all(_absent(pid) for pid in pids):
            report.update(status="active", reason="recorded process still exists")
            return report
        job = run(["launchctl", "print", target], capture_output=True, text=True, timeout=5)
        if job.returncode == 0:
            report.update(status="active", reason="job remains loaded")
            return report
        if job.returncode != 113 or "Could not find service" not in job.stderr or job.stdout.strip():
            raise ValueError("job absence unverified")
        inventory = run(["ps", "-ww", "-axo", "pid=,uid=,command="],
                        capture_output=True, text=True, timeout=5, check=True)
        if inventory.stderr.strip() or not inventory.stdout.strip():
            raise ValueError("process inventory incomplete")
        for line in inventory.stdout.splitlines():
            pid, uid, command = line.strip().split(None, 2)
            if int(pid) in pids:
                raise ValueError("pid reappeared")
            # Non-shell argv can contain unquoted content unrelated to us.
            executable = command.split(None, 1)[0]
            if Path(executable).name in {"bash", "sh", "zsh"}:
                args = shlex.split(command)
                direct = str(script) in args[1:3]
                legacy = len(args) > 2 and args[1] == "-lc" and str(script) in args[2]
                if direct or legacy:
                    raise ValueError("another watcher process exists")
            int(uid)  # malformed ps rows cannot establish an empty inventory
        if before != _controls(lock) or not all(_absent(pid) for pid in pids):
            raise ValueError("witness changed")
        report.update(status="stale", reason="recorded processes absent; exact job unloaded; controls stable")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        report["reason"] = str(exc)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock-dir", type=Path, required=True)
    parser.add_argument("--expected-pid", type=int, required=True)
    parser.add_argument("--backend-pid", type=int, action="append", required=True)
    parser.add_argument("--job-target", required=True)
    parser.add_argument("--watcher-script", type=Path, required=True)
    args = parser.parse_args()
    report = inspect_lock(args.lock_dir, args.expected_pid, args.backend_pid,
                          args.job_target, args.watcher_script)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "stale" else 1


if __name__ == "__main__":
    raise SystemExit(main())

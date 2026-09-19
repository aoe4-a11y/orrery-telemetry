#!/usr/bin/env python3
"""Fixture tests for scripts/rotate_runtime_logs.sh (copytruncate rotation).

Everything runs inside a temporary directory passed as the DIR argument; the
real ~/.agentstack/runtime is never read or written. The script is executed
with /bin/bash so macOS bash 3.2 is what gets exercised.

Runnable two ways (stdlib only):
    python3 tests/test_rotate_runtime_logs.py
    pytest tests/test_rotate_runtime_logs.py
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import time

_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = _ROOT / "scripts" / "rotate_runtime_logs.sh"
THRESHOLD = 4096  # small threshold so fixtures stay tiny


def _run(*dirs: pathlib.Path, dry_run: bool = False, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    full_env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(dirs[0]) if dirs else "/nonexistent",
        "AGENTSTACK_LOG_ROTATE_THRESHOLD_BYTES": str(THRESHOLD),
        "AGENTSTACK_LOG_ROTATE_KEEP": "3",
    }
    if env:
        full_env.update(env)
    args = ["/bin/bash", str(SCRIPT)]
    if dry_run:
        args.append("--dry-run")
    args.extend(str(d) for d in dirs)
    return subprocess.run(args, capture_output=True, text=True, env=full_env)


def _fill(path: pathlib.Path, tag: str, size: int = THRESHOLD + 100) -> None:
    line = f"{tag} " + "x" * 60 + "\n"
    with open(path, "w", encoding="utf-8") as fh:
        while fh.tell() < size:
            fh.write(line)


def _lock_env(tmp: pathlib.Path) -> dict[str, str]:
    return {"AGENTSTACK_LOG_ROTATE_LOCK_DIR": str(tmp / "lock")}


def test_below_threshold_untouched() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        log = tmp / "small.log"
        log.write_text("hello\n")
        proc = _run(tmp, env=_lock_env(tmp))
        assert proc.returncode == 0, proc.stderr
        assert log.read_text() == "hello\n"
        assert not (tmp / "small.log.1").exists()


def test_rotation_shifts_three_archives_and_drops_oldest() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        log = tmp / "watcher.log"
        for n in range(1, 5):
            _fill(log, f"gen{n}")
            proc = _run(tmp, env=_lock_env(tmp))
            assert proc.returncode == 0, proc.stderr
            assert f"rotated watcher.log" in proc.stdout
            assert log.stat().st_size == 0, "current file must be truncated in place"
        # After four rotations: .1=gen4, .2=gen3, .3=gen2, gen1 dropped.
        assert (tmp / "watcher.log.1").read_text().startswith("gen4 ")
        assert (tmp / "watcher.log.2").read_text().startswith("gen3 ")
        assert (tmp / "watcher.log.3").read_text().startswith("gen2 ")
        assert not (tmp / "watcher.log.4").exists()
        assert not (tmp / "watcher.log.1.tmp").exists()


def test_dry_run_changes_nothing() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        log = tmp / "big.log"
        _fill(log, "dry")
        before = log.read_bytes()
        proc = _run(tmp, dry_run=True, env=_lock_env(tmp))
        assert proc.returncode == 0, proc.stderr
        assert "would rotate big.log" in proc.stdout
        assert log.read_bytes() == before
        assert not (tmp / "big.log.1").exists()


def test_symlinked_file_is_skipped_and_target_untouched() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        outside = tmp / "outside"
        outside.mkdir()
        target = outside / "real.log"
        _fill(target, "outside")
        root = tmp / "runtime"
        root.mkdir()
        (root / "link.log").symlink_to(target)
        proc = _run(root, env=_lock_env(tmp))
        assert proc.returncode == 0, proc.stderr
        assert target.stat().st_size > THRESHOLD
        assert not (outside / "real.log.1").exists()
        assert not (root / "link.log.1").exists()


def test_symlinked_root_is_refused() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        real = tmp / "real"
        real.mkdir()
        _fill(real / "a.log", "a")
        link = tmp / "link"
        link.symlink_to(real)
        proc = _run(link, env=_lock_env(tmp))
        assert proc.returncode == 3
        assert (real / "a.log").stat().st_size > THRESHOLD
        assert not (real / "a.log.1").exists()


def test_subdirectories_and_non_log_files_are_left_alone() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        sub = tmp / "audit"
        sub.mkdir()
        _fill(sub / "nested.log", "nested")
        _fill(tmp / "notes.txt", "txt")
        _fill(tmp / "old.log.1", "archive")  # an archive must not be re-rotated
        proc = _run(tmp, env=_lock_env(tmp))
        assert proc.returncode == 0, proc.stderr
        assert (sub / "nested.log").stat().st_size > THRESHOLD
        assert (tmp / "notes.txt").stat().st_size > THRESHOLD
        assert (tmp / "old.log.1").stat().st_size > THRESHOLD
        assert not (tmp / "old.log.1.1").exists()


def test_symlinked_archive_blocks_rotation() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        _fill(tmp / "victim.log", "victim")
        elsewhere = tmp / "elsewhere"
        elsewhere.write_text("do not clobber\n")
        (tmp / "victim.log.1").symlink_to(elsewhere)
        proc = _run(tmp, env=_lock_env(tmp))
        assert proc.returncode == 0, proc.stderr
        assert "not a plain file" in proc.stdout
        assert elsewhere.read_text() == "do not clobber\n"
        assert (tmp / "victim.log").stat().st_size > THRESHOLD


def test_concurrent_run_with_live_lock_holder_does_nothing() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        _fill(tmp / "busy.log", "busy")
        lock = tmp / "lock"
        lock.mkdir()
        holder = subprocess.Popen(["/bin/sleep", "30"])
        try:
            (lock / "pid").write_text(f"{holder.pid}\n")
            proc = _run(tmp, env=_lock_env(tmp))
        finally:
            holder.kill()
            holder.wait()
        assert proc.returncode == 0, proc.stderr
        assert "another rotation is running" in proc.stdout
        assert (tmp / "busy.log").stat().st_size > THRESHOLD
        assert lock.is_dir(), "a foreign lock must not be removed"


def test_existing_lock_with_dead_pid_fails_closed() -> None:
    """No automatic stale recovery: an old lock with a dead pid blocks the run."""
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        _fill(tmp / "stale.log", "stale")
        lock = tmp / "lock"
        lock.mkdir()
        (lock / "pid").write_text("999999999\n")
        old = time.time() - 7200
        os.utime(lock, (old, old))
        proc = _run(tmp, env=_lock_env(tmp))
        assert proc.returncode == 0, proc.stderr
        assert "refusing to rotate" in proc.stdout
        assert not (tmp / "stale.log.1").exists()
        assert (tmp / "stale.log").stat().st_size > THRESHOLD
        assert lock.is_dir() and (lock / "pid").read_text() == "999999999\n"


def test_existing_lock_with_foreign_content_is_left_alone() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        _fill(tmp / "guarded.log", "guarded")
        lock = tmp / "lock"
        lock.mkdir()
        (lock / "someone-elses-file").write_text("keep me\n")
        proc = _run(tmp, env=_lock_env(tmp))
        assert proc.returncode == 0, proc.stderr
        assert "refusing to rotate" in proc.stdout
        assert not (tmp / "guarded.log.1").exists()
        assert (lock / "someone-elses-file").read_text() == "keep me\n"
        assert not list(tmp.glob("lock.*")), "nothing may be renamed or moved"


def test_lock_dir_symlink_is_not_followed_on_release() -> None:
    """The lock path pre-exists as a symlink: mkdir fails, run refuses, link stays."""
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        _fill(tmp / "s.log", "s")
        target = tmp / "target-dir"
        target.mkdir()
        (target / "pid").write_text("999999999\n")
        (tmp / "lock").symlink_to(target)
        proc = _run(tmp, env=_lock_env(tmp))
        assert proc.returncode == 0, proc.stderr
        assert "refusing to rotate" in proc.stdout
        assert (tmp / "lock").is_symlink() and (target / "pid").exists()
        assert not (tmp / "s.log.1").exists()


def test_two_concurrent_runs_rotate_exactly_once() -> None:
    """mkdir atomicity: with no prior lock, one of two simultaneous runs wins."""
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        _fill(tmp / "race.log", "race")
        env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp),
               "AGENTSTACK_LOG_ROTATE_THRESHOLD_BYTES": str(THRESHOLD),
               "AGENTSTACK_LOG_ROTATE_KEEP": "3", **_lock_env(tmp)}
        procs = [subprocess.Popen(["/bin/bash", str(SCRIPT), str(tmp)], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        outs = [pr.communicate() for pr in procs]
        assert all(pr.returncode == 0 for pr in procs), outs
        rotated = sum("rotated race.log" in out for out, _ in outs)
        assert rotated == 1, outs
        assert (tmp / "race.log.1").exists() and not (tmp / "race.log.2").exists()
        assert not (tmp / "lock").exists(), "the winner releases its own lock"


def test_successful_run_releases_only_its_own_lock() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        _fill(tmp / "own.log", "own")
        proc = _run(tmp, env=_lock_env(tmp))
        assert proc.returncode == 0, proc.stderr
        assert (tmp / "own.log.1").exists()
        assert not (tmp / "lock").exists()


def test_preexisting_symlink_named_like_the_old_tmp_is_not_followed() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        outside = tmp / "outside.txt"
        outside.write_text("external\n")
        root = tmp / "runtime"
        root.mkdir()
        _fill(root / "w.log", "w")
        (root / "w.log.1.tmp").symlink_to(outside)
        proc = _run(root, env=_lock_env(tmp))
        assert proc.returncode == 0, proc.stderr
        assert outside.read_text() == "external\n"
        assert (root / "w.log.1.tmp").is_symlink()
        assert (root / "w.log.1").read_text().startswith("w ")
        assert not list(root.glob(".w.log.rotate.*")), "temp copy must not be left behind"


def test_archive_slot_that_is_a_directory_blocks_rotation() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        _fill(tmp / "d.log", "d")
        (tmp / "d.log.2").mkdir()
        (tmp / "d.log.2" / "inner").write_text("inner\n")
        _fill(tmp / "d.log.1", "old-archive")
        proc = _run(tmp, env=_lock_env(tmp))
        assert proc.returncode == 0, proc.stderr
        assert "not a plain file" in proc.stdout
        assert (tmp / "d.log").stat().st_size > THRESHOLD
        assert (tmp / "d.log.1").read_text().startswith("old-archive ")
        assert (tmp / "d.log.2" / "inner").read_text() == "inner\n"


def test_hard_linked_archive_slot_blocks_rotation() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        _fill(tmp / "h.log", "h")
        keep = tmp / "keep.txt"
        keep.write_text("linked\n")
        os.link(keep, tmp / "h.log.3")
        proc = _run(tmp, env=_lock_env(tmp))
        assert proc.returncode == 0, proc.stderr
        assert "not a plain file" in proc.stdout
        assert keep.read_text() == "linked\n"
        assert (tmp / "h.log").stat().st_size > THRESHOLD


def test_keep_one_with_existing_archive_and_leftover_tmp() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        log = tmp / "k.log"
        _fill(log, "new")
        _fill(tmp / "k.log.1", "previous")
        leftover = tmp / ".k.log.rotate.LEFTOVER"
        leftover.write_text("crashed run\n")
        proc = _run(tmp, env={**_lock_env(tmp), "AGENTSTACK_LOG_ROTATE_KEEP": "1"})
        assert proc.returncode == 0, proc.stderr
        assert log.stat().st_size == 0
        assert (tmp / "k.log.1").read_text().startswith("new ")
        assert not (tmp / "k.log.2").exists()
        assert leftover.read_text() == "crashed run\n", "foreign temp files are not touched"


def test_open_append_writer_survives_rotation() -> None:
    """launchd opens StandardOutPath with O_APPEND; this is that writer."""
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        log = tmp / "live.log"
        _fill(log, "before")
        with open(log, "a", encoding="utf-8") as writer:
            writer.write("still-open-before\n")
            writer.flush()
            proc = _run(tmp, env=_lock_env(tmp))
            assert proc.returncode == 0, proc.stderr
            writer.write("after-rotate\n")
            writer.flush()
        data = log.read_bytes()
        assert data == b"after-rotate\n", data[:80]
        archived = (tmp / "live.log.1").read_text()
        assert archived.startswith("before ") and archived.endswith("still-open-before\n")


def test_non_append_writer_leaves_a_sparse_hole() -> None:
    """Documents the stated hazard: a writer without O_APPEND keeps its old
    offset, so the truncated file grows back with a NUL-filled hole."""
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        log = tmp / "hole.log"
        _fill(log, "before")
        fd = os.open(log, os.O_WRONLY)
        try:
            os.lseek(fd, 0, os.SEEK_END)
            proc = _run(tmp, env=_lock_env(tmp))
            assert proc.returncode == 0, proc.stderr
            os.write(fd, b"after\n")
        finally:
            os.close(fd)
        data = log.read_bytes()
        assert data.endswith(b"after\n")
        assert data.count(b"\0") > 0 and len(data) > THRESHOLD


ALL_TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]

if __name__ == "__main__":
    failed = 0
    for test in ALL_TESTS:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
    print(f"{len(ALL_TESTS) - failed}/{len(ALL_TESTS)} passed")
    sys.exit(1 if failed else 0)

#!/usr/bin/env python3
"""Serialize a local seat lifecycle and bind cleanup to one launch generation.

Lock files are never unlinked. Journals contain paths/inodes, never credentials.
An automatic caller without a complete journal cannot retire or delete a seat.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import uuid


LOCK_FD = 9


def seat_key(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise ValueError("invalid seat name")
    normalized = re.sub(r"[^a-z0-9]", "", name.lower())
    if not normalized:
        raise ValueError("empty seat key")
    return hashlib.sha256(normalized.encode()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Seat:
    def __init__(self, runtime: str | Path, name: str):
        self._held = False
        self.root = Path(runtime).resolve()
        self.name = name
        self.key = seat_key(name)
        self.locks = self.root / "seat-locks"
        self.journals = self.root / "seat-launches"
        self.lock_path = self.locks / (self.key + ".lock")
        self.lease_path = self.journals / (self.key + ".current.json")

    def directories(self):
        for path in (self.root, self.locks, self.journals):
            if path.is_symlink():
                raise ValueError("lifecycle directory is a symlink")
            path.mkdir(mode=0o700, parents=True, exist_ok=True)

    def inherited_lock(self) -> bool:
        if self._held:
            return True
        if os.environ.get("AGENTSTACK_SEAT_LOCK_FD") != str(LOCK_FD):
            return False
        try:
            opened = os.fstat(LOCK_FD)
            named = self.lock_path.lstat()
            if not stat.S_ISREG(named.st_mode) or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
                return False
            fcntl.flock(LOCK_FD, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (OSError, ValueError):
            return False

    @contextmanager
    def locked(self, *, blocking=True):
        if self.inherited_lock():
            yield
            return
        self.directories()
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.lock_path, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("invalid seat lock")
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            self._held = True
            yield
        finally:
            self._held = False
            os.close(fd)

    def lock_exec(self, command: list[str]):
        self.directories()
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("invalid seat lock")
        fcntl.flock(fd, fcntl.LOCK_EX)
        if fd != LOCK_FD:
            os.dup2(fd, LOCK_FD, inheritable=True)
            os.close(fd)
        os.set_inheritable(LOCK_FD, True)
        environment = dict(os.environ, AGENTSTACK_SEAT_LOCK_FD=str(LOCK_FD))
        os.execvpe(command[0], command, environment)

    def paths(self) -> dict[str, Path]:
        children = self.root / "child-agents"
        return dict(token=self.root / ("agent_token_" + self.name),
                    state=children / (self.name + ".json"),
                    mcp=children / (self.name + ".mcp.json"),
                    home=children / (self.name + ".codex-home"))

    def begin(self, project: str, managed: Path) -> dict:
        if not project or not self.inherited_lock():
            raise ValueError("begin requires project and seat lock")
        self.directories()
        children = self.root / "child-agents"
        if children.is_symlink() or (children.exists() and not children.is_dir()):
            raise ValueError("child state directory is not a real directory")
        state = self.paths()['state']
        if state.exists() or state.is_symlink():
            fd = os.open(state, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
            with os.fdopen(fd) as stream:
                prior_state = json.load(stream)
            if prior_state.get('project_key') != project or prior_state.get('agent_name') != self.name:
                raise ValueError('existing state project/name mismatch')
        if self.lease_path.exists() and any(self.paths()[k].exists() for k in ('token', 'state')):
            prior_lease = json.loads(self.lease_path.read_text())
            if prior_lease.get('journal'):
                prior = self.load(prior_lease['journal'])
                if self.current(prior) and prior.get('session_started'):
                    raise ValueError('active generation requires authenticated restart invalidation')
        generation = uuid.uuid4().hex
        journal = self.journals / (self.key + "." + generation + ".json")
        managed_exists = managed.is_file() and self.name in managed.read_text().splitlines()
        preserve = managed_exists or any(os.path.lexists(p) for p in self.paths().values())
        value = dict(version=1, name=self.name, project=project, generation=generation,
                     attempt=os.environ.get("AGENTSTACK_LAUNCH_ATTEMPT_ID", ""),
                     journal=str(journal), preserve=preserve, managed=str(managed),
                     managed_added=False, auth={"owned": [], "observed": []},
                     artifacts={"owned": []}, session_started=False)
        atomic_json(journal, value)
        if value['attempt']:
            # A dashboard request binds once. Inheriting/reusing its nonce must
            # never transfer its delayed callback to a successor generation.
            binding = self.attempt_path(value['attempt'])
            try:
                fd = os.open(binding, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, 'w') as stream:
                    json.dump({'journal': str(journal), 'generation': generation}, stream)
                    stream.flush(); os.fsync(stream.fileno())
        atomic_json(self.lease_path, {k: value[k] for k in ("name", "project", "generation", "journal", "attempt")})
        return value

    def attempt_path(self, attempt):
        return self.journals / (self.key + '.attempt-' + hashlib.sha256(attempt.encode()).hexdigest() + '.json')

    def attempt_journal(self, attempt):
        path = self.attempt_path(attempt)
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd) as stream:
            value = json.load(stream)
        journal = self.load(value['journal'])
        if journal['generation'] != value['generation'] or journal['attempt'] != attempt:
            raise ValueError('attempt generation mismatch')
        return journal['journal']

    def invalidate(self):
        if not self.inherited_lock():
            raise ValueError("invalidation requires seat lock")
        self.directories()
        atomic_json(self.lease_path, dict(name=self.name, generation=uuid.uuid4().hex,
                                         journal="", project="", attempt=""))

    def load(self, journal: str | Path) -> dict:
        path = Path(journal)
        # Do not read a caller-selected file outside this seat's journal area.
        if path.parent.resolve() != self.journals or path.is_symlink():
            raise ValueError("journal outside lifecycle namespace")
        value = json.loads(path.read_text())
        generation = value["generation"]
        if (value.get("version") != 1 or value.get("name") != self.name or
                not re.fullmatch(r"[0-9a-f]{32}", generation) or
                path.name != self.key + "." + generation + ".json"):
            raise ValueError("journal identity mismatch")
        return value

    def current(self, value: dict) -> bool:
        try:
            current = json.loads(self.lease_path.read_text())
            return all(current.get(k) == value.get(k) for k in ("name", "project", "generation", "journal"))
        except (OSError, ValueError):
            return False

    def update(self, journal: str, *, auth=None, artifacts=None, session_started=None):
        if not self.inherited_lock():
            raise ValueError("journal update requires seat lock")
        value = self.load(journal)
        if not self.current(value):
            raise ValueError("launch generation changed")
        if auth is not None:
            # Intent records may precede publication. Merge, rather than lose
            # objects a helper reported before a later signal/error.
            for kind in ("owned", "observed"):
                value["auth"][kind] = list({tuple(e) for e in value["auth"][kind] + auth.get(kind, [])})
            owned = {tuple(e) for e in value["auth"]["owned"]}
            if any(tuple(e) not in owned for e in value["auth"]["observed"]):
                value["preserve"] = True
        if artifacts is not None:
            value["artifacts"]["owned"] = list({tuple(e) for e in value["artifacts"]["owned"] + artifacts.get("owned", [])})
            contents = {e[0]: e for e in value["artifacts"].get("home_contents", [])}
            contents.update({e[0]: e for e in artifacts.get("home_contents", [])})
            value["artifacts"]["home_contents"] = list(contents.values())
        if session_started is not None:
            value["session_started"] = session_started
        atomic_json(Path(journal), value)
        return value

    def entries(self, value: dict):
        expected = self.paths()
        auth = {str(expected[k]) for k in ("token", "state")}
        artifacts = {str(expected["mcp"]): "file", str(expected["home"]): "directory"}
        entries = []
        for group in ("owned", "observed"):
            for entry in value["auth"][group]:
                path, device, inode = entry
                path = str(Path(path).absolute().parent.resolve() / Path(path).name)
                if path not in auth or type(device) is not int or type(inode) is not int:
                    raise ValueError("invalid auth ownership")
                entries.append((Path(path), device, inode, "file"))
        for path, device, inode, kind in value["artifacts"]["owned"]:
            path = str(Path(path).absolute().parent.resolve() / Path(path).name)
            if artifacts.get(path) != kind or type(device) is not int or type(inode) is not int:
                raise ValueError("invalid artifact ownership")
            entries.append((Path(path), device, inode, kind))
        return entries

    @staticmethod
    def matches(path: Path, device: int, inode: int, kind: str) -> bool:
        try:
            current = path.lstat()
        except FileNotFoundError:
            return True
        correct_kind = stat.S_ISDIR(current.st_mode) if kind == "directory" else stat.S_ISREG(current.st_mode)
        return correct_kind and (current.st_dev, current.st_ino) == (device, inode)

    def validate(self, journal: str, *, automatic=False) -> dict | None:
        try:
            value = self.load(journal)
            if not self.current(value) or (automatic and value["preserve"]):
                return None
            if not value["project"]:
                return None
            if automatic:
                # A partial intent record is useful for rollback, but cannot
                # authorize server retirement. Require the complete published
                # auth pair from this launch, plus a started child session.
                expected = {str(self.paths()[k]) for k in ("token", "state")}
                published = {p for p, _, _ in value["auth"]["observed"]}
                owned = {p for p, _, _ in value["auth"]["owned"]}
                if (not value.get("session_started") or published != expected
                        or owned != expected or any(not Path(p).is_file() for p in expected)):
                    return None
            if any(not self.matches(*entry) for entry in self.entries(value)):
                return None
            return value
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def delete(self, journal: str, *, automatic=False) -> bool:
        if not self.inherited_lock():
            raise ValueError("deletion requires seat lock")
        value = self.validate(journal, automatic=automatic)
        if value is None:
            return False
        # Revalidate after HTTP and immediately before each destructive call.
        owned = [(Path(p), d, i, "file") for p, d, i in value["auth"]["owned"]]
        owned += [(Path(p), d, i, k) for p, d, i, k in value["artifacts"]["owned"]]
        for path, device, inode, kind in owned:
            if not self.current(value) or not self.matches(path, device, inode, kind):
                return False
            if not os.path.lexists(path):
                continue
            if kind == "directory":
                # The directory inode does not confer ownership of its contents.
                # Unknown files (including permanent child receipts) veto removal.
                contents = value["artifacts"].get("home_contents", [])
                expected = {entry[0] for entry in contents}
                if {entry.name for entry in path.iterdir()} != expected:
                    continue
                for name, child_device, child_inode, child_kind, digest in contents:
                    if Path(name).name != name or name in (".", ".."):
                        return False
                    child = path / name
                    if not self.current(value) or not home_entry_matches(child, child_device, child_inode, child_kind, digest):
                        return False
                for name, child_device, child_inode, child_kind, digest in contents:
                    child = path / name
                    if (not self.current(value) or not self.matches(path, device, inode, kind)
                            or not home_entry_matches(child, child_device, child_inode, child_kind, digest)):
                        return False
                    # No recursive removal and no following symlinks.
                    child.unlink()
                try:
                    path.rmdir()
                except OSError:
                    # A concurrent new entry belongs to its writer.
                    continue
            else:
                path.unlink()
        if value["managed_added"]:
            managed_update(Path(value["managed"]), self.name, add=False)
        return True


def managed_update(path: Path, name: str, *, add: bool, before_add=None) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = os.open(str(path) + ".lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.is_symlink():
            raise ValueError("managed list is a symlink")
        lines = path.read_text().splitlines() if path.exists() else []
        existed = name in lines
        if add and not existed:
            if before_add is not None:
                before_add()
            lines.append(name)
        elif not add:
            lines = [line for line in lines if line != name]
        fd, temporary = tempfile.mkstemp(prefix=".managed.", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write("\n".join(lines) + ("\n" if lines else ""))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return not existed
    finally:
        os.close(lock)


def record_intent(*, auth=None, artifacts=None):
    """Called inside a writer before publishing an object or returning stdout."""
    journal = os.environ.get("AGENTSTACK_LAUNCH_JOURNAL")
    name = os.environ.get("AGENTSTACK_LIFECYCLE_NAME")
    runtime = os.environ.get("AGENTSTACK_RUNTIME_DIR")
    if journal and name and runtime:
        Seat(runtime, name).update(journal, auth=auth, artifacts=artifacts)


def home_entry_identity(path: Path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        kind, data = "symlink", os.readlink(path).encode()
    elif stat.S_ISREG(info.st_mode):
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise ValueError('home entry changed while opening')
            kind, data = "file", stream.read()
    else:
        raise ValueError("unowned child home entry kind")
    current = path.lstat()
    if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
        raise ValueError('home entry changed while reading')
    return [path.name, info.st_dev, info.st_ino, kind, hashlib.sha256(data).hexdigest()]


def home_entry_matches(path, device, inode, kind, digest):
    try:
        return home_entry_identity(path)[1:] == [device, inode, kind, digest]
    except (OSError, ValueError):
        return False


def record_home_entry(path: Path):
    record_intent(artifacts={"home_contents": [home_entry_identity(path)]})


def refresh_generated_file(path: Path, payload: str):
    """Authenticated restart only: retain old bytes before atomic config refresh."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        identity = os.fstat(stream.fileno())
        if not stat.S_ISREG(identity.st_mode) or identity.st_uid != os.getuid():
            raise ValueError("existing config is not an owned regular file")
        old = stream.read()
    root = Path(os.environ['AGENTSTACK_RUNTIME_DIR']) / 'seat-launches' / 'config-backups'
    if root.is_symlink():
        raise ValueError('config backup directory is a symlink')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    digest = hashlib.sha256(old).hexdigest()
    backup = root / (path.name + '.' + digest + '.before')
    try:
        backup_fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    except FileExistsError:
        if backup.is_symlink() or backup.read_bytes() != old:
            raise ValueError('config backup collision')
    else:
        with os.fdopen(backup_fd, 'wb') as stream:
            stream.write(old); stream.flush(); os.fsync(stream.fileno())
    fd, temporary = tempfile.mkstemp(prefix='.refresh-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        now = path.lstat()
        if ((now.st_dev, now.st_ino) != (identity.st_dev, identity.st_ino)
                or path.is_symlink() or path.read_bytes() != old):
            raise ValueError('config changed during refresh')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def handoff_location(runtime: Path, path: Path) -> Path:
    """Only the dedicated one-shot namespace can publish consumable credentials."""
    directory = runtime.resolve() / "spawn-tokens"
    if directory.is_symlink() or path.is_symlink() or path.parent.resolve() != directory:
        raise ValueError("handoff must be in runtime/spawn-tokens")
    if not re.fullmatch(r"(?:[A-Za-z0-9_-]+\.)*[0-9a-f]{32}\.token", path.name):
        raise ValueError("handoff needs a unique 32-hex token filename")
    return directory / path.name


def bind_handoff(runtime: Path, path: Path, name: str, project: str):
    path = handoff_location(runtime, path)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or not 0 < info.st_size <= 4096
                or info.st_nlink != 1):
            raise ValueError("handoff must be an owned regular 0600 bounded file")
        data = stream.read(4097)
    ticket = path.with_name(path.name + ".handoff.json")
    value = dict(version=1, name=name, project=project, device=info.st_dev, inode=info.st_ino,
                 sha256=hashlib.sha256(data).hexdigest())
    fd = os.open(ticket, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream); stream.flush(); os.fsync(stream.fileno())


def check_handoff(runtime: Path, path: Path, name: str, project: str, info, data: bytes):
    path = handoff_location(runtime, path)
    if info.st_nlink != 1:
        raise ValueError("handoff is hardlinked")
    ticket = path.with_name(path.name + ".handoff.json")
    fd = os.open(ticket, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd) as stream:
        entry = os.fstat(stream.fileno())
        if (not stat.S_ISREG(entry.st_mode) or entry.st_uid != os.getuid()
                or stat.S_IMODE(entry.st_mode) != 0o600 or entry.st_size > 4096):
            raise ValueError("invalid handoff ticket")
        value = json.load(stream)
    expected = dict(version=1, name=name, project=project, device=info.st_dev, inode=info.st_ino,
                    sha256=hashlib.sha256(data).hexdigest())
    if value != expected:
        raise ValueError("handoff belongs to another launch, name or project")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("held", "lock-exec", "begin", "invalidate", "check", "delete", "record", "managed-add", "managed-ensure", "retire-args", "failure-retire-args", "available"))
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--project", default="")
    parser.add_argument("--journal", default=os.environ.get("AGENTSTACK_LAUNCH_JOURNAL", ""))
    parser.add_argument("--managed", default="")
    parser.add_argument("--auth")
    parser.add_argument("--artifacts")
    parser.add_argument("--automatic", action="store_true")
    parser.add_argument("--session-started", action="store_true")
    args, command = parser.parse_known_args()
    seat = Seat(args.runtime, args.name)
    if args.command == "held":
        return 0 if seat.inherited_lock() else 1
    if args.command == "lock-exec":
        if command and command[0] == "--": command.pop(0)
        if not command: raise ValueError("command required")
        seat.lock_exec(command)
    if args.command == "managed-ensure":
        managed_update(Path(args.managed), args.name, add=True)
        return 0
    if args.command == "available":
        # Local paths are shared by all projects. Do not treat whois(project B)
        # as permission to overwrite a project A identity.
        for pattern in ("agent_token_*", "child-agents/*"):
            for path in seat.root.glob(pattern):
                name = path.name.removeprefix("agent_token_")
                for suffix in (".codex-home", ".mcp.json", ".json"):
                    name = name.removesuffix(suffix)
                if seat_key(name) == seat.key:
                    return 1
        return 0
    if not seat.inherited_lock():
        raise ValueError("lifecycle operation requires held seat lock")
    if args.command == "begin":
        print(json.dumps(seat.begin(args.project, Path(args.managed))))
    elif args.command == "invalidate":
        seat.invalidate()
    elif args.command == "check":
        return 0 if seat.validate(args.journal, automatic=args.automatic) is not None else 1
    elif args.command in ("retire-args", "failure-retire-args"):
        automatic = args.command == "retire-args"
        value = seat.validate(args.journal, automatic=automatic)
        if value is None:
            return 1
        expected = {str(seat.paths()[k]) for k in ('token', 'state')}
        if value['preserve'] or {p for p, _, _ in value['auth']['owned']} != expected or {p for p, _, _ in value['auth']['observed']} != expected:
            return 1
        token_path = seat.paths()["token"]
        entry = next(e for e in value["auth"]["owned"] if e[0] == str(token_path))
        fd = os.open(token_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "r") as stream:
            identity = os.fstat(stream.fileno())
            if (identity.st_dev, identity.st_ino) != tuple(entry[1:]):
                return 1
            token = stream.read(4097).strip()
        if not token or len(token) > 4096 or seat.validate(args.journal, automatic=automatic) is None:
            return 1
        print(json.dumps(dict(project_key=value["project"], agent_name=seat.name, registration_token=token)))
    elif args.command == "delete":
        return 0 if seat.delete(args.journal, automatic=args.automatic) else 1
    elif args.command == "record":
        seat.update(args.journal, auth=json.loads(args.auth) if args.auth is not None else None,
                    artifacts=json.loads(args.artifacts) if args.artifacts is not None else None,
                    session_started=True if args.session_started else None)
    elif args.command == "managed-add":
        value = seat.load(args.journal)
        if not seat.current(value):
            raise ValueError("launch generation changed")
        def mark_added():
            value["managed_added"] = True
            atomic_json(Path(args.journal), value)
        managed_update(Path(args.managed), args.name, add=True, before_add=mark_added)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"seat lifecycle: {error}; preserving existing state", file=sys.stderr)
        raise SystemExit(1)

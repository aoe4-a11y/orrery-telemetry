"""The dashboard keeps one tmux consumer per endpoint (2026-10-16).

_tmux_run built a new legacy consumer for every tmux command, and building one
resolves and verifies the endpoint with a display-message process: about a
fifth of a /api/agents computation in a profile. The consumer is now kept while
the endpoint's socket is the same file (same device and inode). Every command
is still admitted by the consumer; a restarted tmux server makes a new socket
file, so the next command builds a new consumer.

These run a real tmux server in a private TMUX_TMPDIR, with the installed
client library under a temporary AGENTSTACK_HOME.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from dashboard import server
from _installed_client_payload import copy_client_library

TMUX = shutil.which("tmux")
pytestmark = pytest.mark.skipif(TMUX is None, reason="tmux is not installed")


@pytest.fixture
def endpoint(monkeypatch):
    base = "/private/tmp" if Path("/private/tmp").is_dir() else None
    with tempfile.TemporaryDirectory(prefix="ct-", dir=base) as directory:
        root = Path(directory).resolve()
        home = root / "home" / ".agentstack"
        (home / "hooks").mkdir(parents=True)
        copy_client_library(home)
        sockets = root / "s"
        sockets.mkdir(mode=0o700)
        for key in list(os.environ):
            if key.startswith("AGENTSTACK_") or key in ("TMUX", "TMUX_PANE"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("AGENTSTACK_HOME", str(home))
        monkeypatch.setenv("TMUX_TMPDIR", str(sockets))
        monkeypatch.setattr(server, "HOOKS_DIR", str(home / "hooks"))
        env = {**os.environ}

        def tmux(*args, check=True):
            return subprocess.run([TMUX, *args], env=env, capture_output=True, text=True, check=check)

        tmux("new-session", "-d", "-s", "Alpha", "sleep 600")
        built, admitted = [], []
        real_build = server._build_legacy_tmux_consumer

        def counting_build():
            consumer = real_build()
            built.append(consumer)
            if consumer is not None:
                real_admission = consumer.admission

                def admission(target, operation):
                    admitted.append((target, operation))
                    return real_admission(target, operation)

                consumer.admission = admission
            return consumer

        monkeypatch.setattr(server, "_build_legacy_tmux_consumer", counting_build)
        server._reset_tmux_consumer_cache()
        try:
            yield {"tmux": tmux, "built": built, "admitted": admitted, "sockets": sockets}
        finally:
            tmux("kill-server", check=False)
            server._reset_tmux_consumer_cache()


def test_one_consumer_serves_many_commands_and_each_is_admitted(endpoint):
    for _ in range(5):
        assert server._tmux(["display-message", "-p", "-t", "=Alpha", "#{session_name}"]).strip() == "Alpha"
    assert len(endpoint["built"]) == 1
    assert endpoint["admitted"] == [("=Alpha", "capture")] * 5


def test_inventory_still_reads_through_the_kept_consumer(endpoint):
    for _ in range(3):
        assert "Alpha" in server._tmux(["list-sessions", "-F", "#{session_name}"])
    assert len(endpoint["built"]) == 1


def test_a_restarted_server_is_a_new_socket_and_a_new_consumer(endpoint):
    tmux = endpoint["tmux"]
    assert server._tmux(["display-message", "-p", "-t", "=Alpha", "#{session_name}"]).strip() == "Alpha"
    first = endpoint["built"][-1]
    identity = first.transport.identity
    tmux("kill-server")
    time.sleep(0.2)
    tmux("new-session", "-d", "-s", "Beta", "sleep 600")
    assert not server._consumer_still_current(first)          # the identity check fails
    assert server._tmux(["display-message", "-p", "-t", "=Beta", "#{session_name}"]).strip() == "Beta"
    assert len(endpoint["built"]) == 2
    assert endpoint["built"][-1].transport.identity != identity
    # admission continues on the new consumer, for every command
    before = len(endpoint["admitted"])
    for _ in range(3):
        server._tmux(["display-message", "-p", "-t", "=Beta", "#{session_name}"])
    assert len(endpoint["admitted"]) == before + 3
    assert len(endpoint["built"]) == 2


def test_a_session_gone_on_a_kept_consumer_is_refused_as_before(endpoint):
    tmux = endpoint["tmux"]
    server._tmux(["display-message", "-p", "-t", "=Alpha", "#{session_name}"])
    tmux("new-session", "-d", "-s", "Keep", "sleep 600")   # the server stays up
    tmux("kill-session", "-t", "=Alpha")
    assert server._tmux(["display-message", "-p", "-t", "=Alpha", "#{session_name}"]) == ""
    assert endpoint["admitted"][-1] == ("=Alpha", "capture")
    assert len(endpoint["built"]) == 1


def test_another_endpoint_in_the_environment_builds_another_consumer(endpoint, monkeypatch, tmp_path):
    server._tmux(["display-message", "-p", "-t", "=Alpha", "#{session_name}"])
    other = Path(tempfile.mkdtemp(prefix="ct-", dir=str(endpoint["sockets"].parent))).resolve()
    other.chmod(0o700)
    monkeypatch.setenv("TMUX_TMPDIR", str(other))
    server._tmux(["list-sessions", "-F", "#{session_name}"])
    assert len(endpoint["built"]) == 2


def test_a_stopped_server_with_its_socket_left_reads_as_empty(endpoint):
    """tmux 3.6 leaves the socket file after kill-server. A consumer built now
    would pin the same file, so keeping one changes nothing: the inventory is
    empty either way."""
    tmux = endpoint["tmux"]
    server._tmux(["list-sessions", "-F", "#{session_name}"])
    tmux("kill-server")
    time.sleep(0.2)
    for _ in range(2):
        assert server._tmux(["list-sessions", "-F", "#{session_name}"]) == ""
    assert len(endpoint["built"]) == 1


def test_no_socket_at_build_time_is_not_kept(endpoint):
    tmux = endpoint["tmux"]
    tmux("kill-server")
    time.sleep(0.2)
    socket = endpoint["sockets"] / f"tmux-{os.getuid()}" / "default"
    if socket.exists():
        socket.unlink()                                       # no server and no socket file
    for _ in range(2):
        assert server._tmux(["list-sessions", "-F", "#{session_name}"]) == ""
    assert len(endpoint["built"]) == 2                        # no identity: built each time, as before
    assert server._TMUX_CONSUMER_CACHE["consumer"] is None

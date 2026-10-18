"""Give subprocess fixtures user directories that cannot resolve to live homes."""
from __future__ import annotations

import os
from pathlib import Path
from collections.abc import Mapping
import atexit
import tempfile

_socket_root = None


def private_tmux_directory():
    global _socket_root
    if _socket_root is None:
        _socket_root = Path(tempfile.mkdtemp(prefix='orrery-test-tmux-', dir='/tmp'))
        def remove_empty_socket_directory():
            # Never unlink a socket or stop a process implicitly.
            for entry in _socket_root.iterdir():
                if entry.is_dir():
                    try: entry.rmdir()
                    except OSError: pass
            try: _socket_root.rmdir()
            except OSError: pass
        atexit.register(remove_empty_socket_directory)
    return str(_socket_root)


def isolated_user_environment(
    home: Path, ambient: Mapping[str, str] | None = None,
) -> dict[str, str]:
    if home.is_symlink():
        raise ValueError("fixture home is a symlink")
    home.mkdir(parents=True, exist_ok=True)
    home = home.resolve(strict=True)
    env = dict(os.environ if ambient is None else ambient)
    for key in list(env):
        if key.startswith(("AGENTSTACK_", "MCP_AGENT_MAIL_")) or key in {
            "AGENT_NAME", "PARENT_AGENT", "PROJECT_KEY", "CHILD_REGISTRATION_TOKEN",
            "TMUX", "TMUX_PANE", "HTTP_BEARER_TOKEN",
        }:
            env.pop(key)
    for key, relative in {
        "HOME": ".",
        "CODEX_HOME": ".codex",
        "CODEX_SHARED_CODEX_DIR": ".codex",
        "CLAUDE_HOME": ".claude",
        "CLAUDE_CONFIG_DIR": ".claude",
        "XDG_CONFIG_HOME": ".config",
        "XDG_DATA_HOME": ".local/share",
        "XDG_CACHE_HOME": ".cache",
    }.items():
        path = home / relative
        # A reused fixture must fail closed rather than traverse a home symlink.
        if path.is_symlink():
            raise ValueError(f"fixture user directory is a symlink: {key}")
        if not path.resolve(strict=False).is_relative_to(home):
            raise ValueError(f"fixture user directory escaped its home: {key}")
        env[key] = str(path)
    # tmux ignores TMPDIR; its default server socket must be private too.
    # A short socket directory avoids AF_UNIX's path length limit on macOS.
    env['TMUX_TMPDIR'] = private_tmux_directory()
    env['AGENTSTACK_MAIL_HTTP_BEARER_MODE'] = 'disabled'
    guards = home / '.test-bin'
    guards.mkdir(exist_ok=True)
    security = guards / 'security'
    security.write_text('#!/bin/sh\necho "test blocked login keychain access" >&2\nexit 77\n')
    security.chmod(0o700)
    env['PATH'] = str(guards) + os.pathsep + env.get('PATH', os.defpath)
    return env

#!/usr/bin/env python3
"""Regression tests for child cleanup identity isolation."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hooks"))
from seat_lifecycle import Seat, atomic_json
HOOK = ROOT / "hooks" / "cleanup-child-agent.sh"


def _arrange_child_state(tmp_path: Path) -> tuple[str, dict[str, str], list[Path]]:
    hooks = tmp_path / "hooks"
    runtime = tmp_path / "runtime"
    state_dir = runtime / "child-agents"
    hooks.mkdir()
    state_dir.mkdir(parents=True)

    agent_name = "Other-Agent"
    managed_file = runtime / "managed_agents.txt"
    lifecycle = Seat(runtime, agent_name)
    with lifecycle.locked():
        journal = lifecycle.begin("/test/project", managed_file)
    (hooks / "seat_lifecycle.py").write_text((ROOT / "hooks/seat_lifecycle.py").read_text())
    (hooks / "resolve-agent-name.sh").write_text(
        f'RESOLVED_AGENT="{agent_name}"\n', encoding="utf-8"
    )
    state_file = state_dir / f"{agent_name}.json"
    state_file.write_text(
        json.dumps(
            {
                "project_key": "/test/project",
                "registration_token": "test-registration-token",
            }
        ),
        encoding="utf-8",
    )
    token_file = runtime / f"agent_token_{agent_name}"
    token_file.write_text("test-registration-token", encoding="utf-8")
    mcp_config = state_dir / f"{agent_name}.mcp.json"
    mcp_config.write_text("{}", encoding="utf-8")
    codex_home = state_dir / f"{agent_name}.codex-home"
    codex_home.mkdir()
    managed_file = runtime / "managed_agents.txt"
    managed_file.write_text(f"{agent_name}\n", encoding="utf-8")

    env = os.environ.copy()
    for inherited_name in (
        "AGENT_NAME",
        "PROJECT_KEY",
        "AGENTSTACK_PROJECT_KEY",
        "CHILD_REGISTRATION_TOKEN",
        "MCP_AGENT_MAIL_TOKEN",
        "AGENTSTACK_MAIL_ENV",
        "MCP_URL",
    ):
        env.pop(inherited_name, None)
    env.update(
        {
            "AGENTSTACK_HOOKS_DIR": str(hooks),
            "AGENTSTACK_RUNTIME_DIR": str(runtime),
            "AGENTSTACK_MANAGED_AGENTS_FILE": str(managed_file),
            "AGENTSTACK_MAIL_HTTP_BEARER_MODE": "disabled",
            "AGENTSTACK_MCP_URL": "http://127.0.0.1:1/mcp",
        }
    )
    auth = [[str(path), path.stat().st_dev, path.stat().st_ino] for path in (token_file, state_file)]
    owned = [[str(path), path.stat().st_dev, path.stat().st_ino, kind]
             for path, kind in ((mcp_config, "file"), (codex_home, "directory"))]
    with lifecycle.locked():
        journal = lifecycle.update(journal["journal"], auth={"owned": auth, "observed": auth},
                                   artifacts={"owned": owned}, session_started=True)
        journal["managed_added"] = True
        atomic_json(Path(journal["journal"]), journal)
    env.update(AGENTSTACK_LIFECYCLE_NAME=agent_name, AGENTSTACK_LAUNCH_JOURNAL=journal["journal"])
    artifacts = [state_file, token_file, mcp_config, codex_home]
    return agent_name, env, artifacts


def test_cleanup_without_explicit_identity_does_not_retire_resolved_agent(
    tmp_path: Path,
) -> None:
    """Ambient resolver state must never select another agent for cleanup."""
    agent_name, env, artifacts = _arrange_child_state(tmp_path)
    result = subprocess.run(
        ["/bin/bash", str(HOOK)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert all(path.exists() for path in artifacts)
    managed_file = Path(env["AGENTSTACK_MANAGED_AGENTS_FILE"])
    assert managed_file.read_text(encoding="utf-8") == f"{agent_name}\n"


def test_cleanup_with_argument_still_cleans_named_child(tmp_path: Path) -> None:
    agent_name, env, artifacts = _arrange_child_state(tmp_path)
    result = subprocess.run(
        ["/bin/bash", str(HOOK), agent_name],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert not any(path.exists() for path in artifacts)


def test_cleanup_with_entry_environment_still_cleans_child(tmp_path: Path) -> None:
    agent_name, env, artifacts = _arrange_child_state(tmp_path)
    env["AGENT_NAME"] = agent_name
    result = subprocess.run(
        ["/bin/bash", str(HOOK)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert not any(path.exists() for path in artifacts)


def test_invalid_child_state_fails_loudly_without_partial_cleanup(
    tmp_path: Path,
) -> None:
    agent_name, env, artifacts = _arrange_child_state(tmp_path)
    artifacts[0].write_text("{not-json", encoding="utf-8")
    result = subprocess.run(
        ["/bin/bash", str(HOOK), agent_name],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert "could not read child state" in result.stderr
    assert all(path.exists() for path in artifacts)


def _main() -> int:
    failures = 0
    for name, function in sorted(globals().items()):
        if not name.startswith("test_") or not callable(function):
            continue
        with tempfile.TemporaryDirectory() as tmp:
            try:
                function(Path(tmp))
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_main())

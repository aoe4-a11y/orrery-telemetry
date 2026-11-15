"""The installed fleet wrapper must preserve global cleanup fail-closed behavior."""
import importlib.util
from pathlib import Path

import pytest

from test_global_child_client import api, client, shell, server as fixture_server

server = fixture_server
ROOT = Path(__file__).resolve().parents[1]


def test_generated_cleanup_refuses_missing_global_library(server, monkeypatch):
    parent = client(server)
    stack = parent.isolation / "agentstack"
    station = stack / "bin/agentstack-station-materials"
    station.parent.mkdir(parents=True)
    station.write_text('from pathlib import Path\nPROJECT_ALIASES = {}\nPRIVATE_ROOT = Path("/fixture/private")\n')
    (stack / "bin/head-accept").write_text('from pathlib import Path\nHOME = Path("/fixture")\nBASES = [Path("/fixture/receipts"), HOME / ".storage"]\n')
    (stack / "bin/agentstack-reap-idle-seats").write_text('REGISTRY_GLOBS="${REAP_REGISTRY_GLOBS:-$HOME/fixture/*}"\n')
    (stack / "bin/agentstack-doctor").write_text("tmux run-shell 'ls /fixture/probe >/dev/null'\n")
    (stack / "bin/agentstack-tmux-server-migrate").write_text("tmux run-shell 'ls /fixture/probe >/dev/null'\n")
    (stack / "bin/agentstack_unstick_seats.py").write_text("if data.get('project_key') != '/fixture/project': pass\n")
    (stack / "bin/codex-session-restore").write_text('from pathlib import Path\nCATALOG = Path("/fixture/catalog")\nLIVE = Path("/fixture/live")\nROOTS = tuple(map(Path, ["/fixture/root"]))\n')
    (stack / "runtime").mkdir(exist_ok=True)
    (stack / "runtime/head-evidence-export.py").write_text('from pathlib import Path\nHOME = Path("/fixture")\nLEDGER = Path("/fixture/ledger")\nARTIFACT_BASES = [Path("/fixture/a"), HOME / "b"]\n')
    for name in ("agentstack_stallself.py", "agentstack_jobend.py"):
        (stack / "bin" / name).write_text('PROJECT = "/fixture/project"\n')
    monkeypatch.setenv("AGENTSTACK_FLEET_MATERIALS_PROJECT", "/fixture/project")
    monkeypatch.setenv("AGENTSTACK_FLEET_CLAUDE_ADD_DIR", "/fixture/extra")
    spec = importlib.util.spec_from_file_location("fixture_fleet_payload", ROOT / "scripts/install-fleet-payload.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.install(stack)
    loader = stack / "bin/lib/global-client-loader.sh"
    loader.write_bytes((ROOT / "bin/lib/global-client-loader.sh").read_bytes())
    output = shell(parent, str(stack / "hooks/cleanup-child-agent.sh"), payload={"session_id": "s"})
    assert output.returncode == 2
    assert "GLOBAL_ENTRY_UNAVAILABLE" in output.stderr


def test_generated_cleanup_keeps_other_live_session(server, monkeypatch):
    import json
    import os
    import runpy
    import shutil
    from _installed_client_payload import copy_client_library
    from test_global_child_client import reserve

    initial = client(server)
    stack = initial.isolation / "agentstack"
    station = stack / "bin/agentstack-station-materials"
    station.parent.mkdir(parents=True)
    station.write_text('from pathlib import Path\nPROJECT_ALIASES = {}\nPRIVATE_ROOT = Path("/fixture/private")\n')
    (stack / "bin/head-accept").write_text('from pathlib import Path\nHOME = Path("/fixture")\nBASES = [Path("/fixture/receipts"), HOME / ".storage"]\n')
    (stack / "bin/agentstack-reap-idle-seats").write_text('REGISTRY_GLOBS="${REAP_REGISTRY_GLOBS:-$HOME/fixture/*}"\n')
    (stack / "bin/agentstack-doctor").write_text("tmux run-shell 'ls /fixture/probe >/dev/null'\n")
    (stack / "bin/agentstack-tmux-server-migrate").write_text("tmux run-shell 'ls /fixture/probe >/dev/null'\n")
    (stack / "bin/agentstack_unstick_seats.py").write_text("if data.get('project_key') != '/fixture/project': pass\n")
    (stack / "bin/codex-session-restore").write_text('from pathlib import Path\nCATALOG = Path("/fixture/catalog")\nLIVE = Path("/fixture/live")\nROOTS = tuple(map(Path, ["/fixture/root"]))\n')
    (stack / "runtime").mkdir(exist_ok=True)
    (stack / "runtime/head-evidence-export.py").write_text('from pathlib import Path\nHOME = Path("/fixture")\nLEDGER = Path("/fixture/ledger")\nARTIFACT_BASES = [Path("/fixture/a"), HOME / "b"]\n')
    for name in ("agentstack_stallself.py", "agentstack_jobend.py"):
        (stack / "bin" / name).write_text('PROJECT = "/fixture/project"\n')
    monkeypatch.setenv("AGENTSTACK_FLEET_MATERIALS_PROJECT", "/fixture/project")
    monkeypatch.setenv("AGENTSTACK_FLEET_CLAUDE_ADD_DIR", "/fixture/extra")
    spec = importlib.util.spec_from_file_location("fixture_fleet_payload_live", ROOT / "scripts/install-fleet-payload.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.install(stack)
    shutil.copytree(ROOT / "bin/lib", stack / "bin/lib", dirs_exist_ok=True)
    copy_client_library(stack)
    shutil.copy2(ROOT / "bin/agentstack-runtime-client", stack / "bin/agentstack-runtime-client")
    config = api["read_json"](initial.path)
    config["wrapper_root"] = str(stack)
    api["atomic_json"](initial.path, config)
    installed_api = runpy.run_path(str(stack / "bin/lib/runtime_client.py"))
    parent = installed_api["RuntimeClient"](initial.path)
    _, lease = reserve(parent)
    monkeypatch.setitem(parent.record_live.__globals__, "process_start", lambda pid: "birth")
    parent.record_live({"session_id": "A", "provider_pid": 123})
    parent.record_live({"session_id": "B", "provider_pid": 124})
    stubs = parent.isolation / "ps-stub"
    stubs.mkdir()
    ps = stubs / "ps"
    ps.write_text('#!/bin/sh\necho birth\n')
    ps.chmod(0o700)
    output = shell(parent, str(stack / "hooks/cleanup-child-agent.sh"),
                   payload={"session_id": "A"},
                   extra={"PATH": str(stubs) + os.pathsep + os.environ["PATH"]})
    assert output.returncode == 0, output.stderr
    assert json.loads(output.stdout)["changed"] is False
    assert any(row["id"] == lease for page in parent.all_leases() for row in page)


def test_generated_spawn_refuses_missing_global_library(server, monkeypatch):
    parent = client(server)
    stack = parent.isolation / "agentstack"
    station = stack / "bin/agentstack-station-materials"
    station.parent.mkdir(parents=True)
    station.write_text('from pathlib import Path\nPROJECT_ALIASES = {}\nPRIVATE_ROOT = Path("/fixture/private")\n')
    (stack / "bin/head-accept").write_text('from pathlib import Path\nHOME = Path("/fixture")\nBASES = [Path("/fixture/receipts"), HOME / ".storage"]\n')
    (stack / "bin/agentstack-reap-idle-seats").write_text('REGISTRY_GLOBS="${REAP_REGISTRY_GLOBS:-$HOME/fixture/*}"\n')
    (stack / "bin/agentstack-doctor").write_text("tmux run-shell 'ls /fixture/probe >/dev/null'\n")
    (stack / "bin/agentstack-tmux-server-migrate").write_text("tmux run-shell 'ls /fixture/probe >/dev/null'\n")
    (stack / "bin/agentstack_unstick_seats.py").write_text("if data.get('project_key') != '/fixture/project': pass\n")
    (stack / "bin/codex-session-restore").write_text('from pathlib import Path\nCATALOG = Path("/fixture/catalog")\nLIVE = Path("/fixture/live")\nROOTS = tuple(map(Path, ["/fixture/root"]))\n')
    (stack / "runtime").mkdir(exist_ok=True)
    (stack / "runtime/head-evidence-export.py").write_text('from pathlib import Path\nHOME = Path("/fixture")\nLEDGER = Path("/fixture/ledger")\nARTIFACT_BASES = [Path("/fixture/a"), HOME / "b"]\n')
    for name in ("agentstack_stallself.py", "agentstack_jobend.py"):
        (stack / "bin" / name).write_text('PROJECT = "/fixture/project"\n')
    monkeypatch.setenv("AGENTSTACK_FLEET_MATERIALS_PROJECT", "/fixture/project")
    monkeypatch.setenv("AGENTSTACK_FLEET_CLAUDE_ADD_DIR", "/fixture/extra")
    spec = importlib.util.spec_from_file_location("fixture_fleet_payload_spawn", ROOT / "scripts/install-fleet-payload.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.install(stack)
    loader = stack / "bin/lib/global-client-loader.sh"
    loader.write_bytes((ROOT / "bin/lib/global-client-loader.sh").read_bytes())
    output = shell(parent, str(stack / "hooks/spawn_child.sh"),
                   ["--child-client-name", "child_01", "--prepare-only"])
    assert output.returncode == 2
    assert "GLOBAL_ENTRY_UNAVAILABLE" in output.stderr


def test_generated_spawn_uses_global_prepare_without_launch(server, monkeypatch):
    import json
    import runpy
    import shutil
    from _installed_client_payload import copy_client_library

    initial = client(server)
    stack = initial.isolation / "agentstack"
    station = stack / "bin/agentstack-station-materials"
    station.parent.mkdir(parents=True)
    station.write_text('from pathlib import Path\nPROJECT_ALIASES = {}\nPRIVATE_ROOT = Path("/fixture/private")\n')
    (stack / "bin/head-accept").write_text('from pathlib import Path\nHOME = Path("/fixture")\nBASES = [Path("/fixture/receipts"), HOME / ".storage"]\n')
    (stack / "bin/agentstack-reap-idle-seats").write_text('REGISTRY_GLOBS="${REAP_REGISTRY_GLOBS:-$HOME/fixture/*}"\n')
    (stack / "bin/agentstack-doctor").write_text("tmux run-shell 'ls /fixture/probe >/dev/null'\n")
    (stack / "bin/agentstack-tmux-server-migrate").write_text("tmux run-shell 'ls /fixture/probe >/dev/null'\n")
    (stack / "bin/agentstack_unstick_seats.py").write_text("if data.get('project_key') != '/fixture/project': pass\n")
    (stack / "bin/codex-session-restore").write_text('from pathlib import Path\nCATALOG = Path("/fixture/catalog")\nLIVE = Path("/fixture/live")\nROOTS = tuple(map(Path, ["/fixture/root"]))\n')
    (stack / "runtime").mkdir(exist_ok=True)
    (stack / "runtime/head-evidence-export.py").write_text('from pathlib import Path\nHOME = Path("/fixture")\nLEDGER = Path("/fixture/ledger")\nARTIFACT_BASES = [Path("/fixture/a"), HOME / "b"]\n')
    for name in ("agentstack_stallself.py", "agentstack_jobend.py"):
        (stack / "bin" / name).write_text('PROJECT = "/fixture/project"\n')
    monkeypatch.setenv("AGENTSTACK_FLEET_MATERIALS_PROJECT", "/fixture/project")
    monkeypatch.setenv("AGENTSTACK_FLEET_CLAUDE_ADD_DIR", "/fixture/extra")
    spec = importlib.util.spec_from_file_location("fixture_fleet_payload_prepare", ROOT / "scripts/install-fleet-payload.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.install(stack)
    shutil.copytree(ROOT / "bin/lib", stack / "bin/lib", dirs_exist_ok=True)
    copy_client_library(stack)
    shutil.copy2(ROOT / "bin/agentstack-runtime-client", stack / "bin/agentstack-runtime-client")
    config = api["read_json"](initial.path)
    config["wrapper_root"] = str(stack)
    api["atomic_json"](initial.path, config)
    installed_api = runpy.run_path(str(stack / "bin/lib/runtime_client.py"))
    parent = installed_api["RuntimeClient"](initial.path)
    parent.prepare_child({"child_client_name": "child_01", "name": "ChildAlpha",
                          "program": "codex", "model": "fixture", "prepare_only": True})
    output = shell(parent, str(stack / "hooks/spawn_child.sh"),
                   ["--child-client-name", "child_01", "--name", "ChildAlpha", "--prepare-only"])
    assert output.returncode == 0, output.stderr
    assert json.loads(output.stdout)["runtime_ready"] is False


def test_generated_release_links_target_installed_hooks(tmp_path, monkeypatch):
    import os
    stack = tmp_path / "agentstack"
    (stack / "bin").mkdir(parents=True)
    (stack / "bin/agentstack-station-materials").write_text('from pathlib import Path\nPROJECT_ALIASES = {}\nPRIVATE_ROOT = Path("/fixture/private")\n')
    (stack / "bin/head-accept").write_text('from pathlib import Path\nHOME = Path("/fixture")\nBASES = [Path("/fixture/receipts"), HOME / ".storage"]\n')
    (stack / "bin/agentstack-reap-idle-seats").write_text('REGISTRY_GLOBS="${REAP_REGISTRY_GLOBS:-$HOME/fixture/*}"\n')
    (stack / "bin/agentstack-doctor").write_text("tmux run-shell 'ls /fixture/probe >/dev/null'\n")
    (stack / "bin/agentstack-tmux-server-migrate").write_text("tmux run-shell 'ls /fixture/probe >/dev/null'\n")
    (stack / "bin/agentstack_unstick_seats.py").write_text("if data.get('project_key') != '/fixture/project': pass\n")
    (stack / "bin/codex-session-restore").write_text('from pathlib import Path\nCATALOG = Path("/fixture/catalog")\nLIVE = Path("/fixture/live")\nROOTS = tuple(map(Path, ["/fixture/root"]))\n')
    (stack / "runtime").mkdir(exist_ok=True)
    (stack / "runtime/head-evidence-export.py").write_text('from pathlib import Path\nHOME = Path("/fixture")\nLEDGER = Path("/fixture/ledger")\nARTIFACT_BASES = [Path("/fixture/a"), HOME / "b"]\n')
    for name in ("agentstack_stallself.py", "agentstack_jobend.py"):
        (stack / "bin" / name).write_text('PROJECT = "/fixture/project"\n')
    monkeypatch.setenv("AGENTSTACK_FLEET_MATERIALS_PROJECT", "/fixture/project")
    monkeypatch.setenv("AGENTSTACK_FLEET_CLAUDE_ADD_DIR", "/fixture/extra")
    spec = importlib.util.spec_from_file_location("fixture_fleet_payload_links", ROOT / "scripts/install-fleet-payload.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.install(stack)
    source = ROOT / "fleet" / module.RELEASE
    links = [p for p in source.rglob("*") if p.is_symlink()]
    assert len(links) == 3
    for link in links:
        installed = stack / link.relative_to(ROOT / "fleet")
        assert installed.is_symlink()
        assert os.readlink(installed) == "../../../../hooks/" + link.name


@pytest.mark.parametrize("missing", [
    "bin/agentstack-station-materials", "bin/head-accept", "bin/agentstack-reap-idle-seats",
    "bin/agentstack-doctor", "bin/agentstack-tmux-server-migrate", "bin/agentstack_unstick_seats.py", "bin/agentstack_stallself.py", "bin/agentstack_jobend.py",
    "bin/codex-session-restore", "runtime/head-evidence-export.py",
])
def test_missing_existing_configuration_stops_before_writes(tmp_path, monkeypatch, missing):
    stack = tmp_path / "agentstack"
    stack.mkdir()
    fixtures = {
        "bin/agentstack-station-materials": 'from pathlib import Path\nPROJECT_ALIASES = {}\nPRIVATE_ROOT = Path("/fixture/private")\n',
        "bin/head-accept": 'from pathlib import Path\nHOME = Path("/fixture")\nBASES = [Path("/fixture/receipts"), HOME / ".storage"]\n',
        "bin/agentstack-reap-idle-seats": 'REGISTRY_GLOBS="${REAP_REGISTRY_GLOBS:-$HOME/fixture/*}"\n',
        "bin/agentstack-doctor": "tmux run-shell 'ls /fixture/probe >/dev/null'\n",
        "bin/agentstack-tmux-server-migrate": "tmux run-shell 'ls /fixture/probe >/dev/null'\n",
        "bin/agentstack_unstick_seats.py": "if data.get('project_key') != '/fixture/project': pass\n",
        "bin/agentstack_stallself.py": 'PROJECT = "/fixture/project"\n',
        "bin/agentstack_jobend.py": 'PROJECT = "/fixture/project"\n',
        "bin/codex-session-restore": 'from pathlib import Path\nCATALOG = Path("/fixture/catalog")\nLIVE = Path("/fixture/live")\nROOTS = tuple(map(Path, ["/fixture/root"]))\n',
        "runtime/head-evidence-export.py": 'from pathlib import Path\nHOME = Path("/fixture")\nLEDGER = Path("/fixture/ledger")\nARTIFACT_BASES = [Path("/fixture/a"), HOME / "b"]\n',
    }
    for name, text in fixtures.items():
        if name != missing:
            path = stack / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    before = {str(p.relative_to(stack)): p.read_bytes() for p in stack.rglob("*") if p.is_file()}
    monkeypatch.setenv("AGENTSTACK_FLEET_MATERIALS_PROJECT", "/fixture/project")
    monkeypatch.setenv("AGENTSTACK_FLEET_CLAUDE_ADD_DIR", "/fixture/extra")
    spec = importlib.util.spec_from_file_location("fixture_fleet_preflight", ROOT / "scripts/install-fleet-payload.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(ValueError):
        module.install(stack)
    assert {str(p.relative_to(stack)): p.read_bytes() for p in stack.rglob("*") if p.is_file()} == before
    assert not (stack / "fleet-install.json").exists()


def test_tmux_migration_is_removed_and_status_is_read_only(tmp_path):
    import os
    import subprocess
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    calls = tmp_path / "calls"
    for name, text in {
        "tmux": '#!/bin/sh\nprintf "%s\\n" "$1" >> "$TEST_CALLS"\n[ "$1" != run-shell ] || echo tcc-ok\n',
        "ps": '#!/bin/sh\necho "tmux -D"\n',
        "launchctl": '#!/bin/sh\nexit 0\n',
    }.items():
        p = stubs / name
        p.write_text(text)
        p.chmod(0o755)
    env = {"HOME": str(tmp_path), "PATH": str(stubs) + ":/usr/bin:/bin", "TEST_CALLS": str(calls),
           "AGENTSTACK_TCC_PROBE_DIR": "/fixture/probe"}
    source = ROOT / "bin/agentstack-tmux-server-migrate"
    rejected = subprocess.run(["/bin/bash", str(source), "--migrate"], env=env, capture_output=True, timeout=10)
    assert rejected.returncode == 2
    assert not calls.exists()
    status = subprocess.run(["/bin/bash", str(source), "--status"], env=env, capture_output=True, timeout=10)
    assert status.returncode == 0
    assert calls.read_text().splitlines() == ["list-sessions", "run-shell"]

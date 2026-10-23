"""Reaper regression: fake ps/tmux/signals and an isolated fixture-only mail DB.

No real tmux endpoint, process target, governor registry or Mail DB is used.
Run with python3 tests/test_reap_idle_seats.py or pytest.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin/agentstack-reap-idle-seats"

FAKE = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ["REAP_FIXTURE"])
data = json.loads((root / "processes.json").read_text())
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
if name == "tmux":
    if args[0] == "list-sessions":
        if data.get("sessions_fail"): sys.exit(1)
        print("\n".join(data["panes"]))
    elif args[0] == "list-panes":
        seat = args[args.index("-t")+1]
        if data.get("panes_fail") == seat: sys.exit(1)
        print(data["panes"][seat])
    elif args[0] == "has-session":
        sys.exit(0 if args[args.index("-t")+1] in data["panes"] else 1)
    elif args[0] == "capture-pane":
        print("Ask Codex to do anything")
    elif args[0] == "kill-session":
        with (root / "tmux-actions").open("a") as out: out.write(" ".join(args)+"\n")
    else: sys.exit(2)
elif name == "ps":
    if data.get("ps_fail"): sys.exit(1)
    for pid, ppid, command, env in data["processes"]:
        print(f"{pid} {command} {env}" if "-E" in args else f"{pid} {ppid} {command}")
elif name == "kill":
    with (root / "signals").open("a") as out: out.write(" ".join(args)+"\n")
elif name == "sleep":
    pass
elif name == "sqlite3":
    # Automatic cleanup's read queries are synthetic, never sent to a live DB.
    query = args[-1]
    if "select distinct" in query: pass
    elif "select m.subject" in query: print("[receipt] fixture complete")
    elif "max(m.id)" in query: print(10 if "sender_id" in query else 1)
    else: print(0)
else:
    sys.exit(2)
'''

class ReaperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="reap-isolated-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        fake = self.root / "fake"
        fake.mkdir()
        for name in ("tmux", "ps", "kill", "sleep", "sqlite3"):
            path = fake / name
            path.write_text(FAKE)
            path.chmod(0o755)
        self.fixture = {
            "panes": {"SeatA": 100, "SeatB": 200},
            "processes": [
                [100, 1, "/bin/zsh", ""],
                [200, 1, "/bin/zsh", ""],
            ],
        }
        self.db = self.root / "fixture.sqlite3"
        with sqlite3.connect(self.db) as con:
            con.executescript("""
                create table agents(id integer primary key, name text);
                insert into agents values(1,'FixtureHead');
                create table messages(id integer primary key, project_id integer,
                  sender_id integer, thread_id text, topic text, subject text, body_md text,
                  importance text, ack_required integer, created_ts text, attachments text);
                create table message_recipients(message_id integer, agent_id integer, kind text);
            """)
        self.registry = self.root / "registry"
        self.registry.mkdir()
        for seat in self.fixture["panes"]:
            roll = self.root / "children" / (seat+".codex-home") / "sessions/2026/01/01"
            roll.mkdir(parents=True)
            (roll / "rollout-fixture.jsonl").write_text("{}\n")
        (self.root / "protect").write_text("")
        self.env = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("REAP_", "AGENTSTACK_", "CODEX_"))
        }
        self.env.update({
            "HOME": str(self.root),
            "PATH": str(fake) + os.pathsep + os.environ["PATH"],
            "REAP_FIXTURE": str(self.root),
            "REAP_TMUX": str(fake / "tmux"),
            "REAP_PS": str(fake / "ps"),
            "REAP_KILL": str(fake / "kill"),
            "REAP_DB": str(self.db),
            "REAP_NOTIFY_TO": "FixtureHead",
            "REAP_PROTECT_FILE": str(self.root / "protect"),
            "REAP_CHILD_ROOT": str(self.root / "children"),
            "REAP_LOG": str(self.root / "log"),
            "REAP_STRIKE_DIR": str(self.root / "strikes"),
            "REAP_HEAVY_LOCK_ROOT": str(self.root / "heavy"),
            "REAP_REGISTRY_GLOBS": str(self.registry / "*" / ".dev-storage.json"),
        })

    def process(self, pid, command="fixture-work", env="AGENT_NAME=SeatA", ppid=1):
        self.fixture["processes"].append([pid, ppid, command, env])

    def owned_root(self, seat, name):
        root = self.registry / name
        root.mkdir()
        (root / ".dev-storage.json").write_text(json.dumps({"owner": seat}))
        return name

    def run_reaper(self, *args):
        (self.root / "processes.json").write_text(json.dumps(self.fixture))
        return subprocess.run(["/bin/bash", str(SCRIPT), *args], env=self.env,
                              capture_output=True, text=True, timeout=15)

    def text(self, name):
        path = self.root / name
        return path.read_text() if path.exists() else ""

    def assert_no_signals(self):
        self.assertEqual(self.text("signals"), "")

    def close(self):
        result = self.run_reaper("--close", "SeatA", "fixture-complete")
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_positive_exclusive_work_and_descendant_are_stopped(self):
        self.process(310)
        self.process(311, env="", ppid=310)
        self.close()
        self.assertEqual(set(self.text("signals").splitlines()),
                         {"-TERM 310", "-TERM 311", "-KILL 310", "-KILL 311"})
        self.assertIn("kill-session -t SeatA", self.text("tmux-actions"))

    def test_shared_environment_root_and_descendant_are_preserved(self):
        root = self.owned_root("SeatB", "fixture-root-b")
        self.process(320, env="AGENT_NAME=SeatA CACHE="+root)
        self.process(321, env="", ppid=320)
        self.process(322)  # positive control in the same run
        result = self.run_reaper("--attribute", "SeatA")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("protected\t320\tother-live-seat\tSeatB", result.stdout)
        self.assertIn("rule\t320\tAGENT_NAME", result.stdout)
        self.assertNotIn(root, result.stdout)
        self.close()
        self.assertEqual(set(self.text("signals").splitlines()), {"-TERM 322", "-KILL 322"})
        self.assertIn("pid=320 reasons=other-live-seat peers=SeatB", self.text("log"))
        with sqlite3.connect(self.db) as con:
            report = con.execute("select body_md from messages").fetchone()[0]
        self.assertIn("pid=320 reasons=other-live-seat peers=SeatB", report)
        self.assertNotIn(root, report)

    def test_shared_agent_name_with_other_live_pane_is_preserved(self):
        self.process(330, env="AGENT_NAME=SeatA", ppid=200)
        self.close()
        self.assert_no_signals()
        self.assertIn("peers=SeatB", self.text("log"))

    def test_two_agent_name_tokens_are_preserved(self):
        self.process(331, env="AGENT_NAME=SeatA AGENT_NAME=SeatB")
        self.close()
        self.assert_no_signals()

    def test_shared_argv_root_is_preserved(self):
        root = self.owned_root("SeatA", "fixture-root-a")
        self.process(332, command="worker "+root, env="AGENT_NAME=SeatB")
        self.close()
        self.assert_no_signals()

    def test_shared_services_and_their_descendants_are_preserved(self):
        names = ("SWBBuildService", "XCBBuildService",
                 "com.apple.CoreSimulator.CoreSimulatorService", "launchd_sim",
                 "SimulatorTrampoline", "simdiskimaged", "Simulator", "SimulatorBridge",
                 "com.apple.CoreSimulator.SimLaunchHost-arm64")
        for i, name in enumerate(names):
            self.process(400+i*2, "/fixture/"+name)
            self.process(401+i*2, env="", ppid=400+i*2)
        self.close()
        self.assert_no_signals()
        self.assertIn("shared-service", self.text("log"))

    def test_reparented_simulator_apps_are_preserved(self):
        self.process(440, "/fixture/CoreSimulator/Devices/opaque/data/Test.app/Test")
        self.process(441, env="AGENT_NAME=SeatA SIMULATOR_UDID=opaque")
        self.process(442, env="AGENT_NAME=SeatA SIMULATOR_DEVICE_NAME=fixture")
        self.close()
        self.assert_no_signals()
        self.assertIn("simulator-device", self.text("log"))

    def test_protected_pane_descendant_refuses_tmux_sighup_and_reports(self):
        self.process(450, env="AGENT_NAME=SeatB", ppid=100)
        result = self.run_reaper("--close", "SeatA", "fixture-complete")
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_signals()
        self.assertEqual(self.text("tmux-actions"), "")
        self.assertIn("protected process depends on pane", self.text("log"))
        with sqlite3.connect(self.db) as con:
            report = con.execute("select body_md from messages").fetchone()[0]
        self.assertIn("close refused", report)
        self.assertIn("peers=SeatB", report)

    def test_automatic_keep_guard_still_counts_protected_work(self):
        self.process(460, "/fixture/SWBBuildService", "AGENT_NAME=SeatA AGENT_NAME=SeatB")
        for _ in range(2):
            result = self.run_reaper()
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_no_signals()
        self.assertEqual(self.text("tmux-actions"), "")
        self.assertIn("keep SeatA: live work process", self.text("log"))
        self.assertIn("keep SeatB: live work process", self.text("log"))
        self.assertFalse((self.root / "strikes" / "SeatA").exists())

    def test_automatic_exclusive_work_still_keeps_seat(self):
        self.process(461)
        result = self.run_reaper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("keep SeatA: live work process", self.text("log"))
        self.assert_no_signals()

    def test_shared_heavy_pid_does_not_bypass_stop_filter_or_remove_peer_entry(self):
        entry = self.root / "heavy" / "slot-1"
        entry.mkdir(parents=True)
        (entry / "pid").write_text("470")
        (entry / "owner").write_text("SeatB")
        (entry / "name").write_text("fixture")
        self.process(470, env="AGENT_NAME=SeatA AGENT_NAME=SeatB")
        self.close()
        self.assert_no_signals()
        self.assertTrue(entry.exists())

    def test_live_peer_heavy_owner_alone_protects_pid(self):
        entry = self.root / "heavy" / "slot-1"
        entry.mkdir(parents=True)
        (entry / "pid").write_text("472")
        (entry / "owner").write_text("SeatB")
        self.process(472)
        self.close()
        self.assert_no_signals()
        self.assertTrue(entry.exists())
        self.assertIn("peers=SeatB", self.text("log"))

    def test_automatic_idle_seat_still_closes_after_two_strikes(self):
        for _ in range(2):
            result = self.run_reaper()
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("kill-session -t SeatA", self.text("tmux-actions"))
        self.assert_no_signals()

    def test_exclusive_heavy_pid_is_stopped_and_entry_removed(self):
        entry = self.root / "heavy" / "slot-1"
        entry.mkdir(parents=True)
        (entry / "pid").write_text("471")
        (entry / "owner").write_text("SeatA")
        (entry / "name").write_text("fixture")
        self.process(471, env="")
        self.close()
        self.assertEqual(set(self.text("signals").splitlines()), {"-TERM 471", "-KILL 471"})
        self.assertFalse(entry.exists())

    def test_peer_inspection_failure_refuses_close(self):
        self.process(480)
        self.fixture["panes_fail"] = "SeatB"
        result = self.run_reaper("--close", "SeatA", "fixture")
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_signals()
        self.assertEqual(self.text("tmux-actions"), "")

    def test_process_snapshot_failure_refuses_close(self):
        self.fixture["ps_fail"] = True
        result = self.run_reaper("--close", "SeatA", "fixture")
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_signals()
        self.assertEqual(self.text("tmux-actions"), "")

if __name__ == "__main__":
    unittest.main(verbosity=2)

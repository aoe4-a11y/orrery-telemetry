#!/usr/bin/env python3
"""FLEET-MEM-2: judge counterexamples and private crash-notice boundaries.

All closure signals, registrations, launches and Mail sends are synthetic sinks.
"""
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import test_agentstack_fleet_memory as base

BIN = Path(__file__).resolve().parent


class FinalReaperTests(base.ReaperTests):
    def test_automatic_close_race(self):
        self.seat('Owner', 100)
        self.script('ps', '''import os,sys
from pathlib import Path
r=Path(os.environ['TEST_ROOT']);p=r/'census-count'
n=int(p.read_text()) if p.exists() else 0
if '-E' not in sys.argv:
 n+=1;p.write_text(str(n))
print('100 1 /bin/bash\\n101 100 /bin/codex')
if n>=2: print('102 100 /bin/sleep 600')
''')
        self.reap()
        self.assertTrue((self.sessions/'Owner').exists())
        self.assertFalse((self.root/'signals').exists())
        self.assertGreaterEqual(int((self.root/'census-count').read_text()), 2)

    def test_automatic_close_heavy_race(self):
        self.seat('Owner', 100)
        self.script('ps', '''import os,sys
from pathlib import Path
r=Path(os.environ['TEST_ROOT']);p=r/'census-count'
n=int(p.read_text()) if p.exists() else 0
if '-E' not in sys.argv:
 n+=1;p.write_text(str(n))
if n>=2:
 ticket=r/'heavy/waiting/ticket-new';ticket.mkdir(parents=True,exist_ok=True)
 (ticket/'owner').write_text('Owner');(ticket/'pid').write_text('101')
print('100 1 /bin/bash\\n101 100 /bin/codex')
''')
        self.reap()
        self.assertTrue((self.sessions/'Owner').exists())
        self.assertTrue((self.root/'heavy/waiting/ticket-new').exists())
        self.assertFalse((self.root/'signals').exists())

    def pane(self, text, final=None):
        p=self.bin/'tmux'; source=p.read_text()
        old="elif cmd=='capture-pane': print('Working (esc to interrupt)' if target=='Busy' else 'Ask Codex to do anything')"
        new="""elif cmd=='capture-pane':
 count=r/'capture-count';n=int(count.read_text()) if count.exists() else 0
 count.write_text(str(n+1))
 print(%r if n==0 else %r)""" % (text, text if final is None else final)
        self.assertIn(old, source);p.write_text(source.replace(old,new))
        strike=self.strikes/'Owner';strike.write_text(hashlib.sha256(text.encode()).hexdigest()+'\n')
        os.utime(strike,(time.time()-600,)*2)

    def test_resident_child_codex_is_work(self):
        self.seat('Owner',100)
        self.census('101 100 /bin/codex\n102 100 /bin/codex exec --long-running-worker\n')
        self.reap()
        self.assertTrue((self.sessions/'Owner').exists())
        self.assertFalse((self.root/'signals').exists())

    def test_second_interactive_codex_is_work(self):
        self.seat('Owner',100)
        self.census('101 100 /bin/codex\n102 101 /bin/codex\n')
        self.reap()
        self.assertTrue((self.sessions/'Owner').exists())

    def test_busy_indicator_outside_tail8(self):
        self.seat('Owner',100);self.census('101 100 /bin/codex\n')
        self.pane('Working (esc to interrupt)\n'+'footer\n'*7+'Ask Codex to do anything')
        self.reap()
        self.assertTrue((self.sessions/'Owner').exists())

    def test_final_pane_busy_race(self):
        self.seat('Owner',100);self.census('101 100 /bin/codex\n')
        self.pane('Ask Codex to do anything', 'Working (esc to interrupt)\n'+'footer\n'*9+'Ask Codex to do anything')
        self.reap()
        self.assertTrue((self.sessions/'Owner').exists())
        self.assertFalse((self.root/'signals').exists())

    def test_final_pane_changed_or_unreadable(self):
        self.seat('Owner',100);self.census('101 100 /bin/codex\n')
        self.pane('Ask Codex to do anything','new output\nAsk Codex to do anything')
        self.reap()
        self.assertTrue((self.sessions/'Owner').exists())


class HoldRecoveryTests(base.MemoryTests):
    def test_orphan_guard_hold(self):
        flag=self.root/'memory-hold';flag.write_text('R-183 physical-headroom; available=1MiB\n')
        for _ in range(3):base.mem.guard(self.root,base.healthy(),lambda _:None)
        self.assertFalse(flag.exists())
        self.assertEqual(base.mem.admit(self.root,base.healthy(),{}),0)

    def test_legacy_guard_hold(self):
        for text in ['2026-11-07 15:59:00 level=29\n',
                     '2026-11-07 15:59:00 sim-app pid=123 rss=7000MB killed\n',
                     '2026-11-07 15:59:00 sim-app pid=123 mem=7000MB killed\n',
                     '2026-11-07 15:59:00 xctrace pid=123 mem=13000MB killed\n']:
            flag=self.root/'memory-hold';flag.write_text(text)
            for _ in range(3):base.mem.guard(self.root,base.healthy(),lambda _:None)
            self.assertFalse(flag.exists(),text)
            self.assertEqual(base.mem.admit(self.root,base.healthy(),{}),0)

    def test_owned_hold_with_corrupt_state_recovers(self):
        (self.root/'memory-guard-state.json').write_text('{')
        (self.root/'memory-hold').write_text('R-183 measurement unavailable\n')
        base.mem.guard(self.root,base.healthy(),lambda _:None)
        self.assertFalse((self.root/'memory-hold').exists())

    def test_legacy_hold_keeps_hysteresis_and_foreign_lookalikes(self):
        flag=self.root/'memory-hold';flag.write_text('2026-11-07 15:59:00 level=29\n')
        base.mem.guard(self.root,base.healthy(available_mb=10000),lambda _:None)
        self.assertTrue(flag.exists())
        for text in ['other owner', '2026-11-07 15:59:00 level=29 foreign',
                     '2026-11-07 15:59:00 maintenance', 'R-183 foreign-owner']:
            flag.write_text(text)
            base.mem.guard(self.root,base.healthy(level=20),lambda _:None)
            base.mem.guard(self.root,base.healthy(),lambda _:None)
            self.assertEqual(flag.read_text(),text)


class LauncherTests(unittest.TestCase):
    def test_noncodex_shell_entries_deny_before_any_side_effect(self):
        stack=BIN.parent
        entries=[(BIN/'agentstack-spawn-claude',[]),(BIN/'agent-start',[]),
                 (stack/'hooks/spawn_child.sh',[]),
                 (stack/'hooks/spawn_child.upstream.sh',[]),
                 (stack/'releases/seat-lifecycle/ee5880e3e23606e0f3252cbeed211868102f4595/hooks/spawn_child.sh',[])]
        with tempfile.TemporaryDirectory(prefix='fleetmem2-entry-') as temp:
            root=Path(temp);(root/'bin').mkdir();(root/'runtime').mkdir()
            gate=root/'bin/agentstack-memory-budget'
            gate.write_text('#!/bin/bash\nprintf "called\\n" >> "${AGENTSTACK_RUNTIME_DIR}/gates"\nexit 75\n');gate.chmod(0o755)
            for i,(source,args) in enumerate(entries):
                with self.subTest(entry=str(source)):
                    copy=root/('entry-'+str(i))
                    copy.write_text(source.read_text().replace('$HOME/.agentstack',str(root)))
                    result=subprocess.run(['/bin/bash',str(copy),*args],env=dict(os.environ,
                        AGENTSTACK_HOME=str(root),AGENTSTACK_RUNTIME_DIR=str(root/'runtime')),
                        capture_output=True,text=True,timeout=10)
                    self.assertEqual(result.returncode,75)
            self.assertEqual(len((root/'runtime/gates').read_text().splitlines()),len(entries))

    def test_noncodex_shell_entries_share_real_pressure_and_hold_gate(self):
        stack=BIN.parent
        entries=[BIN/'agentstack-spawn-claude',BIN/'agent-start',stack/'hooks/spawn_child.sh',
                 stack/'hooks/spawn_child.upstream.sh',
                 stack/'releases/seat-lifecycle/ee5880e3e23606e0f3252cbeed211868102f4595/hooks/spawn_child.sh']
        with tempfile.TemporaryDirectory(prefix='fleetmem2-real-gate-') as temp:
            root=Path(temp)
            for condition in ['pressure','hold']:
                if condition=='hold':(root/'memory-hold').write_text('foreign hold')
                for entry in entries:
                    with self.subTest(condition=condition,entry=str(entry)):
                        env=dict(os.environ,AGENTSTACK_HOME=str(stack),AGENTSTACK_RUNTIME_DIR=str(root),
                                 AGENTSTACK_MEMORY_STATE_DIR=str(root))
                        if condition=='pressure':env['AGENTSTACK_MEMORY_RESERVE_MB']='1000000'
                        r=subprocess.run(['/bin/bash',str(entry)],env=env,capture_output=True,text=True,timeout=30)
                        self.assertEqual(r.returncode,75)
                        self.assertEqual(len(r.stderr.strip().splitlines()),1)
                        self.assertIn('memory admission refused:',r.stderr)
                        if condition=='hold':self.assertIn('memory-hold',r.stderr)

    def test_claude_allowed_gate_reaches_preregister_stub(self):
        with tempfile.TemporaryDirectory(prefix='fleetmem2-allow-') as temp:
            root=Path(temp);(root/'bin').mkdir();(root/'runtime').mkdir()
            launcher=root/'launcher';launcher.write_text((BIN/'agentstack-spawn-claude').read_text().replace('$HOME/.agentstack',str(root)))
            for name,exitcode in [('agentstack-memory-budget',0),('agentstack-preregister-child',42)]:
                p=root/'bin'/name;p.write_text('#!/bin/bash\nprintf called > "'+str(root/name)+'"\nexit '+str(exitcode)+'\n');p.chmod(0o755)
            (root/'bin/lib').mkdir()
            (root/'bin/lib/agentstack-child-name.sh').write_bytes((BIN/'lib/agentstack-child-name.sh').read_bytes())
            task=root/'task.md';task.write_text('# Boundary fixture\n')
            r=subprocess.run(['/bin/bash',str(launcher),'fable',str(task),str(root),'fixture'],env=dict(os.environ,
                AGENTSTACK_HOME=str(root),AGENTSTACK_RUNTIME_DIR=str(root/'runtime')),capture_output=True,text=True,timeout=10)
            self.assertEqual(r.returncode,42)
            self.assertTrue((root/'agentstack-memory-budget').exists())
            self.assertTrue((root/'agentstack-preregister-child').exists())

    def test_claude_bypasses_memory_hold(self):
        with tempfile.TemporaryDirectory(prefix='fleetmem2-claude-') as temp:
            root=Path(temp);(root/'bin').mkdir();(root/'runtime').mkdir()
            (root/'runtime/memory-hold').write_text('R-183 physical-headroom\n')
            launcher=root/'launcher';launcher.write_text((BIN/'agentstack-spawn-claude').read_text().replace('$HOME/.agentstack',str(root)))
            for name,exitcode in [('agentstack-memory-budget',75),('agentstack-preregister-child',42)]:
                p=root/'bin'/name;p.write_text('#!/bin/bash\nprintf called > "'+str(root/name)+'"\nexit '+str(exitcode)+'\n');p.chmod(0o755)
            task=root/'task.md';task.write_text('# Boundary fixture\n')
            r=subprocess.run(['/bin/bash',str(launcher),'fable',str(task),str(root),'fixture'],env=dict(os.environ,
                AGENTSTACK_HOME=str(root),AGENTSTACK_RUNTIME_DIR=str(root/'runtime')),capture_output=True,text=True,timeout=10)
            self.assertEqual(r.returncode,75)
            self.assertTrue((root/'agentstack-memory-budget').exists())
            self.assertFalse((root/'agentstack-preregister-child').exists())

    def test_resume_gate_precedes_loader_and_http(self):
        from unittest.mock import Mock
        loader=importlib.machinery.SourceFileLoader('fleet_resume',str(BIN/'agentstack-resume'))
        spec=importlib.util.spec_from_loader(loader.name,loader);module=importlib.util.module_from_spec(spec);loader.exec_module(module)
        with patch.object(module.subprocess,'run',return_value=Mock(returncode=75)) as run:
            self.assertEqual(module.main(),75)
        self.assertEqual(len(run.call_args_list),1)
        self.assertEqual(Path(run.call_args.args[0][0]).name,'agentstack-memory-budget')

    def test_global_claude_start_deny_before_prepare(self):
        spec=importlib.util.spec_from_file_location('fleet_delivery',BIN/'lib/runtime_delivery.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        delivery=module.RuntimeDelivery.__new__(module.RuntimeDelivery)
        delivery.client=object()
        with patch.object(delivery,'memory_admit',side_effect=SystemExit(75)) as gate:
            with self.assertRaises(SystemExit) as caught:delivery.start('claude','/fixture')
        self.assertEqual(caught.exception.code,75);gate.assert_called_once()

    def test_global_create_wrapper_and_exec_provider_cover_all_providers(self):
        from types import SimpleNamespace
        spec=importlib.util.spec_from_file_location('fleet_all_delivery',BIN/'lib/runtime_delivery.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        for provider in ['codex','claude','gemini']:
            delivery=module.RuntimeDelivery.__new__(module.RuntimeDelivery)
            delivery.client=SimpleNamespace(operation_mutex=contextlib.nullcontext)
            with patch.object(delivery,'memory_admit',side_effect=SystemExit(75)) as gate:
                with self.assertRaises(SystemExit) as caught:delivery.create_wrapper({'provider':provider})
            self.assertEqual(caught.exception.code,75);gate.assert_called_once()
            row=dict(provider=provider,launch_id='launch',receipt_nonce='nonce',phase='exec-unknown',
                     execution={'outcome':{'state':'pending'},'runner':{'pid':os.getppid(),'process_start':'start'}})
            delivery.api={'process_start':lambda pid:'start'}
            with patch.object(delivery,'launch',return_value=row),patch.object(delivery,'provider_command',return_value=['fixture']),patch.object(delivery,'memory_admit',side_effect=SystemExit(75)) as gate,patch.object(module.os,'execvpe') as execute:
                with self.assertRaises(SystemExit) as caught:delivery.exec_provider('launch','nonce')
            self.assertEqual(caught.exception.code,75);gate.assert_called_once();execute.assert_not_called()


class GuardWrapperTests(unittest.TestCase):
    def test_crash_scan_runs_even_if_memory_fails_and_exit_is_preserved(self):
        with tempfile.TemporaryDirectory(prefix='fleetmem2-wrapper-') as temp:
            root=Path(temp);(root/'bin').mkdir()
            for memory_exit,crash_exit,expected in [(0,0,0),(75,0,75),(0,75,75),(75,1,75)]:
                for name,code in [('agentstack-memory-budget',memory_exit),('agentstack-sim-crash-watch',crash_exit)]:
                    p=root/'bin'/name;p.write_text('#!/bin/bash\nprintf called >> "'+str(root/name)+'"\nexit '+str(code)+'\n');p.chmod(0o755)
                r=subprocess.run(['/bin/bash',str(BIN/'agentstack-memory-guard')],env=dict(os.environ,AGENTSTACK_HOME=str(root)),capture_output=True,text=True,timeout=10)
                self.assertEqual(r.returncode,expected)
                self.assertEqual(r.stdout+r.stderr,'')
            self.assertEqual((root/'agentstack-memory-budget').read_text(),'called'*4)
            self.assertEqual((root/'agentstack-sim-crash-watch').read_text(),'called'*4)


if __name__=='__main__':unittest.main(verbosity=2)

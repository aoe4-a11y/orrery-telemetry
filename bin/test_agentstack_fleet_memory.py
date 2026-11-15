#!/usr/bin/env python3
"""FLEET-MEM-1: deterministic pressure, admission, idle/protected-process checks.
Only synthetic Mail DBs/process tables/tmux are used; no live process is signalled.
"""
import contextlib
import glob
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

BIN = Path(__file__).resolve().parent
loader = importlib.machinery.SourceFileLoader('fleet_memory', str(BIN/'agentstack-memory-budget'))
spec = importlib.util.spec_from_loader(loader.name, loader)
mem = importlib.util.module_from_spec(spec)
loader.exec_module(mem)


def healthy(**updates):
    s = dict(total_mb=36864, available_mb=20000, free_mb=14000,
             compressor_mb=500, fleet_mb=4000, cli_count=2, seat_mb=2048, level=85)
    s.update(updates)
    return s


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='fleetmem-test-')
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for key in list(os.environ):
            if key.startswith('AGENTSTACK_MEMORY_'):
                del os.environ[key]

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_healthy_and_separate_pressure_metrics(self):
        s = healthy()
        self.assertEqual(mem.reasons(s, mem.limits(s), 2048), [])
        for values, expected in [({'available_mb':10000}, 'physical-headroom'),
                                 ({'compressor_mb':11100}, 'compressor'),  # 11-08: limit is 30% of 36864 = 11059
                                 ({'fleet_mb':28000}, 'Codex-footprint'),
                                 ({'level':49}, 'memorystatus-level'),
                                 ({'sim_app_mb':7000}, 'simulator-app-footprint'),
                                 ({'tool_mb':13000}, 'xctrace-footprint')]:
            s = healthy(**values)
            self.assertIn(expected, mem.reasons(s, mem.limits(s), 2048))

    def test_compressed_pages_do_not_make_free_memory(self):
        # vm_stat has a huge logical compressed count; only occupied physical
        # compressor pages are read and none are added to available.
        vm = ('Mach Virtual Memory Statistics: (page size of 16384 bytes)\n'
              'Pages free: 100.\nPages inactive: 200.\nPages speculative: 30.\n'
              'Pages occupied by compressor: 500.\nPages stored in compressor: 99999999.\n')
        def output(argv):
            if argv[0].endswith('vm_stat'): return vm
            if argv[-1] == 'hw.memsize': return str(36*1024**3)
            if argv[-1] == 'kern.memorystatus_level': return '80'
            if argv[0].endswith('ps'):
                return str(os.getpid())+' 1 /bin/python3\n10 1 /bin/codex\n11 10 /bin/codex-code-mode-host\n12 1 /App/Codex\n'
            return 'PID MEM\n'+str(os.getpid())+' 80M\n10 1600M\n11 200M\n12 4G\n'
        with patch.object(mem, 'run', output):
            s, _ = mem.sample()
        self.assertEqual(s['available_mb'], 330*16384/1024**2)
        self.assertEqual(s['fleet_mb'],1800)
        self.assertEqual(s['cli_count'],1)

    def test_footprint_units(self):
        self.assertEqual(mem.mem_mb('1.5G+'),1536)
        self.assertEqual(mem.mem_mb('1024K'),1)
        self.assertEqual(mem.mem_mb('1048576B'),1)
        with self.assertRaises(ValueError): mem.mem_mb('unknown')

    def test_invalid_limits_fail_closed(self):
        for value in ['nan','inf','-1','wrong']:
            with patch.dict(os.environ, AGENTSTACK_MEMORY_RESERVE_MB=value):
                with self.assertRaises(ValueError): mem.limits(healthy())

    def test_hold_blocks_admission(self):
        (self.root/'memory-hold').write_text('foreign hold')
        with contextlib.redirect_stderr(io.StringIO()) as err:
            rc = mem.admit(self.root,healthy(),{})
        self.assertEqual(rc,75)
        self.assertIn('memory-hold',err.getvalue())

    def test_seat_weight_light_default_heavy_keeps_largest(self):
        # 11-08 owner (chat「分けてよい」): light seats 2 GiB; Simulator/Xcode stations keep the largest seat.
        s = healthy(available_mb=12760, seat_mb=5722)
        self.assertEqual(mem.limits(s)['seat'], 2048)
        self.assertEqual(mem.admit(self.root, s, {}), 0)
        with patch.dict(os.environ, AGENTSTACK_MEMORY_SEAT_WEIGHT='heavy'):
            self.assertEqual(mem.limits(s)['seat'], 5722)
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(mem.admit(self.root, s, {}), 75)
            self.assertIn('physical-headroom', err.getvalue())
        with patch.dict(os.environ, AGENTSTACK_MEMORY_SEAT_WEIGHT='bogus'):
            with self.assertRaises(ValueError): mem.limits(s)

    def test_guard_clears_with_light_estimate_but_floors_stay(self):
        mem.guard(self.root, healthy(level=20), lambda _: None)
        self.assertTrue((self.root/'memory-hold').exists())
        mem.guard(self.root, healthy(available_mb=12760, seat_mb=5722, compressor_mb=7800), lambda _: None)
        self.assertFalse((self.root/'memory-hold').exists())
        for values in [{'available_mb':8000}, {'level':49}, {'compressor_mb':11100}]:
            mem.guard(self.root, healthy(seat_mb=5722, **values), lambda _: None)
            self.assertTrue((self.root/'memory-hold').exists(), values)
            mem.guard(self.root, healthy(), lambda _: None)

    def test_spawners_mark_simulator_stations_heavy(self):
        home = self.root/'home'; (home/'bin').mkdir(parents=True)
        stub = home/'bin/agentstack-memory-budget'
        stub.write_text('#!/bin/bash\necho "weight=${AGENTSTACK_MEMORY_SEAT_WEIGHT:-light}" >&2\nexit 75\n')
        stub.chmod(0o755)
        heavy = self.root/'heavy.md'; heavy.write_text('iPad の Simulator で測る\n')
        light = self.root/'light.md'; light.write_text('解説を書く\n')
        for entry in [BIN/'agentstack-spawn-codex', BIN/'agentstack-spawn-claude']:
            for task, want in [(heavy, 'weight=heavy'), (light, 'weight=light')]:
                env = dict(os.environ, AGENTSTACK_HOME=str(home))
                env.pop('AGENTSTACK_MEMORY_SEAT_WEIGHT', None)
                r = subprocess.run(['/bin/bash', str(entry), 'model', str(task)], env=env,
                                   capture_output=True, text=True, timeout=30)
                self.assertEqual(r.returncode, 75, entry.name)
                self.assertIn(want, r.stderr, entry.name)

    def test_pending_launches_accounted_and_nested_wrapper_reused(self):
        parent=os.getppid()
        procs={parent:(1,'bash'),500:(1,'bash')}
        (self.root/'memory-admissions.json').write_text(json.dumps({'500':dict(at=time.time(),mb=2048)}))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(mem.admit(self.root,healthy(available_mb=12000),procs),75)
        (self.root/'memory-admissions.json').write_text(json.dumps({str(parent):dict(at=time.time(),mb=2048)}))
        self.assertEqual(mem.admit(self.root,healthy(available_mb=12000),procs),0)
        self.assertEqual(len(json.loads((self.root/'memory-admissions.json').read_text())),1)

    def test_guard_one_notice_per_episode_and_recovery_hysteresis(self):
        sent=[]
        for _ in range(3): mem.guard(self.root,healthy(fleet_mb=30000),sent.append)
        self.assertEqual(len(sent),1)
        self.assertTrue((self.root/'memory-hold').exists())
        mem.guard(self.root,healthy(available_mb=9000),sent.append)
        self.assertTrue((self.root/'memory-hold').exists())
        mem.guard(self.root,healthy(),sent.append)
        self.assertFalse((self.root/'memory-hold').exists())
        mem.guard(self.root,healthy(compressor_mb=11100),sent.append)
        self.assertEqual(len(sent),2)

    def test_guard_unknown_delivery_not_resent(self):
        sent=[]
        def lose(body): sent.append(body); raise RuntimeError('lost response')
        mem.guard(self.root,healthy(level=20),lose)
        mem.guard(self.root,healthy(level=20),lose)
        self.assertEqual(len(sent),1)
        self.assertIn('unknown',json.loads((self.root/'memory-guard-state.json').read_text())['delivery'])

    def test_foreign_hold_never_cleared(self):
        flag=self.root/'memory-hold';flag.write_text('other owner')
        mem.guard(self.root,healthy(),lambda _:None)
        self.assertEqual(flag.read_text(),'other owner')
        mem.guard(self.root,healthy(level=1),lambda _:None)
        mem.guard(self.root,healthy(),lambda _:None)
        self.assertEqual(flag.read_text(),'other owner')

    def test_all_shell_codex_entrypoints_refuse_before_launch(self):
        home=Path.home()/'.agentstack'
        entries=[(BIN/'agentstack-spawn-codex',[]), (BIN/'agentstack-restart-seat',[]),
                 (BIN/'agent-start-codex',[]), (home/'hooks/spawn_child.sh',['--codex']),
                 (home/'hooks/spawn_child.upstream.sh',['--codex']),
                 (home/'releases/seat-lifecycle/ee5880e3e23606e0f3252cbeed211868102f4595/hooks/spawn_child.sh',['--codex'])]
        for entry,args in entries:
            env=dict(os.environ,AGENTSTACK_MEMORY_RESERVE_MB='1000000',
                     AGENTSTACK_RUNTIME_DIR=str(self.root))
            r=subprocess.run(['/bin/bash',str(entry),*args],env=env,
                             capture_output=True,text=True,timeout=30)
            self.assertEqual(r.returncode,75,entry.name+': '+r.stderr)
            self.assertEqual(len(r.stderr.strip().splitlines()),1)
            self.assertIn('memory admission refused:',r.stderr)

    def test_global_admission_is_shared_host_runtime_and_denies(self):
        source=BIN/'lib/runtime_delivery.py'
        spec=importlib.util.spec_from_file_location('memory_runtime_delivery',source)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        from types import SimpleNamespace
        delivery=module.RuntimeDelivery.__new__(module.RuntimeDelivery)
        delivery.client=SimpleNamespace(config={'agentstack_home':str(self.root)})
        response=SimpleNamespace(returncode=75,stderr='memory admission refused: physical-headroom\n')
        with patch.object(module.subprocess,'run',return_value=response) as invoke:
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ex:delivery.memory_admit()
        self.assertEqual(ex.exception.code,75)
        self.assertEqual(invoke.call_args.kwargs['env']['AGENTSTACK_RUNTIME_DIR'],str(self.root/'runtime'))

    def test_six_real_jetsam_snapshots_rejected_before_1105(self):
        paths=sorted(glob.glob('/Library/Logs/DiagnosticReports/JetsamEvent-2026-11-07-*.ips'))
        if not paths: self.skipTest('historical reports not installed')
        self.assertEqual(len(paths),6)
        for p in paths:
            with open(p) as f: f.readline(); d=json.load(f)
            ms=d['memoryStatus']; pages=ms['memoryPages']; unit=ms['pageSize']/1024**2
            cli=[x for x in d['processes'] if x['name']=='codex']
            s=healthy(total_mb=36864, level=100,
                available_mb=sum(pages[k] for k in ('free','inactive','speculative'))*unit,
                compressor_mb=ms['compressorSize']*unit,
                fleet_mb=sum(x['rpages'] for x in cli)*unit)
            why=mem.reasons(s,mem.limits(s))
            self.assertIn('compressor',why,Path(p).name)
            self.assertIn('Codex-footprint',why,Path(p).name)
        # Healthy controls and a conservative ramp hit the configured guard well
        # before even the earliest report. This is replay, not prediction proof.
        for g in range(1,8):
            s=healthy(compressor_mb=g*1024)
            self.assertNotIn('compressor',mem.reasons(s,mem.limits(s)))
        s=healthy(compressor_mb=8*1024)
        self.assertIn('compressor',mem.reasons(s,mem.limits(s)))


class ReaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='fleetmem-reaper-')
        self.root=Path(self.tmp.name); self.bin=self.root/'bin';self.bin.mkdir()
        self.child=self.root/'child';self.child.mkdir()
        self.sessions=self.root/'sessions';self.sessions.mkdir()
        self.strikes=self.root/'strikes';self.strikes.mkdir()
        (self.root/'protect').write_text('')
        self.db=self.root/'mail.sqlite3'
        with sqlite3.connect(self.db) as c:
            c.executescript('''create table agents(id integer primary key,name text);
            create table messages(id integer primary key,sender_id int,subject text,created_ts text,ack_required int);
            create table message_recipients(message_id int,agent_id int,kind text,ack_ts text);''')
        # Fake tmux only changes files in this test directory; no process signal.
        self.script('tmux', '''import sys,os
from pathlib import Path
r=Path(os.environ['TEST_ROOT']);args=sys.argv[1:];cmd=args[0]
target=args[args.index('-t')+1].lstrip('=') if '-t' in args else ''
p=r/'sessions'/target
if cmd=='list-sessions': print('\\n'.join(x.name for x in (r/'sessions').iterdir()))
elif cmd=='list-panes': print(p.read_text().strip())
elif cmd=='has-session': sys.exit(0 if p.exists() else 1)
elif cmd=='capture-pane': print('Working (esc to interrupt)' if target=='Busy' else 'Ask Codex to do anything')
elif cmd=='kill-session':
 with (r/'closed').open('a') as f:f.write(target+'\\n')
 p.unlink()
else: sys.exit(1)
''')
        self.script('ps','''import sys,os
from pathlib import Path
r=Path(os.environ['TEST_ROOT'])
print((r/('ps-env' if '-E' in sys.argv else 'ps')).read_text())
''')
        self.script('signal','''import os,sys
from pathlib import Path
with (Path(os.environ['TEST_ROOT'])/'signals').open('a') as f:f.write(' '.join(sys.argv[1:])+'\\n')
''')
        # Stub only the installed operations sender for hermetic tests.
        self.script('python3','''import os,sys
if 'from agentstack_stallself import' in ' '.join(sys.argv):
 from pathlib import Path
 with (Path(os.environ['TEST_ROOT'])/'notices').open('a') as f:f.write(sys.stdin.read()+'\\n')
else:
 os.execv(sys.executable,[sys.executable,*sys.argv[1:]])
''')
        self.env=dict(os.environ,TEST_ROOT=str(self.root),PATH=str(self.bin)+':'+os.environ['PATH'],
            REAP_DB=str(self.db),REAP_TMUX=str(self.bin/'tmux'),REAP_PS=str(self.bin/'ps'),
            REAP_KILL=str(self.bin/'signal'),REAP_PROTECT_FILE=str(self.root/'protect'),
            REAP_CHILD_ROOT=str(self.child),REAP_STRIKE_DIR=str(self.strikes),
            REAP_LOG=str(self.root/'log'),REAP_HEAVY_LOCK_ROOT=str(self.root/'heavy'),
            REAP_REGISTRY_GLOBS=str(self.root/'registry/*/.dev-storage.json'))
        (self.root/'ps').write_text('');(self.root/'ps-env').write_text('')

    def tearDown(self): self.tmp.cleanup()

    def script(self,name,source):
        p=self.bin/name;p.write_text('#!'+os.sys.executable+'\n'+source);p.chmod(0o755)

    def seat(self,name,pid,subject='[blocked] waiting',age=600,strike_age=600):
        (self.sessions/name).write_text(str(pid))
        rollout=self.child/(name+'.codex-home')/'sessions/2026/11/07/rollout-proof.jsonl'
        rollout.parent.mkdir(parents=True);rollout.write_text('retained evidence\n')
        os.utime(rollout,(time.time()-age,)*2)
        strike=self.strikes/name;strike.write_text(hashlib.sha256(b'Ask Codex to do anything').hexdigest()+'\n');os.utime(strike,(time.time()-strike_age,)*2)
        with sqlite3.connect(self.db) as c:
            aid=c.execute('insert into agents(name) values (?)',(name,)).lastrowid
            c.execute("insert into messages(sender_id,subject,created_ts,ack_required) values (?,?,datetime('now',?),0)",
                      (aid,subject,'-%d seconds'%age))
        return rollout

    def census(self,lines):
        lines=''.join(p.read_text().strip()+' 1 /bin/bash\n' for p in self.sessions.iterdir())+lines
        (self.root/'ps').write_text(lines);(self.root/'ps-env').write_text(lines)

    def reap(self,*args,expected=0):
        r=subprocess.run(['/bin/bash',str(BIN/'agentstack-reap-idle-seats'),*args],env=self.env,
                         capture_output=True,text=True,timeout=20)
        self.assertEqual(r.returncode,expected,r.stderr)
        return r

    def test_blocked_untagged_unfinished_closed_preserving_rollouts(self):
        originals=[]
        for n,sub,pid in [('Blocked','[blocked] waiting',100),('Untagged','waiting',200),('Unfinished','[progress] waiting',300)]:
            p=self.seat(n,pid,sub);originals.append((p,hashlib.sha256(p.read_bytes()).digest()))
        self.census('101 100 /bin/codex\n201 200 /bin/codex\n301 300 /bin/codex\n')
        self.reap()
        self.assertEqual(set((self.root/'closed').read_text().splitlines()),{'Blocked','Untagged','Unfinished'})
        for p,digest in originals:self.assertEqual(hashlib.sha256(p.read_bytes()).digest(),digest)
        self.assertFalse((self.root/'signals').exists())
        self.assertEqual((self.root/'notices').read_text().count('R-183 idle'),3)

    def test_work_heavy_recent_mail_and_busy_preserved(self):
        for n,pid in [('Work',100),('Heavy',200),('Recent',300),('Busy',400),('Fresh',500)]:
            self.seat(n,pid,age=10 if n=='Recent' else 600,strike_age=10 if n=='Fresh' else 600)
        ticket=self.root/'heavy/waiting/ticket-1';ticket.mkdir(parents=True)
        (ticket/'owner').write_text('Heavy');(ticket/'pid').write_text('201')
        self.census('101 100 /bin/codex\n102 100 /bin/sleep 600\n201 200 /bin/codex\n301 300 /bin/codex\n401 400 /bin/codex\n501 500 /bin/codex\n')
        self.reap()
        self.assertEqual(len(list(self.sessions.iterdir())),5)
        self.assertFalse((self.root/'signals').exists())

    def test_shared_service_and_simulator_block_pane_closure(self):
        self.seat('Owner',100);self.seat('Peer',200)
        self.census('101 100 /bin/codex\n102 100 /X/SWBBuildService\n103 100 /CoreSimulator/Devices/opaque/data/App\n201 200 /bin/codex\n')
        self.reap('--close','Owner','test',expected=1)
        self.assertTrue((self.sessions/'Owner').exists())
        self.assertFalse((self.root/'signals').exists())

    def test_exclusive_work_close_signals_only_owned_pid(self):
        self.seat('Owner',100);self.seat('Peer',200)
        self.census('101 100 /bin/codex\n102 100 /bin/sleep 600\n201 200 /bin/codex\n202 200 /bin/sleep 600\n')
        self.reap('--close','Owner','test')
        signals=(self.root/'signals').read_text()
        self.assertIn('-TERM 102',signals);self.assertNotIn('202',signals)
        self.assertTrue((self.sessions/'Peer').exists())

    def test_detached_process_attributed_to_two_live_seats_is_not_signalled(self):
        self.seat('Owner',100);self.seat('Peer',200)
        registry=self.root/'registry/shared-root';registry.mkdir(parents=True)
        (registry/'.dev-storage.json').write_text('{"owner":"Peer"}')
        self.census('101 100 /bin/codex\n102 100 /bin/sleep 600\n201 200 /bin/codex\n900 1 /bin/sleep shared-root\n')
        with (self.root/'ps-env').open('a') as f:f.write('900 /bin/sleep shared-root AGENT_NAME=Owner\n')
        self.reap('--close','Owner','test')
        signals=(self.root/'signals').read_text()
        self.assertIn('-TERM 102',signals);self.assertNotIn('900',signals)
        self.assertTrue((self.sessions/'Peer').exists())

    def test_dry_run_changes_no_strikes_or_rollouts(self):
        p=self.seat('Owner',100);self.census('101 100 /bin/codex\n')
        before={str(x): (x.stat().st_mtime_ns,x.read_bytes()) for x in [p,self.strikes/'Owner']}
        self.reap('--dry-run')
        self.assertTrue((self.sessions/'Owner').exists())
        for x,(ts,data) in before.items():
            self.assertEqual(Path(x).stat().st_mtime_ns,ts);self.assertEqual(Path(x).read_bytes(),data)


if __name__=='__main__': unittest.main(verbosity=2)

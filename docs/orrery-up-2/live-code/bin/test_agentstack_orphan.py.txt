import ast
import contextlib
import copy
import fcntl
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).parent))
import agentstack_orphan as m


def process(pid=200, parent=1, cpu=150, seconds=100, started='Wed Oct 21 06:00:00 2026', args='/bin/codex app-server daemon'):
    return dict(pid=pid,ppid=parent,cpu_percent=cpu,cpu_seconds=seconds,
                cpu_time=str(int(seconds)//60)+':'+str(seconds%60),
                started=started,key=str(pid)+':'+started,args=args)


def path(pid):return dict(kind='cwd',path='/Volumes/DevSSD-Private/artifacts/task/scratch/work')


class OrphanTests(unittest.TestCase):
    def advance(self,state,t,p=None,finder=path):
        row=p or process(seconds=100+1.5*t)
        return m.advance(state,{row['pid']:row},now=t,path_finder=finder)

    def full(self,state=None):
        state={} if state is None else state
        out=[]
        for t in range(0,1801,300):out=self.advance(state,t)
        return state,out

    def test_exact_real_duration_not_process_age(self):
        state={}
        for t in range(0,1800,300):self.assertEqual(self.advance(state,t),[])
        self.assertEqual(self.advance(state,1799),[])
        # Same steady1.5core process; threshold is elapsed from first observation.
        self.assertEqual(len(self.advance(state,1800)),1)
        self.assertEqual(next(iter(state['events'].values()))['observed_seconds'],1800)

    def test_old_process_first_seen_has_no_immediate_alert(self):
        state={};self.advance(state,100000,process(seconds=999999))
        self.assertFalse(state['events']);self.assertEqual(next(iter(state['candidates'].values()))['since'],100000)

    def test_strict_cpu_boundary_and_parent(self):
        for parent,cpu in [(2,250),(1,100),(1,99.99),(1,0)]:
            state={}
            for t in range(0,2101,300):self.advance(state,t,process(parent=parent,cpu=cpu,seconds=1.5*t))
            self.assertEqual(state['candidates'],{});self.assertEqual(state['events'],{})

    def test_transient_cpu_dip_resets(self):
        state={}
        for t in range(0,1501,300):self.advance(state,t)
        self.advance(state,1700,process(cpu=99,seconds=2700))
        self.assertEqual(self.advance(state,1800),[])
        self.assertEqual(next(iter(state['candidates'].values()))['since'],1800)

    def test_interval_cpu_not_current_percent_alone(self):
        state={};self.advance(state,0,process(seconds=100))
        self.advance(state,300,process(seconds=400,cpu=200)) # exactly100% interval
        self.assertEqual(next(iter(state['candidates'].values()))['since'],300)

    def test_census_gap_clock_reversal_and_cpu_regression_reset(self):
        for t,seconds in [(451,900),(-1,100),(300,50)]:
            state={};self.advance(state,0,process(seconds=100))
            self.advance(state,t,process(seconds=seconds))
            self.assertEqual(next(iter(state['candidates'].values()))['since'],t)

    def test_process_disappears_resets(self):
        state={};self.advance(state,0)
        m.advance(state,{},now=300,path_finder=path)
        self.assertEqual(state['candidates'],{})
        self.advance(state,600);self.assertEqual(next(iter(state['candidates'].values()))['since'],600)

    def test_path_change_and_no_match_reset(self):
        state={};self.advance(state,0)
        self.advance(state,300,finder=lambda _:dict(kind='CODEX_HOME',path='/tmp/evidence/home'))
        self.assertEqual(next(iter(state['candidates'].values()))['since'],300)
        self.advance(state,600,finder=lambda _:None);self.assertEqual(state['candidates'],{})

    def test_actual_path_only_and_directory_components(self):
        for p in ['/tmp/artifacts/proc','/tmp/evidence/home','/tmp/source-worktree/bin/tool','/tmp/scratch/work','/tmp/20261020T012345Z-evidence-abc123/home']:
            self.assertTrue(m.managed_path(p),p)
        for p in ['/usr/bin/codex','/tmp/not-evidence/foo','/tmp/scratchpad/work','relative/artifacts/foo','/usr/bin/scratch']:
            self.assertFalse(m.managed_path(p),p)
        self.assertTrue(m.managed_path('/tmp/scratch',directory=True))
        state={}
        for t in range(0,2101,300):self.advance(state,t,process(args='codex --prompt /tmp/artifacts/a',seconds=1.5*t),finder=lambda _:None)
        self.assertFalse(state['events'])

    def test_cpu_and_process_parser(self):
        self.assertAlmostEqual(m.cpu_seconds('12345:20.25'),740720.25)
        self.assertEqual(m.cpu_seconds('1:02:03'),3723)
        self.assertEqual(m.cpu_seconds('2-01:00:00'),176400)
        text='200 1 151.2 Wed Oct 21 06:00:00 2026 12:03.5 /bin/codex app-server daemon\n'
        row=m.parse_processes(text)[200];self.assertEqual(row['cpu_seconds'],723.5);self.assertEqual(row['args'],'/bin/codex app-server daemon')
        for bad in ['', 'bad\n',text.replace('151.2','nan')]:
            with self.assertRaises(ValueError):m.parse_processes(bad)

    def test_environment_is_not_argv_and_supports_spaces(self):
        raw=struct.pack('i',3)+b'/bin/codex\0\0codex\0--prompt\0CODEX_HOME=/fake/artifacts/prompt\0OTHER_SECRET=do-not-store\0CODEX_HOME=/tmp/evidence/home with spaces\0'
        self.assertEqual(m.codex_home_from_procargs(raw),'/tmp/evidence/home with spaces')
        raw=struct.pack('i',2)+b'/bin/codex\0codex\0CODEX_HOME=/fake/artifacts/prompt\0OTHER_SECRET=secret\0'
        self.assertIsNone(m.codex_home_from_procargs(raw))
        self.assertIsNone(m.codex_home_from_procargs(b'bad'))

    def test_exe_cwd_and_codex_home_each_match(self):
        with mock.patch.object(m,'executable_path',return_value='/tmp/artifacts/exe/codex'),mock.patch.object(m.subprocess,'run') as run:
            self.assertEqual(m.matched_path(200)['kind'],'executable');run.assert_not_called()
        result=mock.Mock(returncode=0,stdout='p200\nn/tmp/evidence/work\n')
        with mock.patch.object(m,'executable_path',return_value='/usr/bin/codex'),mock.patch.object(m.subprocess,'run',return_value=result):
            self.assertEqual(m.matched_path(200)['kind'],'cwd')
        with mock.patch.object(m,'executable_path',return_value='/usr/bin/codex'),mock.patch.object(m.subprocess,'run',return_value=mock.Mock(returncode=1,stdout='')),mock.patch.object(m,'codex_home',return_value='/tmp/artifacts/home'):
            self.assertEqual(m.matched_path(200)['kind'],'CODEX_HOME')

    def test_private_command_and_long_prompt_never_persist(self):
        for command in ['codex --prompt "PRIVATE_MEDICAL_CONTENT" --token key-SECRET',
                        '/bin/sh -lc "PRIVATE_MEDICAL_CONTENT"',
                        'codex exec "PRIVATE_MEDICAL_CONTENT"',
                        'codex --api-key=key-SECRET /tmp/evidence/file',
                        'codex '+('PRIVATE_MEDICAL_CONTENT'*100000)]:
            excerpt=m.command_excerpt(command)
            self.assertLessEqual(len(excerpt),200);self.assertNotIn('PRIVATE_MEDICAL_CONTENT',excerpt);self.assertNotIn('key-SECRET',excerpt)
        self.assertIn('app-server daemon',m.command_excerpt('/bin/codex app-server daemon'))

    def test_simulator_xcode_claude_supervisor_and_live_codex_no_alert(self):
        roles=[('codex',2,250),('Simulator',1,2),('xcodebuild',44,800),('claude',88,150),('supervisor',1,.5)]
        state={}
        for t in range(0,2101,300):
            rows={i:process(i,parent,cpu,100+cpu/100*t,args=role) for i,(role,parent,cpu) in enumerate(roles,10)}
            self.assertFalse(m.advance(state,rows,now=t,path_finder=path))
        self.assertFalse(state['events'])

    def test_restart_duplicate_sweep_and_lost_response_once(self):
        for fails in [False,True]:
            state,events=self.full();self.assertEqual(len(events),1)
            with tempfile.TemporaryDirectory() as tmp:
                file=Path(tmp)/'state.json';calls=[]
                def sender(payload):
                    self.assertEqual(next(iter(json.loads(file.read_text())['events'].values()))['status'],'sending')
                    self.assertEqual(payload['seat'],'ProudTuring');calls.append(payload)
                    if fails:raise TimeoutError('PRIVATE_ERROR_TOKEN')
                    return dict(id=42)
                m.notify_pending(state,file,sender)
                reloaded=json.loads(file.read_text());self.advance(reloaded,2100);m.notify_pending(reloaded,file,sender)
                self.assertEqual(len(calls),1);self.assertNotIn('PRIVATE_ERROR_TOKEN',file.read_text())
                self.assertEqual(next(iter(reloaded['events'].values()))['status'],'delivery_uncertain' if fails else 'sent')

    def test_crash_sending_claim_and_pid_reuse_identity(self):
        state,events=self.full();event=events[0];event['status']='sending'
        with tempfile.TemporaryDirectory() as tmp:
            sender=mock.Mock();m.notify_pending(state,Path(tmp)/'state.json',sender);sender.assert_not_called()
        new=process(started='Wed Oct 21 07:00:00 2026',seconds=900)
        self.assertEqual(self.advance(state,2100,new),[]);self.assertEqual(len(state['events']),1)
        self.assertNotEqual(new['key'],next(iter(state['events'])))

    def test_missing_message_receipt_is_uncertain_without_retry(self):
        state,_=self.full()
        with tempfile.TemporaryDirectory() as tmp:
            sender=mock.Mock(return_value={});p=Path(tmp)/'state.json'
            m.notify_pending(state,p,sender);m.notify_pending(json.loads(p.read_text()),p,sender)
            self.assertEqual(sender.call_count,1);self.assertEqual(next(iter(state['events'].values()))['status'],'delivery_uncertain')

    def test_dry_run_does_not_create_lock_write_or_send(self):
        state={}
        for t in range(0,1800,300):self.advance(state,t)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'state.json';p.write_text(json.dumps(state));before=p.read_bytes();sender=mock.Mock()
            events=m.sweep(p,dry_run=True,now=1800,snapshot=lambda:{200:process(seconds=2800)},path_finder=path,sender=sender)
            self.assertEqual(len(events),1);self.assertEqual(p.read_bytes(),before);self.assertFalse(Path(str(p)+'.lock').exists());sender.assert_not_called()

    def test_concurrent_sweeps_cannot_send_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'state.json';sender=mock.Mock()
            with open(str(p)+'.lock','a') as held:
                fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
                self.assertEqual(m.sweep(p,snapshot=mock.Mock(side_effect=AssertionError('no census')),sender=sender),[])
            sender.assert_not_called()

    def test_notice_required_fields_and_at_most200_command(self):
        _,out=self.full();v=m.notice(out[0]);self.assertEqual(v['seat'],'ProudTuring')
        for text in ['PID: 200','開始時刻:','累計CPU時間:','該当path','command先頭200字']:self.assertIn(text,v['body_md'])
        self.assertTrue(v['subject'].startswith('[station]'))

    def test_detector_has_no_signal_or_pane_mutation(self):
        tree=ast.parse(Path(m.__file__).read_text())
        forbidden={'kill','killpg','system','popen','terminate','send_signal'}
        for node in ast.walk(tree):
            if isinstance(node,ast.Call):
                name=getattr(node.func,'attr',getattr(node.func,'id',''))
                self.assertNotIn(name,forbidden)

    def test_existing_watcher_functions_byte_ast_unchanged(self):
        b=Path(__file__).parent
        def funcs(p):return {x.name:ast.dump(x) for x in ast.parse(p.read_text()).body if isinstance(x,ast.FunctionDef)}
        old=funcs(b/'agentstack-seat-stall-watch.py.bak-20261021-orphan');new=funcs(b/'agentstack-seat-stall-watch.py')
        for name in old:
            if name!='guarded_main':self.assertEqual(old[name],new[name],name)

    def test_existing_watcher_guard_calls_orphan_and_keeps_main(self):
        spec=importlib.util.spec_from_file_location('watch',Path(__file__).with_name('agentstack-seat-stall-watch.py'));watch=importlib.util.module_from_spec(spec);spec.loader.exec_module(watch)
        with tempfile.TemporaryDirectory() as tmp, mock.patch('agentstack_retainprune.sweep', return_value={'kind':'healthy'}):
            watch.STATE=str(Path(tmp)/'state.json');watch.LOG=str(Path(tmp)/'watch.log')
            with mock.patch.object(m,'sweep',return_value=[]) as orphan,mock.patch.object(watch,'main') as main,mock.patch.object(sys,'argv',['watch.py']):watch.guarded_main()
            orphan.assert_called_once();main.assert_called_once()
            with mock.patch.object(m,'sweep') as orphan,mock.patch.object(watch,'main') as main,mock.patch.object(sys,'argv',['watch.py','--jobend-only']):watch.guarded_main()
            orphan.assert_not_called();main.assert_called_once()
            with mock.patch.object(m,'sweep',side_effect=RuntimeError('secret')) as orphan,mock.patch.object(watch,'main') as main,mock.patch.object(sys,'argv',['watch.py']):watch.guarded_main()
            main.assert_called_once();self.assertNotIn('secret',Path(watch.LOG).read_text())


if __name__=='__main__':unittest.main(verbosity=2)

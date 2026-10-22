#!/usr/bin/python3
"""All commands use fake tmux/ps. Real Claude captures supply the UI and NBSP."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
SCRIPT=Path(os.environ.get('UNSTICK_SCRIPT',Path(__file__).with_name('agentstack-unstick-seats.sh')))
FIXTURES=Path(os.environ.get('UNSTICK_FIXTURE_DIR','/Users/huyuhutaru/.agentstack/runtime/UNSTICK-FIX-2'))
WARN='⚠ 2 warnings · f2 to view'
NOTICE='› ORRERY notification\n'+ '\n'.join('  continuation '+str(i) for i in range(20))+'\n'+WARN

def claude_frame(text,continuation=''):
    source=(FIXTURES/'KindPasteur.plain.txt').read_text()
    lines=source.splitlines();i=max(i for i,line in enumerate(lines) if line.startswith('❯\u00a0'))
    # The real capture is unchanged except test draft contents. Preserve NBSP and frame.
    return '\n'.join(lines[i-1:i]+[lines[i][:2]+text]+(['  '+continuation] if continuation else [])+lines[i+1:])

def captured_codex_queue():
    # Derived fixture: actual queued UI prefix + actual idle plain/ANSI UI.
    # No claim that these two captures occurred in the same natural frame.
    queued=(FIXTURES/'BlackMendeleev.queued-source.txt').read_text().splitlines()
    q=next(i for i,line in enumerate(queued) if line.startswith('• Messages to be submitted'))
    end=max(i for i,line in enumerate(queued) if line.startswith('› '))
    prefix='\n'.join(queued[q:end])+'\n'
    plain=(FIXTURES/'placeholder-check.plain.txt').read_text().splitlines()
    ansi=(FIXTURES/'placeholder-check.ansi.txt').read_text().splitlines()
    start=max(i for i,line in enumerate(plain) if line.startswith('› '))
    return prefix+'\n'.join(plain[start:]),prefix+'\n'.join(ansi[start:])

class UnstickFixtureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        fake=self.root/'tmux';ps=self.root/'ps'
        fake.write_text('#!'+sys.executable+'\n'+'''import os,sys,json
from pathlib import Path
root=Path(os.environ['FAKE_TMUX_ROOT']);x=json.loads((root/'fixture.json').read_text());a=sys.argv[1:]
with (root/'calls.jsonl').open('a') as f:f.write(json.dumps(a)+'\\n')
name=x.get('session','FixtureSeat');target='='+name+':'
if a==['list-sessions','-F','#{session_name}']:
 if x.get('list_exit'):print(x.get('list_error','denied'),file=sys.stderr);sys.exit(x['list_exit'])
 print(name)
elif a==['display-message','-p','-t',target,'#{session_name}|#{pane_id}|#{pane_pid}|#{session_attached}']:
 p=root/'meta_count';n=int(p.read_text())+1 if p.exists() else 1;p.write_text(str(n))
 pane='%10' if n>=x.get('meta_flip_after',999999) else '%9'
 print(name+'|'+pane+'|100|'+str(x.get('attached',0)))
elif a==['list-clients','-t',target,'-F','#{session_name}|#{client_activity}']:
 if x.get('clients_exit'):sys.exit(1)
 if 'activity' in x:print(name+'|'+str(x['activity']))
elif a in (['capture-pane','-p','-t',target],['capture-pane','-p','-e','-t',target]):
 print(x.get('ansi',x['pane']) if '-e' in a else x['pane'])
elif a in (['send-keys','-t',target,'C-m'],['send-keys','-t',target,'Enter']):
 if x.get('send_exit'):sys.exit(x['send_exit'])
 with (root/'keys.jsonl').open('a') as f:f.write(json.dumps(a)+'\\n')
else:raise SystemExit('unexpected fake tmux call: '+repr(a))
''');fake.chmod(0o755)
        ps.write_text('#!'+sys.executable+'\n'+'''import os,sys,json
from pathlib import Path
x=json.loads((Path(os.environ['FAKE_TMUX_ROOT'])/'fixture.json').read_text());k=x.get('kind','codex')
if k=='unreadable':sys.exit(1)
if sys.argv[1:]==['-axo','pid=,ppid=,comm=']:
 print('100 1 zsh')
 if k!='none':print('101 100 /bin/'+('claude' if k=='claude' else 'codex'))
 if k=='ambiguous':print('102 100 /bin/claude')
elif sys.argv[1:]==['-axo','pid=,args=']:
 print('100 zsh');print('101 /bin/'+('claude' if k=='claude' else 'codex'))
else:sys.exit(2)
''');ps.chmod(0o755)
        roster=self.root/'roster.json';roster.write_text(json.dumps({'project_id':1,'project_key':'/Users/huyuhutaru/tools/examforge','agents':['FixtureSeat']}))
        self.env=dict(os.environ,HOME=str(self.root),FAKE_TMUX_ROOT=str(self.root),UNSTICK_TEST_MODE='1',TMUX_BIN=str(fake),UNSTICK_TEST_PS_BIN=str(ps),UNSTICK_ROSTER_PATH=str(roster),UNSTICK_LIVE='1')
        self.env.pop('UNSTICK_DRY_RUN',None)
        for k in ['UNSTICK_LOG_PATH','UNSTICK_STATE_DIR','UNSTICK_ERR_PATH']:self.env.pop(k,None)
        self.now=1000
    def tearDown(self):self.tmp.cleanup()
    def run_pane(self,text,kind='codex',seconds=80,expect=0,**extra):
        (self.root/'fixture.json').write_text(json.dumps({'pane':text,'kind':kind,**extra}))
        env=dict(self.env,UNSTICK_TEST_NOW=str(self.now));self.now+=seconds
        x=subprocess.run(['/bin/bash',str(SCRIPT)],env=env,capture_output=True,text=True)
        self.assertEqual(x.returncode,expect,x.stderr);return x
    def keys(self):
        p=self.root/'keys.jsonl';return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []
    def events(self):
        runtime=self.root/'.agentstack/runtime'
        live=self.env.get('UNSTICK_LIVE')=='1' and not self.env.get('UNSTICK_DRY_RUN')
        names=['unstick-seats.log','unstick-seats.live-diagnostics.log'] if live else ['unstick-seats.dry-run.log']
        return [json.loads(line) for name in names for p in [runtime/name] if p.exists() for line in p.read_text().splitlines()]
    def ignored(self,text,**extra):
        self.run_pane(text,**extra);self.run_pane(text,**extra);self.assertEqual(self.keys(),[])
    def test_multiline_warning_footer_requires_elapsed_80(self):
        self.run_pane(NOTICE,seconds=1);self.run_pane(NOTICE,seconds=79);self.assertEqual(self.keys(),[])
        self.run_pane(NOTICE);self.assertEqual([x[-1] for x in self.keys()],['C-m'])
        self.run_pane(NOTICE);self.assertEqual(len(self.keys()),1)
    def test_single_line_model_footer(self):
        text='› notification\ngpt-6.1-sol high';self.run_pane(text);self.run_pane(text);self.assertEqual(len(self.keys()),1)
    def test_changed_continuation_restarts_stability(self):
        self.run_pane(NOTICE);changed=NOTICE.replace('continuation 19','changed continuation 19')
        self.run_pane(changed);self.assertEqual(self.keys(),[]);self.run_pane(changed);self.assertEqual(len(self.keys()),1)
    def test_working_clears_stability(self):
        self.run_pane(NOTICE);self.run_pane('Working (2s)\n'+NOTICE);self.run_pane(NOTICE);self.assertEqual(self.keys(),[])
        self.run_pane(NOTICE);self.assertEqual(len(self.keys()),1)
    def test_codex_modal(self):
        self.ignored('Would you like to run this?\n› 1. Yes, proceed\n  2. Cancel\nPress enter to confirm or esc to cancel\nGPT-6.1-sol')
    def test_claude_modal(self):self.ignored(claude_frame('1. Allow')+'\nEsc to cancel',kind='claude')
    def test_empty_placeholder(self):self.ignored('› Ask Codex to do anything\n'+WARN)
    def test_whitespace(self):self.ignored('›   \n  \n'+WARN)
    def test_latest_empty_prompt_wins(self):self.ignored(NOTICE+'\n› Ask Codex to do anything\n'+WARN)
    def test_no_footer(self):self.ignored('› notice\n  more text')
    def test_warning_without_composer(self):self.ignored('completed output\n'+WARN)
    def test_interrupt_footer(self):self.ignored(NOTICE+'\n esc to interrupt')
    def test_actual_claude_captures(self):
        for name in ['KindPasteur','LushEuler','SpryPasteur','StormyLeeuwenhoek']:
            text=(FIXTURES/(name+'.plain.txt')).read_text();self.assertIn('❯\u00a0',text);self.ignored(text,kind='claude')
    def test_claude_nbsp_draft_live_fake(self):
        text=claude_frame('test notification');self.run_pane(text,kind='claude');self.run_pane(text,kind='claude');self.assertEqual([x[-1] for x in self.keys()],['Enter'])
    def test_claude_wrapped_continuation_in_fingerprint(self):
        a=claude_frame('draft','line 2');b=claude_frame('draft','line 2 changed')
        self.run_pane(a,kind='claude');self.run_pane(b,kind='claude');self.assertEqual(self.keys(),[])
        self.run_pane(b,kind='claude');self.assertEqual(len(self.keys()),1)
    def test_claude_dim_cannot_fall_into_case_c(self):
        text='submitted after next tool call\n'+claude_frame('suggested prompt');ansi=text.replace('❯\u00a0suggested prompt','❯\u00a0\x1b[2msuggested prompt\x1b[22m')
        self.ignored(text,kind='claude',ansi=ansi)
    def test_claude_phrase_does_not_submit_first_run(self):
        text='submitted after next tool call\n'+claude_frame('draft');self.run_pane(text,kind='claude');self.assertEqual(self.keys(),[])
    def test_codex_quoted_phrase_without_ui(self):self.ignored('example: submitted after next tool call\n› Ask Codex to do anything\nGPT-6.1-sol')
    def test_codex_real_queued_ui_requires_time(self):
        lines=(FIXTURES/'BlackMendeleev.queued-source.txt').read_text().splitlines();q=next(i for i,x in enumerate(lines) if x.startswith('• Messages to be submitted'))
        text='\n'.join(lines[q:]);self.run_pane(text,seconds=1);self.run_pane(text,seconds=79);self.assertEqual(self.keys(),[])
        self.run_pane(text);self.assertEqual(len(self.keys()),1)
    def test_codex_dim_draft_cannot_fall_into_queue(self):
        text=NOTICE;ansi=text.replace('› ORRERY notification','› \x1b[2mORRERY notification\x1b[22m');self.ignored(text,ansi=ansi)
    def test_real_dim_placeholder_queue_requires_two_stable_scans(self):
        text,ansi=captured_codex_queue()
        self.run_pane(text,ansi=ansi,seconds=1);self.run_pane(text,ansi=ansi,seconds=79)
        self.assertEqual(self.keys(),[])
        self.run_pane(text,ansi=ansi);self.assertEqual(len(self.keys()),1)
        self.assertEqual(next(x for x in self.events() if x['event']=='sent')['branch'],'codex-queued')
    def test_real_dim_placeholder_one_character_difference_stops(self):
        text,ansi=captured_codex_queue()
        self.ignored(text.replace('Ask Codex to do anything','Ask Codex to do anythinX'),ansi=ansi.replace('Ask Codex to do anything','Ask Codex to do anythinX'))
    def test_real_dim_suggestion_with_queue_stops(self):
        text,ansi=captured_codex_queue()
        self.ignored(text.replace('Ask Codex to do anything','Review the pending change'),ansi=ansi.replace('Ask Codex to do anything','Review the pending change'))
    def test_real_dim_placeholder_with_continuation_stops(self):
        text,ansi=captured_codex_queue()
        self.ignored(text.replace('› Ask Codex to do anything\n','› Ask Codex to do anything\n  additional input\n'),ansi=ansi.replace('Ask Codex to do anything','Ask Codex to do anything\n  additional input'))
    def test_exact_placeholder_exception_does_not_apply_to_claude(self):
        text=claude_frame('Ask Codex to do anything')
        ansi=text.replace('Ask Codex to do anything','\x1b[2mAsk Codex to do anything\x1b[22m')
        self.ignored(text,kind='claude',ansi=ansi)
    def test_nonfleet_session_no_capture(self):
        self.ignored(NOTICE,session='ROADBLOCK');calls=[json.loads(x) for x in (self.root/'calls.jsonl').read_text().splitlines()]
        self.assertFalse(any(x[0]=='capture-pane' for x in calls))
    def test_shell_not_eligible(self):self.ignored('submitted after next tool call\nbypass permissions\n'+NOTICE,kind='none')
    def test_ambiguous_tree(self):self.ignored(NOTICE,kind='ambiguous')
    def test_unreadable_tree(self):self.ignored(NOTICE,kind='unreadable')
    def test_recent_attached_client(self):self.ignored(NOTICE,attached=1,activity=999)
    def test_attached_missing_activity(self):self.ignored(NOTICE,attached=1)
    def test_client_query_error(self):self.ignored(NOTICE,clients_exit=1)
    def test_target_switch_recheck(self):
        self.ignored(NOTICE,meta_flip_after=3)
        self.assertTrue(any(x['event']=='changed-before-send' for x in self.events()))
    def test_exact_session_target_and_audit(self):
        self.run_pane(NOTICE);self.run_pane(NOTICE)
        for x in self.keys():self.assertEqual(x[2],'=FixtureSeat:')
        sent=next(x for x in self.events() if x['event']=='sent')
        for k in ['branch','session','composer_sha256','pane_tail_sha256']:self.assertTrue(sent[k])
    def test_palette_index_2_is_not_dim(self):
        text=claude_frame('test colored input');ansi=text.replace('❯\u00a0test colored input','❯\u00a0\x1b[38;5;2mtest colored input\x1b[0m')
        self.run_pane(text,kind='claude',ansi=ansi);self.run_pane(text,kind='claude',ansi=ansi);self.assertEqual(len(self.keys()),1)
    def test_fail_closed_live_values(self):
        for i,value in enumerate(['','0','true','yes',' 1','1 ']):
            self.env['UNSTICK_LIVE']=value;self.env['UNSTICK_STATE_DIR']=str(self.root/('state'+str(i)))
            self.run_pane(NOTICE);self.run_pane(NOTICE)
        self.assertEqual(self.keys(),[]);self.assertTrue(any(x['event']=='would-send-keys' for x in self.events()))
    def test_dry_override_even_with_live_one(self):
        self.env['UNSTICK_DRY_RUN']='1';self.ignored(NOTICE)
    def test_lock_blocks_concurrent_invocation(self):
        runtime=self.root/'.agentstack/runtime';runtime.mkdir(parents=True)
        with (runtime/'unstick-seats.lock').open('a') as f:
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);x=self.run_pane(NOTICE);self.assertIn('lock-busy',x.stdout)
        self.assertEqual(self.keys(),[]);self.run_pane(NOTICE);self.assertEqual(self.keys(),[])
    def test_no_server_is_info_once(self):
        self.run_pane('',list_exit=1,list_error='no server running');self.run_pane('',list_exit=1,list_error='no server running')
        self.assertEqual(len([x for x in self.events() if x.get('reason')=='no-tmux-server']),1)
        self.assertFalse((self.root/'.agentstack/runtime/unstick-seats.err').exists())
    def test_error_written_once(self):
        self.run_pane('',list_exit=1,list_error='permission denied',expect=1)
        self.assertEqual(len((self.root/'.agentstack/runtime/unstick-seats.err').read_text().splitlines()),1)
    def test_live_missing_is_dry(self):
        self.env.pop('UNSTICK_LIVE');self.ignored(NOTICE)
    def test_tmux_override_ignored_outside_test_mode(self):
        spec=importlib.util.spec_from_file_location('unstick_candidate',SCRIPT.with_name('agentstack_unstick_seats.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        env=dict(self.env);env.pop('UNSTICK_TEST_MODE')
        with patch.dict(os.environ,env,clear=True):self.assertEqual(module.Watchdog().tmux,'/opt/homebrew/bin/tmux')
    def test_dry_logs_bounded_and_permanent_unchanged(self):
        spec=importlib.util.spec_from_file_location('unstick_candidate',SCRIPT.with_name('agentstack_unstick_seats.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        env=dict(self.env,UNSTICK_DRY_RUN='1')
        with patch.dict(os.environ,env,clear=True):
            watchdog=module.Watchdog();permanent=watchdog.runtime/'unstick-seats.log';permanent.write_text('protected record\n')
            for i in range(1400):watchdog.record('test',index=i,detail='x'*100)
            self.assertEqual(permanent.read_text(),'protected record\n')
            self.assertLessEqual(watchdog.log.stat().st_size,65536);self.assertLessEqual(watchdog.log.with_name(watchdog.log.name+'.previous').stat().st_size,65536)
    def test_invalid_roster_fails_closed(self):
        p=Path(self.env['UNSTICK_ROSTER_PATH']);x=json.loads(p.read_text());x['project_id']=2;p.write_text(json.dumps(x));self.run_pane(NOTICE,expect=1);self.assertEqual(self.keys(),[])
    def test_unreadable_tree_clears_prior_stability(self):
        self.run_pane(NOTICE);self.run_pane(NOTICE,kind='unreadable');self.run_pane(NOTICE);self.assertEqual(self.keys(),[])
        self.run_pane(NOTICE);self.assertEqual(len(self.keys()),1)
    def test_invalid_roster_clears_prior_stability(self):
        self.run_pane(NOTICE)
        p=Path(self.env['UNSTICK_ROSTER_PATH']);valid=p.read_bytes();bad=json.loads(valid);bad['project_id']=2;p.write_text(json.dumps(bad))
        self.run_pane(NOTICE,expect=1);self.assertEqual(self.keys(),[])
        p.write_bytes(valid);self.run_pane(NOTICE);self.assertEqual(self.keys(),[])
        self.run_pane(NOTICE);self.assertEqual(len(self.keys()),1)
    def test_missing_roster_clears_prior_stability(self):
        self.run_pane(NOTICE)
        p=Path(self.env['UNSTICK_ROSTER_PATH']);valid=p.read_bytes();p.unlink()
        self.run_pane(NOTICE,expect=1);self.assertEqual(self.keys(),[])
        p.write_bytes(valid);self.run_pane(NOTICE);self.assertEqual(self.keys(),[])
        self.run_pane(NOTICE);self.assertEqual(len(self.keys()),1)
    def test_wall_clock_jump_does_not_shorten_interval(self):
        self.env['UNSTICK_TEST_MONO']='1000';self.run_pane(NOTICE)
        self.now=2000;self.env['UNSTICK_TEST_MONO']='1001';self.run_pane(NOTICE);self.assertEqual(self.keys(),[])
        self.env['UNSTICK_TEST_MONO']='1080';self.run_pane(NOTICE);self.assertEqual(len(self.keys()),1)
    def test_clock_backwards_resets_stability(self):
        self.run_pane(NOTICE);self.now=900;self.run_pane(NOTICE);self.assertEqual(self.keys(),[])

    def test_native_clock_two_processes_both_python_versions(self):
        module_path=str(SCRIPT.with_name('agentstack_unstick_seats.py'))
        code="import importlib.util,json,os,sys,time; s=importlib.util.spec_from_file_location('native_watchdog',"+repr(module_path)+"); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); w=object.__new__(m.Watchdog); w.test=False; print(json.dumps({'pid':os.getpid(),'version':list(sys.version_info[:3]),'value':w.monotonic(),'uptime':time.clock_gettime(time.CLOCK_UPTIME_RAW)}))"
        evidence=[]
        for executable,version in [('/usr/bin/python3',[3,9,6]),('/opt/homebrew/bin/python3',[3,14,7])]:
            samples=[]
            for _ in range(2):
                child=subprocess.run([executable,'-c',code],capture_output=True,text=True)
                self.assertEqual(child.returncode,0,child.stderr);sample=json.loads(child.stdout)
                self.assertEqual(sample['version'],version)
                self.assertLess(abs(sample['value']-sample['uptime']),1)
                samples.append(sample);time.sleep(0.15)
            self.assertNotEqual(samples[0]['pid'],samples[1]['pid'])
            self.assertGreater(samples[1]['value'],samples[0]['value'])
            evidence.append({'executable':executable,'samples':samples})
        print('NATIVE_CLOCK '+json.dumps(evidence),file=sys.stderr,flush=True)

    def test_native_processes_real_eighty_second_gate(self):
        # Actual /usr/bin/python3 processes and native wall/uptime clocks.
        # Only tmux/ps are fake; no UNSTICK_TEST_NOW or TEST_MONO is supplied.
        (self.root/'fixture.json').write_text(json.dumps({'pane':NOTICE,'kind':'codex'}))
        env=dict(self.env)
        for name in ['UNSTICK_TEST_NOW','UNSTICK_TEST_MONO']:env.pop(name,None)
        def invoke():
            child=subprocess.run(['/usr/bin/python3',str(SCRIPT.with_name('agentstack_unstick_seats.py'))],env=env,capture_output=True,text=True)
            self.assertEqual(child.returncode,0,child.stderr)
        start=time.clock_gettime(time.CLOCK_UPTIME_RAW)
        invoke();state=next((self.root/'.agentstack/runtime/unstick-state-v2/live').glob('*.json'))
        first=json.loads(state.read_text())
        self.assertEqual(first.get('clock_source'),'uptime-raw-v1')
        self.assertLess(abs(first['first_seen_mono']-time.clock_gettime(time.CLOCK_UPTIME_RAW)),2)
        self.assertEqual(self.keys(),[])
        invoke();self.assertEqual(self.keys(),[])
        time.sleep(81)
        invoke();self.assertEqual(len(self.keys()),1)
        elapsed=time.clock_gettime(time.CLOCK_UPTIME_RAW)-start
        self.assertGreaterEqual(elapsed,80)
        sessions=[x for x in self.events() if x['event']=='session']
        self.assertEqual([x['branch'] for x in sessions],['first-seen','too-soon','sent'])
        self.assertEqual(len({x['run_id'] for x in sessions}),3)
        print('NATIVE_GATE '+json.dumps({'executable':'/usr/bin/python3','elapsed':elapsed,'decisions':[x['branch'] for x in sessions],'run_ids':[x['run_id'] for x in sessions],'fake_keys':len(self.keys())}),file=sys.stderr,flush=True)

    def test_legacy_clock_state_restarts_stability(self):
        self.run_pane(NOTICE)
        p=next((self.root/'.agentstack/runtime/unstick-state-v2/live').glob('*.json'))
        state=json.loads(p.read_text());state.pop('clock_source',None);state['first_seen_mono']=0.1;p.write_text(json.dumps(state))
        self.run_pane(NOTICE);self.assertEqual(self.keys(),[])
        self.run_pane(NOTICE);self.assertEqual(len(self.keys()),1)

    def test_live_permanent_log_critical_only_and_diagnostics_bounded(self):
        spec=importlib.util.spec_from_file_location('live_log_candidate',SCRIPT.with_name('agentstack_unstick_seats.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with patch.dict(os.environ,self.env,clear=True):
            w=module.Watchdog();w.log.write_text('protected record\n')
            for i in range(1400):w.record('session',session='FixtureSeat',branch='empty-composer',detail='x'*100,index=i)
            w.record('scan');w.record('info',reason='no-tmux-server')
            self.assertEqual(w.log.read_text(),'protected record\n')
            for event in ['sent','send-failed','changed-before-send']:w.record(event,session='FixtureSeat')
            w.error('controlled test failure')
            self.assertEqual([json.loads(x)['event'] for x in w.log.read_text().splitlines()[1:]],['sent','send-failed','changed-before-send','error'])
            diag=w.runtime/'unstick-seats.live-diagnostics.log'
            self.assertLessEqual(diag.stat().st_size,65536);self.assertLessEqual(diag.with_name(diag.name+'.previous').stat().st_size,65536)
            self.assertEqual(len(w.err.read_text().splitlines()),1)

    def test_send_failure_has_permanent_audit(self):
        self.run_pane(NOTICE,send_exit=1);self.run_pane(NOTICE,send_exit=1);self.assertEqual(self.keys(),[])
        p=self.root/'.agentstack/runtime/unstick-seats.log'
        records=[json.loads(x) for x in p.read_text().splitlines()]
        self.assertEqual([x['event'] for x in records],['send-failed','error'])
        for key in ['session','branch','composer_sha256','pane_tail_sha256']:self.assertTrue(records[0][key])

if __name__=='__main__':unittest.main(verbosity=2)

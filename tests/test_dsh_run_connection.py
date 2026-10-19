"""Offline product-bound lifecycle controls; no real registration or Mail.

ORRERY_DSH_TEST_BACKEND selects strata (default) or deepseek for the real TUI fixture.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import sys


INTEGRATION = Path(__file__).resolve().parents[1] / 'integrations/dsh'
spec = importlib.util.spec_from_file_location('dsh_mail_lifecycle', INTEGRATION / 'mail_lifecycle.py')
lifecycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lifecycle)


class ProductLifecycle(unittest.TestCase):
    def test_stop_from_japanese_locale_matches_c_locale_supervisor_start(self):
        sys.path.insert(0,str(INTEGRATION))
        try:
            import launch
        finally:
            sys.path.remove(str(INTEGRATION))
        lifecycle.save(self.root/'attempt.json',{'attempt_id':'attempt'})
        lifecycle.save(self.root/'runtime-process.json',{'attempt_id':'attempt',
            'supervisor_pid':4242,'pgid':4243,'supervisor_started':'Mon Oct 19 15:15:26 2026'})
        def ps(argv,**options):
            self.assertEqual(argv,['/bin/ps','-p','4242','-o','lstart='])
            locale=options.get('env',os.environ).get('LC_ALL')
            return subprocess.CompletedProcess(argv,0,
                'Mon Oct 19 15:15:26 2026\n' if locale=='C' else '月 10/19 15:15:26 2026\n','')
        def stopped(pid,sig):
            lifecycle.save(self.root/'runtime-exit.json',{'group_absent':True,'group_check':'observed'})
        with mock.patch.dict(os.environ,{'LC_ALL':'ja_JP.UTF-8','LANG':'ja_JP.UTF-8'}), \
             mock.patch.object(launch.subprocess,'run',side_effect=ps), \
             mock.patch.object(launch.os,'kill',side_effect=stopped) as terminate, \
             mock.patch.object(launch,'group_absent',return_value=True):
            launch.stop_run(self.root)
        import signal
        terminate.assert_called_once_with(4242,signal.SIGTERM)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dsh-run-connection-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.product = self.root / 'product'
        for file in ['bin/agentstack-runtime-client', 'bin/agentstack-preregister-child',
                     'hooks/child_tools.py', 'integrations/codex_app/plugin/scripts/run-mcp.sh']:
            target = self.product / file
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch(mode=0o700)
        self.config = dict(product_root=str(self.product), project_key='/fixture/project',
            home=str(self.root), node='/fixture/node', proxy_python='/fixture/python',
            parent='FixtureParent', model='fixture-model', worktree=str(self.root),
            connection=dict(runtime_dir=str(self.root / 'runtime'), mcp_url='http://127.0.0.1:1/mcp',
                            mail_env=str(self.root / 'not-read.env'), bearer_mode='auto'))
        lifecycle.save(self.root / 'run-config.json', self.config)
        self.calls = []

    def fake_product(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        self.assertNotIn('DEEPSEEK_API_KEY', kwargs['env'])
        if argv[0].endswith('/agentstack-runtime-client'):
            return subprocess.CompletedProcess(argv, 0, 'legacy\n', '')
        if argv[0].endswith('/agentstack-preregister-child'):
            handoff = Path(argv[argv.index('--token-file-out') + 1])
            handoff.touch(mode=0o600)
            return subprocess.CompletedProcess(argv, 0, 'FixtureChild\n', '')
        if 'claude-config' in argv:
            def arg(name):
                return argv[argv.index(name) + 1]
            proxy = dict(command=arg('--runner'), args=[], env={
                'AGENTSTACK_PROXY_AGENT_NAME': arg('--child'),
                'AGENTSTACK_PROXY_TOKEN_FILE': arg('--token-file'),
                'AGENTSTACK_PROXY_PROGRAM': 'claude-code',
                'AGENTSTACK_PROJECT_KEY': arg('--project-key')})
            lifecycle.save(Path(arg('--out')), {'mcpServers': {'orrery-mail': proxy}})
        return subprocess.CompletedProcess(argv, 0, '', '')

    def test_registration_uses_generated_proxy_unchanged_and_no_retry(self):
        self.assertEqual(lifecycle.register(self.root, self.fake_product), 'FixtureChild')
        config = lifecycle.read(self.root / 'mcp.json')['mcpServers']['orrery-mail']
        actual = lifecycle.read(self.root / 'mail.patch.json')[0]['insert'][0]['config']
        for key in ('command', 'args', 'env'):
            self.assertEqual(actual[key], config[key])
        self.assertEqual(actual['env']['AGENTSTACK_PROXY_PROGRAM'], 'claude-code')
        with self.assertRaises(ValueError):
            lifecycle.register(self.root, self.fake_product)
        self.assertEqual(sum('/agentstack-preregister-child' in call[0][0] for call in self.calls), 1)

    def test_failed_helper_preserves_intent_and_blocks_second_registration(self):
        def failed(argv, **kwargs):
            if argv[0].endswith('/agentstack-preregister-child'):
                return subprocess.CompletedProcess(argv, 1, '', '')
            return self.fake_product(argv, **kwargs)
        with self.assertRaises(ValueError):
            lifecycle.register(self.root, failed)
        self.assertTrue((self.root / 'registration-intent.json').exists())
        with self.assertRaises(FileExistsError):
            lifecycle.register(self.root, self.fake_product)

    def test_unexpected_mode_stops_before_registration_intent(self):
        def global_mode(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, 'global\n', '')
        with self.assertRaises(ValueError):
            lifecycle.register(self.root, global_mode)
        self.assertFalse((self.root / 'registration-intent.json').exists())

    def test_cleanup_exit_zero_is_still_unconfirmed(self):
        lifecycle.register(self.root, self.fake_product)
        lifecycle.save(self.root / 'attempt.json', {'agent_name': 'FixtureChild', 'attempt_id': 'attempt'})
        lifecycle.save(self.root / 'runtime-exit.json', {'group_absent': True, 'group_check': 'observed'})
        lifecycle.save(self.root / 'release-receipt.json', {'agent_name': 'FixtureChild', 'attempt_id': 'attempt', 'confirmed': True, 'source':'product-bound-proxy'})
        receipt = lifecycle.retire(self.root, self.fake_product)
        self.assertEqual(receipt['cleanup_exit_code'], 0)
        self.assertIsNone(receipt['retired_at'])
        self.assertIs(receipt['confirmed'], False)
        lifecycle.save(self.root / 'runtime-exit.json', {'group_absent': False, 'group_check': 'unknown'})
        with self.assertRaises(ValueError):
            lifecycle.retire(self.root, self.fake_product)

    def test_partial_registration_can_retire_without_fabricated_reservation(self):
        lifecycle.register(self.root,self.fake_product)
        lifecycle.save(self.root/'attempt.json',{'agent_name':'FixtureChild','attempt_id':'attempt'})
        lifecycle.save(self.root/'runtime-exit.json',{'group_absent':True,'group_check':'observed','runtime_not_started':True})
        self.assertIs(lifecycle.retire(self.root,self.fake_product)['confirmed'],False)
        lifecycle.save(self.root/'reservation-intent.json',{'paths':['one.txt']})
        with self.assertRaises(ValueError):
            lifecycle.retire(self.root,self.fake_product)

    def test_unsupported_credential_adapter_never_invokes_helper(self):
        sys.path.insert(0,str(INTEGRATION))
        try:
            import launch
        finally:
            sys.path.remove(str(INTEGRATION))
        with mock.patch.object(launch.sys,'platform','linux'), mock.patch.object(launch.subprocess,'run') as helper:
            with self.assertRaisesRegex(ValueError,'not implemented'):
                launch.credential({})
            helper.assert_not_called()

    def test_parent_inbox_record_requires_same_attempt_actual_message(self):
        lifecycle.save(self.root/'attempt.json',{'attempt_id':'attempt','agent_name':'FixtureChild'})
        lifecycle.save(self.root/'task.json',{'attempt_id':'attempt','task_id':'task','report_to':'FixtureParent'})
        event={'phase':'mail-sent','attempt_id':'attempt','task_id':'task','message_id':42,
               'from':'FixtureChild','to':'FixtureParent','verified_sender':True,'ok':True}
        (self.root/'events.jsonl').write_text(json.dumps(event)+'\n')
        capture=self.root/'inbox.json'
        message={'id':42,'project_id':1,'sender_id':1,'thread_id':None,'topic':None,
                 'subject':'fixture','importance':'high','ack_required':False,
                 'created_ts':'2026-10-19T06:00:00Z','attachments':[],
                 'body_md':'Not copied into receipt','from':'FixtureChild','kind':'to'}
        lifecycle.save(capture,{'result':[message]})
        with mock.patch.object(lifecycle.subprocess,'run',side_effect=AssertionError('No RPC')):
            receipt=lifecycle.record_mail(self.root,capture)
        self.assertEqual(receipt['message_id'],42)
        self.assertNotIn('body_md',receipt)
        for wrong in ({**message,'id':43},{**message,'from':'Other'}, {**message,'kind':'cc'},
                      {**message,'to':['FixtureParent']}):
            lifecycle.save(capture,{'result':[wrong]})
            with self.assertRaises(ValueError):
                lifecycle.record_mail(self.root,capture)
        lifecycle.save(capture,{'result':[message]})
        event['attempt_id']='old'
        (self.root/'events.jsonl').write_text(json.dumps(event)+'\n')
        with self.assertRaises(ValueError):
            lifecycle.record_mail(self.root,capture)

    def test_parent_whois_confirms_same_child_after_real_cleanup_receipt(self):
        lifecycle.save(self.root/'attempt.json',{'attempt_id':'attempt','agent_name':'FixtureChild'})
        lifecycle.save(self.root/'retire-receipt.json',{'attempt_id':'attempt','agent_name':'FixtureChild',
            'cleanup_exit_code':0,'retired_at':None,'confirmed':False,'source':'parent-bound-whois','checked_at':None})
        capture=self.root/'whois.json'
        for profile in ({'name':'Other','retired_at':'2026-10-19T06:00:00Z'},
                        {'name':'FixtureChild','retired_at':None}):
            lifecycle.save(capture,profile)
            with self.assertRaises(ValueError):
                lifecycle.confirm_retire(self.root,capture)
            self.assertIs(lifecycle.read(self.root/'retire-receipt.json')['confirmed'],False)
        lifecycle.save(capture,{'structuredContent':{'name':'FixtureChild','retired_at':'2026-10-19T06:00:00Z'}})
        with mock.patch.object(lifecycle.subprocess,'run',side_effect=AssertionError('No RPC')):
            receipt=lifecycle.confirm_retire(self.root,capture)
        self.assertIs(receipt['confirmed'],True)
        self.assertEqual(receipt['cleanup_exit_code'],0)
        self.assertEqual(receipt['retired_at'],'2026-10-19T06:00:00Z')
        with self.assertRaises(ValueError):
            lifecycle.capture_value({'isError':True,'structuredContent':{}})

    def test_mail_receipt_controls(self):
        node = os.environ.get('ORRERY_DSH_TEST_NODE')
        if not node:
            self.skipTest('explicit fixed Node required')
        code = r'''
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {checkBinding,normalizeReservations,releaseReceipt}=await import(pathToFileURL(process.argv[1]));
const identity={agent_name:'Child',project_key:'/fixture',program:'dsh',parent:'Parent'};
const proxy={env:{AGENTSTACK_PROXY_PROGRAM:'claude-code'}};
const status={agent_name:'Child',project_key:'/fixture',program:'claude-code',lineage:{parent_agent:'Parent'}};
const who={name:'Child',program:'dsh',retired_at:null};
checkBinding(status,who,identity,proxy);
assert.throws(()=>checkBinding({...status,agent_name:'Other'},who,identity,proxy));
assert.throws(()=>checkBinding(status,{...who,retired_at:'now'},identity,proxy));
const row={id:1,path_pattern:'one.txt',expires_ts:new Date(Date.now()+1800000).toISOString()};
assert.equal(normalizeReservations({granted:[row]},['one.txt'],'Child')[0].owner,'Child');
assert.throws(()=>normalizeReservations({granted:[row],conflicts:[{}]},['one.txt'],'Child'));
assert.throws(()=>normalizeReservations({granted:[]},['one.txt'],'Child'));
assert.throws(()=>normalizeReservations({granted:[{...row,expires_ts:'2000-01-01'}]},['one.txt'],'Child'));
const attempt={attempt_id:'attempt',agent_name:'Child'};
assert.equal(releaseReceipt({attempt,ids:[1],result:{released:1}}).confirmed,true);
assert.equal(releaseReceipt({attempt,ids:[1],result:{released:0}}).confirmed,false);
assert.equal(releaseReceipt({attempt,ids:[],result:{released:0}}).confirmed,true);
'''
        result = subprocess.run([node, '--input-type=module', '-e', code, str(INTEGRATION / 'mail_probe.mjs')],
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_keyless_full_preflight_with_real_tui_and_synthetic_stdio_server(self):
        node, runtime = os.environ.get('ORRERY_DSH_TEST_NODE'), os.environ.get('ORRERY_DSH_TEST_RUNTIME')
        if not node or not runtime:
            self.skipTest('explicit isolated fixed Node/runtime required')
        # This server is a test fixture, not a proxy: no sockets/HTTP/forwarding,
        # tokens, registration or actual Mail. The real SDK/TUI use its stdio.
        server = self.root / 'fixture-server.py'
        server.write_text('''import sys,json,os,datetime
names=['runtime_status','whois','send_message','fetch_inbox','reserve_files','renew_reservations','release_reservations']
for line in sys.stdin:
 try:
  q=json.loads(line)
  if 'id' not in q: continue
  method=q['method']; params=q.get('params',{})
  if method=='initialize':
   r={'protocolVersion':params['protocolVersion'],'capabilities':{'tools':{}},'serverInfo':{'name':'explicit-offline-fixture','version':'1'}}
  elif method=='tools/list':
   r={'tools':[{'name':n,'description':'Offline synthetic fixture','inputSchema':{'type':'object','properties':{'to':{'type':'array','items':{'type':'string'}},'subject':{'type':'string'},'body_md':{'type':'string'}} if n=='send_message' else {}}} for n in names]}
  elif method=='tools/call':
   name=params['name']; args=params.get('arguments',{})
   if name=='whois' and ':1/' in os.environ['AGENTSTACK_MCP_URL']:
    r={'isError':True,'content':[{'type':'text','text':'offline backend-down fixture'}]}
   else:
    if name=='runtime_status': value={'agent_name':'FixtureChild','project_key':'/fixture/project','program':'claude-code','lineage':{'parent_agent':os.environ.get('AGENTSTACK_PROXY_PARENT_AGENT','FixtureParent')}}
    elif name=='whois': value={'name':'FixtureChild','program':'dsh','retired_at':None}
    elif name=='reserve_files': value={'granted':[{'id':i+1,'path_pattern':p,'expires_ts':(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=1800)).isoformat()} for i,p in enumerate(args['paths'])],'conflicts':[]}
    elif name=='release_reservations': value={'released':len(args['file_reservation_ids'])}
    else: value={'not_real_mail':True}
    r={'content':[{'type':'text','text':json.dumps(value)}],'structuredContent':value}
  else: r={}
  print(json.dumps({'jsonrpc':'2.0','id':q['id'],'result':r}),flush=True)
 except Exception:
  sys.exit(2)
''')
        home = self.root / 'home'
        home.mkdir()
        product = home / '.agentstack'
        proxy = product / 'integrations/codex_app/plugin/scripts/run-mcp.sh'
        proxy.parent.mkdir(parents=True)
        import shlex
        proxy.write_text('#!/bin/sh\nexec ' + shlex.join([sys.executable, str(server)]) + '\n')
        proxy.chmod(0o700)
        for file in ('hooks/child_tools.py', 'hooks/cleanup-child-agent.sh'):
            target = product / file
            target.parent.mkdir(exist_ok=True, parents=True)
            target.write_text('# Explicit offline fixture\n')
        backend = self.root / 'backend.json'
        spec = json.loads((INTEGRATION / 'backend.json').read_text())
        backend_id = os.environ.get('ORRERY_DSH_TEST_BACKEND','strata')
        self.assertIn(backend_id,('strata','deepseek'))
        selected_backend = spec['backends'][backend_id]
        # Keep the actual template's model/definition/effort/idle policy unchanged.
        # Only the address is synthetic; egress must stop before any socket.
        selected_backend['base_url'] = ('https://deepseek.invalid/anthropic' if backend_id == 'deepseek'
                                        else 'https://strata.invalid')
        backend.write_text(json.dumps(spec))
        work = self.root / 'work'
        work.mkdir()
        receipt = Path(runtime).parent / 'evidence/tui-patch-applied.json'
        config = dict(node=node,runtime=runtime,worktree=str(work),backend_file=str(backend),backend_id=backend_id,
            patch_receipt=str(receipt),home=str(home),product_root=str(product),project_key='/fixture/project',
            proxy_python=sys.executable,parent='FixtureParent',connection={
                'mcp_url':'http://127.0.0.1:9999/mcp','runtime_dir':str(self.root/'runtime-state'),
                'mail_env':str(self.root/'never-open.env'),'bearer_mode':'auto'},
            task={'prompt':f'Write {backend_id}-first-ok into trial-ok.txt and report to the parent.',
                  'allowed_paths':['trial-ok.txt'],'expected':[{'path':'trial-ok.txt','contains':f'{backend_id}-first-ok'}]})
        interactive = os.environ.get('ORRERY_DSH_TEST_INTERACTIVE') == '1'
        if interactive:
            config.update(parent=None, task={'prompt': '', 'task_mode': 'conversation', 'report_policy': 'pane',
                                            'allowed_paths': [], 'expected': []})
        config_file = self.root / 'init.json'
        config_file.write_text(json.dumps(config))
        sys.path.insert(0,str(INTEGRATION))
        self.addCleanup(lambda: sys.path.remove(str(INTEGRATION)))
        import launch
        import preflight
        # Synthetic/offline controls must reach their intended seam even when
        # the machine is busy. The production launch load gate stays intact.
        state = self.root / 'attempt'
        with mock.patch.dict(os.environ,{'HOME':str(home)}):
            launch.init_run(config_file,state)
        identity = {'agent_name':'FixtureChild','program':'dsh','project_key':'/fixture/project','parent':config['parent']}
        lifecycle.save(state/'mail-identity.json',identity)
        proxy_config = {'command':str(proxy),'args':[], 'env':{
            'AGENTSTACK_PROXY_PROGRAM':'claude-code','AGENTSTACK_PROXY_AGENT_NAME':'FixtureChild',
            'AGENTSTACK_PROJECT_KEY':'/fixture/project','AGENTSTACK_MCP_URL':'http://127.0.0.1:9999/mcp',
            'AGENTSTACK_PROXY_PARENT_AGENT': config['parent'] or ''}}
        lifecycle.save(state/'mcp.json',{'mcpServers':{'orrery-mail':proxy_config}})
        lifecycle.save(state/'mail.patch.json',[{'insert':[{'id':'orrery-mail','name':'@deepseek-ai/dsh-mcp-client',
            'config':{'serverName':'orrery_mail','transport':'stdio',**proxy_config,
                      'cwd':str(work),'failOnStartupError':True,'reconnect':{'enabled':False}}}]}])
        try:
            proof = preflight.full(state, offline_check=not interactive)
        except Exception:
            evidence = os.environ.get('ORRERY_DSH_TEST_EVIDENCE')
            if evidence:
                import shutil
                shutil.copytree(state, Path(evidence) / ('failed-preflight-' + self.root.name), symlinks=True)
            raise
        self.assertTrue(proof['ok'])
        self.assertEqual(proof['forwarded_requests'],0)
        if interactive:
            self.exercise_native_two_turns(state, launch, backend, config)
            return
        evidence = os.environ.get('ORRERY_DSH_TEST_EVIDENCE')
        if evidence:
            import shutil
            destination = Path(evidence) / ('passed-preflight-' + self.root.name)
            shutil.copytree(state,destination,symlinks=True)
            lifecycle.save(Path(evidence)/'verification.json',{
                'fixture':'synthetic stdio server, no backend sockets or registration',
                'evidence_directory':str(destination),
                'actual_sdk':True,'actual_tui':True,'actual_tools':proof['actual_tools'],
                'backend_id':backend_id,'model':selected_backend['model'],
                'model_definition':selected_backend['model_definition'],
                'idle_check':selected_backend['idle_check'],
                'forwarded_requests':0,'schema_and_backend_negative_controls':True,
                'dummy_value_file_hits':sum(b'offline-dummy' in p.read_bytes()
                    for p in state.rglob('*') if p.is_file() and not p.is_symlink()
                    and 'node_modules' not in p.parts),
                'real_mail':False,'real_credentials':False})
        preflight.verify(state)
        with mock.patch.object(launch,'credential',side_effect=AssertionError('Must not read a credential')):
            # Changed inputs are refused before the credential seam is reached.
            task = lifecycle.read(state/'task.json')
            task['prompt'] += ' changed'
            lifecycle.save(state/'task.json',task)
            with self.assertRaises((ValueError,subprocess.CalledProcessError)):
                launch.execute_run(state)
        task['prompt'] = config['task']['prompt']
        lifecycle.save(state/'task.json',task)
        preflight.verify(state)
        aid=lifecycle.read(state/'attempt.json')['attempt_id']
        lifecycle.save(state/'owned-pane.json',{'attempt_id':aid,'pane_id':'%fixture','session':'fixture'})
        with mock.patch.dict(os.environ,{'TMUX_PANE':'%other'}), \
             mock.patch.object(launch,'credential',side_effect=AssertionError('Wrong pane must not read key')):
            with self.assertRaisesRegex(ValueError,'owned pane'):
                launch.execute_run(state)
        self.assertFalse((state/'run-started.json').exists())
        # Exercise the final credential seam and env handoff with no real key
        # and no runtime spawn. The real SDK probe still uses synthetic stdio.
        from types import SimpleNamespace
        captured = []
        child = SimpleNamespace(pid=999999,returncode=0,poll=lambda:0)
        def fake_spawn(argv,**options):
            captured.append(dict(options['env']))
            return child
        with mock.patch.object(launch,'credential',return_value='fixture-only-key') as key, \
             mock.patch.object(launch.subprocess,'Popen',side_effect=fake_spawn), \
             mock.patch.object(launch,'stop_owned_group',return_value=True), \
             mock.patch.object(launch,'run_config',return_value=lifecycle.read(state/'run-config.json')), \
             mock.patch.dict(os.environ,{'TMUX_PANE':'%fixture'}):
            # Popen is shared by subprocess helpers: isolate only the final
            # runtime handoff after keyless gate/probe have already passed.
            with mock.patch.object(launch,'call_mail'), \
                 mock.patch.object(launch,'check_preflight'), \
                 mock.patch.object(launch.subprocess,'check_output',return_value='v24.3.0'):
                self.assertEqual(launch.execute_run(state),0)
            self.assertEqual(key.call_count,1)
        self.assertEqual(captured[0]['DEEPSEEK_API_KEY'],'fixture-only-key')
        self.assertEqual(captured[0]['ORRERY_DSH_OFFLINE'],'0')
        with mock.patch.object(launch,'credential',side_effect=AssertionError('No second lookup')):
            with self.assertRaises((ValueError,subprocess.CalledProcessError)):
                launch.execute_run(state)
        self.assertFalse((work/'trial-ok.txt').exists())

    def test_keyless_two_turn_native_tui(self):
        with mock.patch.dict(os.environ, {'ORRERY_DSH_TEST_INTERACTIVE': '1'}):
            self.test_keyless_full_preflight_with_real_tui_and_synthetic_stdio_server()

    def exercise_native_two_turns(self, state, launch, backend_file, config):
        # Real pinned TUI, real generated stdio SDK transport, in-memory provider.
        # The fixture replaces fetch only in this dedicated test process.
        import pty, select, signal, time, fcntl, termios, struct
        shim = self.root / 'fixture-egress.mjs'
        shim.write_text('''import fs from 'node:fs'; import {pathToFileURL} from 'node:url';
const {createEgress}=await import(pathToFileURL(process.env.FIXTURE_EGRESS));
const spec=JSON.parse(fs.readFileSync(process.env.ORRERY_DSH_BACKEND_FILE));
const backend=spec.backends[process.env.ORRERY_DSH_BACKEND_ID];
const aid=process.env.ORRERY_DSH_ATTEMPT_ID;
const audit=e=>fs.appendFileSync(process.env.ORRERY_DSH_AUDIT_FILE,
 JSON.stringify({...e,attempt_id:aid,at:new Date().toISOString()})+'\\n');
const wire=JSON.parse(fs.readFileSync(process.env.ORRERY_DSH_STATE_ROOT+'/wire-tools.json'));
let seq=0;
const {EventEmitter}=await import(pathToFileURL(process.env.ORRERY_DSH_RUNTIME_ROOT+
 '/node_modules/@deepseek-harness-tui/dsh-tui/lib/types/ink/events/emitter.js'));
for(const method of ['on','prependListener']){
 const original=EventEmitter.prototype[method];
 EventEmitter.prototype[method]=function(type,...args){
  const result=original.call(this,type,...args);
  if(type==='input')setTimeout(()=>{
   if(this.listenerCount('input')>0 && process.stdin.isRaw)
    fs.writeFileSync(process.env.ORRERY_DSH_STATE_ROOT+'/fixture-input-ready.json',
     JSON.stringify({raw:true,input_handlers:this.listenerCount('input')}));
  },250).unref();
  return result;
 };
}
globalThis.fetch=createEgress({backend,limits:spec.limits,wireTools:wire.tools,offline:false,
 audit,key:process.env.DEEPSEEK_API_KEY,fetchImpl:async url=>{
 if(String(url).endsWith('/v1/status'))return new Response('{"activity":{"in_flight":0}}');
 const events=[{type:'message_start',message:{id:'fixture-'+(++seq),type:'message',role:'assistant',
  model:backend.model,content:[],usage:{input_tokens:10,cache_read_input_tokens:0,output_tokens:0}}},
  {type:'content_block_start',index:0,content_block:{type:'text',text:''}},
  {type:'content_block_delta',index:0,delta:{type:'text_delta',text:'Offline fixture response '+seq}},
  {type:'content_block_stop',index:0},
  {type:'message_delta',delta:{stop_reason:'end_turn',stop_sequence:null},usage:{output_tokens:4}},
  {type:'message_stop'}];
 return new Response(events.map(e=>'event: '+e.type+'\\ndata: '+JSON.stringify(e)+'\\n\\n').join(''),
  {headers:{'content-type':'text/event-stream'}});
}});
''')
        plan = launch.plan_run(state, offline=False)
        env = {**plan['env'], 'DEEPSEEK_API_KEY': 'fixture-native-secret-value',
               'FIXTURE_EGRESS': str(INTEGRATION / 'egress.mjs')}
        argv = [config['node'], '--import', str(shim), str(INTEGRATION / 'managed_entry.mjs')]
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 100, 0, 0))
        process = subprocess.Popen(argv, env=env, cwd=config['worktree'], stdin=slave,
                                   stdout=slave, stderr=slave, start_new_session=True)
        os.close(slave)
        lifecycle.save(state / 'runtime-process.json', {'attempt_id': lifecycle.read(state / 'attempt.json')['attempt_id'],
                                                      'pid': process.pid, 'pgid': process.pid})
        transcript = bytearray()
        def rows(name):
            p = state / name
            if not p.exists(): return []
            return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
        def wait_for(predicate, seconds=90):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if select.select([master], [], [], .1)[0]:
                    try: transcript.extend(os.read(master, 65536))
                    except OSError: pass
                if predicate(): return
                self.assertIsNone(process.poll(), transcript.decode(errors='replace')[-2000:])
            self.fail('Native TUI fixture timeout: '+transcript.decode(errors='replace')[-1200:])
        try:
            wait_for(lambda: (state / 'fixture-input-ready.json').exists() and
                     any(row.get('phase') == 'plugin-ready' for row in rows('events.jsonl')))
            self.assertFalse(any(row.get('phase') == 'provider-request-start' for row in rows('audit.jsonl')))
            for turn in (1, 2):
                os.write(master, ('\x1b[200~fixture question '+str(turn)+'\x1b[201~').encode())
                time.sleep(.2)  # Separate native paste and Enter input events.
                os.write(master, b'\r')
                wait_for(lambda: sum(row.get('phase') == 'turn-end' for row in rows('events.jsonl')) >= turn)
                self.assertIsNone(process.poll())
                completed = [row for row in rows('events.jsonl') if row.get('phase') == 'turn-end']
                self.assertEqual(completed[-1]['reason_kind'], 'completed')
            audit = rows('audit.jsonl')
            requests = [row for row in audit if row.get('phase') == 'provider-request-start']
            self.assertEqual(len(requests), 2)
            self.assertEqual(len([row for row in audit if row.get('phase') == 'stream-end' and row.get('ok') is True]), 2)
            self.assertTrue(all(row.get('key_present') is False for row in audit if row.get('phase') == 'mcp-child-env'))
            self.assertFalse((state / 'credential-read.json').exists())
            from integrations.dsh import managed_lifecycle
            status = managed_lifecycle.status(state)
            self.assertTrue(status['ready']); self.assertFalse(status['terminal'])
            self.assertIsNone(status['task_success'])
            self.assertEqual(status['activity'], 'idle')
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=5)
            os.close(master)
            (state / 'native-fixture.tty').write_bytes(transcript)
            evidence = os.environ.get('ORRERY_DSH_TEST_EVIDENCE')
            if evidence:
                import shutil
                destination = Path(evidence) / ('native-two-turn-' + self.root.name)
                shutil.copytree(state, destination, symlinks=True)
                lifecycle.save(destination / 'fixture-result.json', {'native_exit': process.returncode,
                    'network_provider_requests': 0, 'provider': 'in-memory SSE only', 'real_mail': False,
                    'real_credentials': False, 'native_pid': process.pid})



class InteractivePreflightTests(unittest.TestCase):
    def test_normal_preflight_does_not_run_negative_controls_or_tui_assembly(self):
        sys.path.insert(0, str(INTEGRATION))
        try:
            import preflight
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            lifecycle.save(state / 'run-config.json', {'home': tmp, 'node': '/fixed/node', 'worktree': tmp})
            lifecycle.save(state / 'attempt.json', {'attempt_id': 'attempt', 'agent_name': 'Child'})
            lifecycle.save(state / 'task.json', {'attempt_id': 'attempt', 'task_mode': 'conversation', 'scope_mode': 'worktree'})
            actions = []
            def probe(state, action='probe', fixture=''):
                actions.append((action, fixture))
                lifecycle.save(state / 'wire-tools.json', {'tools': ['read', 'write', 'mcp__orrery_mail__fetch_inbox']})
            with mock.patch.object(preflight, 'run_probe', side_effect=probe), \
                 mock.patch.object(preflight, 'verify_reservations'), \
                 mock.patch.object(preflight, 'inputs', return_value=[]), \
                 mock.patch.object(preflight.subprocess, 'run') as subprocess_run:
                proof = preflight.full(state)
            self.assertTrue(proof['ok'])
            self.assertEqual(actions, [('probe', '')])
            self.assertEqual(subprocess_run.call_count, 2)  # Bind only.
            self.assertFalse(any('assemble' in c.args[0] for c in subprocess_run.call_args_list))
            self.assertEqual(lifecycle.read(state / 'reservations.json')['receipts'], [])

    def test_unset_effort_is_absent_from_all_three_runtime_projections(self):
        sys.path.insert(0, str(INTEGRATION))
        try:
            import launch
        finally:
            sys.path.pop(0)
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); runtime = root / 'runtime'; runtime.mkdir()
            for package, version in (('@deepseek-ai/dsh', '0.2.1-rc.2'), ('@deepseek-harness-tui/dsh-tui', '0.16.1')):
                target = runtime / 'node_modules' / package / 'package.json'
                target.parent.mkdir(parents=True); target.write_text(json.dumps({'version': version}))
            node = root / 'fixed-node'; node.write_text('fixture-node-bytes')
            backend = root / 'backends.json'
            backend.write_text(json.dumps({'backends': {'deepseek': {'base_url': 'https://fixture.invalid', 'model': 'fixture'}}}))
            args = SimpleNamespace(node=str(node), runtime=str(runtime), state=str(root / 'state'),
                worktree=str(root), backend_file=str(backend), backend='deepseek',
                patch_receipt=str(root / 'receipt.json'), guard_probe=False)
            with mock.patch.object(launch.subprocess, 'check_output', return_value='v24.3.0'):
                state, plan = launch.prepare(args)
            patches = lifecycle.read(state / 'selected.patch.json')
            for identifier in ('llm-deepseek', 'agent-default-model', 'dsh-tui'):
                config = next(row['config'] for row in patches if row.get('id') == identifier)
                self.assertNotIn('reasoningEffort', config)
                self.assertNotIn('effort', config)
            self.assertNotIn('maxTokens', next(row['config'] for row in patches if row.get('id') == 'llm-deepseek'))


if __name__ == '__main__':
    unittest.main()

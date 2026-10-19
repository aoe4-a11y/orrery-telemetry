"""Real pinned native CLI, with only the wire and product server replaced.

The fixture owns a temporary profile/PM selection and PTY. It denies socket
access and credential/install commands; no provider SDK or CLI result is faked.
"""
import hashlib
import json
import os
from pathlib import Path
import pty
import select
import shlex
import signal
import subprocess
import time

import mail_lifecycle
import runner


SERVER = '''from datetime import datetime,timedelta,timezone
from mcp.server import MCPServer
server=MCPServer('native-fixture')
@server.tool()
def fetch_inbox(): return []
@server.tool()
def send_message(to:list[str],subject:str,body_md:str): return {'fixture':True}
@server.tool()
def runtime_status(): return {'fixture':True}
@server.tool()
def whois(name:str): return {'fixture':True}
@server.tool()
def reserve_files(paths:list[str],ttl_seconds:int=1800,exclusive:bool=True,reason:str=''):
 return {'granted':[{'id':501,'owner':'FixtureChild','path_pattern':p,
  'expires_ts':(datetime.now(timezone.utc)+timedelta(seconds=1800)).isoformat()} for p in paths]}
@server.tool()
def release_reservations(file_reservation_ids:list[int]): return {'released':len(file_reservation_ids)}
server.run(transport='stdio')
'''

ENTRY = '''import sys,os,json,subprocess
from pathlib import Path
sys.path.insert(0,sys.argv[1])
state=Path(sys.argv[2]);config=json.loads((state/'run-config.json').read_text())
os.environ.update(HERMES_HOME=config['profile_home'],ORRERY_HERMES_STATE_ROOT=str(state),ORRERY_HERMES_ADAPTER_DIR=sys.argv[1])
def offline(name,args):
 if name in ('socket.connect','socket.getaddrinfo'): raise RuntimeError('offline native fixture')
 if name=='subprocess.Popen' and Path(str(args[0])).name in ('security','uv','pip','curl','wget'):
  raise RuntimeError('fixture forbids credential/install commands')
sys.addaudithook(offline)
import httpx
def payload(request):
 body=json.loads(request.content)
 tools=body.get('tools',[])
 messages=json.dumps(body.get('messages',[]))
 write=(any(t.get('name',t.get('function',{}).get('name'))=='write_file' for t in tools)
        and 'tool_result' not in messages and not any(m.get('role')=='tool' for m in body.get('messages',[])))
 if config['profiles'][config['profile_name']]['api_mode']=='chat_completions':
  data={'tool_calls':[{'index':0,'id':'write_native','type':'function','function':{'name':'write_file',
   'arguments':json.dumps({'path':str(Path(config['worktree'])/'native-result.txt'),'content':'native-done'})}}]} if write else {'content':'Native fixture response.'}
  base={'id':'chat_fixture','object':'chat.completion.chunk','created':0,'model':'fixture-model'}
  frames=[{**base,'choices':[{'index':0,'delta':{'role':'assistant',**data},'finish_reason':None}]},
   {**base,'choices':[{'index':0,'delta':{},'finish_reason':'tool_calls' if write else 'stop'}]},
   {**base,'choices':[],'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15,
    'prompt_tokens_details':{'cached_tokens':0}}}]
  return (''.join('data: '+json.dumps(row)+chr(10)+chr(10) for row in frames)+'data: [DONE]'+chr(10)+chr(10)).encode()
 content={'type':'tool_use','id':'write_native','name':'write_file','input':{}} if write else {'type':'text','text':''}
 delta={'type':'input_json_delta','partial_json':json.dumps({'path':str(Path(config['worktree'])/'native-result.txt'),
  'content':'native-done'})} if write else {'type':'text_delta','text':'Native fixture response.'}
 frames=[{'type':'message_start','message':{'id':'msg_fixture','type':'message','role':'assistant',
  'model':'fixture-model','content':[],'stop_reason':None,'stop_sequence':None,
  'usage':{'input_tokens':10,'output_tokens':0,'cache_read_input_tokens':0}}},
  {'type':'content_block_start','index':0,'content_block':content},
  {'type':'content_block_delta','index':0,'delta':delta},
  {'type':'content_block_stop','index':0},
  {'type':'message_delta','delta':{'stop_reason':'tool_use' if write else 'end_turn','stop_sequence':None},
   'usage':{'output_tokens':5}}, {'type':'message_stop'}]
 return ''.join('event: '+r['type']+chr(10)+'data: '+json.dumps(r)+chr(10)+chr(10) for r in frames).encode()
class Wire(httpx.SyncByteStream):
 def __init__(self,data): self.data=data
 def __iter__(self): yield self.data
class AsyncWire(httpx.AsyncByteStream):
 def __init__(self,data): self.data=data
 async def __aiter__(self): yield self.data
def response(client,req):
 return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Wire(payload(req)),request=req)
async def aresponse(client,req):
 return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=AsyncWire(payload(req)),request=req)
httpx.Client._send_single_request=response;httpx.AsyncClient._send_single_request=aresponse
import owned_credential,interactive
original=owned_credential.install
owned_credential.install=lambda state:original(state,run=lambda argv,**kwargs:
 subprocess.CompletedProcess(argv,0,bytes.fromhex('6e387252773851724c33584b73374e506b4c304d')))
original_activity=interactive.activity
count=0
def activity(state,value,**fields):
 global count
 result=original_activity(state,value,**fields)
 if value=='idle' and fields.get('latest_turn'):
  count+=1;print('FIXTURE_IDLE_'+str(count),flush=True)
 elif value=='idle': print('FIXTURE_READY',flush=True)
 return result
interactive.activity=activity
import managed_entry
raise SystemExit(managed_entry.execute(state))
'''

SUPERVISOR = '''import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import pane_entry,tty_runtime
original=tty_runtime.run
def injected(command,**kwargs):
 assert Path(command[3]).name=='managed_entry.py'
 return original([command[0],'-I','-B',sys.argv[3],sys.argv[1],sys.argv[2]],**kwargs)
tty_runtime.run=injected
raise SystemExit(pane_entry.execute(Path(sys.argv[2])))
'''


def run(fixture, adapter, source, python, *, empty=False, backend='strata', transport='anthropic_messages'):
    root = fixture.root
    config = runner.read(fixture.config_path)
    config.update(hermes_source=source, parent=None, credential_mode='owned-once')
    config['profiles'][backend].update(key_cmd='/usr/bin/security find-generic-password -s fixture-only -w',
                                       context_length=131072, api_mode=transport)
    fixture.install = Path(config['managed_root']) / 'installs' / hashlib.sha256(str(Path(source).resolve()).encode()).hexdigest()[:16]
    fixture.add_generation('native-fixture')
    environment = Path(runner.read(fixture.install / 'facts.json')['packages']['venv']['environment'])
    real = Path(python).parent.parent
    (environment / 'pyvenv.cfg').write_bytes((real / 'pyvenv.cfg').read_bytes())
    (environment / 'lib').mkdir()
    for path in (real / 'lib').glob('python*'):
        (environment / 'lib' / path.name).mkdir()
        (environment / 'lib' / path.name / 'site-packages').symlink_to(path / 'site-packages', target_is_directory=True)
    runner.save(fixture.config_path, config)
    state = root / 'native-state'
    task = {} if empty else {'task_mode': 'assignment', 'report_policy': 'pane', 'prompt': 'first fixture turn',
                            'expected': [{'path': 'native-result.txt', 'contains': 'native-done'}]}
    runner.initialize(fixture.config_path, state, backend, fixture.product.run, file_task=True, task_spec=task)
    config = runner.read(state / 'run-config.json')
    projection = subprocess.run([python, '-I', '-B', str(adapter / 'profile_projection.py'), '--spec',
        str(state / 'profile-spec.json'), '--profile', config['profile_home'], '--source', source],
        env=runner.base_env(config), capture_output=True, text=True, check=True, timeout=30)
    runner.save(state / 'profile-plan.json', json.loads(projection.stdout))
    mail_lifecycle.register(state, fixture.product.run, generate_config=False)
    runner.configure(state, fixture.product.run)
    config = runner.read(state / 'run-config.json')
    runner.save(state / 'mail-probe.json', {'schema': True, 'backend': True, 'ok': True,
        'agent_name': 'FixtureChild', 'tools': ['runtime_status', 'whois', 'fetch_inbox', 'send_message',
                                              'reserve_files', 'release_reservations']})
    server = root / 'fake_mcp.py'
    server.write_text(SERVER)
    proxy = fixture.product.product / 'integrations/codex_app/plugin/scripts/run-mcp.sh'
    proxy.write_text('#!/bin/sh\nexec ' + shlex.join([python, '-I', '-B', str(server)]) + '\n')
    proxy.chmod(0o700)
    entry = root / 'native_entry.py'
    entry.write_text(ENTRY)
    supervisor = root / 'native_supervisor.py'
    supervisor.write_text(SUPERVISOR)
    runner.save(state / 'start-intent.json', {'agent_name': 'FixtureChild'})
    master, slave = pty.openpty()
    child = subprocess.Popen([python, '-I', '-B', str(supervisor), str(adapter), str(state), str(entry)],
        stdin=slave, stdout=slave, stderr=slave, env=runner.base_env(config), cwd=config['worktree'], start_new_session=True)
    os.close(slave)
    received = b''
    snapshots = []
    try:
        steps = [(b'FIXTURE_IDLE_1', b'second fixture turn'), (b'FIXTURE_IDLE_2', b'/exit')]
        if empty:
            steps.insert(0, (b'FIXTURE_READY', b'first fixture turn'))
        for marker, text in steps:
            deadline = time.monotonic() + 45
            while marker not in received:
                if child.poll() is not None or time.monotonic() > deadline:
                    raise AssertionError('Native CLI did not finish turn: ' + repr(marker) + '\n' + received[-5000:].decode(errors='replace'))
                if select.select([master], [], [], .1)[0]:
                    received += os.read(master, 65536)
            snapshots.append(runner.read(state / 'activity.json'))
            # Native Enter distinguishes paste from key input by time interval.
            os.write(master, text)
            time.sleep(.2)
            os.write(master, b'\r')
        deadline = time.monotonic() + 15
        while child.poll() is None and time.monotonic() < deadline:
            if select.select([master], [], [], .1)[0]:
                try:
                    received += os.read(master, 65536)
                except OSError:
                    break
        if child.wait(timeout=5) != 0:
            raise AssertionError('Native CLI failed: ' + received[-5000:].decode(errors='replace'))
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        os.close(master)
        (root / 'native-output.log').write_bytes(received)
    return state, snapshots

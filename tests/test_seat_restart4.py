"""Production-shaped overlay probes; fake seats and isolated filesystem only."""
import asyncio
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import test_restart_identity as identity
import test_seat_lifecycle as lifecycle
from lifecycle_overlay import stage, wrapper
from schema_mail_fake import tool_schemas, validate_call

@pytest.fixture
def lane():
    value=lifecycle.LifecycleTests(); value.setUp()
    try: yield value
    finally: value.doCleanups()

@pytest.mark.parametrize('provider',['codex','claude'])
def test_partial_overlay_wrapper_keeps_canonical_home_and_general_hooks(lane,provider):
    seat=lane.arrange(); layout=stage(lane,seat)
    child=wrapper(lane,seat,layout,provider)
    assert child['AGENTSTACK_HOME']==str(layout['stack'])
    assert child['AGENTSTACK_HOOKS_DIR']==str(layout['hooks'])
    assert child['AGENTSTACK_LIFECYCLE_HOOKS_DIR']==str(layout['release'])
    for sibling in ('session-identity-policy.sh','release-file-reservation-worker.py','record-session-index.py'):
        assert (Path(child['AGENTSTACK_HOOKS_DIR'])/sibling).exists()
    if provider=='codex':
        assert child['CODEX_HOME']==str(seat['home'])
        config=(seat['home']/'config.toml').read_text()
    else:
        config=seat['config'].read_text()
        assert child['CLAUDE_CHILD_MCP_CONFIG']==str(seat['config'])
    assert str(layout['stack']/'integrations/codex_app/plugin/scripts/run-mcp.sh') in config
    assert identity.NAME in config
    assert not (layout['release'].parent/'integrations').exists()


def test_partial_overlay_authenticated_restart_refreshes_and_explicit_cleanup_preserves(lane):
    seat=lane.arrange(); layout=stage(lane,seat)
    old=wrapper(lane,seat,layout,'codex')
    before={k:seat[k].read_bytes() for k in ('token','state')}
    config=seat['home']/'config.toml'; original=config.read_bytes()
    record=seat['home']/'mail-receipt.json';record.write_text('permanent fixture')
    inode=seat['token'].stat().st_ino
    task=lane.base/'restart.md'; task.write_text('restart fixture')
    result=subprocess.run(['/bin/bash',str(layout['stack']/'bin/agentstack-restart-seat'),identity.NAME,str(task),'gpt-5.5','medium','/'],env=seat['env'],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    child=json.loads((lane.base/'tmux-verbs.env').read_text())
    assert child['AGENTSTACK_HOME']==str(layout['stack'])
    assert child['CODEX_HOME']==str(seat['home'])
    assert seat['token'].stat().st_ino==inode
    for k,b in before.items():assert seat[k].read_bytes()==b
    assert any(p.read_bytes()==original for p in (layout['runtime']/'seat-launches/config-backups').iterdir())
    # Name-only administration has no deletion authority; a lease in runtime
    # must select guarded even with no lifecycle environment.
    clean={k:v for k,v in seat['env'].items() if k not in ('AGENTSTACK_LAUNCH_JOURNAL','AGENTSTACK_LIFECYCLE_NAME','AGENTSTACK_LIFECYCLE_HOOKS_DIR')}
    owner=lifecycle.Seat(layout['runtime'],identity.NAME)
    with owner.locked():
        process=subprocess.Popen(['/bin/bash',str(layout['hooks']/'cleanup-child-agent.sh'),identity.NAME],env=clean,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        import select
        assert select.select([process.stdout],[],[],.2)[0]==[]
        assert not (layout['stack']/'legacy.called').exists()
    out,err=process.communicate(timeout=15);assert process.returncode==0,err
    assert not (layout['stack']/'legacy.called').exists()
    assert record.read_text()=='permanent fixture'
    for k,b in before.items():assert seat[k].read_bytes()==b
    stale=dict(old,AGENTSTACK_LIFECYCLE_HOOKS_DIR=str(layout['release']))
    lifecycle_call=subprocess.run(['/bin/bash',str(layout['hooks']/'cleanup-child-agent.sh')],env=stale,capture_output=True,text=True,timeout=15)
    assert lifecycle_call.returncode==0,lifecycle_call.stderr
    assert seat['token'].read_bytes()==before['token']


def test_dispatcher_legacy_exit_and_invalid_generation_never_fallback(lane):
    seat=lane.arrange();layout=stage(lane,seat)
    result=subprocess.run(['/bin/bash',str(layout['hooks']/'cleanup-child-agent.sh'),identity.NAME],env=seat['env'],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    assert (layout['stack']/'legacy.called').read_text()=='legacy'
    (layout['stack']/'legacy.called').unlink()
    owner=lifecycle.Seat(layout['runtime'],identity.NAME)
    owner.directories();owner.lease_path.write_text('invalid state')
    result=subprocess.run(['/bin/bash',str(layout['hooks']/'cleanup-child-agent.sh'),identity.NAME],env=seat['env'],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    assert not (layout['stack']/'legacy.called').exists()


def test_schema_fake_rejects_the_same_extra_kwarg_as_real_fastmcp(monkeypatch):
    from fastmcp import Client
    from agentstack_mail import app
    reached=[]
    async def stop_before_db(identifier):
        reached.append(identifier)
        raise ValueError('fixture reached business logic')
    monkeypatch.setattr(app,'_get_project_by_identifier',stop_before_db)
    args=dict(project_key='/fixture/project',agent_name=identity.NAME)
    with pytest.raises(ValueError,match='unexpected arguments'):
        validate_call('release_file_reservations',dict(args,registration_token='synthetic-only'))
    validate_call('release_file_reservations',args)
    async def probe():
        async with Client(app.build_mcp_server()) as client:
            invalid=await client.call_tool('release_file_reservations',dict(args,registration_token='synthetic-only'),raise_on_error=False)
            assert invalid.is_error
            assert not reached
            valid=await client.call_tool('release_file_reservations',args,raise_on_error=False)
            assert reached==['/fixture/project']
    asyncio.run(probe())


@pytest.mark.parametrize('mode',['resource-conflict','mail-rejection','release-rejection'])
def test_schema_strict_parent_and_child_rollback_always_attempt_retire(lane,mode):
    seat=lane.arrange(); calls=[]; rejected=[]
    schemas=tool_schemas()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            method=request['params']['name'];arguments=request['params']['arguments']
            calls.append(method)
            error=None
            try: validate_call(method,arguments)
            except Exception as exc: rejected.append(str(exc));error=str(exc)
            if mode=='mail-rejection' and method=='send_message': error='injected delivery failure'
            if mode=='release-rejection' and method=='release_file_reservations': error='injected release failure'
            data={'name':identity.NAME,'registration_token':identity.TOKEN} if method=='register_agent' else {}
            if mode=='resource-conflict' and method=='file_reservation_paths':
                data={'granted':[],'conflicts':[{'path':'fixture.txt','holders':[{'agent_name':'OtherSeat'}]}]}
            result={'isError':True,'content':[{'type':'text','text':error}]} if error else {'structuredContent':data,'content':[{'type':'text','text':json.dumps(data)}]}
            self.send_response(200); self.end_headers(); self.wfile.write(json.dumps({'result':result}).encode())
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    task=lane.base/'task.md';task.write_text('fixture work')
    env=dict(seat['env'],AGENTSTACK_MCP_URL=f'http://127.0.0.1:{server.server_port}/mcp',AGENTSTACK_DIRECT_CANDIDATE='Restart-Fixture',FIXTURE_EARLY_FAILURE='1')
    identity.freeze_tmux_fixture(env)
    try:
        result=subprocess.run(['/bin/bash',str(identity.SPAWN),'--codex','--model','gpt-5.5','--resources','fixture.txt','--task-file',str(task),str(seat['work'])],env=env,capture_output=True,text=True,timeout=30)
    finally:
        server.shutdown();server.server_close();thread.join()
    assert result.returncode=={'resource-conflict':21,'mail-rejection':1,'release-rejection':17}[mode],result.stderr
    assert not rejected,rejected
    assert 'release_file_reservations' in calls
    assert 'retire_agent' in calls,calls
    assert calls.index('release_file_reservations')<calls.index('retire_agent')
    for key in ('token','state','home'): assert not seat[key].exists(),key
